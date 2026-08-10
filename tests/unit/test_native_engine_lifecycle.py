"""Lifecycle tests for the native engine DLL (skipped when not built)."""

from __future__ import annotations

import pytest

from snowlink.native_engine import (
    NativeEngine,
    NativeEngineUnavailable,
    is_native_engine_available,
    probe_native_engine,
)
from snowlink.native_engine.engine import SNOWLINK_ERR_NOT_IMPLEMENTED


pytestmark = pytest.mark.skipif(
    not is_native_engine_available(),
    reason="snowlink_engine.dll not built (run scripts/dev/build_native_engine.ps1)",
)


def test_native_engine_initialize_shutdown() -> None:
    engine = NativeEngine.create()
    try:
        assert "0.1.0" in engine.version()
        engine.initialize()
        assert engine.state() == 1  # Initialized
        stats = engine.get_stats()
        assert stats.frames_captured == 0
        engine.set_target_fps(30)
        engine.set_bitrate(2_000_000)
        engine.set_resolution(1280, 720)
        engine.shutdown()
        # shutdown from Initialized leaves Shutdown state
        assert engine.state() == 4
    finally:
        engine.destroy()


def test_native_engine_context_manager() -> None:
    with NativeEngine.create() as engine:
        assert engine.state() == 1
        stats = engine.get_stats()
        assert stats.bitrate_bps >= 0


def test_native_engine_capture_stream_not_implemented() -> None:
    with NativeEngine.create() as engine:
        assert engine.start_capture(target_fps=30) == SNOWLINK_ERR_NOT_IMPLEMENTED
        assert engine.start_stream() == SNOWLINK_ERR_NOT_IMPLEMENTED
        assert engine.request_keyframe() == SNOWLINK_ERR_NOT_IMPLEMENTED


def test_probe_native_engine() -> None:
    result = probe_native_engine()
    assert result["available"] is True
    assert "foundation" in result["version"]


def test_create_raises_when_forced_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from snowlink.native_engine import loader

    loader.clear_loader_cache()
    monkeypatch.setenv("SNOWLINK_ENGINE_DLL", r"C:\nonexistent\snowlink_engine.dll")
    monkeypatch.setattr(loader, "find_engine_dll", lambda: None)
    with pytest.raises(NativeEngineUnavailable):
        NativeEngine.create()
    loader.clear_loader_cache()
