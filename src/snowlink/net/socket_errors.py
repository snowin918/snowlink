"""Sanitized socket-error classification for Phase 0 networking experiments."""

from __future__ import annotations

import errno
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SocketFailure:
    """Machine-readable failure with safe guidance (no secrets)."""

    code: str
    message: str
    os_error: int | None = None
    possible_causes: tuple[str, ...] = ()
    suggested_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_CAUSES: dict[str, tuple[str, ...]] = {
    "INVALID_LOCAL_IP": (
        "The supplied local IPv4 address is malformed.",
        "A hostname was provided where a dotted IPv4 was required.",
    ),
    "INVALID_REMOTE_IP": (
        "The destination address is not a valid IPv4 address.",
        "A typo in the remote IP entered for the test.",
    ),
    "IP_NOT_ASSIGNED": (
        "The IPv4 is not currently assigned to any local adapter.",
        "The wrong adapter/IP was copied from the list command.",
        "The interface went down after the IP was noted.",
    ),
    "BIND_FAILED": (
        "The local address cannot be bound by this process.",
        "The address is not available on this host.",
    ),
    "PORT_IN_USE": (
        "Another process is already listening on that IP and port.",
        "A previous experiment server did not exit cleanly.",
    ),
    "CONNECTION_REFUSED": (
        "Nothing is accepting TCP connections on the destination IP:port.",
        "The server bound a different address than the one you dialed.",
        "Windows Firewall or another filter actively refused the SYN.",
    ),
    "CONNECTION_TIMEOUT": (
        "Windows Firewall may have blocked the inbound connection.",
        "The VPN client may block local LAN traffic (kill switch / no Allow LAN).",
        "The wrong physical LAN IP was selected.",
        "The server is not listening on the expected address.",
        "An intermediate network filter dropped the packets.",
    ),
    "NETWORK_UNREACHABLE": (
        "No usable route exists to the destination network.",
        "VPN routing may have removed or overridden the LAN route.",
    ),
    "HOST_UNREACHABLE": (
        "The destination host is not reachable on the current route table.",
        "The peers may not share a common LAN subnet.",
    ),
    "CONNECTION_RESET": (
        "A middlebox or the peer reset the TCP connection.",
        "Firewall or VPN policy interrupted the handshake or transfer.",
    ),
    "ECHO_MISMATCH": (
        "Bytes received did not match the diagnostic payload sent.",
        "A proxy or unexpected service answered on that port.",
    ),
    "MESSAGE_TOO_LARGE": (
        "The diagnostic payload exceeded the enforced size limit.",
    ),
    "SERVER_CLOSED": (
        "The remote side closed the connection before the echo completed.",
        "The server timed out or exited during the transfer.",
    ),
    "UNKNOWN_SOCKET_ERROR": (
        "An unexpected socket error occurred.",
    ),
    "BIND_ALL_FORBIDDEN": (
        "Binding to all interfaces was refused by experiment policy.",
    ),
}

_ACTIONS: dict[str, str] = {
    "INVALID_LOCAL_IP": "Pass a dotted IPv4 such as 192.168.1.30 for --source-ip / --ip.",
    "INVALID_REMOTE_IP": "Confirm the remote LAN IPv4 with Experiment A `list` on the server PC.",
    "IP_NOT_ASSIGNED": "Re-run adapter `list` and copy an IPv4 that is currently assigned.",
    "BIND_FAILED": "Verify the IP is local and not restricted; retry with the preferred LAN IP.",
    "PORT_IN_USE": "Stop the other listener or choose a free --port.",
    "CONNECTION_REFUSED": "Confirm the server is running and bound to the IP you dialed.",
    "CONNECTION_TIMEOUT": (
        "Check firewall prompts, VPN Allow LAN / local network settings, and the selected IPs. "
        "Do not disable managed security controls; contact an administrator if required."
    ),
    "NETWORK_UNREACHABLE": "Confirm both PCs are on the same physical LAN and review VPN routes.",
    "HOST_UNREACHABLE": "Ping is optional; prefer re-checking LAN IPs and VPN LAN-access options.",
    "CONNECTION_RESET": "Retry once; if persistent, inspect firewall/VPN LAN policy.",
    "ECHO_MISMATCH": "Ensure only the Experiment B server is bound to that port.",
    "MESSAGE_TOO_LARGE": (
        "Shorten the diagnostic message or use the documented size limit."
    ),
    "SERVER_CLOSED": "Keep the server running until the client finishes; check server logs.",
    "UNKNOWN_SOCKET_ERROR": (
        "Capture the OS error number and re-run with --json for the result file."
    ),
    "BIND_ALL_FORBIDDEN": (
        "Supply a specific IPv4, or pass the explicit allow-bind-all development flag."
    ),
}


