"""TCP diagnostic client/server helpers for Experiment B (reuse Experiment A echo)."""

from __future__ import annotations

import ipaddress
import socket
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from snowlink.net.adapter_models import NetworkAdapter, SelectedEndpoint
from snowlink.net.adapter_selection import find_endpoint_by_ip
from snowlink.net.experiment_b_models import (
    EnvironmentInfo,
    ExperimentBResult,
    LocalEndpointInfo,
    RemoteEndpointInfo,
    TimingInfo,
    utc_now_iso,
)
from snowlink.net.socket_errors import (
    SocketFailure,
    classify_os_error,
    failure_for,
    legacy_code_to_b,
)
from snowlink.net.tcp_echo import (
    DEFAULT_CONNECT_TIMEOUT_S,
    MAX_MESSAGE_BYTES,
    RECV_BUFFER,
    TcpEchoError,
    encode_message,
    run_echo_server,
)

PROTOCOL_MARKER = "snowlink-exp-b/1"


@dataclass(slots=True)
class DiagnosticConnectionLog:
    connected_at_utc: str
    peer_ip: str
    peer_port: int
    bytes_echoed: int
    test_id: str | None = None


@dataclass(slots=True)
class DiagnosticServerOutcome:
    result: ExperimentBResult
    connections: list[DiagnosticConnectionLog] = field(default_factory=list)
    actual_bound_address: str | None = None


def validate_ipv4(address: str, *, kind: str) -> str:
    """Validate a dotted IPv4 address.

    Raises:
        SocketFailure-compatible :class:`TcpEchoError` via ValueError wrapping —
        callers should catch and map with :func:`invalid_ip_failure`.
    """
    try:
        ip = ipaddress.IPv4Address(address)
    except ValueError as exc:
        code = "INVALID_LOCAL_IP" if kind == "local" else "INVALID_REMOTE_IP"
        raise ValueError(code) from exc
    return str(ip)


def invalid_ip_failure(kind: str, raw: str) -> SocketFailure:
    code = "INVALID_LOCAL_IP" if kind == "local" else "INVALID_REMOTE_IP"
    return failure_for(code, f"Invalid IPv4 address: {raw!r}")


def resolve_local_endpoint(
    adapters: Sequence[NetworkAdapter],
    ipv4: str,
) -> SelectedEndpoint:
    """Resolve *ipv4* to a local adapter or raise :class:`SocketFailure` via ValueError."""
    try:
        validate_ipv4(ipv4, kind="local")
    except ValueError as exc:
        raise ValueError("INVALID_LOCAL_IP") from exc
    try:
        return find_endpoint_by_ip(adapters, ipv4)
    except ValueError as exc:
        raise ValueError("IP_NOT_ASSIGNED") from exc


def build_diagnostic_payload(
    *,
    test_id: str,
    session_name: str,
    hostname: str,
    timestamp: str | None = None,
) -> str:
    """Build a bounded, newline-delimited diagnostic message."""
    ts = timestamp or utc_now_iso()
    # Keep hostname sanitized / short.
    host = "".join(ch if ch.isalnum() or ch in ".-_" else "-" for ch in hostname)[:64]
    lines = [
        PROTOCOL_MARKER,
        f"test_id={test_id}",
        f"timestamp={ts}",
        f"session={session_name}",
        f"host={host or 'unknown'}",
    ]
    return "\n".join(lines) + "\n"


def parse_test_id_from_payload(data: bytes) -> str | None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    for line in text.splitlines():
        if line.startswith("test_id="):
            return line.split("=", 1)[1].strip() or None
    return None


def environment_info() -> EnvironmentInfo:
    import platform
    import sys

    plat = platform.platform()
    # Prefer a short Windows-11 style label when available.
    if sys.platform == "win32":
        plat = f"Windows-{platform.version()}" if platform.version() else "Windows"
    return EnvironmentInfo(platform=plat, python_version=sys.version.split()[0])


def sanitized_hostname() -> str:
    import socket as _socket

    raw = _socket.gethostname() or "unknown"
    return "".join(ch if ch.isalnum() or ch in ".-_" else "-" for ch in raw)[:64]


