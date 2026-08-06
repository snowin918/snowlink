"""Unit tests for ICE candidate diagnostics."""

from __future__ import annotations

from snowlink.net.adapter_models import (
    AdapterCategory,
    IPv4AddressInfo,
    NetworkAdapter,
    OperationalStatus,
)
from snowlink.rtc.ice_diagnostics import (
    CandidateFilter,
    classify_candidate_ip,
    mismatch_warning,
    parse_candidate_sdp,
    selected_matches_requested_ip,
    serialize_candidates,
)
from snowlink.rtc.models import IceCandidateInfo


def _adapter(ip: str, category: AdapterCategory) -> NetworkAdapter:
    return NetworkAdapter(
        adapter_id="a1",
        friendly_name="Test",
        description="Test",
        operational_status=OperationalStatus.UP,
        interface_type=6,
        interface_type_name="ETHERNET",
        tunnel_type=0,
        tunnel_type_name="NONE",
        physical_medium_type=None,
        physical_medium_name=None,
        speed_bps=1_000_000_000,
        ipv4_addresses=(
            IPv4AddressInfo(address=ip, prefix_length=24, is_private=True, is_loopback=False),
        ),
        category=category,
        preferred=category
        in {AdapterCategory.PHYSICAL_ETHERNET, AdapterCategory.PHYSICAL_WIFI},
        preference_score=1000,
    )


def test_parse_candidate_sdp() -> None:
    line = (
        "candidate:1 1 udp 2122260223 192.168.1.30 54022 typ host generation 0"
    )
    info = parse_candidate_sdp(line)
    assert info.ip == "192.168.1.30"
    assert info.port == 54022
    assert info.protocol == "udp"
    assert info.type == "host"
    assert info.foundation == "1"
    assert info.priority == 2122260223


def test_parse_candidate_with_a_prefix_and_raddr() -> None:
    line = (
        "a=candidate:2 1 udp 1686052607 10.64.8.12 9 typ srflx "
        "raddr 192.168.1.30 rport 54022"
    )
    info = parse_candidate_sdp(line)
    assert info.ip == "10.64.8.12"
    assert info.type == "srflx"
    assert info.related_address == "192.168.1.30"
    assert info.related_port == 54022


def test_classify_candidate_adapter() -> None:
    adapters = [
        _adapter("192.168.1.30", AdapterCategory.PHYSICAL_WIFI),
        _adapter("10.64.8.12", AdapterCategory.VPN_OR_TUNNEL),
    ]
    # annotate_adapters re-derives category from interface_type (6 → ethernet).
    assert classify_candidate_ip("192.168.1.30", adapters) == "physical_ethernet"
    # VPN fixture still uses ethernet if_type in this helper; force tunnel type.
    vpn = NetworkAdapter(
        adapter_id="vpn",
        friendly_name="VPN",
        description="VPN",
        operational_status=OperationalStatus.UP,
        interface_type=131,
        interface_type_name="TUNNEL",
        tunnel_type=1,
        tunnel_type_name="OTHER",
        physical_medium_type=None,
        physical_medium_name=None,
        speed_bps=100_000_000,
        ipv4_addresses=(
            IPv4AddressInfo(
                address="10.64.8.12",
                prefix_length=32,
                is_private=True,
                is_loopback=False,
            ),
        ),
    )
    assert classify_candidate_ip("10.64.8.12", [vpn]) == "vpn_or_tunnel"
    assert classify_candidate_ip("8.8.8.8", adapters) is None


def test_selected_candidate_mismatch_warning() -> None:
    selected = IceCandidateInfo(
        ip="10.64.8.12",
        port=9,
        protocol="udp",
        type="host",
        adapter_category="vpn_or_tunnel",
    )
    assert selected_matches_requested_ip(selected, "192.168.1.30") is False
    warning = mismatch_warning(selected, "192.168.1.30")
    assert warning is not None
    assert "ICE_SELECTED_WRONG_INTERFACE" in warning
    assert selected_matches_requested_ip(selected, "10.64.8.12") is True
    assert mismatch_warning(selected, "10.64.8.12") is None


def test_serialize_candidates() -> None:
    infos = [
        IceCandidateInfo(ip="192.168.1.30", port=1, protocol="udp", type="host"),
    ]
    data = serialize_candidates(infos)
    assert data[0]["ip"] == "192.168.1.30"
    assert data[0]["protocol"] == "udp"


def test_candidate_filter_default_passthrough() -> None:
    filt = CandidateFilter()
    infos = [
        IceCandidateInfo(ip="192.168.1.30", port=1, protocol="udp", type="host"),
        IceCandidateInfo(ip="10.0.0.1", port=2, protocol="udp", type="host"),
    ]
    assert filt.filter_local_candidates(infos, preferred_ip="192.168.1.30") == infos
