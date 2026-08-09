"""Persisted past Share/View session history (no secrets)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from snowlink.platform_win.paths import appdata_dir, ensure_app_dirs

logger = logging.getLogger(__name__)

MAX_HISTORY_ENTRIES = 50
Role = Literal["share", "view"]


@dataclass(slots=True)
class SessionHistoryEntry:
    role: Role
    peer: str
    port: int
    started_at: str
    ended_at: str | None = None
    outcome: str = "connected"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionHistoryEntry | None:
        try:
            role = str(data.get("role", ""))
            if role not in {"share", "view"}:
                return None
            return cls(
                role=role,  # type: ignore[arg-type]
                peer=str(data.get("peer") or "—"),
                port=int(data.get("port") or 3847),
                started_at=str(data.get("started_at") or ""),
                ended_at=(
                    str(data["ended_at"]) if data.get("ended_at") is not None else None
                ),
                outcome=str(data.get("outcome") or "connected"),
            )
        except Exception:
            return None


def history_path() -> Path:
    return appdata_dir() / "session_history.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_history(path: Path | None = None) -> list[SessionHistoryEntry]:
    target = path or history_path()
    if not target.is_file():
        return []
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        entries: list[SessionHistoryEntry] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            entry = SessionHistoryEntry.from_dict(item)
            if entry is not None:
                entries.append(entry)
        return entries
    except Exception:
        logger.exception("Failed to load session history from %s", target)
        return []


def save_history(
    entries: list[SessionHistoryEntry],
    path: Path | None = None,
) -> Path:
    ensure_app_dirs()
    target = path or history_path()
    payload = [e.to_dict() for e in entries[:MAX_HISTORY_ENTRIES]]
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(target)
    return target


def prepend_history(
    entry: SessionHistoryEntry,
    *,
    path: Path | None = None,
) -> list[SessionHistoryEntry]:
    entries = [entry, *load_history(path=path)]
    entries = entries[:MAX_HISTORY_ENTRIES]
    save_history(entries, path=path)
    return entries


def format_history_label(entry: SessionHistoryEntry) -> str:
    role = "Shared with" if entry.role == "share" else "Viewed"
    when = entry.started_at.replace("T", " ").replace("+00:00", " UTC")
    return f"{role} {entry.peer}:{entry.port} — {when}"
