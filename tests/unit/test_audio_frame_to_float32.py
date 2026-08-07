"""Unit tests for remote audio frame → float32 conversion."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from snowlink.rtc.audio_receiver import audio_frame_to_float32


class _FakeLayout:
    def __init__(self, channels: int) -> None:
        self.nb_channels = channels
        self.name = "stereo" if channels == 2 else "mono"


class _FakeFormat:
    def __init__(self, name: str) -> None:
        self.name = name


def test_packed_s16_stereo_row_reshapes_to_interleaved() -> None:
    """PyAV packed s16 stereo often returns shape (1, samples*channels)."""
    samples = 960
    channels = 2
    # Interleaved LRLR… pattern so reshape errors are obvious.
    packed = np.empty((1, samples * channels), dtype=np.int16)
    packed[0, 0::2] = 1000
    packed[0, 1::2] = -2000
    frame = SimpleNamespace(
        layout=_FakeLayout(channels),
        format=_FakeFormat("s16"),
        samples=samples,
        planes=[packed.tobytes()],
        to_ndarray=lambda: packed.copy(),
    )
    pcm = audio_frame_to_float32(frame)
    assert pcm.shape == (samples, channels)
    assert abs(float(pcm[0, 0]) - 1000 / 32768.0) < 1e-6
    assert abs(float(pcm[0, 1]) - (-2000 / 32768.0)) < 1e-6


def test_planar_stereo_transposes_to_interleaved() -> None:
    samples = 960
    planar = np.zeros((2, samples), dtype=np.int16)
    planar[0, :] = 3000
    planar[1, :] = -3000
    frame = SimpleNamespace(
        layout=_FakeLayout(2),
        format=_FakeFormat("s16"),
        samples=samples,
        planes=[b""],
        to_ndarray=lambda: planar.copy(),
    )
    pcm = audio_frame_to_float32(frame)
    assert pcm.shape == (samples, 2)
    assert abs(float(pcm[10, 0]) - 3000 / 32768.0) < 1e-6
    assert abs(float(pcm[10, 1]) - (-3000 / 32768.0)) < 1e-6


def test_already_interleaved_passthrough() -> None:
    samples = 960
    interleaved = np.zeros((samples, 2), dtype=np.float32)
    interleaved[:, 0] = 0.5
    frame = SimpleNamespace(
        layout=_FakeLayout(2),
        format=_FakeFormat("fltp"),
        samples=samples,
        planes=[b""],
        to_ndarray=lambda: interleaved.copy(),
    )
    pcm = audio_frame_to_float32(frame)
    assert pcm.shape == (samples, 2)
    assert float(pcm[0, 0]) == 0.5
