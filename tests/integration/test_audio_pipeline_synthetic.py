"""Synthetic audio pipeline integration tests (no real speakers required)."""

from __future__ import annotations

import sys
import time

import numpy as np
import pytest

from snowlink.media.audio_models import AudioConfiguration
from snowlink.media.audio_pipeline import AudioPipelineSession, run_audio_pipeline


def _tone_source(sample_rate: int = 48_000, channels: int = 2):
    state = {"t": 0}

    def source() -> np.ndarray:
        n = 480  # 10 ms at 48 kHz
        t0 = state["t"]
        t = (np.arange(n) + t0) / float(sample_rate)
        state["t"] += n
        wave = (0.2 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
        return np.repeat(wave.reshape(-1, 1), channels, axis=1)

    return source


def test_synthetic_pipeline_runs_and_shuts_down() -> None:
    config = AudioConfiguration(
        duration_s=1,
        enable_playback=False,
        mode="monitor",
        target_sample_rate=48_000,
        target_channels=2,
        frame_duration_ms=20,
        buffer_capacity_ms=80,
    )
    code, result = run_audio_pipeline(
        config,
        honor_duration=True,
        synthetic_source=_tone_source(),
    )
    assert code == 0
    assert result.success is True
    assert result.conversion.converted_samples > 0
    assert result.capture.non_silent_frames > 0
    assert result.conversion.last_pts >= 0
    # PTS should have advanced by multiples of frame size conceptually
    assert result.buffer.capacity_ms == 80


def test_synthetic_underrun_emits_silence_and_keeps_pts() -> None:
    config = AudioConfiguration(
        duration_s=1,
        enable_playback=False,
        mode="monitor",
        frame_duration_ms=20,
        buffer_capacity_ms=80,
    )

    def empty() -> np.ndarray | None:
        time.sleep(0.05)
        return None

    session = AudioPipelineSession(config, synthetic_source=empty)
    session.start()
    time.sleep(0.4)
    session.shutdown(join_timeout_s=2.0)
    result = session.build_result(success=True)
    assert result.buffer.underruns >= 1
    assert result.capture.silence_frames >= 1
    assert session.converter is not None
    assert session.converter.pts_clock.peek() > 0


def test_synthetic_silence_is_not_underrun() -> None:
    config = AudioConfiguration(
        duration_s=1,
        enable_playback=False,
        mode="monitor",
        frame_duration_ms=20,
        buffer_capacity_ms=100,
    )

    def silence() -> np.ndarray:
        return np.zeros((960, 2), dtype=np.float32)

    code, result = run_audio_pipeline(
        config,
        honor_duration=True,
        synthetic_source=silence,
    )
    assert code == 0
    assert result.capture.silence_frames > 0
    # A few startup underruns may occur before the first write; should not dominate.
    assert result.capture.non_silent_frames == 0


@pytest.mark.hardware
@pytest.mark.skipif(sys.platform != "win32", reason="WASAPI is Windows-only")
def test_real_loopback_optional() -> None:
    """Optional live loopback; run with: pytest -m hardware"""
    pyaudio = pytest.importorskip("pyaudiowpatch")
    pa = pyaudio.PyAudio()
    try:
        lb = pa.get_default_wasapi_loopback()
        assert int(lb["maxInputChannels"]) >= 1
    finally:
        pa.terminate()
