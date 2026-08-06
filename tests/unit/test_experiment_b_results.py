"""Unit tests for Experiment B models, results I/O, and error sanitization."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from snowlink.net.experiment_b_models import (
    SCHEMA_VERSION,
    ExperimentBResult,
    LocalEndpointInfo,
    RemoteEndpointInfo,
    TimingInfo,
    validate_session_name,
)
from snowlink.net.experiment_b_results import (
    SchemaVersionError,
    format_summary_table,
    result_filename,
    sanitize_filename_component,
    summarize_results,
    write_result,
)
from snowlink.net.socket_errors import classify_os_error, failure_for, format_failure_human
from snowlink.net.tcp_diagnostics import (
    build_diagnostic_payload,
    invalid_ip_failure,
    validate_ipv4,
)


def test_validate_known_session_names() -> None:
    assert validate_session_name("vpn-on-on", allow_custom=False) == "vpn-on-on"


def test_validate_custom_session_requires_flag() -> None:
    with pytest.raises(ValueError, match="Unrecognized"):
        validate_session_name("lab-run-1", allow_custom=False)
    assert validate_session_name("lab-run-1", allow_custom=True) == "lab-run-1"


def test_filename_sanitization() -> None:
    assert "/" not in sanitize_filename_component("../evil/name")
    assert "\\" not in sanitize_filename_component("a\\b")
    name = result_filename(
        role="client",
        session_name="vpn-on-on",
        when=datetime(2026, 8, 6, 14, 55, 0, tzinfo=UTC),
        test_id="abc/../x",
    )
    assert name.startswith("2026-08-06T145500_vpn-on-on_client_")
    assert "/" not in name
    assert ".." not in Path(name).name


def test_result_json_serialization_roundtrip(tmp_path: Path) -> None:
    result = ExperimentBResult(
        test_id="tid-1",
        role="client",
        session_name="vpn-off-off",
        success=True,
        local=LocalEndpointInfo(
            hostname="pc-b",
            requested_source_ip="192.168.1.30",
            actual_source_ip="192.168.1.30",
            actual_source_port=51234,
            adapter_id="{wifi}",
            adapter_name="Wi-Fi",
            adapter_category="physical_wifi",
        ),
        remote=RemoteEndpointInfo(ip="192.168.1.25", port=3847),
        timing_ms=TimingInfo(connect_ms=4.2, echo_round_trip_ms=1.1, total_ms=7.8),
        error=None,
    )
    path = write_result(result, tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["experiment"] == "experiment_b_two_machine_tcp"
    assert raw["schema_version"] == SCHEMA_VERSION
    assert raw["local"]["actual_source_ip"] == "192.168.1.30"
    assert raw["timing_ms"]["connect"] == 4.2
    loaded = ExperimentBResult.from_dict(raw)
    assert loaded.success is True
    assert loaded.remote is not None
    assert loaded.remote.ip == "192.168.1.25"


def test_summary_table_generation(tmp_path: Path) -> None:
    for session, ok, connect in (
        ("vpn-off-off", True, 3.8),
        ("vpn-on-on", False, None),
    ):
        result = ExperimentBResult(
            test_id=session,
            role="client",
            session_name=session,
            success=ok,
            local=LocalEndpointInfo(
                hostname="pc-b",
                actual_source_ip="192.168.1.30",
            ),
            remote=RemoteEndpointInfo(ip="192.168.1.25", port=3847),
            timing_ms=TimingInfo(connect_ms=connect),
            error=None
            if ok
            else failure_for(
                "CONNECTION_TIMEOUT",
                "The TCP connection did not complete before the timeout.",
            ).to_dict(),
        )
        write_result(result, tmp_path, filename=f"{session}_client.json")

    table = format_summary_table(summarize_results(tmp_path))
    assert "vpn-off-off" in table
    assert "PASS" in table
    assert "vpn-on-on" in table
    assert "FAIL" in table
    assert "192.168.1.30" in table
    assert "192.168.1.25" in table


def test_incompatible_schema_version_handling(tmp_path: Path) -> None:
    good = ExperimentBResult(
        test_id="a",
        role="client",
        session_name="vpn-off-off",
        success=True,
        remote=RemoteEndpointInfo(ip="192.168.1.25", port=3847),
    )
    write_result(good, tmp_path, filename="good.json")
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(
        json.dumps(
            {
                "experiment": "experiment_b_two_machine_tcp",
                "schema_version": SCHEMA_VERSION + 1,
                "role": "client",
                "session_name": "vpn-on-on",
                "success": False,
                "timing_ms": {},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SchemaVersionError, match="Incompatible schema"):
        summarize_results(tmp_path)


def test_sanitized_error_output() -> None:
    failure = failure_for(
        "CONNECTION_TIMEOUT",
        "The TCP connection did not complete before the timeout.",
        os_error=10060,
    )
    text = format_failure_human(failure)
    assert "Possible causes:" in text
    assert "VPN" in text or "firewall" in text.lower() or "Firewall" in text
    assert "10060" in text
    assert "password" not in text.lower()
    assert "token" not in text.lower()


def test_classify_os_error_timeout() -> None:
    exc = TimeoutError()
    exc.errno = 10060  # type: ignore[attr-defined]
    failure = classify_os_error(exc)
    assert failure.code == "CONNECTION_TIMEOUT"


def test_invalid_ip_validation() -> None:
    with pytest.raises(ValueError):
        validate_ipv4("not-an-ip", kind="remote")
    failure = invalid_ip_failure("remote", "not-an-ip")
    assert failure.code == "INVALID_REMOTE_IP"
    assert validate_ipv4("192.168.1.25", kind="remote") == "192.168.1.25"


def test_diagnostic_payload_contains_marker() -> None:
    payload = build_diagnostic_payload(
        test_id="abc",
        session_name="vpn-on-on",
        hostname="pc-b",
    )
    assert "snowlink-exp-b/1" in payload
    assert "test_id=abc" in payload
    assert "session=vpn-on-on" in payload
