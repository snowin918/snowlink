"""Latest-frame video consumer and optional OpenCV preview for Experiment E."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from snowlink.media.frame_slot import LatestFrameSlot
from snowlink.rtc.errors import WebRTCError, failure_for


@dataclass(slots=True)
class DecodedFrame:
    bgr: np.ndarray
    sequence: int | None
    received_at_ns: int
    pts: int | None = None


_SEQ_RE = re.compile(r"seq=(\d+)")


def parse_sequence_from_overlay(bgr: np.ndarray) -> int | None:
    """Best-effort OCR-free sequence extraction is not available; return None.

    Sequence is primarily tracked by embedding in HUD text for human inspection.
    Automated tests use SyntheticVideoTrack metrics / PTS; receivers may also
    pass sequence via an out-of-band counter when the sender increments steadily.
    """
    _ = bgr
    return None


def extract_sequence_hint(text: str) -> int | None:
    match = _SEQ_RE.search(text)
    if not match:
        return None
    return int(match.group(1))


class RemoteVideoConsumer:
    """Continuously drains ``remote_track.recv()`` into a depth-1 frame slot."""

    def __init__(self) -> None:
        self.slot: LatestFrameSlot[DecodedFrame] = LatestFrameSlot()
        self.frames_received = 0
        self.frames_decoded = 0
        self.decode_failures = 0
        self._task: asyncio.Task[None] | None = None
        self._stopped = False
        self.first_frame_at_ns: int | None = None
        self.last_frame_at_ns: int | None = None
        self._sequence_counter = 0

    async def start(self, track: Any) -> None:
        self._stopped = False
        self._task = asyncio.create_task(self._loop(track), name="remote-video-consumer")

    async def _loop(self, track: Any) -> None:
        while not self._stopped:
            try:
                frame = await track.recv()
            except Exception:
                break
            recv_ns = time.perf_counter_ns()
            self.frames_received += 1
            if self.first_frame_at_ns is None:
                self.first_frame_at_ns = recv_ns
            self.last_frame_at_ns = recv_ns
            try:
                # Prefer BGR for OpenCV preview.
                img = frame.to_ndarray(format="bgr24")
            except Exception:
                self.decode_failures += 1
                continue
            self.frames_decoded += 1
            # Local monotonic receive counter (cross-machine seq is in the HUD).
            self._sequence_counter += 1
            decoded = DecodedFrame(
                bgr=img,
                sequence=self._sequence_counter,
                received_at_ns=recv_ns,
                pts=getattr(frame, "pts", None),
            )
            self.slot.publish(decoded, captured_at_ns=recv_ns)

    async def stop(self) -> None:
        self._stopped = True
        self.slot.close()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._task = None


def run_preview_loop(
    slot: LatestFrameSlot[DecodedFrame],
    *,
    window_name: str = "Snowlink Experiment E",
    stop_event: asyncio.Event | None = None,
    get_fps: Any | None = None,
) -> int:
    """Blocking OpenCV preview loop (call from a worker thread).

    Returns the number of frames rendered. Escape or window close ends the loop.
    """
    try:
        import cv2
    except ImportError as exc:
        raise WebRTCError(
            failure_for(
                "PREVIEW_FAILED",
                "OpenCV is not installed; use --no-preview or install .[webrtc].",
                exception=exc,
            )
        ) from exc

    rendered = 0
    try:
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    except Exception as exc:
        raise WebRTCError(
            failure_for(
                "PREVIEW_FAILED",
                "Could not create OpenCV preview window.",
                exception=exc,
            )
        ) from exc

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            if slot.closed and not slot.has_frame():
                break
            item = slot.take(clear=True)
            if item is None:
                slot.wait_for_frame(timeout=0.05)
                # Check whether the window was closed.
                try:
                    if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                        break
                except Exception:
                    break
                continue
            frame = item.payload.bgr
            title = window_name
            if get_fps is not None:
                try:
                    fps = get_fps()
                    if fps is not None:
                        title = f"{window_name}  recv_fps={fps:.1f}"
                except Exception:
                    pass
            try:
                cv2.setWindowTitle(window_name, title)
                cv2.imshow(window_name, frame)
                key = cv2.waitKey(1) & 0xFF
            except Exception as exc:
                raise WebRTCError(
                    failure_for(
                        "PREVIEW_FAILED",
                        "OpenCV preview update failed.",
                        exception=exc,
                    )
                ) from exc
            rendered += 1
            if key == 27:  # Escape
                break
            try:
                if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                    break
            except Exception:
                break
    finally:
        try:
            cv2.destroyWindow(window_name)
        except Exception:
            pass
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
    return rendered
