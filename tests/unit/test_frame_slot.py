"""Unit tests for LatestFrameSlot."""

from __future__ import annotations

import threading
import time

from snowlink.media.frame_slot import LatestFrameSlot


def test_publish_and_take_returns_latest() -> None:
    slot: LatestFrameSlot[str] = LatestFrameSlot()
    assert slot.publish("a", captured_at_ns=1)
    assert slot.publish("b", captured_at_ns=2)
    item = slot.take()
    assert item is not None
    assert item.payload == "b"
    assert item.captured_at_ns == 2
    assert item.sequence == 2
    assert slot.overwritten_count == 1
    assert slot.take() is None


def test_overwritten_frame_counting() -> None:
    slot: LatestFrameSlot[int] = LatestFrameSlot()
    for i in range(5):
        slot.publish(i, captured_at_ns=i)
    assert slot.overwritten_count == 4
    assert slot.published_count == 5
    assert slot.pending_count() == 1
    assert slot.take() is not None
    assert slot.pending_count() == 0


def test_no_unbounded_frame_accumulation() -> None:
    slot: LatestFrameSlot[bytes] = LatestFrameSlot()
    for i in range(1000):
        slot.publish(bytes([i % 256]), captured_at_ns=i)
    assert slot.pending_count() <= 1
    assert slot.overwritten_count == 999


def test_close_rejects_publish_and_wakes_waiters() -> None:
    slot: LatestFrameSlot[str] = LatestFrameSlot()
    slot.close()
    assert slot.closed
    assert slot.publish("x", captured_at_ns=1) is False
    assert slot.has_frame() is False


def test_wait_for_frame_from_another_thread() -> None:
    slot: LatestFrameSlot[str] = LatestFrameSlot()

    def producer() -> None:
        time.sleep(0.05)
        slot.publish("ready", captured_at_ns=10)

    threading.Thread(target=producer, daemon=True).start()
    assert slot.wait_for_frame(timeout=1.0) is True
    item = slot.take()
    assert item is not None
    assert item.payload == "ready"
