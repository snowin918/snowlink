"""Unit tests for session history persistence."""

from __future__ import annotations

from pathlib import Path

from snowlink.session_history import (
    SessionHistoryEntry,
    format_history_label,
    load_history,
    prepend_history,
    save_history,
)


def test_history_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "session_history.json"
    entry = SessionHistoryEntry(
        role="view",
        peer="192.168.1.25",
        port=3847,
        started_at="2026-08-09T12:00:00+00:00",
        outcome="connected",
    )
    prepend_history(entry, path=path)
    loaded = load_history(path=path)
    assert len(loaded) == 1
    assert loaded[0].peer == "192.168.1.25"
    assert "Viewed" in format_history_label(loaded[0])


def test_clear_history(tmp_path: Path) -> None:
    path = tmp_path / "session_history.json"
    prepend_history(
        SessionHistoryEntry(
            role="share",
            peer="192.168.1.40:5555",
            port=3847,
            started_at="2026-08-09T12:00:00+00:00",
        ),
        path=path,
    )
    save_history([], path=path)
    assert load_history(path=path) == []
