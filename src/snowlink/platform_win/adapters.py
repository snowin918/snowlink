"""Windows adapter enumeration via IP Helper ``GetAdaptersAddresses``.

This is the authoritative source for Experiment A on Windows. Non-Windows
platforms raise :class:`AdapterEnumerationError` so callers can skip or mock.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Any

from snowlink.net.adapter_models import NetworkAdapter, OperationalStatus
from snowlink.net.adapter_selection import annotate_adapters, ipv4_address_info

# --- Win32 constants ---------------------------------------------------------

AF_UNSPEC = 0
AF_INET = 2

GAA_FLAG_SKIP_ANYCAST = 0x0002
GAA_FLAG_SKIP_MULTICAST = 0x0004
GAA_FLAG_SKIP_DNS_SERVER = 0x0008
GAA_FLAG_INCLUDE_PREFIX = 0x0010

ERROR_BUFFER_OVERFLOW = 111
ERROR_SUCCESS = 0

IF_TYPE_NAMES: dict[int, str] = {
    1: "OTHER",
    6: "ETHERNET_CSMACD",
    9: "ISO88025_TOKENRING",
    23: "PPP",
    24: "SOFTWARE_LOOPBACK",
    37: "ATM",
    53: "PROP_VIRTUAL",
    71: "IEEE80211",
    131: "TUNNEL",
    144: "IEEE1394",
}

TUNNEL_TYPE_NAMES: dict[int, str] = {
    0: "NONE",
    1: "OTHER",
    2: "DIRECT",
    11: "6TO4",
    13: "ISATAP",
    14: "TEREDO",
    15: "IPHTTPS",
}

OPER_STATUS_MAP: dict[int, OperationalStatus] = {
    1: OperationalStatus.UP,
    2: OperationalStatus.DOWN,
    3: OperationalStatus.TESTING,
    4: OperationalStatus.UNKNOWN,
    5: OperationalStatus.DORMANT,
    6: OperationalStatus.NOT_PRESENT,
    7: OperationalStatus.LOWER_LAYER_DOWN,
}

PHYSICAL_MEDIUM_NAMES: dict[int, str] = {
    0: "802_3",
    1: "WirelessLan",
    8: "1394",
    9: "WirelessWan",
    10: "Native802_11",
    11: "Bluetooth",
}


class AdapterEnumerationError(RuntimeError):
    """Raised when Windows adapter enumeration is unavailable or fails."""


class SOCKET_ADDRESS(ctypes.Structure):
    _fields_ = [
        ("lpSockaddr", ctypes.POINTER(ctypes.c_ubyte)),
        ("iSockaddrLength", ctypes.c_int),
    ]


class IP_ADAPTER_UNICAST_ADDRESS(ctypes.Structure):
    pass


IP_ADAPTER_UNICAST_ADDRESS._fields_ = [
    ("Length", ctypes.c_ulong),
    ("Flags", ctypes.c_ulong),
    ("Next", ctypes.POINTER(IP_ADAPTER_UNICAST_ADDRESS)),
    ("Address", SOCKET_ADDRESS),
    ("PrefixOrigin", ctypes.c_int),
    ("SuffixOrigin", ctypes.c_int),
    ("DadState", ctypes.c_int),
    ("ValidLifetime", ctypes.c_ulong),
    ("PreferredLifetime", ctypes.c_ulong),
    ("LeaseLifetime", ctypes.c_ulong),
    ("OnLinkPrefixLength", ctypes.c_ubyte),
]


class IP_ADAPTER_ADDRESSES(ctypes.Structure):
    pass


# Vista+ IP_ADAPTER_ADDRESSES_LH field layout for the members we read.
IP_ADAPTER_ADDRESSES._fields_ = [
    ("Length", ctypes.c_ulong),
    ("IfIndex", ctypes.c_ulong),
    ("Next", ctypes.POINTER(IP_ADAPTER_ADDRESSES)),
    ("AdapterName", ctypes.c_char_p),
    ("FirstUnicastAddress", ctypes.POINTER(IP_ADAPTER_UNICAST_ADDRESS)),
    ("FirstAnycastAddress", ctypes.c_void_p),
    ("FirstMulticastAddress", ctypes.c_void_p),
    ("FirstDnsServerAddress", ctypes.c_void_p),
    ("DnsSuffix", ctypes.c_wchar_p),
    ("Description", ctypes.c_wchar_p),
    ("FriendlyName", ctypes.c_wchar_p),
    ("PhysicalAddress", ctypes.c_ubyte * 8),
    ("PhysicalAddressLength", ctypes.c_ulong),
    ("Flags", ctypes.c_ulong),
    ("Mtu", ctypes.c_ulong),
    ("IfType", ctypes.c_ulong),
    ("OperStatus", ctypes.c_uint),
    ("Ipv6IfIndex", ctypes.c_ulong),
    ("ZoneIndices", ctypes.c_ulong * 16),
    ("FirstPrefix", ctypes.c_void_p),
    ("TransmitLinkSpeed", ctypes.c_uint64),
    ("ReceiveLinkSpeed", ctypes.c_uint64),
    ("FirstWinsServerAddress", ctypes.c_void_p),
    ("FirstGatewayAddress", ctypes.c_void_p),
    ("Ipv4Metric", ctypes.c_ulong),
    ("Ipv6Metric", ctypes.c_ulong),
    ("Luid", ctypes.c_uint64),
    ("Dhcpv4Server", SOCKET_ADDRESS),
    ("CompartmentId", ctypes.c_ulong),
    ("NetworkGuid", ctypes.c_ubyte * 16),
    ("ConnectionType", ctypes.c_int),
    ("TunnelType", ctypes.c_int),
    ("Dhcpv6Server", SOCKET_ADDRESS),
    ("Dhcpv6ClientDuid", ctypes.c_ubyte * 130),
    ("Dhcpv6ClientDuidLength", ctypes.c_ulong),
    ("Dhcpv6Iaid", ctypes.c_ulong),
    ("FirstDnsSuffix", ctypes.c_void_p),
]


def _load_iphlpapi() -> Any:
    if sys.platform != "win32":
        raise AdapterEnumerationError("GetAdaptersAddresses is only available on Windows")
    return ctypes.WinDLL("iphlpapi.dll")


def _parse_ipv4_from_sockaddr(sock_addr: SOCKET_ADDRESS) -> str | None:
    if not sock_addr.lpSockaddr or sock_addr.iSockaddrLength < 8:
        return None
    raw = ctypes.string_at(sock_addr.lpSockaddr, sock_addr.iSockaddrLength)
    family = int.from_bytes(raw[0:2], byteorder="little")
    if family != AF_INET:
        return None
    return ".".join(str(b) for b in raw[4:8])


def _collect_ipv4(
    first: ctypes.POINTER(IP_ADAPTER_UNICAST_ADDRESS) | None,  # type: ignore[valid-type]
) -> list[tuple[str, int | None]]:
    results: list[tuple[str, int | None]] = []
    current = first
    while current:
        node = current.contents
        addr = _parse_ipv4_from_sockaddr(node.Address)
        if addr is not None:
            prefix_raw = int(node.OnLinkPrefixLength)
            prefix: int | None = prefix_raw if 0 <= prefix_raw <= 32 else None
            results.append((addr, prefix))
        current = node.Next
    return results


def enumerate_raw_adapters() -> list[NetworkAdapter]:
    """Enumerate adapters using ``GetAdaptersAddresses`` (IPv4 unicast collected).

    Returns unclassified adapters. Prefer :func:`enumerate_adapters` for scored results.
    """
    iphlpapi = _load_iphlpapi()
    get_adapters = iphlpapi.GetAdaptersAddresses
    get_adapters.argtypes = [
        wintypes.ULONG,
        wintypes.ULONG,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.ULONG),
    ]
    get_adapters.restype = wintypes.ULONG

    flags = (
        GAA_FLAG_SKIP_ANYCAST
        | GAA_FLAG_SKIP_MULTICAST
        | GAA_FLAG_SKIP_DNS_SERVER
        | GAA_FLAG_INCLUDE_PREFIX
    )

    size = wintypes.ULONG(0)
    ret = get_adapters(AF_UNSPEC, flags, None, None, ctypes.byref(size))
    if ret != ERROR_BUFFER_OVERFLOW:
        raise AdapterEnumerationError(f"GetAdaptersAddresses size probe failed: winerror={ret}")

    buffer = ctypes.create_string_buffer(size.value)
    ret = get_adapters(AF_UNSPEC, flags, None, buffer, ctypes.byref(size))
    if ret != ERROR_SUCCESS:
        raise AdapterEnumerationError(f"GetAdaptersAddresses failed: winerror={ret}")

    adapters: list[NetworkAdapter] = []
    ptr = ctypes.cast(buffer, ctypes.POINTER(IP_ADAPTER_ADDRESSES))
    while ptr:
        node = ptr.contents
        ipv4_pairs = _collect_ipv4(node.FirstUnicastAddress)
        ipv4_infos = tuple(ipv4_address_info(addr, prefix) for addr, prefix in ipv4_pairs)
        if_type = int(node.IfType)
        tunnel = int(node.TunnelType)
        tx = int(node.TransmitLinkSpeed)
        speed: int | None = tx if tx > 0 else None
        physical_medium: int | None = None

        adapter_name = (node.AdapterName or b"").decode("ascii", errors="replace")
        friendly = node.FriendlyName or ""
        description = node.Description or ""
        oper = OPER_STATUS_MAP.get(int(node.OperStatus), OperationalStatus.UNKNOWN)

        adapters.append(
            NetworkAdapter(
                adapter_id=adapter_name or f"ifindex-{int(node.IfIndex)}",
                friendly_name=friendly,
                description=description,
                operational_status=oper,
                interface_type=if_type,
                interface_type_name=IF_TYPE_NAMES.get(if_type, f"TYPE_{if_type}"),
                tunnel_type=tunnel,
                tunnel_type_name=TUNNEL_TYPE_NAMES.get(tunnel, f"TUNNEL_{tunnel}"),
                physical_medium_type=physical_medium,
                physical_medium_name=(
                    PHYSICAL_MEDIUM_NAMES.get(physical_medium)
                    if physical_medium is not None
                    else None
                ),
                speed_bps=speed,
                ipv4_addresses=ipv4_infos,
            )
        )
        ptr = node.Next

    return adapters


def enumerate_adapters() -> list[NetworkAdapter]:
    """Enumerate and classify Windows adapters.

    Nothing is excluded. VPN/virtual adapters are labeled and marked not preferred.
    """
    return annotate_adapters(enumerate_raw_adapters())


def is_windows() -> bool:
    """Return True when running on native Windows."""
    return sys.platform == "win32"
