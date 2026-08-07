"""Filesystem paths for Snowlink config and logs."""

from __future__ import annotations

import os
from pathlib import Path

from snowlink.constants import APP_NAME


def appdata_dir() -> Path:
    """Return ``%LOCALAPPDATA%\\Snowlink`` (created on demand by callers)."""
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_NAME


def config_path() -> Path:
    return appdata_dir() / "config.toml"


def logs_dir() -> Path:
    return appdata_dir() / "logs"


def ensure_app_dirs() -> Path:
    """Create config/logs directories; return the appdata root."""
    root = appdata_dir()
    root.mkdir(parents=True, exist_ok=True)
    logs_dir().mkdir(parents=True, exist_ok=True)
    return root
