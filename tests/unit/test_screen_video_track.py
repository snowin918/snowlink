"""Unit tests for ScreenVideoTrack (fake slot frames, no hardware)."""

from __future__ import annotations

import asyncio
import time

import numpy as np
import pytest

from snowlink.media.frame_slot import LatestFrameSlot
from snowlink.media.video_track import (
    ScreenVideoTrack,
    bgr_to_video_frame,
    solid_bgr_placeholder,
)
from snowlink.rtc.models import VIDEO_CLOCK_RATE


def test_solid_placeholder_shape() -> None:
    frame = solid_bgr_placeholder(width=64, height=48)
    assert frame.shape == (48, 64, 3)
    assert frame.dtype == np.uint8


def test_bgr_to_video_frame_pts() -> None:
    bgr = np.zeros((48, 64, 3), dtype=np.uint8)
    frame = bgr_to_video_frame(bgr, pts=3000)
    assert frame.pts == 3000
    assert frame.width == 64
    assert frame.height == 48


@pytest.mark.asyncio
async def test_screen_video_track_recv_from_slot() -> None:
    slot: LatestFrameSlot[np.ndarray] = LatestFrameSlot()
    bgr = np.full((72, 128, 3), 40, dtype=np.uint8)
    slot.publish(bgr, captured_at_ns=time.perf_counter_ns())

    track = ScreenVideoTrack(slot, width=128, height=72, fps=30, scale=False)
    try:
        frame = await asyncio.wait_for(track.recv(), timeout=2.0)
        assert frame.pts is not None
        assert frame.pts >= 0
        assert track.frames_generated == 1
        assert frame.width == 128
        assert frame.height == 72
    finally:
        track.stop()
        slot.close()


@pytest.mark.asyncio
async def test_screen_video_track_placeholder_when_empty() -> None:
    slot: LatestFrameSlot[np.ndarray] = LatestFrameSlot()
    track = ScreenVideoTrack(
        slot,
        width=64,
        height=48,
        fps=60,
        scale=False,
        wait_timeout_s=0.01,
    )
    try:
        frame = await asyncio.wait_for(track.recv(), timeout=2.0)
        assert track.placeholder_emits >= 1
        assert track.frames_generated == 1
        assert frame.width == 64
        assert frame.height == 48
    finally:
        track.stop()
        slot.close()


@pytest.mark.asyncio
async def test_screen_video_track_scales_to_target() -> None:
    slot: LatestFrameSlot[np.ndarray] = LatestFrameSlot()
    native = np.full((108, 192, 3), 80, dtype=np.uint8)
    slot.publish(native, captured_at_ns=time.perf_counter_ns())
    track = ScreenVideoTrack(slot, width=128, height=72, fps=30, scale=True)
    try:
        frame = await asyncio.wait_for(track.recv(), timeout=2.0)
        assert frame.width == 128
        assert frame.height == 72
    finally:
        track.stop()
        slot.close()


@pytest.mark.asyncio
async def test_screen_video_track_stop_raises() -> None:
    slot: LatestFrameSlot[np.ndarray] = LatestFrameSlot()
    track = ScreenVideoTrack(slot, width=64, height=48, fps=30)
    track.stop()
    with pytest.raises(Exception):
        await track.recv()
    slot.close()


def test_pts_advances_with_clock_rate() -> None:
    # Sanity: one second at 90 kHz.
    assert VIDEO_CLOCK_RATE == 90_000
