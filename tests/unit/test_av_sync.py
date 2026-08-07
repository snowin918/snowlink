"""Unit tests for audio-primary A/V sync controller."""

from __future__ import annotations

from snowlink.rtc.av_sync import AvSyncController


def test_drop_behind_playhead() -> None:
    sync = AvSyncController(drop_behind_ms=90.0)
    sync.set_audio_healthy(True)
    sync.observe_audio_pts_ms(1000.0)
    # First paint latches offset (850 - 1000 = -150); paints freely.
    assert sync.should_paint_video(850.0) is True
    # After latch, video still 150ms behind relative → drop.
    sync.observe_audio_pts_ms(1100.0)
    assert sync.should_paint_video(850.0) is False
    assert sync.dropped_for_sync == 1


def test_paint_near_playhead() -> None:
    sync = AvSyncController()
    sync.set_audio_healthy(True)
    sync.observe_audio_pts_ms(1000.0)
    assert sync.should_paint_video(1010.0) is True  # latches offset=+10
    sync.observe_audio_pts_ms(1020.0)
    assert sync.should_paint_video(1030.0) is True  # relative skew ~0
    assert sync.av_skew_ms is not None
    assert abs(sync.av_skew_ms) < 1.0


def test_paint_without_audio_clock() -> None:
    sync = AvSyncController()
    assert sync.should_paint_video(100.0) is True


def test_unhealthy_audio_skips_sync_drops() -> None:
    sync = AvSyncController()
    sync.set_audio_healthy(False)
    sync.observe_audio_pts_ms(1000.0)
    assert sync.should_paint_video(850.0) is True
    assert sync.dropped_for_sync == 0


def test_extreme_skew_relatches_instead_of_freezing() -> None:
    sync = AvSyncController()
    sync.set_audio_healthy(True)
    sync.observe_audio_pts_ms(0.0)
    assert sync.should_paint_video(0.0) is True
    sync.observe_audio_pts_ms(100.0)
    # Jump video PTS by several seconds → re-latch, still paint.
    assert sync.should_paint_video(5000.0) is True
    assert sync.dropped_for_sync == 0
