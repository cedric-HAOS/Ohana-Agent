"""Scoped, revocable identities for personal Ohana companion applications."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field

from administration.models import AdministrationModel

PAIRING_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
CompanionPairingStatus = Literal[
    "PENDING", "APPROVED", "CONSUMED", "EXPIRED", "REJECTED"
]


class CompanionConflictError(RuntimeError):
    """Raised when a companion lifecycle transition is no longer possible."""


class CompanionPairingRequest(AdministrationModel):
    """Bounded identity proposed by an iPhone before user approval."""

    protocol_version: Literal[1] = 1
    device_id: str = Field(
        min_length=8,
        max_length=80,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    device_name: str = Field(min_length=1, max_length=80)
    platform: Literal["ios"] = "ios"
    app_version: str = Field(min_length=1, max_length=40)


class CompanionPairingCreated(AdministrationModel):
    """One-time polling material returned to the unpaired iPhone."""

    protocol_version: Literal[1] = 1
    pairing_id: UUID
    polling_secret: str = Field(min_length=32, max_length=128)
    verification_code: str = Field(pattern=r"^[A-Z0-9]{4}-[A-Z0-9]{4}$")
    expires_at: datetime
    tls_ca_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tls_ca_certificate_pem: str = Field(min_length=64, max_length=16_384)


class CompanionPairingPoll(AdministrationModel):
    """Proof that a poll belongs to the iPhone that opened the request."""

    protocol_version: Literal[1] = 1
    polling_secret: str = Field(min_length=32, max_length=128)


class CompanionPairingDocument(AdministrationModel):
    """Administrative view that never exposes credentials or polling secrets."""

    protocol_version: Literal[1] = 1
    pairing_id: UUID
    device_id: str
    device_name: str
    platform: Literal["ios"] = "ios"
    app_version: str
    verification_code: str
    tls_ca_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: CompanionPairingStatus
    created_at: datetime
    expires_at: datetime


class CompanionPairingCollection(AdministrationModel):
    """Bounded collection of companion pairing requests."""

    protocol_version: Literal[1] = 1
    pairings: list[CompanionPairingDocument] = Field(default_factory=list)


class CompanionPairingResult(AdministrationModel):
    """Polling result that returns a scoped credential exactly once."""

    protocol_version: Literal[1] = 1
    pairing_id: UUID
    status: CompanionPairingStatus
    expires_at: datetime
    companion_token: str | None = Field(default=None, min_length=32, max_length=128)
    token_expires_at: datetime | None = None


class CompanionDeviceDocument(AdministrationModel):
    """Revocable companion session visible to the administration plane."""

    protocol_version: Literal[1] = 1
    device_id: str
    device_name: str
    platform: Literal["ios"] = "ios"
    app_version: str
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None


class CompanionDeviceCollection(AdministrationModel):
    """Known companion devices without their bearer credentials."""

    protocol_version: Literal[1] = 1
    devices: list[CompanionDeviceDocument] = Field(default_factory=list)


class CompanionPushRegistration(AdministrationModel):
    """APNs address registered only by its authenticated companion device."""

    protocol_version: Literal[1] = 1
    enabled: bool = True
    device_token: str | None = Field(
        default=None,
        min_length=32,
        max_length=512,
        pattern=r"^[0-9A-Fa-f]+$",
    )
    environment: Literal["development", "production"] = "production"


class CompanionRepository:
    """Persist short-lived pairings and hashed, scoped companion credentials."""

    def __init__(
        self,
        database_path: Path | str,
        *,
        pairing_ttl_seconds: int = 600,
        credential_ttl_days: int = 90,
        max_pending_pairings: int = 10,
        utc_now=None,
    ) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.pairing_ttl_seconds = pairing_ttl_seconds
        self.credential_ttl_days = credential_ttl_days
        self.max_pending_pairings = max_pending_pairings
        self._utc_now = utc_now or (lambda: datetime.now(UTC))
        self._lock = RLock()
        self._connection = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def close(self) -> None:
        """Close the repository connection."""
        with self._lock:
            self._connection.close()

    def create_pairing(
        self,
        payload: dict[str, object],
        *,
        tls_ca_sha256: str,
        tls_ca_certificate_pem: str,
    ) -> CompanionPairingCreated:
        """Open one explicit pairing without issuing a credential."""
        request = CompanionPairingRequest.model_validate(payload)
        now = self._now()
        expires_at = now + timedelta(seconds=self.pairing_ttl_seconds)
        pairing_id = str(uuid4())
        polling_secret = secrets.token_urlsafe(32)
        code = "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(8))
        verification_code = f"{code[:4]}-{code[4:]}"
        with self._lock, self._connection:
            self._expire_pairings_locked(now)
            existing = self._connection.execute(
                """SELECT 1 FROM companion_pairings
                WHERE device_id=? AND status IN ('PENDING','APPROVED')""",
                (request.device_id,),
            ).fetchone()
            if existing is not None:
                raise CompanionConflictError(
                    "Une demande d’association est déjà active pour cet appareil"
                )
            pending_count = int(
                self._connection.execute(
                    """SELECT COUNT(*) FROM companion_pairings
                    WHERE status IN ('PENDING','APPROVED')"""
                ).fetchone()[0]
            )
            if pending_count >= self.max_pending_pairings:
                raise ValueError("La file d’association Shizune est pleine")
            self._connection.execute(
                """INSERT INTO companion_pairings (
                pairing_id,device_id,device_name,platform,app_version,
                polling_secret_sha256,verification_code,tls_ca_sha256,status,
                created_at,expires_at
                ) VALUES (?,?,?,?,?,?,?,?,'PENDING',?,?)""",
                (
                    pairing_id,
                    request.device_id,
                    request.device_name,
                    request.platform,
                    request.app_version,
                    self._digest(polling_secret),
                    verification_code,
                    tls_ca_sha256,
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )
        return CompanionPairingCreated(
            pairing_id=pairing_id,
            polling_secret=polling_secret,
            verification_code=verification_code,
            expires_at=expires_at,
            tls_ca_sha256=tls_ca_sha256,
            tls_ca_certificate_pem=tls_ca_certificate_pem,
        )

    def list_pairings(self) -> CompanionPairingCollection:
        """List recent pairings without exposing their secrets."""
        with self._lock, self._connection:
            self._expire_pairings_locked(self._now())
            rows = self._connection.execute(
                "SELECT * FROM companion_pairings ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        return CompanionPairingCollection(
            pairings=[self._pairing_document(row) for row in rows]
        )

    def approve_pairing(self, pairing_id: UUID | str) -> CompanionPairingDocument:
        """Approve only the pairing whose code was verified by the user."""
        now = self._now()
        with self._lock, self._connection:
            self._expire_pairings_locked(now)
            row = self._required_pairing(pairing_id)
            if row["status"] == "APPROVED":
                return self._pairing_document(row)
            if row["status"] != "PENDING":
                raise CompanionConflictError(
                    f"Association impossible depuis l’état {row['status']}"
                )
            self._connection.execute(
                "UPDATE companion_pairings SET status='APPROVED',approved_at=? "
                "WHERE pairing_id=?",
                (now.isoformat(), str(pairing_id)),
            )
            return self._pairing_document(self._required_pairing(pairing_id))

    def reject_pairing(self, pairing_id: UUID | str) -> CompanionPairingDocument:
        """Reject a pairing before any credential can be delivered."""
        with self._lock, self._connection:
            self._expire_pairings_locked(self._now())
            row = self._required_pairing(pairing_id)
            if row["status"] == "REJECTED":
                return self._pairing_document(row)
            if row["status"] not in {"PENDING", "APPROVED"}:
                raise CompanionConflictError(
                    f"Rejet impossible depuis l’état {row['status']}"
                )
            self._connection.execute(
                "UPDATE companion_pairings SET status='REJECTED' WHERE pairing_id=?",
                (str(pairing_id),),
            )
            return self._pairing_document(self._required_pairing(pairing_id))

    def poll_pairing(
        self,
        pairing_id: UUID | str,
        payload: dict[str, object],
    ) -> CompanionPairingResult:
        """Return a new bearer credential once, after explicit approval."""
        poll = CompanionPairingPoll.model_validate(payload)
        now = self._now()
        token: str | None = None
        token_expires_at: datetime | None = None
        with self._lock, self._connection:
            self._expire_pairings_locked(now)
            row = self._required_pairing(pairing_id)
            if not hmac.compare_digest(
                row["polling_secret_sha256"], self._digest(poll.polling_secret)
            ):
                raise LookupError("Association Shizune inconnue")
            if row["status"] == "APPROVED":
                token = secrets.token_urlsafe(48)
                token_expires_at = now + timedelta(days=self.credential_ttl_days)
                self._connection.execute(
                    """INSERT INTO companion_credentials (
                    device_id,device_name,platform,app_version,token_sha256,
                    created_at,expires_at,last_seen_at,revoked_at
                    ) VALUES (?,?,?,?,?,?,?,NULL,NULL)
                    ON CONFLICT(device_id) DO UPDATE SET
                    device_name=excluded.device_name,platform=excluded.platform,
                    app_version=excluded.app_version,
                    token_sha256=excluded.token_sha256,
                    created_at=excluded.created_at,expires_at=excluded.expires_at,
                    last_seen_at=NULL,revoked_at=NULL""",
                    (
                        row["device_id"],
                        row["device_name"],
                        row["platform"],
                        row["app_version"],
                        self._digest(token),
                        now.isoformat(),
                        token_expires_at.isoformat(),
                    ),
                )
                self._connection.execute(
                    """UPDATE companion_pairings
                    SET status='CONSUMED',consumed_at=? WHERE pairing_id=?""",
                    (now.isoformat(), str(pairing_id)),
                )
                row = self._required_pairing(pairing_id)
        return CompanionPairingResult(
            pairing_id=row["pairing_id"],
            status=row["status"],
            expires_at=datetime.fromisoformat(row["expires_at"]),
            companion_token=token,
            token_expires_at=token_expires_at,
        )

    def authorize(self, device_id: str, token: str) -> bool:
        """Validate a non-revoked, non-expired token and record last use."""
        now = self._now()
        with self._lock, self._connection:
            row = self._connection.execute(
                """SELECT token_sha256,expires_at FROM companion_credentials
                WHERE device_id=? AND revoked_at IS NULL""",
                (device_id,),
            ).fetchone()
            if (
                row is None
                or datetime.fromisoformat(row["expires_at"]) <= now
                or not hmac.compare_digest(row["token_sha256"], self._digest(token))
            ):
                return False
            self._connection.execute(
                "UPDATE companion_credentials SET last_seen_at=? WHERE device_id=?",
                (now.isoformat(), device_id),
            )
        return True

    def list_devices(self) -> CompanionDeviceCollection:
        """List sessions for administration and explicit revocation."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM companion_credentials ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        return CompanionDeviceCollection(
            devices=[self._device_document(row) for row in rows]
        )

    def revoke(self, device_id: str) -> CompanionDeviceDocument:
        """Immediately revoke one companion credential."""
        now = self._now()
        with self._lock, self._connection:
            row = self._required_device(device_id)
            if row["revoked_at"] is None:
                self._connection.execute(
                    "UPDATE companion_credentials SET revoked_at=? WHERE device_id=?",
                    (now.isoformat(), device_id),
                )
                self._connection.execute(
                    "UPDATE companion_push_tokens SET enabled=0 WHERE device_id=?",
                    (device_id,),
                )
            return self._device_document(self._required_device(device_id))

    def register_push_token(
        self,
        device_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        """Bind or disable one APNs token after companion authentication."""
        request = CompanionPushRegistration.model_validate(payload)
        if request.enabled and request.device_token is None:
            raise ValueError("Un jeton APNs est requis pour activer les notifications")
        now = self._now()
        with self._lock, self._connection:
            credential = self._required_device(device_id)
            if credential["revoked_at"] is not None:
                raise CompanionConflictError("La session Shizune est révoquée")
            self._connection.execute(
                """INSERT INTO companion_push_tokens (
                device_id,device_token,environment,enabled,updated_at
                ) VALUES (?,?,?,?,?)
                ON CONFLICT(device_id) DO UPDATE SET
                device_token=excluded.device_token,
                environment=excluded.environment,
                enabled=excluded.enabled,updated_at=excluded.updated_at""",
                (
                    device_id,
                    request.device_token.lower() if request.device_token else None,
                    request.environment,
                    int(request.enabled),
                    now.isoformat(),
                ),
            )
        return {
            "schema_version": 1,
            "enabled": request.enabled,
            "environment": request.environment,
            "updated_at": now.isoformat(),
        }

    def push_targets(self, environment: str) -> list[tuple[str, str]]:
        """Return active APNs targets without exposing them through HTTP APIs."""
        now = self._now()
        with self._lock:
            rows = self._connection.execute(
                """SELECT p.device_id,p.device_token
                FROM companion_push_tokens p
                JOIN companion_credentials c ON c.device_id=p.device_id
                WHERE p.enabled=1 AND p.environment=? AND p.device_token IS NOT NULL
                AND c.revoked_at IS NULL AND c.expires_at>?""",
                (environment, now.isoformat()),
            ).fetchall()
        return [(str(row["device_id"]), str(row["device_token"])) for row in rows]

    def disable_push_token(self, device_id: str) -> None:
        """Disable a token rejected as unregistered by APNs."""
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE companion_push_tokens SET enabled=0 WHERE device_id=?",
                (device_id,),
            )

    def _initialize(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                PRAGMA busy_timeout=5000;
                CREATE TABLE IF NOT EXISTS companion_pairings (
                    pairing_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    device_name TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    app_version TEXT NOT NULL,
                    polling_secret_sha256 TEXT NOT NULL,
                    verification_code TEXT NOT NULL,
                    tls_ca_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    approved_at TEXT,
                    consumed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS companion_pairings_status
                ON companion_pairings(status,expires_at);
                CREATE TABLE IF NOT EXISTS companion_credentials (
                    device_id TEXT PRIMARY KEY,
                    device_name TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    app_version TEXT NOT NULL,
                    token_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT,
                    revoked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS companion_push_tokens (
                    device_id TEXT PRIMARY KEY,
                    device_token TEXT,
                    environment TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            columns = {
                str(row["name"])
                for row in self._connection.execute(
                    "PRAGMA table_info(companion_pairings)"
                ).fetchall()
            }
            if "tls_ca_sha256" not in columns:
                self._connection.execute(
                    "ALTER TABLE companion_pairings ADD COLUMN tls_ca_sha256 TEXT"
                )
                self._connection.execute(
                    "UPDATE companion_pairings SET tls_ca_sha256=? "
                    "WHERE tls_ca_sha256 IS NULL",
                    ("0" * 64,),
                )

    def _expire_pairings_locked(self, now: datetime) -> None:
        self._connection.execute(
            """UPDATE companion_pairings SET status='EXPIRED'
            WHERE status IN ('PENDING','APPROVED') AND expires_at<=?""",
            (now.isoformat(),),
        )

    def _required_pairing(self, pairing_id: UUID | str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM companion_pairings WHERE pairing_id=?",
            (str(pairing_id),),
        ).fetchone()
        if row is None:
            raise LookupError("Association Shizune inconnue")
        return row

    def _required_device(self, device_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM companion_credentials WHERE device_id=?", (device_id,)
        ).fetchone()
        if row is None:
            raise LookupError("Appareil Shizune inconnu")
        return row

    @staticmethod
    def _pairing_document(row: sqlite3.Row) -> CompanionPairingDocument:
        return CompanionPairingDocument(
            pairing_id=row["pairing_id"],
            device_id=row["device_id"],
            device_name=row["device_name"],
            platform=row["platform"],
            app_version=row["app_version"],
            verification_code=row["verification_code"],
            tls_ca_sha256=row["tls_ca_sha256"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
        )

    @staticmethod
    def _device_document(row: sqlite3.Row) -> CompanionDeviceDocument:
        return CompanionDeviceDocument(
            device_id=row["device_id"],
            device_name=row["device_name"],
            platform=row["platform"],
            app_version=row["app_version"],
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            last_seen_at=(
                datetime.fromisoformat(row["last_seen_at"])
                if row["last_seen_at"]
                else None
            ),
            revoked_at=(
                datetime.fromisoformat(row["revoked_at"]) if row["revoked_at"] else None
            ),
        )

    def _now(self) -> datetime:
        return self._utc_now().astimezone(UTC)

    @staticmethod
    def _digest(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()
