"""Unit tests for RFC1918 detection, classification, preference, and overrides."""

from __future__ import annotations

import pytest
from tests.fixtures.adapters import make_adapter, sample_adapter_set

from snowlink.net.adapter_models import AdapterCategory, OperationalStatus
from snowlink.net.adapter_selection import (
    IF_TYPE_ETHERNET_CSMACD,
    IF_TYPE_TUNNEL,
    annotate_adapter,
    annotate_adapters,
    classify_adapter,
    find_adapter_by_id,
    find_endpoint_by_ip,
    is_loopback_address,
    is_rfc1918_private,
    select_preferred_endpoint,
)


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("10.0.0.1", True),
        ("10.255.255.255", True),
        ("172.16.0.1", True),
        ("172.31.255.1", True),
        ("172.15.0.1", False),
        ("172.32.0.1", False),
        ("192.168.0.1", True),
        ("192.168.255.255", True),
        ("8.8.8.8", False),
        ("100.64.1.2", False),  # CGNAT / Tailscale — not RFC1918
        ("169.254.10.1", False),
        ("127.0.0.1", False),
        ("not-an-ip", False),
    ],
)
def test_rfc1918_private_detection(address: str, expected: bool) -> None:
    assert is_rfc1918_private(address) is expected


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("127.0.0.1", True),
        ("127.255.0.1", True),
        ("192.168.1.1", False),
        ("0.0.0.0", False),
        ("bad", False),
    ],
)
def test_loopback_detection(address: str, expected: bool) -> None:
    assert is_loopback_address(address) is expected


def test_physical_ethernet_and_wifi_classification() -> None:
    adapters = annotate_adapters(sample_adapter_set())
    by_id = {a.adapter_id: a for a in adapters}
    assert by_id["{eth0}"].category == AdapterCategory.PHYSICAL_ETHERNET
    assert by_id["{wifi0}"].category == AdapterCategory.PHYSICAL_WIFI
    assert by_id["{eth0}"].preferred is True
    assert by_id["{wifi0}"].preferred is True


def test_vpn_deprioritized_but_still_listed() -> None:
    adapters = annotate_adapters(sample_adapter_set())
    vpn = next(a for a in adapters if a.adapter_id == "{vpn0}")
    eth = next(a for a in adapters if a.adapter_id == "{eth0}")
    assert vpn.category == AdapterCategory.VPN_OR_TUNNEL
    assert vpn.preferred is False
    assert vpn.preference_score < eth.preference_score
    assert any(a.adapter_id == "{vpn0}" for a in adapters)


def test_tailscale_mesh_and_virtual_categories() -> None:
    adapters = annotate_adapters(sample_adapter_set())
    by_id = {a.adapter_id: a for a in adapters}
    assert by_id["{ts0}"].category == AdapterCategory.TAILSCALE_OR_MESH
    assert by_id["{hv0}"].category == AdapterCategory.VIRTUAL_MACHINE_OR_HYPERVISOR
    assert by_id["{wsl0}"].category == AdapterCategory.WSL_OR_CONTAINER
    assert by_id["{lo}"].category == AdapterCategory.LOOPBACK
    assert by_id["{ts0}"].preferred is False
    assert by_id["{lo}"].preferred is False


def test_physical_adapter_preference_selects_ethernet_over_wifi_when_faster() -> None:
    selected = select_preferred_endpoint(sample_adapter_set())
    assert selected is not None
    assert selected.ipv4 == "192.168.1.20"
    assert selected.adapter.category == AdapterCategory.PHYSICAL_ETHERNET


def test_manual_override_by_ip_selects_vpn() -> None:
    endpoint = find_endpoint_by_ip(sample_adapter_set(), "10.64.8.12")
    assert endpoint.ipv4 == "10.64.8.12"
    assert endpoint.adapter.category == AdapterCategory.VPN_OR_TUNNEL


def test_manual_override_by_adapter_id() -> None:
    endpoint = find_adapter_by_id(sample_adapter_set(), "{wifi0}")
    assert endpoint.ipv4 == "192.168.1.55"
    assert endpoint.adapter.category == AdapterCategory.PHYSICAL_WIFI


def test_manual_override_unknown_ip_raises() -> None:
    with pytest.raises(ValueError, match="not assigned"):
        find_endpoint_by_ip(sample_adapter_set(), "192.168.9.9")


def test_tunnel_metadata_without_vpn_name_still_vpn() -> None:
    adapter = make_adapter(
        friendly_name="Opaque Interface",
        description="Mysterious Device",
        interface_type=IF_TYPE_TUNNEL,
        interface_type_name="TUNNEL",
        tunnel_type=15,
        tunnel_type_name="IPHTTPS",
        ipv4=(("10.1.2.3", 32),),
    )
    assert classify_adapter(adapter) == AdapterCategory.VPN_OR_TUNNEL


def test_down_physical_adapter_not_preferred() -> None:
    adapter = annotate_adapter(
        make_adapter(
            operational_status=OperationalStatus.DOWN,
            interface_type=IF_TYPE_ETHERNET_CSMACD,
            ipv4=(("192.168.1.20", 24),),
        )
    )
    assert adapter.category == AdapterCategory.PHYSICAL_ETHERNET
    assert adapter.preferred is False


def test_wintun_without_tailscale_is_vpn_not_mesh() -> None:
    from snowlink.net.adapter_selection import IF_TYPE_PROP_VIRTUAL

    adapter = make_adapter(
        friendly_name="Astrill VPN",
        description="Wintun Userspace Tunnel",
        interface_type=IF_TYPE_PROP_VIRTUAL,
        interface_type_name="PROP_VIRTUAL",
        ipv4=(("198.18.12.31", 20),),
    )
    assert classify_adapter(adapter) == AdapterCategory.VPN_OR_TUNNEL


def test_tailscale_name_still_mesh_on_tunnel() -> None:
    adapter = make_adapter(
        friendly_name="Tailscale",
        description="Tailscale Tunnel",
        interface_type=IF_TYPE_TUNNEL,
        interface_type_name="TUNNEL",
        tunnel_type=1,
        ipv4=(("100.64.1.2", 32),),
    )
    assert classify_adapter(adapter) == AdapterCategory.TAILSCALE_OR_MESH
