"""Unit tests for Experiment D audio metrics, results, and error mapping."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from snowlink.media.audio_errors import (
    AudioError,
    failure_for,
    format_failure_human,
    map_exception,
)
from snowlink.media.audio_metrics import AudioTimingAccumulator
from snowlink.media.audio_models import (
    SCHEMA_VERSION,
    AudioConfiguration,
    ExperimentDResult,
)
from snowlink.media.audio_pipeline import AudioPipelineSession
from snowlink.media.experiment_d_results import (
    load_result,
    result_filename,
    sanitize_filename_component,
    write_result,
)


def test_audio_timing_accumulator() -> None:
    acc = AudioTimingAccumulator()
    acc.add_processing_ns(1_000_000)
    acc.add_processing_ns(2_000_000)
    acc.add_queue_delay_ms(40.0)
    acc.add_fill_ms(50.0)
    stats = acc.to_timing_stats()
    assert stats.processing_average == pytest.approx(1.5)
    assert stats.queue_delay_average == pytest.approx(40.0)
    assert acc.peak_fill_ms() == pytest.approx(50.0)


def test_metrics_serialization_roundtrip(tmp_path: Path) -> None:
    result = ExperimentDResult(
        success=True,
        configuration=AudioConfiguration(
            capture_device="default",
            playback_device="4",
            target_sample_rate=48000,
            target_channels=2,
            frame_duration_ms=20,
            buffer_capacity_ms=160,
            duration_s=60,
            gain=0.7,
        ),
    )
    result.capture.captured_samples = 2880000
    result.buffer.underruns = 2
    path = write_result(result, tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["experiment"] == "experiment_d_audio_loopback"
    assert raw["schema_version"] == SCHEMA_VERSION
    assert raw["buffer"]["underruns"] == 2
    assert any("queue delay" in n.lower() for n in raw["notes"])
    loaded = load_result(path)
    assert loaded.success is True
    assert loaded.configuration is not None
    assert loaded.configuration.gain == 0.7


def test_safe_result_filenames() -> None:
    assert "/" not in sanitize_filename_component("../evil/name")
    name = result_filename(
        capture_label="default",
        sample_rate=48000,
        channels=2,
        when=datetime(2026, 8, 6, 17, 0, 0, tzinfo=UTC),
    )
    assert name == "2026-08-06T170000_loopback-default_48k_stereo.json"
    assert ".." not in Path(name).name


def test_error_mapping() -> None:
    failure = failure_for("PYAUDIO_WPATCH_NOT_INSTALLED", "missing")
    assert "pip install" in failure.suggested_next_step
    text = format_failure_human(failure)
    assert "PYAUDIO_WPATCH_NOT_INSTALLED" in text
    mapped = map_exception(ModuleNotFoundError("No module named 'pyaudiowpatch'"))
    assert mapped.code == "PYAUDIO_WPATCH_NOT_INSTALLED"
    wrapped = AudioError(failure_for("NO_LOOPBACK_DEVICE", "none"))
    assert map_exception(wrapped).code == "NO_LOOPBACK_DEVICE"


def test_shutdown_after_synthetic_capture_failure() -> None:
    config = AudioConfiguration(
        duration_s=1,
        enable_playback=False,
        mode="monitor",
        buffer_capacity_ms=80,
        frame_duration_ms=20,
    )
    calls = {"n": 0}

    def source() -> np.ndarray:
        calls["n"] += 1
        if calls["n"] > 2:
            raise RuntimeError("synthetic capture failure")
        return np.zeros((480, 2), dtype=np.float32)

    session = AudioPipelineSession(config, synthetic_source=source)
    session.start()
    deadline = time.perf_counter() + 2.0
    while not session.errors and time.perf_counter() < deadline:
        time.sleep(0.02)
    session.shutdown(join_timeout_s=2.0)
    assert session.ring is not None
    assert session.ring.closed
    assert session.errors
    assert session.errors[0].code == "UNEXPECTED_AUDIO_ERROR"
