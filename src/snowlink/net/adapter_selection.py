"""Adapter classification, scoring, and manual/auto selection."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Sequence

from snowlink.net.adapter_models import (
    AdapterCategory,
    IPv4AddressInfo,
    NetworkAdapter,
    OperationalStatus,
    SelectedEndpoint,
)

# Windows IF_TYPE values (ipifcons.h)
IF_TYPE_ETHERNET_CSMACD = 6
IF_TYPE_ISO88025_TOKENRING = 9
IF_TYPE_PPP = 23
IF_TYPE_SOFTWARE_LOOPBACK = 24
IF_TYPE_ATM = 37
IF_TYPE_PROP_VIRTUAL = 53
IF_TYPE_IEEE80211 = 71
IF_TYPE_TUNNEL = 131
IF_TYPE_IEEE1394 = 144
IF_TYPE_OTHER = 1

# Windows TUNNEL_TYPE values (ifdef.h)
TUNNEL_TYPE_NONE = 0

# Preference: higher is better. Physical LAN private IPs win.
_CATEGORY_BASE_SCORE: dict[AdapterCategory, int] = {
    AdapterCategory.PHYSICAL_ETHERNET: 1000,
    AdapterCategory.PHYSICAL_WIFI: 900,
    AdapterCategory.TAILSCALE_OR_MESH: 200,
    AdapterCategory.UNKNOWN: 100,
    AdapterCategory.VIRTUAL_MACHINE_OR_HYPERVISOR: 50,
    AdapterCategory.WSL_OR_CONTAINER: 40,
    AdapterCategory.VPN_OR_TUNNEL: 20,
    AdapterCategory.LOOPBACK: 0,
}

_PREFERRED_CATEGORIES = frozenset(
    {
        AdapterCategory.PHYSICAL_ETHERNET,
        AdapterCategory.PHYSICAL_WIFI,
    }
)

_TAILSCALE_OR_MESH_PATTERNS = (
    re.compile(r"tailscale", re.I),
    re.compile(r"zerotier", re.I),
    re.compile(r"nebula", re.I),
    re.compile(r"netbird", re.I),
    re.compile(r"headscale", re.I),
)

_VPN_NAME_PATTERNS = (
    re.compile(r"\bvpn\b", re.I),
    re.compile(r"openvpn", re.I),
    re.compile(r"wireguard", re.I),
    re.compile(r"wintun", re.I),
    re.compile(r"tap-windows", re.I),
    re.compile(r"\btap\b", re.I),
    re.compile(r"\btun\b", re.I),
    re.compile(r"cisco", re.I),
    re.compile(r"anyconnect", re.I),
    re.compile(r"globalprotect", re.I),
    re.compile(r"pangp", re.I),
    re.compile(r"forticlient", re.I),
    re.compile(r"fortinet", re.I),
    re.compile(r"checkpoint", re.I),
    re.compile(r"pulse\s*secure", re.I),
    re.compile(r"juniper", re.I),
    re.compile(r"nordlynx", re.I),
    re.compile(r"nordvpn", re.I),
    re.compile(r"astrill", re.I),
    re.compile(r"expressvpn", re.I),
    re.compile(r"mullvad", re.I),
    re.compile(r"proton\s*vpn", re.I),
    re.compile(r"surfshark", re.I),
    re.compile(r"softether", re.I),
    re.compile(r"sstp", re.I),
    re.compile(r"l2tp", re.I),
    re.compile(r"pptp", re.I),
    re.compile(r"ikev2", re.I),
    re.compile(r"ras\s*adapter", re.I),
    re.compile(r"wan\s*minmax", re.I),
)

_HYPERVISOR_PATTERNS = (
    re.compile(r"hyper-?v", re.I),
    re.compile(r"vmware", re.I),
    re.compile(r"virtualbox", re.I),
    re.compile(r"vboxnet", re.I),
    re.compile(r"vethernet", re.I),
    re.compile(r"virtio", re.I),
    re.compile(r"qemu", re.I),
    re.compile(r"parallels", re.I),
    re.compile(r"virtual\s*machine", re.I),
)

_WSL_OR_CONTAINER_PATTERNS = (
    re.compile(r"\bwsl\b", re.I),
    re.compile(r"wslv2", re.I),
    re.compile(r"docker", re.I),
    # Linux-style veth peers (veth0), not Windows "vEthernet" Hyper-V switches.
    re.compile(r"\bveth\d+\b", re.I),
    re.compile(r"bridged.*container", re.I),
    re.compile(r"container\s*network", re.I),
)


_RFC1918_NETWORKS = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)


def is_rfc1918_private(address: str) -> bool:
    """Return True if *address* is in RFC1918 private space (not CGNAT/link-local)."""
    try:
        ip = ipaddress.IPv4Address(address)
    except ValueError:
        return False
    return any(ip in network for network in _RFC1918_NETWORKS)


def is_loopback_address(address: str) -> bool:
    """Return True if *address* is an IPv4 loopback address (127.0.0.0/8)."""
    try:
        return ipaddress.IPv4Address(address).is_loopback
    except ValueError:
        return False


def ipv4_address_info(address: str, prefix_length: int | None = None) -> IPv4AddressInfo:
    """Build :class:`IPv4AddressInfo` with private/loopback flags derived from the address."""
    return IPv4AddressInfo(
        address=address,
        prefix_length=prefix_length,
        is_private=is_rfc1918_private(address),
        is_loopback=is_loopback_address(address),
    )


def _blob(adapter: NetworkAdapter) -> str:
    return f"{adapter.friendly_name} {adapter.description}"


def _matches_any(text: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    return any(p.search(text) for p in patterns)


def classify_adapter(adapter: NetworkAdapter) -> AdapterCategory:
    """Classify an adapter using Windows metadata first, then name/description heuristics.

    Never drops adapters; VPN/virtual types are labeled so callers can deprioritize them.
    """
    if (
        adapter.interface_type == IF_TYPE_SOFTWARE_LOOPBACK
        or any(a.is_loopback for a in adapter.ipv4_addresses)
        or "loopback" in _blob(adapter).lower()
    ):
        return AdapterCategory.LOOPBACK

    text = _blob(adapter)

    # Structured tunnel / PPP / proprietary-virtual interfaces are VPN-like even
    # when names are opaque.
    if adapter.interface_type in (
        IF_TYPE_TUNNEL,
        IF_TYPE_PPP,
        IF_TYPE_PROP_VIRTUAL,
    ) or (
        adapter.tunnel_type != TUNNEL_TYPE_NONE
        and adapter.interface_type != IF_TYPE_SOFTWARE_LOOPBACK
    ):
        if _matches_any(text, _TAILSCALE_OR_MESH_PATTERNS):
            return AdapterCategory.TAILSCALE_OR_MESH
        return AdapterCategory.VPN_OR_TUNNEL

    if _matches_any(text, _TAILSCALE_OR_MESH_PATTERNS):
        return AdapterCategory.TAILSCALE_OR_MESH

    if _matches_any(text, _WSL_OR_CONTAINER_PATTERNS):
        return AdapterCategory.WSL_OR_CONTAINER

    if _matches_any(text, _HYPERVISOR_PATTERNS):
        return AdapterCategory.VIRTUAL_MACHINE_OR_HYPERVISOR

    if _matches_any(text, _VPN_NAME_PATTERNS):
        return AdapterCategory.VPN_OR_TUNNEL

    if adapter.interface_type == IF_TYPE_IEEE80211:
        return AdapterCategory.PHYSICAL_WIFI

    if adapter.interface_type in (
        IF_TYPE_ETHERNET_CSMACD,
        IF_TYPE_ISO88025_TOKENRING,
        IF_TYPE_ATM,
        IF_TYPE_IEEE1394,
    ):
        # Ethernet IF_TYPE is also used by some virtual switches; hypervisor heuristics
        # already ran above. Remaining Ethernet-type adapters are treated as physical.
        return AdapterCategory.PHYSICAL_ETHERNET

    return AdapterCategory.UNKNOWN


def score_adapter(adapter: NetworkAdapter, category: AdapterCategory | None = None) -> int:
    """Score an adapter for auto-selection. Higher is better."""
    cat = category if category is not None else classify_adapter(adapter)
    score = _CATEGORY_BASE_SCORE.get(cat, 0)

    if adapter.operational_status == OperationalStatus.UP:
        score += 50
    else:
        score -= 200

    private_addrs = [a for a in adapter.ipv4_addresses if a.is_private and not a.is_loopback]
    if private_addrs:
        score += 100
    elif any(not a.is_loopback for a in adapter.ipv4_addresses):
        score += 10  # public/link-local unicast still usable but not preferred for LAN

    if adapter.speed_bps is not None and adapter.speed_bps > 0 and cat in _PREFERRED_CATEGORIES:
        # Tiny tie-breaker favoring faster NICs (Mbps scale).
        score += min(adapter.speed_bps // 1_000_000, 100)

    return score


def annotate_adapter(adapter: NetworkAdapter) -> NetworkAdapter:
    """Return a copy of *adapter* with category, preference flag, and score filled in."""
    category = classify_adapter(adapter)
    preference_score = score_adapter(adapter, category)
    preferred = (
        category in _PREFERRED_CATEGORIES
        and adapter.operational_status == OperationalStatus.UP
        and any(a.is_private and not a.is_loopback for a in adapter.ipv4_addresses)
    )
    return NetworkAdapter(
        adapter_id=adapter.adapter_id,
        friendly_name=adapter.friendly_name,
        description=adapter.description,
        operational_status=adapter.operational_status,
        interface_type=adapter.interface_type,
        interface_type_name=adapter.interface_type_name,
        tunnel_type=adapter.tunnel_type,
        tunnel_type_name=adapter.tunnel_type_name,
        physical_medium_type=adapter.physical_medium_type,
        physical_medium_name=adapter.physical_medium_name,
        speed_bps=adapter.speed_bps,
        ipv4_addresses=adapter.ipv4_addresses,
        category=category,
        preferred=preferred,
        preference_score=preference_score,
    )


def annotate_adapters(adapters: Sequence[NetworkAdapter]) -> list[NetworkAdapter]:
    """Classify and score every adapter. Nothing is excluded."""
    return [annotate_adapter(a) for a in adapters]


def select_preferred_endpoint(
    adapters: Sequence[NetworkAdapter],
) -> SelectedEndpoint | None:
    """Auto-select the highest-scoring preferred physical LAN IPv4, if any."""
    annotated = annotate_adapters(adapters)
    candidates: list[tuple[int, NetworkAdapter, str]] = []
    for adapter in annotated:
        if not adapter.preferred:
            continue
        for addr in adapter.ipv4_addresses:
            if addr.is_private and not addr.is_loopback:
                candidates.append((adapter.preference_score, adapter, addr.address))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, adapter, ipv4 = candidates[0]
    return SelectedEndpoint(adapter=adapter, ipv4=ipv4)


def find_endpoint_by_ip(
    adapters: Sequence[NetworkAdapter],
    ipv4: str,
) -> SelectedEndpoint:
    """Resolve a user-supplied IPv4 to its adapter (manual override).

    Raises:
        ValueError: if *ipv4* is not a valid IPv4 address or is not present locally.
    """
    try:
        ipaddress.IPv4Address(ipv4)
    except ValueError as exc:
        raise ValueError(f"Invalid IPv4 address: {ipv4}") from exc

    annotated = annotate_adapters(adapters)
    for adapter in annotated:
        for addr in adapter.ipv4_addresses:
            if addr.address == ipv4:
                return SelectedEndpoint(adapter=adapter, ipv4=ipv4)
    raise ValueError(f"IPv4 address is not assigned to a local adapter: {ipv4}")


def find_adapter_by_id(
    adapters: Sequence[NetworkAdapter],
    adapter_id: str,
    ipv4: str | None = None,
) -> SelectedEndpoint:
    """Select an adapter by identifier, optionally choosing a specific IPv4 on it."""
    annotated = annotate_adapters(adapters)
    matches = [a for a in annotated if a.adapter_id == adapter_id]
    if not matches:
        raise ValueError(f"No adapter with id: {adapter_id}")
    adapter = matches[0]
    if not adapter.ipv4_addresses:
        raise ValueError(f"Adapter has no IPv4 addresses: {adapter_id}")
    if ipv4 is not None:
        if not any(a.address == ipv4 for a in adapter.ipv4_addresses):
            raise ValueError(f"Adapter {adapter_id} does not have IPv4 {ipv4}")
        return SelectedEndpoint(adapter=adapter, ipv4=ipv4)
    # Prefer private non-loopback, else first address.
    for addr in adapter.ipv4_addresses:
        if addr.is_private and not addr.is_loopback:
            return SelectedEndpoint(adapter=adapter, ipv4=addr.address)
    return SelectedEndpoint(adapter=adapter, ipv4=adapter.ipv4_addresses[0].address)
