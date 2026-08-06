"""Unit tests for capture metrics, results serialization, and error mapping."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from snowlink.media.capture_errors import (
    CaptureError,
    failure_for,
    format_failure_human,
    map_exception,
)
from snowlink.media.capture_metrics import TimingAccumulator, average, percentile
from snowlink.media.capture_models import (
    SCHEMA_VERSION,
    CaptureConfiguration,
    CaptureStats,
    ExperimentCResult,
    RenderStats,
)
from snowlink.media.experiment_c_results import (
    load_result,
    result_filename,
    sanitize_filename_component,
    write_result,
)
from snowlink.media.frame_slot import LatestFrameSlot
from snowlink.media.screen_capture import ScreenCaptureSession


def test_percentile_calculations() -> None:
    samples = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    assert percentile([], 50) is None
    assert percentile(samples, 50) == 50.0
    assert percentile(samples, 95) == 100.0
    assert percentile(samples, 0) == 10.0
    assert percentile(samples, 100) == 100.0
    assert average(samples) == 55.0


def test_timing_accumulator_to_stats() -> None:
    acc = TimingAccumulator()
    for ns in (10_000_000, 20_000_000, 30_000_000):
        acc.add_capture_interval_ns(ns)
        acc.add_frame_age_ns(ns // 2)
        acc.add_scale_ns(1_000_000)
    stats = acc.to_timing_stats()
    assert stats.capture_interval_average == pytest.approx(20.0)
    assert stats.scale_average == pytest.approx(1.0)
    assert stats.frame_age_p50 is not None


def test_metrics_serialization_roundtrip(tmp_path: Path) -> None:
    result = ExperimentCResult(
        success=True,
        configuration=CaptureConfiguration(
            monitor=0,
            backend="dxgi",
            requested_fps=30,
            requested_width=1280,
            requested_height=720,
            duration_s=60,
            cursor_requested=False,
            show_preview=False,
            preset_name="balanced",
        ),
        capture=CaptureStats(
            native_width=1920,
            native_height=1080,
            frames_captured=1792,
            actual_fps=29.87,
            null_frames=0,
            overwritten_frames=18,
        ),
        render=RenderStats(frames_rendered=1774, actual_fps=29.56),
    )
    path = write_result(result, tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["experiment"] == "experiment_c_screen_capture"
    assert raw["schema_version"] == SCHEMA_VERSION
    assert raw["capture"]["overwritten_frames"] == 18
    assert any("not glass-to-glass" in n.lower() for n in raw["notes"])
    loaded = load_result(path)
    assert loaded.success is True
    assert loaded.configuration is not None
    assert loaded.configuration.preset_name == "balanced"


def test_safe_result_filenames() -> None:
    assert "/" not in sanitize_filename_component("../evil/name")
    assert "\\" not in sanitize_filename_component("a\\b")
    name = result_filename(
        monitor=0,
        backend="dxgi",
        preset_or_label="balanced",
        when=datetime(2026, 8, 6, 16, 0, 0, tzinfo=UTC),
    )
    assert name == "2026-08-06T160000_monitor-0_dxgi_balanced.json"
    assert ".." not in Path(name).name


def test_error_mapping() -> None:
    failure = failure_for("DXCAM_NOT_INSTALLED", "missing")
    assert "pip install" in failure.suggested_next_step
    text = format_failure_human(failure)
    assert "DXCAM_NOT_INSTALLED" in text
    mapped = map_exception(ModuleNotFoundError("No module named 'dxcam'"))
    assert mapped.code == "DXCAM_NOT_INSTALLED"
    wrapped = CaptureError(failure_for("BACKEND_UNAVAILABLE", "nope"))
    assert map_exception(wrapped).code == "BACKEND_UNAVAILABLE"


def test_shutdown_after_synthetic_capture_failure() -> None:
    """Capture worker records unexpected errors and shutdown joins cleanly."""
    import time

    def boom() -> None:
        raise RuntimeError("synthetic grab failure")

    config = CaptureConfiguration(
        monitor=0,
        backend="dxgi",
        requested_fps=30,
        requested_width=64,
        requested_height=64,
        duration_s=1,
        show_preview=False,
    )
    session = ScreenCaptureSession(config, grabber=boom)
    session.start()
    deadline = time.perf_counter() + 2.0
    while session._worker_stats.unexpected_error is None and time.perf_counter() < deadline:
        time.sleep(0.01)
    session.shutdown(join_timeout_s=2.0)
    assert session._thread is None
    assert session.slot.closed
    assert session._worker_stats.unexpected_error is not None
    assert session._worker_stats.unexpected_error.code == "UNEXPECTED_CAPTURE_ERROR"


def test_slot_used_by_session_does_not_accumulate() -> None:
    slot: LatestFrameSlot[int] = LatestFrameSlot()
    for i in range(50):
        slot.publish(i, captured_at_ns=i)
    assert slot.pending_count() == 1
