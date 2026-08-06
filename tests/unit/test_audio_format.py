"""Unit tests for audio format conversion, PTS, and frame sizing."""

from __future__ import annotations

import numpy as np

from snowlink.media.audio_format import (
    AudioFormatConverter,
    AudioPtsClock,
    convert_channels,
    is_silent_frame,
    samples_per_frame,
    silence_frame,
)


def test_frame_size_20ms_48k_is_960() -> None:
    assert samples_per_frame(48_000, 20) == 960


def test_sample_driven_pts_progression() -> None:
    clock = AudioPtsClock(sample_rate=48_000)
    assert clock.peek() == 0
    pts0 = clock.advance(960)
    pts1 = clock.advance(960)
    pts2 = clock.advance(960)
    assert pts0 == 0
    assert pts1 == 960
    assert pts2 == 1920
    assert clock.peek() == 2880
    # Silence / underrun still advances via advance().
    pts3 = clock.advance(960)
    assert pts3 == 2880
    assert clock.peek() == 3840


def test_channel_conversion_mono_to_stereo() -> None:
    mono = np.array([[0.25], [-0.5]], dtype=np.float32)
    stereo = convert_channels(mono, source_channels=1, target_channels=2)
    assert stereo.shape == (2, 2)
    assert float(stereo[0, 0]) == 0.25
    assert float(stereo[0, 1]) == 0.25


def test_channel_conversion_stereo_to_mono() -> None:
    stereo = np.array([[1.0, -1.0], [0.5, 0.5]], dtype=np.float32)
    mono = convert_channels(stereo, source_channels=2, target_channels=1)
    assert mono.shape == (2, 1)
    assert float(mono[0, 0]) == 0.0
    assert float(mono[1, 0]) == 0.5


def test_partial_chunk_accumulation() -> None:
    conv = AudioFormatConverter(
        source_rate=48_000,
        source_channels=2,
        target_rate=48_000,
        target_channels=2,
        frame_duration_ms=20,
        prefer_pyav=False,
    )
    # 400 + 400 + 160 = 960
    chunk = np.zeros((400, 2), dtype=np.float32)
    chunk[:, :] = 0.1
    assert conv.push(chunk) == []
    assert conv.push(chunk) == []
    frames = conv.push(np.full((160, 2), 0.1, dtype=np.float32))
    assert len(frames) == 1
    assert frames[0].sample_count == 960
    assert frames[0].pts == 0
    frames2 = conv.push(np.full((960, 2), 0.2, dtype=np.float32))
    assert len(frames2) == 1
    assert frames2[0].pts == 960
    assert frames2[0].pts > frames[0].pts


def test_silence_frame_generation() -> None:
    frame = silence_frame(960, channels=2, underrun_padding=True)
    assert frame.is_silence
    assert frame.is_underrun_padding
    assert frame.samples.shape == (960, 2)
    assert is_silent_frame(frame.samples)


def test_resample_44k_to_48k_partial_chunks() -> None:
    conv = AudioFormatConverter(
        source_rate=44_100,
        source_channels=1,
        target_rate=48_000,
        target_channels=2,
        frame_duration_ms=20,
        prefer_pyav=False,
    )
    # Feed ~100 ms of mono 44.1 kHz.
    n = int(44_100 * 0.1)
    t = np.linspace(0, 1, n, dtype=np.float32)
    mono = (0.2 * np.sin(2 * np.pi * 440 * t)).reshape(-1, 1)
    frames = conv.push(mono)
    assert conv.input_samples == n
    assert len(frames) >= 1
    for f in frames:
        assert f.sample_count == 960
        assert f.channels == 2
    # PTS strictly increasing
    pts = [f.pts for f in frames]
    assert pts == sorted(pts)
    assert len(set(pts)) == len(pts)
