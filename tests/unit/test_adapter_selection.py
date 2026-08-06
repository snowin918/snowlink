"""Unit tests focused on adapter selection helpers."""

from __future__ import annotations

import pytest
from tests.fixtures.adapters import make_adapter, sample_adapter_set

from snowlink.net.adapter_selection import (
    find_adapter_by_id,
    find_endpoint_by_ip,
    ipv4_address_info,
    select_preferred_endpoint,
)


def test_ipv4_address_info_flags() -> None:
    private = ipv4_address_info("192.168.1.20", 24)
    assert private.is_private is True
    assert private.is_loopback is False
    assert private.prefix_length == 24

    loopback = ipv4_address_info("127.0.0.1", 8)
    assert loopback.is_loopback is True
    assert loopback.is_private is False


def test_select_preferred_none_when_only_vpn() -> None:
    adapters = [
        make_adapter(
            adapter_id="{vpn}",
            friendly_name="VPN",
            description="OpenVPN TAP Adapter",
            interface_type=131,
            interface_type_name="TUNNEL",
            tunnel_type=1,
            ipv4=(("10.8.0.2", 24),),
        )
    ]
    assert select_preferred_endpoint(adapters) is None


def test_manual_override_invalid_ip_raises() -> None:
    with pytest.raises(ValueError, match="Invalid IPv4"):
        find_endpoint_by_ip(sample_adapter_set(), "not.an.ip")


def test_find_adapter_by_id_missing_raises() -> None:
    with pytest.raises(ValueError, match="No adapter"):
        find_adapter_by_id(sample_adapter_set(), "{missing}")


def test_find_adapter_by_id_with_explicit_ipv4() -> None:
    dual = make_adapter(
        adapter_id="{dual}",
        ipv4=(("192.168.1.20", 24), ("10.0.0.5", 8)),
    )
    endpoint = find_adapter_by_id([dual], "{dual}", ipv4="10.0.0.5")
    assert endpoint.ipv4 == "10.0.0.5"
