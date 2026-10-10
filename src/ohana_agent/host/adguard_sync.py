"""Agent-owned administration of the installed AdGuard replication capability."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from time import monotonic, sleep
from typing import Any

import yaml

from ohana_agent.configuration.adguard_sync import AdGuardSyncPluginConfig
from ohana_agent.plugins.adguard_sync.snapshot import AdGuardSnapshotProbe, _features

CONFIGURATION = Path("/etc/ohana-agent/adguardhome-sync.yaml")
STATE = Path("/etc/ohana-agent/adguard-sync-state.json")
BINARY = Path("/opt/adguardhome-sync/adguardhome-sync")
HELPER = Path("/opt/ohana-agent/venv/bin/ohana-agent-adguard-sync-helper")
SERVICE = "adguardhome-sync.service"
TIMER = "adguardhome-sync.timer"


class AdGuardSyncAdministration:
    def __init__(
        self,
        *,
        configuration: Path = CONFIGURATION,
        state: Path = STATE,
        binary: Path = BINARY,
        helper: Path = HELPER,
        command_runner=subprocess.run,
        probe: AdGuardSnapshotProbe | None = None,
    ) -> None:
        self.configuration = configuration
        self.state = state
        self.binary = binary
        self.helper = helper
        self.runner = command_runner
        self.probe = probe or AdGuardSnapshotProbe()
        self.lock = RLock()

    @contextmanager
    def _file_lock(self):
        """Serialize a root activation with an Agent configuration update."""
        if os.name != "posix":
            yield
            return
        import fcntl
        import grp

        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
        descriptor = os.open(
            self.configuration.with_name(".adguard-sync.lock"), flags, 0o660
        )
        try:
            if os.geteuid() == 0:
                os.fchmod(descriptor, 0o660)
                os.fchown(descriptor, 0, grp.getgrnam("ohana-agent").gr_gid)
            deadline = monotonic() + 5
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if monotonic() >= deadline:
                        raise ValueError(
                            "Une opération AdGuard est déjà en cours."
                        ) from None
                    sleep(0.05)
            yield
        finally:
            os.close(descriptor)

    def _document(self) -> dict[str, Any]:
        try:
            if self.configuration.is_symlink():
                raise ValueError()
            with self.configuration.open("rb") as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError()
            document = yaml.safe_load(raw)
            if not isinstance(document, dict):
                raise ValueError()
            return document
        except (OSError, ValueError, yaml.YAMLError) as error:
            raise ValueError(
                "Configuration de synchronisation AdGuard illisible."
            ) from error

    def _systemctl(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        try:
            return self.runner(
                ("/usr/bin/systemctl", *arguments),
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError("État systemd AdGuard indisponible.") from error

    def read(self) -> dict[str, Any]:
        with self.lock:
            installed = self.binary.is_file() and self.helper.is_file()
            try:
                document = self._document() if self.configuration.is_file() else {}
            except ValueError:
                document = {}
            active = self._systemctl("is-active", TIMER)
            enabled = self._systemctl("is-enabled", TIMER)
            service = self._systemctl("is-active", SERVICE)
            instances = {}
            configured = True
            for role in ("origin", "replica"):
                instance = document.get(role, {})
                if not isinstance(instance, dict):
                    instance = {}
                # URLs must never export embedded credentials or arbitrary content.
                public_url = ""
                try:
                    AdGuardSnapshotProbe._instance(instance)
                    public_url = instance["url"]
                except (ValueError, TypeError):
                    configured = False
                    if instance.get("password") in (None, ""):
                        candidate = {**instance, "password": "validation-only"}
                        try:
                            AdGuardSnapshotProbe._instance(candidate)
                            public_url = instance["url"]
                        except (ValueError, TypeError):
                            pass
                username = instance.get("username", "")
                instances[role] = {
                    "url": public_url,
                    "username": username if isinstance(username, str) else "",
                    "password_configured": bool(instance.get("password")),
                }
            return {
                "installed": installed,
                "configured": configured,
                "running": service.stdout.strip()
                in {"active", "activating", "deactivating"},
                "enabled": enabled.returncode == 0
                and enabled.stdout.strip() == "enabled",
                "active": active.returncode == 0 and active.stdout.strip() == "active",
                **instances,
            }

    def _validate(self, configuration: Path) -> None:
        try:
            plugin_path = self.configuration.parent / "plugins/adguard-sync.yaml"
            if (
                configuration.is_symlink()
                or plugin_path.is_symlink()
                or plugin_path.parent.is_symlink()
            ):
                raise ValueError()
            settings = AdGuardSyncPluginConfig()
            if plugin_path.is_file():
                with plugin_path.open("rb") as source:
                    raw = source.read(65537)
                if len(raw) > 65536:
                    raise ValueError()
                settings = AdGuardSyncPluginConfig.model_validate(yaml.safe_load(raw))
            self.probe.validate_access(
                settings.model_copy(update={"sync_config_path": configuration})
            )
        except Exception as error:
            # Credentials, bodies and exception URLs never leave this boundary.
            raise ValueError("Accès aux deux API AdGuard non validés.") from error

    def write(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock, self._file_lock():
            if set(payload) != {"origin", "replica"}:
                raise ValueError("Origine et réplique AdGuard requises.")
            status = self.read()
            if status["active"] or status["running"]:
                raise ValueError(
                    "Désactiver la synchronisation avant de modifier ses accès."
                )
            document = self._document()
            for role in ("origin", "replica"):
                candidate = payload[role]
                if not isinstance(candidate, dict) or set(candidate) != {
                    "url",
                    "username",
                    "password",
                }:
                    raise ValueError("Paramètres AdGuard invalides.")
                if any(not isinstance(value, str) for value in candidate.values()):
                    raise ValueError("Paramètres AdGuard invalides.")
                if any(len(value) > 4096 for value in candidate.values()):
                    raise ValueError("Paramètres AdGuard trop longs.")
                previous = document.get(role, {})
                if not isinstance(previous, dict):
                    raise ValueError("Configuration AdGuard incompatible.")
                instance = {**previous, **candidate}
                instance["password"] = candidate["password"] or previous.get(
                    "password", ""
                )
                AdGuardSnapshotProbe._instance(instance)
                document[role] = instance
            _features(document)
            temporary: Path | None = None
            try:
                with NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=self.configuration.parent,
                    prefix=".adguard-sync-",
                    delete=False,
                ) as stream:
                    temporary = Path(stream.name)
                    temporary.chmod(0o600)
                    yaml.safe_dump(
                        document, stream, allow_unicode=True, sort_keys=False
                    )
                self._validate(temporary)
                os.replace(temporary, self.configuration)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            return self.read()

    def set_enabled(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if set(payload) != {"enabled"} or not isinstance(payload["enabled"], bool):
                raise ValueError("Activation AdGuard booléenne requise.")
            if not self.helper.is_file():
                raise ValueError("Capacité AdGuard à installer avec Ohana-Installer.")
            try:
                result = self.runner(
                    (
                        "/usr/bin/sudo",
                        "-n",
                        str(self.helper),
                        "activate" if payload["enabled"] else "deactivate",
                    ),
                    capture_output=True,
                    text=True,
                    timeout=90,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as error:
                raise ValueError("Activation AdGuard impossible.") from error
            if result.returncode:
                raise ValueError(
                    "Activation AdGuard refusée ; vérifier les accès et Installer."
                )
            return self.read()

    def privileged_set_enabled(self, enabled: bool) -> None:
        with self._file_lock():
            self._apply_enabled(enabled)

    def _apply_enabled(self, enabled: bool) -> None:
        """Validate activation and persist the successful operator choice."""
        if enabled:
            if not self.binary.is_file():
                raise ValueError("Moteur AdGuard absent.")
            self._validate(self.configuration)
        previous = self.read()
        temporary: Path | None = None
        try:
            if enabled:
                result = self._systemctl("enable", "--now", TIMER)
            else:
                result = self._systemctl("disable", "--now", TIMER)
                if result.returncode == 0:
                    result = self._systemctl("stop", SERVICE)
            if result.returncode:
                raise ValueError("Commande systemd AdGuard refusée.")
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.state.parent,
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                temporary.chmod(0o640)
                if hasattr(os, "chown"):
                    import grp

                    os.chown(temporary, 0, grp.getgrnam("ohana-agent").gr_gid)
                json.dump({"schema_version": 1, "enabled": enabled}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state)
        except Exception:
            self._systemctl("enable" if previous["enabled"] else "disable", TIMER)
            self._systemctl("start" if previous["active"] else "stop", TIMER)
            if not previous["running"]:
                self._systemctl("stop", SERVICE)
            raise
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gestion privilégiée de la synchronisation AdGuard"
    )
    parser.add_argument("action", choices=("activate", "deactivate"))
    args = parser.parse_args()
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return 1
    try:
        AdGuardSyncAdministration().privileged_set_enabled(args.action == "activate")
        return 0
    except Exception:
        print(
            "Commande AdGuard refusée ; configuration, accès ou état système invalides."
        )
        return 1
