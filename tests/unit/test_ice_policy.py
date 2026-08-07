"""Unit tests for ICE host-candidate SDP filtering."""

from __future__ import annotations

from snowlink.rtc.ice_policy import TRICKLE_ICE_ENABLED, prefer_selected_host_ip


def test_trickle_disabled_for_mvp() -> None:
    assert TRICKLE_ICE_ENABLED is False


def test_prefer_selected_host_ip_filters_other_hosts() -> None:
    sdp = (
        "v=0\r\n"
        "o=- 0 0 IN IP4 0.0.0.0\r\n"
        "s=-\r\n"
        "t=0 0\r\n"
        "a=candidate:1 1 UDP 2122252543 192.168.1.10 50000 typ host\r\n"
        "a=candidate:2 1 UDP 2122252542 10.8.0.2 50001 typ host\r\n"
        "a=end-of-candidates\r\n"
    )
    out = prefer_selected_host_ip(sdp, "192.168.1.10")
    assert "192.168.1.10" in out
    assert "10.8.0.2" not in out


def test_prefer_selected_host_ip_leaves_sdp_if_would_remove_all() -> None:
    sdp = (
        "v=0\r\n"
        "a=candidate:1 1 UDP 2122252543 10.8.0.2 50000 typ host\r\n"
    )
    out = prefer_selected_host_ip(sdp, "192.168.1.10")
    assert "10.8.0.2" in out
