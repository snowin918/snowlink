"""Data models for network adapter enumeration and classification."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class AdapterCategory(StrEnum):
    """High-level adapter classification used for preference and display."""

    PHYSICAL_ETHERNET = "physical_ethernet"
    PHYSICAL_WIFI = "physical_wifi"
    VPN_OR_TUNNEL = "vpn_or_tunnel"
    VIRTUAL_MACHINE_OR_HYPERVISOR = "virtual_machine_or_hypervisor"
    WSL_OR_CONTAINER = "wsl_or_container"
    TAILSCALE_OR_MESH = "tailscale_or_mesh"
    LOOPBACK = "loopback"
    UNKNOWN = "unknown"


class OperationalStatus(StrEnum):
    """Subset of IF_OPER_STATUS values we surface to users."""

    UP = "up"
    DOWN = "down"
    TESTING = "testing"
    UNKNOWN = "unknown"
    DORMANT = "dormant"
    NOT_PRESENT = "not_present"
    LOWER_LAYER_DOWN = "lower_layer_down"


@dataclass(frozen=True, slots=True)
class IPv4AddressInfo:
    """One IPv4 unicast address bound to an adapter."""

    address: str
    prefix_length: int | None
    is_private: bool
    is_loopback: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class NetworkAdapter:
    """Normalized view of a Windows (or mock) network adapter with IPv4 addresses."""

    adapter_id: str
    friendly_name: str
    description: str
    operational_status: OperationalStatus
    interface_type: int
    interface_type_name: str
    tunnel_type: int
    tunnel_type_name: str
    physical_medium_type: int | None
    physical_medium_name: str | None
    speed_bps: int | None
    ipv4_addresses: tuple[IPv4AddressInfo, ...] = field(default_factory=tuple)
    category: AdapterCategory = AdapterCategory.UNKNOWN
    preferred: bool = False
    preference_score: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["operational_status"] = self.operational_status.value
        data["category"] = self.category.value
        data["ipv4_addresses"] = [addr.to_dict() for addr in self.ipv4_addresses]
        return data


@dataclass(frozen=True, slots=True)
class SelectedEndpoint:
    """User- or auto-selected adapter plus the IPv4 used for binding."""

    adapter: NetworkAdapter
    ipv4: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter.to_dict(),
            "ipv4": self.ipv4,
        }
