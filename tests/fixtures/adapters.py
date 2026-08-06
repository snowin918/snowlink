"""Shared mock adapters for unit tests."""

from __future__ import annotations

from snowlink.net.adapter_models import NetworkAdapter, OperationalStatus
from snowlink.net.adapter_selection import (
    IF_TYPE_ETHERNET_CSMACD,
    IF_TYPE_IEEE80211,
    IF_TYPE_SOFTWARE_LOOPBACK,
    IF_TYPE_TUNNEL,
    TUNNEL_TYPE_NONE,
    ipv4_address_info,
)


def make_adapter(
    *,
    adapter_id: str = "test-adapter",
    friendly_name: str = "Test Adapter",
    description: str = "Test Adapter Description",
    operational_status: OperationalStatus = OperationalStatus.UP,
    interface_type: int = IF_TYPE_ETHERNET_CSMACD,
    interface_type_name: str = "ETHERNET_CSMACD",
    tunnel_type: int = TUNNEL_TYPE_NONE,
    tunnel_type_name: str = "NONE",
    physical_medium_type: int | None = None,
    physical_medium_name: str | None = None,
    speed_bps: int | None = 1_000_000_000,
    ipv4: tuple[tuple[str, int | None], ...] = (("192.168.1.20", 24),),
) -> NetworkAdapter:
    return NetworkAdapter(
        adapter_id=adapter_id,
        friendly_name=friendly_name,
        description=description,
        operational_status=operational_status,
        interface_type=interface_type,
        interface_type_name=interface_type_name,
        tunnel_type=tunnel_type,
        tunnel_type_name=tunnel_type_name,
        physical_medium_type=physical_medium_type,
        physical_medium_name=physical_medium_name,
        speed_bps=speed_bps,
        ipv4_addresses=tuple(ipv4_address_info(addr, prefix) for addr, prefix in ipv4),
    )


def sample_adapter_set() -> list[NetworkAdapter]:
    """Deterministic mix of physical, VPN, virtual, Tailscale, and loopback adapters."""
    return [
        make_adapter(
            adapter_id="{eth0}",
            friendly_name="Ethernet",
            description="Intel(R) Ethernet Connection",
            interface_type=IF_TYPE_ETHERNET_CSMACD,
            ipv4=(("192.168.1.20", 24),),
            speed_bps=1_000_000_000,
        ),
        make_adapter(
            adapter_id="{wifi0}",
            friendly_name="Wi-Fi",
            description="Intel(R) Wi-Fi 6 AX201",
            interface_type=IF_TYPE_IEEE80211,
            interface_type_name="IEEE80211",
            ipv4=(("192.168.1.55", 24),),
            speed_bps=600_000_000,
        ),
        make_adapter(
            adapter_id="{vpn0}",
            friendly_name="Corp VPN",
            description="Cisco AnyConnect Secure Mobility Client Virtual Miniport Adapter",
            interface_type=IF_TYPE_TUNNEL,
            interface_type_name="TUNNEL",
            tunnel_type=15,
            tunnel_type_name="IPHTTPS",
            ipv4=(("10.64.8.12", 32),),
            speed_bps=100_000_000,
        ),
        make_adapter(
            adapter_id="{ts0}",
            friendly_name="Tailscale",
            description="Tailscale Tunnel",
            interface_type=IF_TYPE_TUNNEL,
            interface_type_name="TUNNEL",
            tunnel_type=1,
            tunnel_type_name="OTHER",
            ipv4=(("100.64.1.2", 32),),
        ),
        make_adapter(
            adapter_id="{hv0}",
            friendly_name="vEthernet (Default Switch)",
            description="Hyper-V Virtual Ethernet Adapter",
            interface_type=IF_TYPE_ETHERNET_CSMACD,
            ipv4=(("172.28.80.1", 20),),
        ),
        make_adapter(
            adapter_id="{wsl0}",
            friendly_name="vEthernet (WSL)",
            description="Hyper-V Virtual Ethernet Adapter",
            interface_type=IF_TYPE_ETHERNET_CSMACD,
            ipv4=(("172.22.32.1", 20),),
        ),
        make_adapter(
            adapter_id="{lo}",
            friendly_name="Loopback Pseudo-Interface 1",
            description="Software Loopback Interface 1",
            interface_type=IF_TYPE_SOFTWARE_LOOPBACK,
            interface_type_name="SOFTWARE_LOOPBACK",
            ipv4=(("127.0.0.1", 8),),
            speed_bps=None,
        ),
    ]