def run_diagnostic_server(
    bind_ip: str,
    port: int,
    *,
    session_name: str,
    adapters: Sequence[NetworkAdapter] | None = None,
    max_clients: int | None = None,
    stop_event: Callable[[], bool] | None = None,
    ready_callback: Callable[[tuple[str, int]], None] | None = None,
    allow_bind_all: bool = False,
    accept_timeout_s: float = 1.0,
    client_timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S,
) -> DiagnosticServerOutcome:
    """Serve diagnostic echoes on a specific IPv4; record peer connection logs."""
    started_at = utc_now_iso()
    test_id = str(uuid.uuid4())
    local_info = LocalEndpointInfo(
        hostname=sanitized_hostname(),
        requested_source_ip=bind_ip if bind_ip not in {"0.0.0.0", ""} else None,
        actual_source_ip=None,
    )
    selected: SelectedEndpoint | None = None
    if adapters and bind_ip not in {"0.0.0.0", "::", ""}:
        try:
            selected = resolve_local_endpoint(adapters, bind_ip)
            local_info.adapter_id = selected.adapter.adapter_id
            local_info.adapter_name = selected.adapter.friendly_name
            local_info.adapter_category = selected.adapter.category.value
        except ValueError:
            selected = None

    connections: list[DiagnosticConnectionLog] = []

    if bind_ip in {"0.0.0.0", "::", ""} and not allow_bind_all:
        failure = failure_for(
            "BIND_ALL_FORBIDDEN",
            "Refusing to bind to all interfaces; supply a specific IPv4 address.",
        )
        result = ExperimentBResult(
            test_id=test_id,
            role="server",
            session_name=session_name,
            started_at_utc=started_at,
            completed_at_utc=utc_now_iso(),
            success=False,
            local=local_info,
            remote=RemoteEndpointInfo(ip=bind_ip or "0.0.0.0", port=port),
            error=failure.to_dict(),
            environment=environment_info(),
        )
        return DiagnosticServerOutcome(result=result, connections=connections)

    # Custom accept loop so we can log peers with timestamps (reuse framing from tcp_echo).
    result = ExperimentBResult(
        test_id=test_id,
        role="server",
        session_name=session_name,
        started_at_utc=started_at,
        local=local_info,
        remote=RemoteEndpointInfo(ip=bind_ip, port=port),
        environment=environment_info(),
    )
    t0 = time.perf_counter()
    server: socket.socket | None = None
    handled = 0
    actual_bound: str | None = None
    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind((bind_ip, port))
        except OSError as exc:
            failure = classify_os_error(exc)
            if failure.code == "IP_NOT_ASSIGNED":
                failure = failure_for(
                    "BIND_FAILED",
                    failure.message,
                    os_error=failure.os_error,
                )
            result.success = False
            result.error = failure.to_dict()
            result.completed_at_utc = utc_now_iso()
            result.timing_ms.total_ms = (time.perf_counter() - t0) * 1000.0
            return DiagnosticServerOutcome(result=result, connections=connections)

        bound = server.getsockname()
        actual_bound = f"{bound[0]}:{bound[1]}"
        local_info.actual_source_ip = bound[0]
        local_info.actual_source_port = int(bound[1])
        result.local = local_info
        server.listen(5)
        server.settimeout(accept_timeout_s)
        if ready_callback is not None:
            ready_callback((bound[0], int(bound[1])))

        while True:
            if stop_event is not None and stop_event():
                break
            if max_clients is not None and handled >= max_clients:
                break
            try:
                conn, peer = server.accept()
            except TimeoutError:
                continue
            except OSError as exc:
                if stop_event is not None and stop_event():
                    break
                failure = classify_os_error(exc)
                result.success = False
                result.error = failure.to_dict()
                result.completed_at_utc = utc_now_iso()
                result.timing_ms.total_ms = (time.perf_counter() - t0) * 1000.0
                return DiagnosticServerOutcome(
                    result=result,
                    connections=connections,
                    actual_bound_address=actual_bound,
                )

            with conn:
                conn.settimeout(client_timeout_s)
                try:
                    data = _recv_limited(conn)
                    if data:
                        conn.sendall(data)
                    connections.append(
                        DiagnosticConnectionLog(
                            connected_at_utc=datetime.now(UTC).isoformat(),
                            peer_ip=peer[0],
                            peer_port=int(peer[1]),
                            bytes_echoed=len(data),
                            test_id=parse_test_id_from_payload(data),
                        )
                    )
                    handled += 1
                except TcpEchoError as exc:
                    failure = failure_for(
                        legacy_code_to_b(exc.code),
                        exc.message,
                    )
                    result.success = False
                    result.error = failure.to_dict()
                    result.details["connections"] = [asdict(c) for c in connections]
                    result.completed_at_utc = utc_now_iso()
                    result.timing_ms.total_ms = (time.perf_counter() - t0) * 1000.0
                    return DiagnosticServerOutcome(
                        result=result,
                        connections=connections,
                        actual_bound_address=actual_bound,
                    )

        result.success = True
        result.details["connections"] = [asdict(c) for c in connections]
        result.details["clients_handled"] = handled
        result.completed_at_utc = utc_now_iso()
        result.timing_ms.total_ms = (time.perf_counter() - t0) * 1000.0
        return DiagnosticServerOutcome(
            result=result,
            connections=connections,
            actual_bound_address=actual_bound,
        )
    finally:
        if server is not None:
            try:
                server.close()
            except OSError:
                pass