def failure_for(
    code: str,
    message: str,
    *,
    os_error: int | None = None,
) -> SocketFailure:
    """Build a :class:`SocketFailure` with standard causes/actions for *code*."""
    return SocketFailure(
        code=code,
        message=message,
        os_error=os_error,
        possible_causes=_CAUSES.get(code, _CAUSES["UNKNOWN_SOCKET_ERROR"]),
        suggested_action=_ACTIONS.get(code, _ACTIONS["UNKNOWN_SOCKET_ERROR"]),
    )


def classify_os_error(exc: OSError) -> SocketFailure:
    """Map an :class:`OSError` to a sanitized :class:`SocketFailure`."""
    winerr = getattr(exc, "winerror", None)
    err = exc.errno
    os_error = winerr if winerr is not None else err

    if isinstance(exc, TimeoutError) or err == errno.ETIMEDOUT or winerr == 10060:
        return failure_for(
            "CONNECTION_TIMEOUT",
            "The TCP connection did not complete before the timeout.",
            os_error=os_error,
        )
    if err == errno.ECONNREFUSED or winerr == 10061:
        return failure_for(
            "CONNECTION_REFUSED",
            "Remote host refused the TCP connection.",
            os_error=os_error,
        )
    if err == errno.ECONNRESET or winerr == 10054:
        return failure_for(
            "CONNECTION_RESET",
            "TCP connection was reset by the remote host.",
            os_error=os_error,
        )
    if err == errno.EADDRINUSE or winerr == 10048:
        return failure_for(
            "PORT_IN_USE",
            "TCP port is already in use on the selected address.",
            os_error=os_error,
        )
    if err == errno.EADDRNOTAVAIL or winerr == 10049:
        return failure_for(
            "IP_NOT_ASSIGNED",
            "Bind address is not available on this host.",
            os_error=os_error,
        )
    if err == errno.ENETUNREACH or winerr == 10051:
        return failure_for(
            "NETWORK_UNREACHABLE",
            "Network is unreachable from this host.",
            os_error=os_error,
        )
    if err == errno.EHOSTUNREACH or winerr == 10065:
        return failure_for(
            "HOST_UNREACHABLE",
            "Host is unreachable from this host.",
            os_error=os_error,
        )

    # Preserve Experiment A-compatible short codes for generic OS errors via UNKNOWN.
    return failure_for(
        "UNKNOWN_SOCKET_ERROR",
        f"Unexpected socket error ({exc.__class__.__name__}).",
        os_error=os_error,
    )


def format_failure_human(failure: SocketFailure) -> str:
    """Render a multi-line operator-facing explanation."""
    lines = [failure.message, "", "Possible causes:"]
    for cause in failure.possible_causes:
        lines.append(f"- {cause}")
    if failure.suggested_action:
        lines.extend(["", f"Suggested next step: {failure.suggested_action}"])
    if failure.os_error is not None:
        lines.append(f"OS error: {failure.os_error}")
    return "\n".join(lines)


# Legacy Experiment A short codes still emitted by tcp_echo helpers.
_LEGACY_CODE_MAP: dict[str, str] = {
    "ADDR_NOT_AVAILABLE": "IP_NOT_ASSIGNED",
    "OS_ERROR": "UNKNOWN_SOCKET_ERROR",
}


def legacy_code_to_b(code: str) -> str:
    """Map Experiment A short codes onto Experiment B taxonomy when needed."""
    if code in _CAUSES:
        return code
    if code.startswith("OS_ERROR_"):
        return "UNKNOWN_SOCKET_ERROR"
    return _LEGACY_CODE_MAP.get(code, code)
