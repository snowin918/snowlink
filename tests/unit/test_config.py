"""Unit tests for user preferences config store."""

from __future__ import annotations

from pathlib import Path

from snowlink.config import UserPreferences, load_preferences, save_preferences


def test_preferences_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    prefs = UserPreferences(
        signaling_port=4000,
        preset="balanced",
        backend="winrt",
        enable_audio=False,
        preferred_bind_ip="192.168.1.10",
        last_remote_ip="192.168.1.20",
        share_monitor=1,
        window_width=1200,
        window_height=800,
    )
    save_preferences(prefs, path=path)
    loaded = load_preferences(path=path)
    assert loaded.signaling_port == 4000
    assert loaded.preset == "balanced"
    assert loaded.backend == "winrt"
    assert loaded.media_engine == "legacy_python"
    assert loaded.enable_audio is False
    assert loaded.preferred_bind_ip == "192.168.1.10"
    assert loaded.last_remote_ip == "192.168.1.20"
    assert loaded.share_monitor == 1
    assert loaded.window_width == 1200


def test_missing_config_returns_defaults(tmp_path: Path) -> None:
    loaded = load_preferences(path=tmp_path / "missing.toml")
    assert loaded.signaling_port == 3847
    assert loaded.preset == "low"
    assert loaded.media_engine == "legacy_python"
    assert loaded.enable_audio is True
    assert loaded.auto_start_share is True
    assert loaded.audio_capture_device == "default"
    assert loaded.window_width == 700
    assert loaded.window_height == 500


def test_corrupt_config_returns_defaults(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text("{{{not toml", encoding="utf-8")
    loaded = load_preferences(path=path)
    assert isinstance(loaded, UserPreferences)
    assert loaded.preset == "low"
