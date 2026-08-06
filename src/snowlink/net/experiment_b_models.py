"""Experiment B result models and VPN scenario helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = 1
EXPERIMENT_NAME = "experiment_b_two_machine_tcp"

KNOWN_SESSION_NAMES: frozenset[str] = frozenset(
    {
        "vpn-off-off",
        "vpn-on-off",
        "vpn-off-on",
        "vpn-on-on",
    }
)

SESSION_MATRIX: dict[str, tuple[str, str]] = {
    "vpn-off-off": ("Off", "Off"),
    "vpn-on-off": ("On", "Off"),
    "vpn-off-on": ("Off", "On"),
    "vpn-on-on": ("On", "On"),
}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class LocalEndpointInfo:
    hostname: str
    requested_source_ip: str | None = None
    actual_source_ip: str | None = None
    actual_source_port: int | None = None
    adapter_id: str | None = None
    adapter_name: str | None = None
    adapter_category: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RemoteEndpointInfo:
    ip: str
    port: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TimingInfo:
    dns_ms: float | None = None
    connect_ms: float | None = None
    echo_round_trip_ms: float | None = None
    total_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dns": self.dns_ms,
            "connect": self.connect_ms,
            "echo_round_trip": self.echo_round_trip_ms,
            "total": self.total_ms,
        }


@dataclass(slots=True)
class EnvironmentInfo:
    platform: str
    python_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExperimentBResult:
    """Schema v1 result for Experiment B client or server roles."""

    experiment: str = EXPERIMENT_NAME
    schema_version: int = SCHEMA_VERSION
    test_id: str = ""
    role: str = "client"
    session_name: str = ""
    started_at_utc: str = field(default_factory=utc_now_iso)
    completed_at_utc: str | None = None
    success: bool = False
    local: LocalEndpointInfo | None = None
    remote: RemoteEndpointInfo | None = None
    timing_ms: TimingInfo = field(default_factory=TimingInfo)
    error: dict[str, Any] | None = None
    environment: EnvironmentInfo | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment,
            "schema_version": self.schema_version,
            "test_id": self.test_id,
            "role": self.role,
            "session_name": self.session_name,
            "started_at_utc": self.started_at_utc,
            "completed_at_utc": self.completed_at_utc,
            "success": self.success,
            "local": self.local.to_dict() if self.local else None,
            "remote": self.remote.to_dict() if self.remote else None,
            "timing_ms": self.timing_ms.to_dict(),
            "error": self.error,
            "environment": self.environment.to_dict() if self.environment else None,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentBResult:
        local_raw = data.get("local")
        remote_raw = data.get("remote")
        timing_raw = data.get("timing_ms") or {}
        env_raw = data.get("environment")
        local = (
            LocalEndpointInfo(
                hostname=str(local_raw.get("hostname", "")),
                requested_source_ip=local_raw.get("requested_source_ip"),
                actual_source_ip=local_raw.get("actual_source_ip"),
                actual_source_port=local_raw.get("actual_source_port"),
                adapter_id=local_raw.get("adapter_id"),
                adapter_name=local_raw.get("adapter_name"),
                adapter_category=local_raw.get("adapter_category"),
            )
            if isinstance(local_raw, dict)
            else None
        )
        remote = (
            RemoteEndpointInfo(ip=str(remote_raw["ip"]), port=int(remote_raw["port"]))
            if isinstance(remote_raw, dict)
            else None
        )
        timing = TimingInfo(
            dns_ms=timing_raw.get("dns"),
            connect_ms=timing_raw.get("connect"),
            echo_round_trip_ms=timing_raw.get("echo_round_trip"),
            total_ms=timing_raw.get("total"),
        )
        environment = (
            EnvironmentInfo(
                platform=str(env_raw.get("platform", "")),
                python_version=str(env_raw.get("python_version", "")),
            )
            if isinstance(env_raw, dict)
            else None
        )
        return cls(
            experiment=str(data.get("experiment", EXPERIMENT_NAME)),
            schema_version=int(data.get("schema_version", 0)),
            test_id=str(data.get("test_id", "")),
            role=str(data.get("role", "")),
            session_name=str(data.get("session_name", "")),
            started_at_utc=str(data.get("started_at_utc", "")),
            completed_at_utc=data.get("completed_at_utc"),
            success=bool(data.get("success", False)),
            local=local,
            remote=remote,
            timing_ms=timing,
            error=data.get("error") if isinstance(data.get("error"), dict) else data.get("error"),
            environment=environment,
            details=dict(data.get("details") or {}),
        )


def validate_session_name(name: str, *, allow_custom: bool) -> str:
    """Validate a scenario / session name.

    Raises:
        ValueError: when *name* is empty or not recognized without *allow_custom*.
    """
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("session name must not be empty")
    if cleaned in KNOWN_SESSION_NAMES:
        return cleaned
    if allow_custom:
        return cleaned
    known = ", ".join(sorted(KNOWN_SESSION_NAMES))
    raise ValueError(
        f"Unrecognized session name {cleaned!r}. "
        f"Use one of: {known} (or pass --allow-custom-session)."
    )
