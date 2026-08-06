"""Thread-safe latest-frame / depth-1 frame slot.

Publishers replace any unread frame; consumers always receive the newest frame.
Overwritten frames are counted so Experiment C can report drop behavior without
unbounded memory growth.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(slots=True)
class SlotItem[T]:
    """A published frame payload with capture metadata."""

    payload: T
    captured_at_ns: int
    sequence: int


class LatestFrameSlot[T]:
    """Depth-1 frame slot: at most one pending frame is retained."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._item: SlotItem[T] | None = None
        self._sequence = 0
        self._overwritten = 0
        self._published = 0
        self._closed = False
        self._new_frame = threading.Event()

    @property
    def overwritten_count(self) -> int:
        with self._lock:
            return self._overwritten

    @property
    def published_count(self) -> int:
        with self._lock:
            return self._published

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def publish(self, payload: T, *, captured_at_ns: int) -> bool:
        """Publish *payload*, replacing any unread frame.

        Returns:
            False if the slot is closed (payload is not retained).
        """
        with self._lock:
            if self._closed:
                return False
            if self._item is not None:
                self._overwritten += 1
            self._sequence += 1
            self._published += 1
            self._item = SlotItem(
                payload=payload,
                captured_at_ns=captured_at_ns,
                sequence=self._sequence,
            )
            self._new_frame.set()
            return True

    def has_frame(self) -> bool:
        with self._lock:
            return self._item is not None

    def take(self, *, clear: bool = True) -> SlotItem[T] | None:
        """Return the newest frame, optionally clearing the pending slot."""
        with self._lock:
            item = self._item
            if clear:
                self._item = None
                self._new_frame.clear()
            return item

    def wait_for_frame(self, timeout: float | None = None) -> bool:
        """Block until a frame is available, the slot closes, or *timeout* elapses."""
        return self._new_frame.wait(timeout=timeout)

    def close(self) -> None:
        """Mark the slot closed and wake waiters. Pending frame is discarded."""
        with self._lock:
            self._closed = True
            self._item = None
            self._new_frame.set()

    def pending_count(self) -> int:
        """Return 0 or 1 — never grows unbounded."""
        with self._lock:
            return 0 if self._item is None else 1
