"""Unit tests for synthetic video track helpers."""

from __future__ import annotations

from fractions import Fraction

import numpy as np
import pytest

from snowlink.rtc.models import VIDEO_CLOCK_RATE
from snowlink.rtc.synthetic_video import (
    VIDEO_TIME_BASE,
    bgr_to_video_frame,
    compute_pts_series,
    render_synthetic_bgr,
    schedule_with_skips,
)


def test_render_synthetic_bgr_shape_and_motion() -> None:
    a = render_synthetic_bgr(
        width=160, height=90, sequence=0, sender_monotonic_ns=1, fps=30
    )
    b = render_synthetic_bgr(
        width=160, height=90, sequence=15, sender_monotonic_ns=2, fps=30
    )
    assert a.shape == (90, 160, 3)
    assert a.dtype == np.uint8
    assert not np.array_equal(a, b)


def test_sequence_progression_in_hud_region() -> None:
    # Frames should differ across sequence numbers (moving geometry).
    frames = [
        render_synthetic_bgr(
            width=128, height=72, sequence=i, sender_monotonic_ns=i * 1_000_000, fps=30
        )
        for i in range(5)
    ]
    assert any(not np.array_equal(frames[0], frames[i]) for i in range(1, 5))


def test_pts_series_90khz_monotonic_no_duplicates() -> None:
    pts = compute_pts_series(fps=30, frame_count=90)
    assert pts[0] == 0
    assert pts[1] == VIDEO_CLOCK_RATE // 30
    for i in range(1, len(pts)):
        assert pts[i] > pts[i - 1]
    assert len(pts) == len(set(pts))


def test_time_base_is_90khz() -> None:
    assert VIDEO_TIME_BASE == Fraction(1, VIDEO_CLOCK_RATE)


def test_schedule_skip_forward() -> None:
    next_index, skipped = schedule_with_skips(fps=30, elapsed_s=1.0, next_index=5)
    assert next_index == 30
    assert skipped == 25
    next_index2, skipped2 = schedule_with_skips(fps=30, elapsed_s=0.1, next_index=5)
    assert next_index2 == 5
    assert skipped2 == 0


def test_bgr_to_video_frame_yuv420p_pts() -> None:
    pytest.importorskip("av")
    bgr = render_synthetic_bgr(
        width=64, height=48, sequence=3, sender_monotonic_ns=123, fps=30
    )
    frame = bgr_to_video_frame(bgr, pts=3000)
    assert frame.pts == 3000
    assert frame.time_base == VIDEO_TIME_BASE
    assert frame.format.name == "yuv420p"


@pytest.mark.asyncio
async def test_synthetic_track_recv_pts_and_skip() -> None:
    pytest.importorskip("aiortc")
    from snowlink.rtc.synthetic_video import SyntheticVideoTrack

    track = SyntheticVideoTrack(width=64, height=48, fps=50)
    frames = []
    for _ in range(3):
        frames.append(await track.recv())
    track.stop()
    pts = [f.pts for f in frames]
    assert pts == sorted(pts)
    assert len(pts) == len(set(pts))
    for f in frames:
        assert f.time_base == VIDEO_TIME_BASE
        assert f.format.name == "yuv420p"
