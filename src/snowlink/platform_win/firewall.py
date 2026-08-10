"""Windows Firewall probe helpers (query only — never modify policy)."""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from snowlink.constants import NATIVE_MEDIA_PORT_MAX, NATIVE_MEDIA_PORT_MIN

logger = logging.getLogger(__name__)

FIREWALL_SETUP_HINT = (
    "Allow Snowlink through Windows Firewall when prompted on first listen, "
    f"or add an inbound rule for the executable (TCP signaling and UDP "
    f"{NATIVE_MEDIA_PORT_MIN}-{NATIVE_MEDIA_PORT_MAX} for native WebRTC). "
    "See docs/vpn-lan-access.md if a VPN kill-switch blocks LAN."
)


@dataclass(slots=True)
class FirewallProbeResult:
    """Result of a read-only firewall rule query."""

    rule_present: bool | None
    """True/False when query succeeded; None when probe could not run."""

    message: str
    details: dict[str, Any] = field(default_factory=dict)
    setup_hint: str = FIREWALL_SETUP_HINT


def _run_netsh(args: list[str], *, timeout_s: float = 8.0) -> tuple[int, str]:
    netsh = shutil.which("netsh")
    if not netsh:
        return 127, "netsh not found on PATH"
    try:
        completed = subprocess.run(
            [netsh, *args],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except OSError as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    except subprocess.TimeoutExpired:
        return 124, "netsh timed out"
    out = (completed.stdout or "") + (completed.stderr or "")
    return int(completed.returncode), out


def probe_firewall_rules(
    *,
    app_name: str = "Snowlink",
    port: int | None = None,
) -> FirewallProbeResult:
    """Query whether an inbound rule mentioning *app_name* (or *port*) exists.

    Never creates, enables, or disables firewall rules.
    """
    code, output = _run_netsh(
        ["advfirewall", "firewall", "show", "rule", "name=all", "dir=in"]
    )
    if code != 0:
        return FirewallProbeResult(
            rule_present=None,
            message=(
                "Could not query Windows Firewall rules. "
                "On first listen, accept the Windows Firewall prompt for Snowlink."
            ),
            details={"exit_code": code, "output_excerpt": output[:500]},
        )

    lower = output.lower()
    name_hit = app_name.lower() in lower
    port_hit = False
    if port is not None:
        # Match common netsh formatting for local ports.
        port_hit = f"localport:{port}" in lower.replace(" ", "") or (
            f" {port} " in f" {output} " and "udp" in lower
        )

    present = bool(name_hit or port_hit)
    if present:
        return FirewallProbeResult(
            rule_present=True,
            message=(
                f"Found an inbound firewall rule referencing "
                f"{'Snowlink' if name_hit else f'port {port}'}."
            ),
            details={"name_match": name_hit, "port_match": port_hit},
        )

    return FirewallProbeResult(
        rule_present=False,
        message=(
            "No inbound firewall rule mentioning Snowlink was found. "
            "Windows may still prompt on first listen; if connect hangs, "
            "add an allow rule for the app executable."
        ),
        details={"name_match": False, "port_match": False},
    )
