"""Unit tests for session stats sampler."""

from __future__ import annotations

import time

from snowlink.stats import SessionStats, StatsSampler


def test_session_stats_format_lines() -> None:
    stats = SessionStats(
        capture_fps=14.5,
        render_fps=14.2,
        width=854,
        height=480,
        estimated_bitrate_kbps=1200.0,
        rtt_ms=18.0,
        packet_loss=0.01,
        dropped_video_frames=3,
        audio_underruns=1,
        av_skew_ms=12.0,
    )
    text = "\n".join(stats.format_lines())
    assert "14.5" in text
    assert "854×480" in text
    assert "1.0%" in text
    assert "Dropped video: 3" in text
    assert "A/V skew" in text


def test_stats_sampler_fps_share() -> None:
    sampler = StatsSampler(width=640, height=360)
    first = sampler.observe_local(video_frames=0, role="share")
    assert first.capture_fps == 0.0 or first.capture_fps is not None
    time.sleep(0.05)
    second = sampler.observe_local(video_frames=10, role="share")
    assert second.capture_fps is not None
    assert second.capture_fps > 0
    assert second.width == 640
    assert second.height == 360


def test_stats_sampler_view_sets_render_fps() -> None:
    sampler = StatsSampler()
    sampler.observe_local(video_frames=0, role="view")
    time.sleep(0.05)
    snap = sampler.observe_local(video_frames=5, role="view")
    assert snap.render_fps is not None
    assert snap.render_fps > 0
