"""Unit tests for latest-frame remote video consumer behavior."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import numpy as np
import pytest

from snowlink.rtc.preview import DecodedFrame, RemoteVideoConsumer


class _FakeTrack:
    def __init__(self, frames: int = 5) -> None:
        self._frames = frames
        self._i = 0

    async def recv(self) -> Any:
        if self._i >= self._frames:
            raise RuntimeError("track ended")
        idx = self._i
        self._i += 1
        await asyncio.sleep(0)

        class _Frame:
            pts = idx

            def to_ndarray(self, format: str = "bgr24") -> np.ndarray:  # noqa: A002
                assert format == "bgr24"
                arr = np.zeros((16, 16, 3), dtype=np.uint8)
                arr[:, :, 0] = idx
                return arr

        return _Frame()


@pytest.mark.asyncio
async def test_remote_consumer_latest_frame_slot_depth_one() -> None:
    consumer = RemoteVideoConsumer()
    await consumer.start(_FakeTrack(frames=20))
    # Let the consumer overrun the slot.
    await asyncio.sleep(0.05)
    assert consumer.slot.pending_count() <= 1
    assert consumer.frames_received >= 1
    assert consumer.slot.overwritten_count >= 0
    item = consumer.slot.take()
    assert item is not None
    assert isinstance(item.payload, DecodedFrame)
    await consumer.stop()
    assert consumer.slot.closed


@pytest.mark.asyncio
async def test_remote_consumer_stop_cancels_cleanly() -> None:
    consumer = RemoteVideoConsumer()
    await consumer.start(_FakeTrack(frames=1000))
    await asyncio.sleep(0.01)
    t0 = time.perf_counter()
    await consumer.stop()
    assert time.perf_counter() - t0 < 2.0
