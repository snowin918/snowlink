"""Unit tests for product connectivity diagnostics helpers."""

from __future__ import annotations

from snowlink.diagnostics.workflow import (
    DiagnosticStepResult,
    LiveSessionSnapshot,
    _check_firewall,
    _check_getsockname,
    _check_ice,
    _check_ip_active,
    _check_media,
    _score_overall,
)
from snowlink.net.adapter_models import (
    AdapterCategory,
    IPv4AddressInfo,
    NetworkAdapter,
    OperationalStatus,
)


def _adapter(ip: str) -> NetworkAdapter:
    return NetworkAdapter(
        adapter_id="{test}",
        friendly_name="Ethernet",
        description="Ethernet",
        operational_status=OperationalStatus.UP,
        interface_type=6,
        interface_type_name="ethernet",
        tunnel_type=0,
        tunnel_type_name="none",
        physical_medium_type=None,
        physical_medium_name=None,
        speed_bps=1_000_000_000,
        ipv4_addresses=(
            IPv4AddressInfo(
                address=ip,
                prefix_length=24,
                is_private=True,
                is_loopback=False,
            ),
        ),
        category=AdapterCategory.PHYSICAL_ETHERNET,
        preferred=True,
        preference_score=1000,
    )


def test_check_ip_active_pass() -> None:
    result = _check_ip_active("192.168.1.10", [_adapter("192.168.1.10")])
    assert result.status == "pass"


def test_check_ip_active_fail_missing() -> None:
    result = _check_ip_active("192.168.1.99", [_adapter("192.168.1.10")])
    assert result.status == "fail"


def test_check_getsockname_skip_on_fail() -> None:
    bind = DiagnosticStepResult(2, "bind", "fail", "nope")
    assert _check_getsockname(bind).status == "skip"


def test_check_ice_pass() -> None:
    live = LiveSessionSnapshot(ice_state="connected", frames=10)
    assert _check_ice(live).status == "pass"


def test_check_media_pass() -> None:
    live = LiveSessionSnapshot(frames=5, phase="viewing")
    assert _check_media(live).status == "pass"


def test_score_overall_fail_wins() -> None:
    steps = [
        DiagnosticStepResult(1, "a", "pass", "ok"),
        DiagnosticStepResult(2, "b", "fail", "no"),
        DiagnosticStepResult(3, "c", "skip", "n/a"),
    ]
    assert _score_overall(steps) == "fail"


def test_firewall_probe_returns_step() -> None:
    step = _check_firewall(3847)
    assert step.step == 7
    assert step.status in {"pass", "warn", "fail", "skip"}
