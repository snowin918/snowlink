"""Lifecycle tests for the native engine DLL (skipped when not built)."""

from __future__ import annotations

import pytest

from snowlink.constants import NATIVE_MEDIA_PORT_MAX, NATIVE_MEDIA_PORT_MIN
from snowlink.native_engine import (
    NativeEngine,
    NativeEngineError,
    NativeEngineUnavailable,
    is_native_engine_available,
    probe_native_engine,
)

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


def test_native_transport_control_plane() -> None:
    with NativeEngine.create() as engine:
        engine.connect(bind_address="127.0.0.1")
        engine.create_offer()
        # ICE gathering is asynchronous; Python polls SDP but never handles frames.
        description = None
        for _ in range(100):
            description = engine.local_description()
            if description is not None:
                break
            __import__("time").sleep(0.01)
        assert description is not None
        assert description["type"] == "offer"
        assert "m=video" in description["sdp"]
        assert "H264/90000" in description["sdp"]
        assert "a=candidate:" in description["sdp"]
        candidate = next(
            line for line in description["sdp"].splitlines() if line.startswith("a=candidate:")
        )
        candidate_port = int(candidate.split()[5])
        assert NATIVE_MEDIA_PORT_MIN <= candidate_port <= NATIVE_MEDIA_PORT_MAX
        with pytest.raises(NativeEngineError):
            engine.start_stream()


def test_native_candidate_summary_excludes_credentials_and_sdp() -> None:
    from snowlink.rtc.screen_session import _native_candidate_summary

    sdp = "\r\n".join(
        (
            "v=0",
            "a=ice-ufrag:secret-value",
            "a=candidate:1 1 UDP 2114977791 192.168.1.20 40001 typ host",
            "a=candidate:2 1 TCP 1234 192.168.1.20 9 typ host tcptype active",
        )
    )
    summary = _native_candidate_summary(sdp)
    assert summary == [
        "udp 192.168.1.20:40001 typ=host",
        "tcp 192.168.1.20:9 typ=host",
    ]
    assert "secret-value" not in repr(summary)


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
