"""Receiver A/V sync: audio-primary clock with video drop / hold policy."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class AvSyncController:
    """Track audio playhead and decide whether a video frame should paint.

    Audio is the primary timing reference. Video frames that lag the playhead
    beyond *drop_behind_ms* are dropped; frames far ahead are dropped to avoid
    backlog.

    Media clocks (sender wall/RTP PTS vs local samples_played) are not aligned
    absolutely — on the first healthy observation we latch an offset so skew is
    measured relatively. When audio is unhealthy, video paints freely.
    """

    drop_behind_ms: float = 90.0
    hold_ahead_ms: float = 40.0
    hard_resync_ms: float = 250.0
    audio_playhead_pts_ms: float | None = None
    last_video_pts_ms: float | None = None
    av_skew_ms: float | None = None
    dropped_for_sync: int = 0
    audio_healthy: bool = False
    _pts_offset_ms: float | None = None
    _updated_at_mono: float = 0.0

    def set_audio_healthy(self, healthy: bool) -> None:
        self.audio_healthy = bool(healthy)
        if not healthy:
            # Force re-latch when audio recovers after a long stall.
            self._pts_offset_ms = None

    def observe_audio_pts_ms(self, pts_ms: float) -> None:
        self.audio_playhead_pts_ms = float(pts_ms)
        self._updated_at_mono = time.monotonic()
        self._recompute_skew()

    def observe_audio_samples(
        self,
        *,
        samples: int,
        sample_rate: int,
    ) -> None:
        if sample_rate <= 0:
            return
        self.observe_audio_pts_ms(1000.0 * float(samples) / float(sample_rate))

    def _aligned_audio_pts(self) -> float | None:
        if self.audio_playhead_pts_ms is None:
            return None
        if self._pts_offset_ms is None:
            return self.audio_playhead_pts_ms
        return self.audio_playhead_pts_ms + self._pts_offset_ms

    def _recompute_skew(self) -> None:
        audio = self._aligned_audio_pts()
        if audio is None or self.last_video_pts_ms is None:
            return
        self.av_skew_ms = self.last_video_pts_ms - audio

    def should_paint_video(self, video_pts_ms: float | None) -> bool:
        """Return True if the frame should be painted; False to drop."""
        if video_pts_ms is not None:
            self.last_video_pts_ms = video_pts_ms

        if (
            video_pts_ms is None
            or self.audio_playhead_pts_ms is None
            or not self.audio_healthy
        ):
            return True

        # Latch clock offset once both clocks are alive so absolute domains
        # (sender PTS vs local playback samples) do not look like huge skew.
        if self._pts_offset_ms is None:
            self._pts_offset_ms = float(video_pts_ms) - float(self.audio_playhead_pts_ms)
            self.av_skew_ms = 0.0
            return True

        skew = float(video_pts_ms) - (float(self.audio_playhead_pts_ms) + self._pts_offset_ms)
        self.av_skew_ms = skew

        # Extreme skew usually means clocks drifted or stalled — re-latch
        # instead of freezing the picture for the rest of the session.
        if abs(skew) > 2000.0:
            self._pts_offset_ms = float(video_pts_ms) - float(self.audio_playhead_pts_ms)
            self.av_skew_ms = 0.0
            return True

        if skew < -self.drop_behind_ms:
            self.dropped_for_sync += 1
            return False
        if skew > self.hard_resync_ms:
            # Far ahead — drop to resync rather than backlog.
            self.dropped_for_sync += 1
            return False
        return True
