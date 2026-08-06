"""Thread-safe bounded audio ring buffer with drop-oldest overflow policy.

Overflow policy (live audio)
----------------------------
When a write would exceed capacity, the oldest buffered samples are discarded
so latency cannot grow indefinitely. Dropped samples and overrun events are
counted. Underruns occur when a read requests more samples than are available
after waiting for an optional timeout; callers should treat underrun as
*missing data*, which is distinct from valid captured silence (all-zero PCM).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class RingBufferStats:
    capacity_samples: int
    fill_samples: int
    peak_fill_samples: int
    underruns: int
    overruns: int
    dropped_samples: int
    written_samples: int
    read_samples: int
    closed: bool


class AudioRingBuffer:
    """Bounded interleaved PCM ring buffer.

    Storage is interleaved float32 frames shaped ``(n, channels)``. Capacity and
    fill levels are measured in frames (one time-sample across all channels).
    """

    def __init__(self, capacity_frames: int, *, channels: int = 2) -> None:
        if capacity_frames < 1:
            raise ValueError("capacity_frames must be >= 1")
        if channels < 1:
            raise ValueError("channels must be >= 1")
        self._channels = int(channels)
        self._capacity = int(capacity_frames)
        self._buf = np.zeros((self._capacity, self._channels), dtype=np.float32)
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._write_pos = 0
        self._read_pos = 0
        self._fill = 0
        self._peak_fill = 0
        self._underruns = 0
        self._overruns = 0
        self._dropped_samples = 0
        self._written_samples = 0
        self._read_samples = 0
        self._closed = False

    @property
    def channels(self) -> int:
        return self._channels

    @property
    def capacity_frames(self) -> int:
        return self._capacity

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def fill_frames(self) -> int:
        with self._lock:
            return self._fill

    def peak_fill_frames(self) -> int:
        with self._lock:
            return self._peak_fill

    def underrun_count(self) -> int:
        with self._lock:
            return self._underruns

    def overrun_count(self) -> int:
        with self._lock:
            return self._overruns

    def dropped_samples(self) -> int:
        """Total frames dropped due to overflow (per-channel sample groups)."""
        with self._lock:
            return self._dropped_samples

    def stats(self) -> RingBufferStats:
        with self._lock:
            return RingBufferStats(
                capacity_samples=self._capacity,
                fill_samples=self._fill,
                peak_fill_samples=self._peak_fill,
                underruns=self._underruns,
                overruns=self._overruns,
                dropped_samples=self._dropped_samples,
                written_samples=self._written_samples,
                read_samples=self._read_samples,
                closed=self._closed,
            )

    def write(self, frames: NDArray[np.floating[Any]]) -> int:
        """Write interleaved float frames; drop oldest on overflow.

        Args:
            frames: Array shaped ``(n, channels)`` or ``(n,)`` for mono.

        Returns:
            Number of frames dropped (0 if no overflow).
        """
        data = _normalize_frames(frames, self._channels)
        n = int(data.shape[0])
        if n == 0:
            return 0

        with self._lock:
            if self._closed:
                return 0
            dropped = 0
            if n >= self._capacity:
                # Keep only the newest capacity frames.
                dropped = self._fill + (n - self._capacity)
                keep = data[-self._capacity :]
                self._buf[:] = keep
                self._write_pos = 0
                self._read_pos = 0
                self._fill = self._capacity
                if dropped > 0:
                    self._overruns += 1
                    self._dropped_samples += dropped
                self._written_samples += n
                self._peak_fill = self._capacity
                self._not_empty.notify_all()
                return dropped

            overflow = self._fill + n - self._capacity
            if overflow > 0:
                self._drop_oldest_unlocked(overflow)
                dropped = overflow
                self._overruns += 1
                self._dropped_samples += dropped

            end = self._write_pos + n
            if end <= self._capacity:
                self._buf[self._write_pos : end] = data
            else:
                first = self._capacity - self._write_pos
                self._buf[self._write_pos :] = data[:first]
                self._buf[: n - first] = data[first:]
            self._write_pos = (self._write_pos + n) % self._capacity
            self._fill += n
            self._written_samples += n
            if self._fill > self._peak_fill:
                self._peak_fill = self._fill
            self._not_empty.notify_all()
            return dropped

    def read(
        self,
        n_frames: int,
        *,
        timeout: float | None = None,
    ) -> tuple[NDArray[np.float32] | None, bool]:
        """Read up to *n_frames* of interleaved PCM.

        Returns:
            ``(data, underrun)`` where *data* is shape ``(got, channels)`` or
            ``None`` when no data was available. *underrun* is True when fewer
            than *n_frames* were available after waiting (missing data — not
            the same as valid silence).
        """
        if n_frames < 1:
            raise ValueError("n_frames must be >= 1")

        with self._not_empty:
            if not self._wait_for_frames_unlocked(n_frames, timeout):
                if self._fill == 0:
                    if not self._closed:
                        self._underruns += 1
                    return None, True
                got = self._read_unlocked(self._fill)
                self._underruns += 1
                return got, True

            data = self._read_unlocked(n_frames)
            return data, False

    def read_exact(
        self,
        n_frames: int,
        *,
        timeout: float | None = None,
    ) -> tuple[NDArray[np.float32], bool]:
        """Read exactly *n_frames*, padding with zeros on underrun.

        The returned flag is True only when padding was required (missing data),
        not when the buffered audio itself was silent.
        """
        data, underrun = self.read(n_frames, timeout=timeout)
        if data is None:
            out = np.zeros((n_frames, self._channels), dtype=np.float32)
            return out, True
        if data.shape[0] == n_frames:
            return data, underrun
        out = np.zeros((n_frames, self._channels), dtype=np.float32)
        out[: data.shape[0]] = data
        return out, True

    def close(self) -> None:
        """Mark closed and wake waiters. Remaining data may still be read."""
        with self._not_empty:
            self._closed = True
            self._not_empty.notify_all()

    def clear(self) -> None:
        with self._lock:
            self._write_pos = 0
            self._read_pos = 0
            self._fill = 0

    def _drop_oldest_unlocked(self, n: int) -> None:
        n = min(n, self._fill)
        self._read_pos = (self._read_pos + n) % self._capacity
        self._fill -= n

    def _wait_for_frames_unlocked(self, n_frames: int, timeout: float | None) -> bool:
        if self._fill >= n_frames:
            return True
        if self._closed:
            return False
        if timeout is None:
            while self._fill < n_frames and not self._closed:
                self._not_empty.wait()
            return self._fill >= n_frames
        deadline = time.monotonic() + timeout
        while self._fill < n_frames and not self._closed:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._not_empty.wait(timeout=remaining)
        return self._fill >= n_frames

    def _read_unlocked(self, n_frames: int) -> NDArray[np.float32]:
        n = min(n_frames, self._fill)
        out = np.empty((n, self._channels), dtype=np.float32)
        end = self._read_pos + n
        if end <= self._capacity:
            out[:] = self._buf[self._read_pos : end]
        else:
            first = self._capacity - self._read_pos
            out[:first] = self._buf[self._read_pos :]
            out[first:] = self._buf[: n - first]
        self._read_pos = (self._read_pos + n) % self._capacity
        self._fill -= n
        self._read_samples += n
        return out


def _normalize_frames(
    frames: NDArray[np.floating[Any]],
    channels: int,
) -> NDArray[np.float32]:
    arr = np.asarray(frames, dtype=np.float32)
    if arr.ndim == 1:
        if channels != 1:
            raise ValueError(f"1-D input requires channels=1, got channels={channels}")
        return arr.reshape(-1, 1)
    if arr.ndim != 2:
        raise ValueError(f"frames must be 1-D or 2-D, got shape {arr.shape}")
    if arr.shape[1] != channels:
        raise ValueError(f"expected {channels} channels, got shape {arr.shape}")
    return arr
