"""Unit tests for Phase 0 Experiment B and Experiment C evidence validation."""

from __future__ import annotations

import json
from pathlib import Path

from snowlink.media.capture_models import (
    CaptureConfiguration,
    CaptureStats,
    ExperimentCResult,
    RenderStats,
    ResourceStats,
    TimingStatsMs,
)
from snowlink.media.experiment_c_results import (
    EvidenceStatus as CEvidenceStatus,
)
from snowlink.media.experiment_c_results import (
    evaluate_experiment_c_result,
    result_filename,
    sanitize_machine_label,
    validate_experiment_c_machines,
)
from snowlink.media.experiment_c_results import (
    evidence_exit_code as c_evidence_exit_code,
)
from snowlink.media.experiment_c_results import (
    write_result as write_c_result,
)
from snowlink.net.experiment_b_models import (
    ExperimentBResult,
    LocalEndpointInfo,
    RemoteEndpointInfo,
    TimingInfo,
)
from snowlink.net.experiment_b_results import (
    EvidenceStatus,
    evidence_exit_code,
    validate_experiment_b_matrix,
    write_result,
)
from snowlink.net.socket_errors import failure_for


def _client(
    session: str,
    *,
    success: bool,
    source: str = "192.168.1.30",
    destination: str = "192.168.1.25",
    error: dict[str, object] | None = None,
) -> ExperimentBResult:
    return ExperimentBResult(
        test_id=session,
        role="client",
        session_name=session,
        success=success,
        local=LocalEndpointInfo(
            hostname="pc-b",
            requested_source_ip=source,
            actual_source_ip=source,
            adapter_category="physical_wifi",
        ),
        remote=RemoteEndpointInfo(ip=destination, port=3847),
        timing_ms=TimingInfo(connect_ms=4.0 if success else 500.0),
        error=error,
    )


def test_matrix_all_pass(tmp_path: Path) -> None:
    write_result(_client("vpn-on-on", success=True), tmp_path, filename="vpn-on-on.json")

    rows = validate_experiment_b_matrix(tmp_path)
    assert len(rows) == 1
    assert rows[0].session_name == "vpn-on-on"
    assert rows[0].status is EvidenceStatus.PASS
    assert evidence_exit_code(rows) == 0


def test_matrix_missing_fail_and_invalid_loopback(tmp_path: Path) -> None:
    write_result(
        _client(
            "vpn-on-on",
            success=False,
            source="127.0.0.1",
            destination="127.0.0.1",
            error=failure_for(
                "CONNECTION_TIMEOUT",
                "The TCP connection did not complete before the timeout.",
            ).to_dict(),
        ),
        tmp_path,
        filename="vpn-on-on.json",
    )

    rows = {row.session_name: row for row in validate_experiment_b_matrix(tmp_path)}
    assert set(rows) == {"vpn-on-on"}
    assert rows["vpn-on-on"].status is EvidenceStatus.INVALID
    assert "Loopback" in rows["vpn-on-on"].detail
    assert evidence_exit_code(list(rows.values())) == 1


def test_loopback_success_is_invalid_not_pass(tmp_path: Path) -> None:
    write_result(
        _client(
            "vpn-on-on",
            success=True,
            source="127.0.0.1",
            destination="127.0.0.1",
        ),
        tmp_path,
        filename="vpn-on-on.json",
    )
    rows = validate_experiment_b_matrix(tmp_path)
    assert rows[0].status is EvidenceStatus.INVALID
    assert rows[0].success is True


def test_unreadable_client_json_is_invalid(tmp_path: Path) -> None:
    path = tmp_path / "vpn-on-on_client.json"
    path.write_text("{not-json", encoding="utf-8")
    # Filename alone does not invent a session; require parseable session_name.
    # Place a corrupt file that includes role=client after fixing to invalid object.
    path.write_text(
        json.dumps({"role": "client", "session_name": "vpn-on-on", "schema_version": "bad"}),
        encoding="utf-8",
    )
    rows = {row.session_name: row for row in validate_experiment_b_matrix(tmp_path)}
    assert rows["vpn-on-on"].status is EvidenceStatus.INVALID


def test_empty_directory_all_missing(tmp_path: Path) -> None:
    rows = validate_experiment_b_matrix(tmp_path)
    assert len(rows) == 1
    assert rows[0].session_name == "vpn-on-on"
    assert rows[0].status is EvidenceStatus.MISSING
    assert evidence_exit_code(rows) == 1


def _balanced_c(
    *,
    machine_label: str,
    success: bool = True,
    duration_s: float = 60.2,
    actual_fps: float = 29.4,
    requested_fps: int = 30,
    width: int = 1280,
    height: int = 720,
    mem_start: float = 100.0,
    mem_end: float = 104.8,
    mem_peak: float = 105.0,
    cpu_avg: float = 12.0,
    overwritten: int = 10,
    frames: int = 1760,
    frame_age_p95: float | None = 40.0,
    notes: list[str] | None = None,
    details: dict[str, object] | None = None,
    errors: list[dict[str, object]] | None = None,
    preset_name: str | None = "balanced",
) -> ExperimentCResult:
    merged_details: dict[str, object] = {"experiment_duration_s": duration_s}
    if details:
        merged_details.update(details)
    return ExperimentCResult(
        success=success,
        machine_label=machine_label,
        configuration=CaptureConfiguration(
            monitor=0,
            backend="dxgi",
            requested_fps=requested_fps,
            requested_width=width,
            requested_height=height,
            duration_s=int(duration_s) if duration_s >= 1 else 1,
            show_preview=False,
            preset_name=preset_name,
        ),
        capture=CaptureStats(
            native_width=1920,
            native_height=1080,
            frames_captured=frames,
            actual_fps=actual_fps,
            overwritten_frames=overwritten,
        ),
        render=RenderStats(frames_rendered=frames, actual_fps=actual_fps),
        timing_ms=TimingStatsMs(
            capture_interval_average=33.4,
            capture_interval_p95=40.0,
            frame_age_average=20.0,
            frame_age_p95=frame_age_p95,
        ),
        resources=ResourceStats(
            cpu_percent_average=cpu_avg,
            cpu_percent_peak=cpu_avg + 5.0,
            memory_mb_start=mem_start,
            memory_mb_end=mem_end,
            memory_mb_peak=mem_peak,
        ),
        errors=list(errors or []),
        notes=list(notes) if notes is not None else ExperimentCResult().notes,
        details=merged_details,
    )


