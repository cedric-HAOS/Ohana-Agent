"""Phase 10: read the reports Ohana-Installer leaves after ``ohana restore``.

The Installer is the only one to know how a restoration of INFRA-01 ended. It
writes a small JSON report without secrets; the Agent reads it and enters the
outcome in its register of restorations, flagged as coming from the Installer.
A report is read once, whatever its content, and a broken file never stops the
others.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ohana_agent.tsunade.preventive_backup import RESTORE_OUTCOMES

LOGGER = logging.getLogger(__name__)
REPORT_DIRECTORY = Path("/var/lib/ohana-installer/restore-reports")
MAX_REPORTS = 50
MAX_BYTES = 16 * 1024
STAGES = {
    "selection": "choix de la sauvegarde",
    "download": "téléchargement et déchiffrement",
    "install": "installation d'Agent et Vision",
    "configuration": "restauration des configurations",
    "identity": "installation de l'identité age",
    "done": "terminée",
}


def read_reports(directory: Path) -> list[dict[str, Any]]:
    """Valid reports of a directory, oldest first; anything else is ignored."""
    try:
        files = sorted(directory.glob("*.json"))[-MAX_REPORTS:]
    except OSError:
        return []
    reports = []
    for path in files:
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            document = json.loads(path.read_text(encoding="utf-8"))
            reports.append(_validate(document))
        except (OSError, ValueError, TypeError, KeyError):
            LOGGER.warning("Ignoring unreadable restore report %s", path.name)
    return sorted(reports, key=lambda report: report["finished_at"])


def _validate(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("unsupported report")
    outcome = document["outcome"]
    if outcome not in RESTORE_OUTCOMES:
        raise ValueError("unknown outcome")
    target = str(document["target"]).strip().lower()
    report_id = str(document["report_id"]).strip()
    if not target or not report_id or len(report_id) > 64:
        raise ValueError("incomplete report")
    finished_at = datetime.fromisoformat(str(document["finished_at"]))
    if finished_at.tzinfo is None:
        raise ValueError("report time without zone")
    stage = str(document.get("stage", ""))
    detail = " ".join(str(document.get("detail", "")).split())[:300]
    backup_id = document.get("backup_id")
    return {
        "report_id": report_id,
        "target": target,
        "outcome": outcome,
        "mode": str(document.get("mode", "")),
        "stage": stage,
        "stage_label": STAGES.get(stage, stage),
        "backup_id": str(backup_id) if backup_id else "",
        "detail": detail,
        "finished_at": finished_at,
    }