def _recv_limited(conn: socket.socket, max_bytes: int = MAX_MESSAGE_BYTES) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        try:
            block = conn.recv(RECV_BUFFER)
        except TimeoutError as exc:
            raise TcpEchoError("CONNECTION_TIMEOUT", "Timed out waiting for client data") from exc
        if not block:
            break
        total += len(block)
        if total > max_bytes:
            raise TcpEchoError(
                "MESSAGE_TOO_LARGE",
                f"Received message exceeds limit of {max_bytes} bytes",
            )
        chunks.append(block)
    return b"".join(chunks)


def run_diagnostic_client(
    remote_ip: str,
    port: int,
    *,
    session_name: str,
    source_ip: str | None = None,
    adapters: Sequence[NetworkAdapter] | None = None,
    timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S,
    hostname: str | None = None,
    test_id: str | None = None,
    message: str | None = None,
) -> ExperimentBResult:
    """Connect with optional source-IP bind, send diagnostic payload, verify echo."""
    started_at = utc_now_iso()
    tid = test_id or str(uuid.uuid4())
    host = hostname or sanitized_hostname()
    t0 = time.perf_counter()
    timing = TimingInfo()
    local = LocalEndpointInfo(
        hostname=host,
        requested_source_ip=source_ip,
    )
    result = ExperimentBResult(
        test_id=tid,
        role="client",
        session_name=session_name,
        started_at_utc=started_at,
        local=local,
        remote=RemoteEndpointInfo(ip=remote_ip, port=port),
        timing_ms=timing,
        environment=environment_info(),
    )

    try:
        validate_ipv4(remote_ip, kind="remote")
    except ValueError:
        result.success = False
        result.error = invalid_ip_failure("remote", remote_ip).to_dict()
        result.completed_at_utc = utc_now_iso()
        result.timing_ms.total_ms = (time.perf_counter() - t0) * 1000.0
        return result

    if source_ip is not None:
        try:
            validate_ipv4(source_ip, kind="local")
        except ValueError:
            result.success = False
            result.error = invalid_ip_failure("local", source_ip).to_dict()
            result.completed_at_utc = utc_now_iso()
            result.timing_ms.total_ms = (time.perf_counter() - t0) * 1000.0
            return result
        if adapters is not None:
            try:
                selected = resolve_local_endpoint(adapters, source_ip)
            except ValueError as exc:
                code = str(exc.args[0]) if exc.args else "IP_NOT_ASSIGNED"
                if code == "INVALID_LOCAL_IP":
                    failure = invalid_ip_failure("local", source_ip)
                else:
                    failure = failure_for(
                        "IP_NOT_ASSIGNED",
                        f"Source IPv4 is not assigned to a local adapter: {source_ip}",
                    )
                result.success = False
                result.error = failure.to_dict()
                result.completed_at_utc = utc_now_iso()
                result.timing_ms.total_ms = (time.perf_counter() - t0) * 1000.0
                return result
            local.adapter_id = selected.adapter.adapter_id
            local.adapter_name = selected.adapter.friendly_name
            local.adapter_category = selected.adapter.category.value
            result.local = local

    payload_text = message or build_diagnostic_payload(
        test_id=tid,
        session_name=session_name,
        hostname=host,
    )
    sock: socket.socket | None = None
    try:
        try:
            payload = encode_message(payload_text)
        except TcpEchoError as exc:
            result.success = False
            result.error = failure_for(legacy_code_to_b(exc.code), exc.message).to_dict()
            result.completed_at_utc = utc_now_iso()
            result.timing_ms.total_ms = (time.perf_counter() - t0) * 1000.0
            return result

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout_s)

        if source_ip is not None:
            try:
                sock.bind((source_ip, 0))
            except OSError as exc:
                failure = classify_os_error(exc)
                # Do not fall back to another source address.
                if failure.code == "IP_NOT_ASSIGNED":
                    failure = failure_for(
                        "BIND_FAILED",
                        f"Failed to bind client to source IP {source_ip}.",
                        os_error=failure.os_error,
                    )
                result.success = False
                result.error = failure.to_dict()
                result.completed_at_utc = utc_now_iso()
                result.timing_ms.total_ms = (time.perf_counter() - t0) * 1000.0
                return result

        t_connect = time.perf_counter()
        try:
            sock.connect((remote_ip, port))
        except OSError as exc:
            failure = classify_os_error(exc)
            result.success = False
            result.error = failure.to_dict()
            result.timing_ms.connect_ms = (time.perf_counter() - t_connect) * 1000.0
            result.timing_ms.total_ms = (time.perf_counter() - t0) * 1000.0
            result.completed_at_utc = utc_now_iso()
            return result
        result.timing_ms.connect_ms = (time.perf_counter() - t_connect) * 1000.0

        local_name = sock.getsockname()
        local.actual_source_ip = local_name[0]
        local.actual_source_port = int(local_name[1])
        result.local = local
        result.details["getsockname"] = f"{local_name[0]}:{local_name[1]}"
        result.details["getpeername"] = f"{sock.getpeername()[0]}:{sock.getpeername()[1]}"

        t_echo = time.perf_counter()
        sock.sendall(payload)
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass

        received = bytearray()
        while len(received) < len(payload):
            try:
                block = sock.recv(RECV_BUFFER)
            except OSError as exc:
                failure = classify_os_error(exc)
                result.success = False
                result.error = failure.to_dict()
                result.timing_ms.echo_round_trip_ms = (time.perf_counter() - t_echo) * 1000.0
                result.timing_ms.total_ms = (time.perf_counter() - t0) * 1000.0
                result.completed_at_utc = utc_now_iso()
                return result
            if not block:
                if received and bytes(received) != payload:
                    result.success = False
                    result.error = failure_for(
                        "ECHO_MISMATCH",
                        "Echoed payload did not match the sent diagnostic message.",
                    ).to_dict()
                else:
                    result.success = False
                    result.error = failure_for(
                        "SERVER_CLOSED",
                        "Server closed the connection before the full echo was received.",
                    ).to_dict()
                result.timing_ms.echo_round_trip_ms = (time.perf_counter() - t_echo) * 1000.0
                result.timing_ms.total_ms = (time.perf_counter() - t0) * 1000.0
                result.completed_at_utc = utc_now_iso()
                return result
            received.extend(block)
            if len(received) > MAX_MESSAGE_BYTES:
                result.success = False
                result.error = failure_for(
                    "MESSAGE_TOO_LARGE",
                    f"Echo response exceeds limit of {MAX_MESSAGE_BYTES} bytes.",
                ).to_dict()
                result.timing_ms.echo_round_trip_ms = (time.perf_counter() - t_echo) * 1000.0
                result.timing_ms.total_ms = (time.perf_counter() - t0) * 1000.0
                result.completed_at_utc = utc_now_iso()
                return result

        result.timing_ms.echo_round_trip_ms = (time.perf_counter() - t_echo) * 1000.0

        if bytes(received) != payload:
            result.success = False
            result.error = failure_for(
                "ECHO_MISMATCH",
                "Echoed payload did not match the sent diagnostic message.",
            ).to_dict()
            result.timing_ms.total_ms = (time.perf_counter() - t0) * 1000.0
            result.completed_at_utc = utc_now_iso()
            return result

        result.success = True
        result.details["message_bytes"] = len(payload)
        result.timing_ms.total_ms = (time.perf_counter() - t0) * 1000.0
        result.completed_at_utc = utc_now_iso()
        return result
    finally:
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass


def run_echo_server_compat(
    bind_ip: str,
    port: int,
    **kwargs: Any,
) -> Any:
    """Thin wrapper retained for callers that still want Experiment A serve behavior."""
    return run_echo_server(bind_ip, port, **kwargs)
