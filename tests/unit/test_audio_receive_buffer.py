"""Unit tests for Experiment F receive buffer / playback drain behavior."""

from __future__ import annotations

import time

import numpy as np

from snowlink.media.audio_ring_buffer import AudioRingBuffer
from snowlink.rtc.audio_receiver import PlaybackWorker


def test_receive_buffer_capacity_bounded() -> None:
    ring = AudioRingBuffer(capacity_frames=4800, channels=2)  # 100 ms @ 48 kHz
    assert ring.capacity_frames == 4800
    chunk = np.zeros((960, 2), dtype=np.float32)
    for _ in range(20):
        ring.write(chunk)
    assert ring.fill_frames() <= 4800
    assert ring.overrun_count() >= 1
    assert ring.dropped_samples() > 0


def test_oldest_data_drop_behavior() -> None:
    ring = AudioRingBuffer(capacity_frames=100, channels=1)
    first = np.full((80, 1), 0.25, dtype=np.float32)
    second = np.full((80, 1), 0.75, dtype=np.float32)
    ring.write(first)
    ring.write(second)
    data, underrun = ring.read(100, timeout=0.0)
    assert not underrun
    assert data is not None
    assert data.shape[0] == 100
    # Newest samples dominate after drop-oldest.
    assert float(np.mean(data[-50:])) > 0.6


def test_underrun_silence_insertion() -> None:
    ring = AudioRingBuffer(capacity_frames=9600, channels=2)
    # Seed enough audio for prebuffer, then stop writing so the worker underruns.
    ring.write(np.zeros((4800, 2), dtype=np.float32))
    worker = PlaybackWorker(
        ring,
        sample_rate=48_000,
        channels=2,
        frame_ms=20,
        gain=0.25,
        muted=False,
        write_pcm=None,
        enabled=False,
        prebuffer_ms=40.0,
        rebuffer_after_underruns=10_000,
    )
    worker.start()
    time.sleep(0.25)
    worker.stop(timeout=1.0)
    assert worker.samples_played >= 960
    assert worker.underruns >= 1
    assert worker.silence_samples_inserted >= 960


def test_playback_waits_for_prebuffer() -> None:
    ring = AudioRingBuffer(capacity_frames=9600, channels=2)
    worker = PlaybackWorker(
        ring,
        sample_rate=48_000,
        channels=2,
        frame_ms=20,
        enabled=False,
        prebuffer_ms=60.0,
    )
    worker.start()
    time.sleep(0.05)
    # Still waiting — no audio written yet.
    assert worker.samples_played == 0
    ring.write(np.zeros((4800, 2), dtype=np.float32))
    time.sleep(0.12)
    worker.stop(timeout=1.0)
    assert worker.samples_played >= 960
    # Healthy start should not underrun every frame.
    assert worker.underruns < worker.samples_played // 960
