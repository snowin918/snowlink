"""Unit tests for AudioRingBuffer."""

from __future__ import annotations

import threading
import time

import numpy as np

from snowlink.media.audio_ring_buffer import AudioRingBuffer


def _frames(n: int, channels: int = 2, value: float = 0.5) -> np.ndarray:
    return np.full((n, channels), value, dtype=np.float32)


def test_bounded_capacity() -> None:
    buf = AudioRingBuffer(10, channels=2)
    assert buf.capacity_frames == 10
    buf.write(_frames(10))
    assert buf.fill_frames() == 10
    dropped = buf.write(_frames(5, value=1.0))
    assert dropped == 5
    assert buf.fill_frames() == 10
    assert buf.overrun_count() == 1
    assert buf.dropped_samples() == 5


def test_fifo_reading() -> None:
    buf = AudioRingBuffer(8, channels=1)
    buf.write(np.array([[1.0], [2.0], [3.0], [4.0]], dtype=np.float32))
    data, underrun = buf.read(2)
    assert underrun is False
    assert data is not None
    assert data.tolist() == [[1.0], [2.0]]
    data2, _ = buf.read(2)
    assert data2 is not None
    assert data2.tolist() == [[3.0], [4.0]]


def test_oldest_data_drop_policy() -> None:
    buf = AudioRingBuffer(4, channels=1)
    buf.write(np.array([[1.0], [2.0], [3.0], [4.0]], dtype=np.float32))
    buf.write(np.array([[5.0], [6.0]], dtype=np.float32))
    data, underrun = buf.read(4)
    assert underrun is False
    assert data is not None
    assert data.reshape(-1).tolist() == [3.0, 4.0, 5.0, 6.0]


def test_underrun_counting() -> None:
    buf = AudioRingBuffer(8, channels=2)
    data, underrun = buf.read(4, timeout=0.05)
    assert underrun is True
    assert data is None
    assert buf.underrun_count() == 1
    padded, underrun2 = buf.read_exact(4, timeout=0.01)
    assert underrun2 is True
    assert padded.shape == (4, 2)
    assert buf.underrun_count() == 2


def test_overrun_counting() -> None:
    buf = AudioRingBuffer(3, channels=2)
    buf.write(_frames(3))
    buf.write(_frames(2))
    assert buf.overrun_count() >= 1
    assert buf.dropped_samples() >= 2


def test_clean_close_wakes_waiters() -> None:
    buf = AudioRingBuffer(4, channels=1)
    result: list[tuple[np.ndarray | None, bool]] = []

    def reader() -> None:
        result.append(buf.read(2, timeout=2.0))

    t = threading.Thread(target=reader)
    t.start()
    time.sleep(0.05)
    buf.close()
    t.join(timeout=2.0)
    assert buf.closed
    assert len(result) == 1
    data, underrun = result[0]
    assert underrun is True
    assert data is None


def test_write_after_close_ignored() -> None:
    buf = AudioRingBuffer(4, channels=2)
    buf.close()
    assert buf.write(_frames(2)) == 0
    assert buf.fill_frames() == 0


def test_peak_fill_tracked() -> None:
    buf = AudioRingBuffer(10, channels=2)
    buf.write(_frames(3))
    buf.write(_frames(4))
    assert buf.peak_fill_frames() == 7
    buf.read(5)
    assert buf.peak_fill_frames() == 7
