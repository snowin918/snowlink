"""User preference load/save under %LOCALAPPDATA%\\Snowlink\\config.toml."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from snowlink.constants import DEFAULT_SIGNALING_PORT
from snowlink.platform_win.paths import config_path, ensure_app_dirs

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class UserPreferences:
    """Persisted UI / session defaults (no secrets)."""

    signaling_port: int = DEFAULT_SIGNALING_PORT
    preset: str = "low"
    backend: str = "dxgi"
    enable_audio: bool = True
    preferred_adapter_name: str | None = None
    preferred_bind_ip: str | None = None
    last_remote_ip: str | None = None
    last_source_ip: str | None = None
    share_monitor: int = 0
    audio_capture_device: str = "default"
    auto_start_share: bool = True
    media_engine: str = "legacy_python"
    window_x: int | None = None
    window_y: int | None = None
    window_width: int = 700
    window_height: int = 500

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserPreferences:
        known = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            if key not in known:
                continue
            kwargs[key] = value
        return cls(**kwargs)


def _escape_toml_str(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _dumps_toml(data: dict[str, Any]) -> str:
    """Minimal TOML writer for flat preference keys (stdlib has no dump)."""
    lines = [
        "# Snowlink user preferences — do not store pairing codes or secrets here.",
        "",
    ]
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, int):
            lines.append(f"{key} = {value}")
        elif isinstance(value, float):
            lines.append(f"{key} = {value}")
        elif isinstance(value, str):
            lines.append(f'{key} = "{_escape_toml_str(value)}"')
        else:
            logger.debug("Skipping unsupported preference type for %s", key)
    return "\n".join(lines) + "\n"


def load_preferences(path: Path | None = None) -> UserPreferences:
    """Load preferences; missing file yields defaults."""
    target = path or config_path()
    if not target.is_file():
        return UserPreferences()
    try:
        raw = target.read_bytes()
        data = tomllib.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            return UserPreferences()
        return UserPreferences.from_dict(data)
    except Exception:
        logger.exception("Failed to load preferences from %s", target)
        return UserPreferences()


def save_preferences(prefs: UserPreferences, path: Path | None = None) -> Path:
    """Write preferences atomically; creates appdata dirs as needed."""
    ensure_app_dirs()
    target = path or config_path()
    text = _dumps_toml(prefs.to_dict())
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)
    return target
