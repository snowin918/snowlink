"""DXcam-backed aiortc VideoStreamTrack for Phase 1 screen share.

Pulls latest BGR frames from a depth-1 :class:`~snowlink.media.frame_slot.LatestFrameSlot`
(fed by :class:`~snowlink.media.screen_capture.ScreenCaptureSession`), converts via
PyAV to yuv420p, and stamps PTS from a session-epoch monotonic clock.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from fractions import Fraction
from typing import Any

import numpy as np

from snowlink.media.frame_slot import LatestFrameSlot, SlotItem
from snowlink.media.scaling import scale_frame_letterbox
from snowlink.rtc.models import VIDEO_CLOCK_RATE

try:
    from av import VideoFrame
except ImportError as exc:  # pragma: no cover - mapped by callers
    raise ImportError("PyAV (av) is required for screen video tracks") from exc

try:
    from aiortc import VideoStreamTrack
    from aiortc.mediastreams import MediaStreamError
except ImportError as exc:  # pragma: no cover
    raise ImportError("aiortc is required for screen video tracks") from exc

VIDEO_TIME_BASE = Fraction(1, VIDEO_CLOCK_RATE)


def bgr_to_video_frame(
    bgr: np.ndarray,
    *,
    pts: int,
    time_base: Fraction = VIDEO_TIME_BASE,
) -> Any:
    """Convert a BGR numpy array to a PyAV VideoFrame in yuv420p."""
    frame = VideoFrame.from_ndarray(bgr, format="bgr24")
    frame = frame.reformat(format="yuv420p")
    frame.pts = pts
    frame.time_base = time_base
    return frame


def solid_bgr_placeholder(*, width: int, height: int) -> np.ndarray:
    """Dark placeholder used when no capture frame is available yet."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :] = (24, 24, 24)
    return frame


class ScreenVideoTrack(VideoStreamTrack):
    """Custom VideoStreamTrack that publishes latest-frame screen captures."""

    kind = "video"

    def __init__(
        self,
        slot: LatestFrameSlot[Any],
        *,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        scale: bool = True,
        session_epoch_ns: int | None = None,
        wait_timeout_s: float = 0.05,
        placeholder_factory: Callable[[], np.ndarray] | None = None,
    ) -> None:
        super().__init__()
        if width < 16 or height < 16:
            raise ValueError("width/height too small")
        if fps < 1:
            raise ValueError("fps must be >= 1")
        self.slot = slot
        self.width = width
        self.height = height
        self.fps = fps
        self.scale = scale
        self.wait_timeout_s = wait_timeout_s
        self._frame_interval = 1.0 / float(fps)
        self._session_epoch_ns = (
            session_epoch_ns if session_epoch_ns is not None else time.perf_counter_ns()
        )
        self._start_mono: float | None = None
        self._next_index = 0
        self._last_pts = -1
        self._last_sequence = -1
        self._frames_generated = 0
        self._frames_skipped = 0
        self._stale_drops = 0
        self._placeholder_emits = 0
        self._stopped = False
        self._stop_event = asyncio.Event()
        self._placeholder_factory = placeholder_factory or (
            lambda: solid_bgr_placeholder(width=self.width, height=self.height)
        )
        self._last_bgr: np.ndarray | None = None

    @property
    def session_epoch_ns(self) -> int:
        return self._session_epoch_ns

    @property
    def frames_generated(self) -> int:
        return self._frames_generated

    @property
    def frames_skipped(self) -> int:
        return self._frames_skipped

    @property
    def stale_drops(self) -> int:
        return self._stale_drops

    @property
    def placeholder_emits(self) -> int:
        return self._placeholder_emits

    def stop(self) -> None:
        self._stopped = True
        self._stop_event.set()
        super().stop()

    def _prepare_bgr(self, item: SlotItem[Any] | None) -> np.ndarray:
        if item is None:
            if self._last_bgr is not None:
                return self._last_bgr
            self._placeholder_emits += 1
            return self._placeholder_factory()

        payload = item.payload
        if not isinstance(payload, np.ndarray) or payload.ndim != 3 or payload.shape[2] < 3:
            if self._last_bgr is not None:
                return self._last_bgr
            self._placeholder_emits += 1
            return self._placeholder_factory()

        bgr = payload[:, :, :3]
        if self.scale and (bgr.shape[1] != self.width or bgr.shape[0] != self.height):
            bgr = scale_frame_letterbox(bgr, self.width, self.height)
        self._last_bgr = bgr
        if item.sequence <= self._last_sequence:
            self._stale_drops += 1
        self._last_sequence = max(self._last_sequence, item.sequence)
        return bgr

    async def recv(self) -> Any:
        if self._stopped or self.slot.closed:
            raise MediaStreamError

        now = time.perf_counter()
        if self._start_mono is None:
            self._start_mono = now

        elapsed = now - self._start_mono
        due_index = int(elapsed / self._frame_interval)
        if due_index > self._next_index:
            skipped = due_index - self._next_index
            self._frames_skipped += skipped
            self._next_index = due_index

        target = self._start_mono + (self._next_index * self._frame_interval)
        delay = target - time.perf_counter()
        if delay > 0:
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            except TimeoutError:
                pass
            if self._stopped or self.slot.closed:
                raise MediaStreamError

        # Prefer waiting briefly for a fresh frame rather than spinning placeholders.
        if not self.slot.has_frame():
            await asyncio.to_thread(self.slot.wait_for_frame, self.wait_timeout_s)

        if self._stopped or self.slot.closed:
            raise MediaStreamError

        item = self.slot.take(clear=True)
        bgr = self._prepare_bgr(item)

        now = time.perf_counter()
        assert self._start_mono is not None
        elapsed = now - self._start_mono
        due_index = int(elapsed / self._frame_interval)
        if due_index > self._next_index:
            skipped = due_index - self._next_index
            self._frames_skipped += skipped
            self._next_index = due_index

        sequence = self._next_index
        pts = int(round(elapsed * VIDEO_CLOCK_RATE))
        if pts <= self._last_pts:
            pts = self._last_pts + 1
        self._last_pts = pts

        frame = bgr_to_video_frame(bgr, pts=pts, time_base=VIDEO_TIME_BASE)
        self._next_index = sequence + 1
        self._frames_generated += 1
        return frame
