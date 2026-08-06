"""Unit tests for LoopbackAudioTrack (synthetic feed, no WASAPI)."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from snowlink.media.audio_format import samples_per_frame
from snowlink.media.audio_track import LoopbackAudioTrack, ShareAudioCapture


@pytest.mark.asyncio
async def test_loopback_audio_track_recv_synthetic() -> None:
    pytest.importorskip("aiortc")
    pytest.importorskip("av")

    frame_n = samples_per_frame(48_000, 20)
    t = {"n": 0}

    def feed() -> np.ndarray:
        t["n"] += 1
        # Soft tone-ish float32 stereo.
        phase = (np.arange(frame_n) + t["n"] * frame_n) / 48_000.0
        mono = (0.05 * np.sin(2.0 * np.pi * 440.0 * phase)).astype(np.float32)
        return np.repeat(mono.reshape(-1, 1), 2, axis=1)

    source = ShareAudioCapture.start(synthetic_feed=feed)
    track = LoopbackAudioTrack(source)
    try:
        frame = await asyncio.wait_for(track.recv(), timeout=2.0)
        assert frame.pts is not None
        assert frame.pts >= 0
        assert track.frames_generated >= 1
        frame2 = await asyncio.wait_for(track.recv(), timeout=2.0)
        assert int(frame2.pts) > int(frame.pts)
    finally:
        track.stop()
        source.shutdown()