def test_sanitize_machine_label() -> None:
    assert sanitize_machine_label("Computer-A") == "computer-a"
    assert sanitize_machine_label(" computer b ") == "computer-b"
    assert "/" not in sanitize_machine_label("../evil/name")
    assert "\\" not in sanitize_machine_label("a\\b")
    assert sanitize_machine_label("@@@") == "unnamed"


def test_result_filename_includes_machine_label() -> None:
    from datetime import UTC, datetime

    name = result_filename(
        monitor=0,
        backend="dxgi",
        preset_or_label="balanced",
        machine_label="Computer A",
        when=datetime(2026, 8, 6, 16, 0, 0, tzinfo=UTC),
    )
    assert name == "2026-08-06T160000_computer-a_monitor-0_dxgi_balanced.json"


def test_experiment_c_matrix_pass_and_warn(tmp_path: Path) -> None:
    write_c_result(
        _balanced_c(machine_label="computer-a", actual_fps=29.4),
        tmp_path,
    )
    write_c_result(
        _balanced_c(machine_label="computer-b", actual_fps=26.3, mem_end=106.2),
        tmp_path,
    )
    rows = {row.machine_label: row for row in validate_experiment_c_machines(tmp_path)}
    assert rows["computer-a"].status is CEvidenceStatus.PASS
    assert rows["computer-b"].status is CEvidenceStatus.WARN
    assert c_evidence_exit_code(list(rows.values())) == 0
    assert rows["computer-a"].path is not None
    assert "computer-a" in Path(rows["computer-a"].path).name


def test_experiment_c_duration_rejection(tmp_path: Path) -> None:
    write_c_result(
        _balanced_c(machine_label="computer-a", duration_s=5.0, actual_fps=21.6),
        tmp_path,
    )
    rows = {row.machine_label: row for row in validate_experiment_c_machines(tmp_path)}
    assert rows["computer-a"].status is CEvidenceStatus.INVALID
    assert "shorter" in rows["computer-a"].detail.lower()
    assert rows["computer-b"].status is CEvidenceStatus.MISSING
    assert c_evidence_exit_code(list(rows.values())) == 1


def test_experiment_c_configuration_rejection(tmp_path: Path) -> None:
    write_c_result(
        _balanced_c(
            machine_label="computer-a",
            width=1920,
            height=1080,
            requested_fps=30,
            preset_name="high",
        ),
        tmp_path,
    )
    status, detail = evaluate_experiment_c_result(
        _balanced_c(
            machine_label="computer-a",
            width=1920,
            height=1080,
            preset_name="high",
        )
    )
    assert status is CEvidenceStatus.INVALID
    assert "1280x720@30" in detail


def test_experiment_c_synthetic_rejected(tmp_path: Path) -> None:
    write_c_result(
        _balanced_c(
            machine_label="computer-a",
            notes=["synthetic fixture for unit tests"],
        ),
        tmp_path,
    )
    rows = {row.machine_label: row for row in validate_experiment_c_machines(tmp_path)}
    assert rows["computer-a"].status is CEvidenceStatus.INVALID
    assert "non-hardware" in rows["computer-a"].detail.lower()


def test_experiment_c_malformed_result(tmp_path: Path) -> None:
    path = tmp_path / "2026-08-06T160000_computer-a_monitor-0_dxgi_balanced.json"
    path.write_text("{not-json", encoding="utf-8")
    rows = {row.machine_label: row for row in validate_experiment_c_machines(tmp_path)}
    assert rows["computer-a"].status is CEvidenceStatus.INVALID


def test_experiment_c_fail_severe_fps_and_memory(tmp_path: Path) -> None:
    write_c_result(
        _balanced_c(
            machine_label="computer-a",
            actual_fps=10.0,
            success=True,
        ),
        tmp_path,
    )
    write_c_result(
        _balanced_c(
            machine_label="computer-b",
            actual_fps=29.0,
            mem_start=100.0,
            mem_end=220.0,
            mem_peak=220.0,
        ),
        tmp_path,
    )
    rows = {row.machine_label: row for row in validate_experiment_c_machines(tmp_path)}
    assert rows["computer-a"].status is CEvidenceStatus.FAIL
    assert rows["computer-b"].status is CEvidenceStatus.FAIL
    assert c_evidence_exit_code(list(rows.values())) == 1


def test_experiment_c_dropped_frames_warn_not_fail() -> None:
    status, detail = evaluate_experiment_c_result(
        _balanced_c(
            machine_label="computer-a",
            overwritten=200,
            frames=1800,
            frame_age_p95=45.0,
            actual_fps=29.0,
        )
    )
    assert status is CEvidenceStatus.WARN
    assert "dropped" in detail.lower()


def test_experiment_c_empty_directory_missing(tmp_path: Path) -> None:
    rows = validate_experiment_c_machines(tmp_path)
    assert len(rows) == 2
    assert all(row.status is CEvidenceStatus.MISSING for row in rows)
    assert c_evidence_exit_code(rows) == 1
