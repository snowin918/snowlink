"""Unit tests for Experiment F synthetic audio track."""

from __future__ import annotations

from fractions import Fraction

import numpy as np
import pytest

from snowlink.rtc.synthetic_audio import (
    AUDIO_TIME_BASE,
    compute_audio_pts_series,
    generate_pcm_s16,
    pcm_to_audio_frame,
    schedule_audio_index,
)


def test_48k_20ms_produces_960_samples() -> None:
    pcm, _ = generate_pcm_s16(
        signal="sine",
        sample_rate=48_000,
        channels=2,
        samples=960,
        sample_index=0,
        frequency_hz=440.0,
        amplitude=0.15,
        pulse_interval_ms=1000,
    )
    assert pcm.shape == (960, 2)


def test_pts_series_sample_driven() -> None:
    pts = compute_audio_pts_series(samples_per_frame=960, frame_count=5)
    assert pts[0] == 0
    assert pts == [0, 960, 1920, 2880, 3840]
    assert all(pts[i] - pts[i - 1] == 960 for i in range(1, len(pts)))
    assert all(pts[i] > pts[i - 1] for i in range(1, len(pts)))


def test_audio_time_base_is_1_over_48000() -> None:
    assert AUDIO_TIME_BASE == Fraction(1, 48_000)


def test_sine_wave_amplitude_limits() -> None:
    pcm, is_silence = generate_pcm_s16(
        signal="sine",
        sample_rate=48_000,
        channels=2,
        samples=960,
        sample_index=0,
        frequency_hz=440.0,
        amplitude=0.15,
        pulse_interval_ms=1000,
    )
    assert not is_silence
    peak = float(np.max(np.abs(pcm.astype(np.float32) / 32768.0)))
    assert peak <= 0.16
    assert peak > 0.05
    assert pcm.dtype == np.int16
    assert np.array_equal(pcm[:, 0], pcm[:, 1])


def test_silence_frame_generation() -> None:
    pcm, is_silence = generate_pcm_s16(
        signal="silence",
        sample_rate=48_000,
        channels=2,
        samples=960,
        sample_index=0,
        frequency_hz=440.0,
        amplitude=0.15,
        pulse_interval_ms=1000,
    )
    assert is_silence
    assert np.all(pcm == 0)


def test_late_frame_schedule_behavior() -> None:
    next_index, late, lateness = schedule_audio_index(
        elapsed_s=0.1,
        frame_duration_s=0.02,
        next_index=2,
    )
    assert next_index == 5
    assert late == 3
    assert lateness > 0


@pytest.mark.asyncio
async def test_synthetic_audio_track_pts_and_time_base() -> None:
    pytest.importorskip("aiortc")
    pytest.importorskip("av")
    from snowlink.rtc.synthetic_audio import SyntheticAudioTrack

    track = SyntheticAudioTrack(
        sample_rate=48_000,
        channels=2,
        frame_ms=20,
        signal="sine",
        frequency_hz=440.0,
        amplitude=0.15,
    )
    try:
        frames = [await track.recv() for _ in range(4)]
        assert frames[0].pts == 0
        for i, frame in enumerate(frames):
            assert frame.pts == i * 960
            assert frame.time_base == Fraction(1, 48_000)
            assert frame.sample_rate == 48_000
            assert frame.samples == 960
            assert frame.format.name == "s16"
            assert frame.layout.nb_channels == 2
        assert track.frames_generated == 4
        assert track.samples_generated == 4 * 960
    finally:
        track.stop()


def test_pcm_to_audio_frame_sets_pts() -> None:
    pytest.importorskip("av")
    pcm, _ = generate_pcm_s16(
        signal="sine",
        sample_rate=48_000,
        channels=2,
        samples=960,
        sample_index=0,
        frequency_hz=440.0,
        amplitude=0.1,
        pulse_interval_ms=1000,
    )
    frame = pcm_to_audio_frame(pcm, sample_rate=48_000, pts=1920)
    assert frame.pts == 1920
    assert frame.time_base == Fraction(1, 48_000)
    assert frame.samples == 960
