"""Snowlink desktop UI (PySide6 app shell). Not the full Phase 3 MVP yet."""

from __future__ import annotations

__all__ = ["run_app"]


def run_app() -> int:
    """Launch the application; imported lazily so non-UI installs stay light."""
    from snowlink.ui.app import run_app as _run

    return _run()
