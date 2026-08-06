"""Synthetic aiortc VideoStreamTrack for Experiment E.

Generates moving geometry with sequence numbers and sender monotonic timestamps.
Uses a 90 kHz RTP video clock and monotonic scheduling (no wall-clock media time).
"""

from __future__ import annotations

import asyncio
import time
from fractions import Fraction
from typing import Any

import numpy as np

from snowlink.rtc.models import VIDEO_CLOCK_RATE

try:
    from av import VideoFrame
except ImportError as exc:  # pragma: no cover - mapped by callers
    raise ImportError("PyAV (av) is required for synthetic video") from exc

try:
    from aiortc import VideoStreamTrack
    from aiortc.mediastreams import MediaStreamError
except ImportError as exc:  # pragma: no cover
    raise ImportError("aiortc is required for synthetic video") from exc


VIDEO_TIME_BASE = Fraction(1, VIDEO_CLOCK_RATE)


def render_synthetic_bgr(
    *,
    width: int,
    height: int,
    sequence: int,
    sender_monotonic_ns: int,
    fps: int,
) -> np.ndarray:
    """Render one synthetic BGR frame (uint8 HxWx3) without disk I/O."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    # Moving background gradient band — continuous visual change for the encoder.
    t = sequence / max(fps, 1)
    band = int((sequence * 7) % max(height, 1))
    frame[:, :, 0] = (40 + (sequence * 3) % 80) & 0xFF
    frame[:, :, 1] = (20 + (sequence * 5) % 100) & 0xFF
    frame[:, :, 2] = (60 + (sequence * 2) % 90) & 0xFF
    y0 = max(0, band - 8)
    y1 = min(height, band + 8)
    frame[y0:y1, :, :] = (frame[y0:y1, :, :] // 2) + np.array([180, 180, 40], dtype=np.uint8)

    # Moving filled rectangle.
    box_w = max(24, width // 8)
    box_h = max(24, height // 8)
    cx = int((0.5 + 0.4 * np.sin(t * 1.7)) * (width - box_w))
    cy = int((0.5 + 0.4 * np.cos(t * 1.3)) * (height - box_h))
    cx = max(0, min(width - box_w, cx))
    cy = max(0, min(height - box_h, cy))
    frame[cy : cy + box_h, cx : cx + box_w] = (40, 220, 40)

    # Moving circle (filled via distance mask).
    radius = max(12, min(width, height) // 16)
    ox = int((0.5 + 0.35 * np.cos(t * 2.1)) * (width - 1))
    oy = int((0.5 + 0.35 * np.sin(t * 1.9)) * (height - 1))
    yy, xx = np.ogrid[:height, :width]
    mask = (xx - ox) ** 2 + (yy - oy) ** 2 <= radius**2
    frame[mask] = (220, 80, 40)

    # Corner markers for scaling checks.
    m = max(4, min(width, height) // 40)
    frame[0:m, 0:m] = (255, 255, 255)
    frame[0:m, width - m : width] = (0, 255, 255)
    frame[height - m : height, 0:m] = (255, 0, 255)
    frame[height - m : height, width - m : width] = (255, 255, 0)

    _draw_hud(
        frame,
        sequence=sequence,
        sender_monotonic_ns=sender_monotonic_ns,
        width=width,
        height=height,
        fps=fps,
    )
    return frame


def _draw_hud(
    frame: np.ndarray,
    *,
    sequence: int,
    sender_monotonic_ns: int,
    width: int,
    height: int,
    fps: int,
) -> None:
    """Overlay sequence / timing text using OpenCV Hershey fonts when available."""
    lines = [
        f"seq={sequence}",
        f"mono_ns={sender_monotonic_ns}",
        f"{width}x{height}@{fps}",
        f"t={sequence / max(fps, 1):.3f}s",
    ]
    try:
        import cv2
    except ImportError:
        # Fallback: burn a simple binary barcode for sequence in the top row.
        bits = sequence & 0xFFFF
        for i in range(16):
            color = 255 if (bits >> i) & 1 else 0
            x0 = 8 + i * 8
            frame[4:12, x0 : x0 + 6] = color
        return

    y = 28
    for text in lines:
        cv2.putText(
            frame,
            text,
            (12, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            text,
            (12, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
        y += 28


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


class SyntheticVideoTrack(VideoStreamTrack):
    """Custom VideoStreamTrack producing synthetic yuv420p frames at a fixed FPS."""

    kind = "video"

    def __init__(
        self,
        *,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
    ) -> None:
        super().__init__()
        if width < 16 or height < 16:
            raise ValueError("width/height too small")
        if fps < 1:
            raise ValueError("fps must be >= 1")
        self.width = width
        self.height = height
        self.fps = fps
        self._frame_interval = 1.0 / float(fps)
        self._start_mono: float | None = None
        self._next_index = 0
        self._last_pts = -1
        self._frames_generated = 0
        self._frames_skipped = 0
        self._stopped = False
        self._stop_event = asyncio.Event()

    @property
    def frames_generated(self) -> int:
        return self._frames_generated

    @property
    def frames_skipped(self) -> int:
        return self._frames_skipped

    def stop(self) -> None:
        self._stopped = True
        self._stop_event.set()
        super().stop()

    async def recv(self) -> Any:
        if self._stopped:
            raise MediaStreamError

        now = time.perf_counter()
        if self._start_mono is None:
            self._start_mono = now

        # Skip forward to the current schedule when behind (do not backlog).
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
            if self._stopped:
                raise MediaStreamError

        # Re-check schedule after sleep in case we still fell behind.
        now = time.perf_counter()
        assert self._start_mono is not None
        elapsed = now - self._start_mono
        due_index = int(elapsed / self._frame_interval)
        if due_index > self._next_index:
            skipped = due_index - self._next_index
            self._frames_skipped += skipped
            self._next_index = due_index

        sequence = self._next_index
        sender_mono_ns = time.perf_counter_ns()
        pts = int(round(elapsed * VIDEO_CLOCK_RATE))
        if pts <= self._last_pts:
            pts = self._last_pts + 1
        self._last_pts = pts

        bgr = render_synthetic_bgr(
            width=self.width,
            height=self.height,
            sequence=sequence,
            sender_monotonic_ns=sender_mono_ns,
            fps=self.fps,
        )
        frame = bgr_to_video_frame(bgr, pts=pts, time_base=VIDEO_TIME_BASE)

        self._next_index = sequence + 1
        self._frames_generated += 1
        return frame


def compute_pts_series(
    *,
    fps: int,
    frame_count: int,
    clock_rate: int = VIDEO_CLOCK_RATE,
) -> list[int]:
    """Exact rational PTS schedule for tests (no sleep)."""
    pts_list: list[int] = []
    last = -1
    for i in range(frame_count):
        pts = int(round((i / float(fps)) * clock_rate))
        if pts <= last:
            pts = last + 1
        pts_list.append(pts)
        last = pts
    return pts_list


def schedule_with_skips(
    *,
    fps: int,
    elapsed_s: float,
    next_index: int,
) -> tuple[int, int]:
    """Return (new_next_index, skipped) when catching up to *elapsed_s*."""
    due = int(elapsed_s * fps)
    if due > next_index:
        return due, due - next_index
    return next_index, 0
