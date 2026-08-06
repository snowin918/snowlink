"""TCP echo server and client bound to a specific IPv4 address."""

from __future__ import annotations

import errno
import socket
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

DEFAULT_PORT = 3847
DEFAULT_CONNECT_TIMEOUT_S = 5.0
MAX_MESSAGE_BYTES = 4096
RECV_BUFFER = 8192


class TcpEchoError(Exception):
    """Base error for TCP echo operations with a sanitized machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class ExperimentResult:
    """Machine-readable Experiment A result payload."""

    experiment: str = "experiment_a_adapter_bind"
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    operation: str = ""
    selected_adapter: dict[str, Any] | None = None
    selected_ip: str | None = None
    requested_port: int | None = None
    actual_bound_address: str | None = None
    success: bool = False
    elapsed_connection_ms: float | None = None
    error_code: str | None = None
    error_message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sanitize_os_error(exc: OSError) -> tuple[str, str]:
    """Map OSError to a stable code and a short safe message (no host secrets)."""
    winerr = getattr(exc, "winerror", None)
    err = exc.errno
    if err in (errno.EADDRNOTAVAIL, errno.EADDRINUSE) or winerr in (10049, 10048):
        if err == errno.EADDRINUSE or winerr == 10048:
            return "PORT_IN_USE", "TCP port is already in use on the selected address"
        return "ADDR_NOT_AVAILABLE", "Bind address is not available on this host"
    if err in (errno.ECONNREFUSED,) or winerr == 10061:
        return "CONNECTION_REFUSED", "Remote host refused the TCP connection"
    if err in (errno.ECONNRESET,) or winerr == 10054:
        return "CONNECTION_RESET", "TCP connection was reset by the remote host"
    if err in (errno.ETIMEDOUT,) or winerr == 10060:
        return "CONNECTION_TIMEOUT", "TCP connection timed out"
    if err in (errno.EHOSTUNREACH, errno.ENETUNREACH) or winerr in (10065, 10051):
        return "HOST_UNREACHABLE", "Host or network is unreachable"
    if isinstance(exc, TimeoutError) or err == errno.EINTR:
        return "CONNECTION_TIMEOUT", "TCP connection timed out"
    code = f"OS_ERROR_{winerr if winerr is not None else err}"
    return code, exc.__class__.__name__


def encode_message(message: str, max_bytes: int = MAX_MESSAGE_BYTES) -> bytes:
    """Encode a UTF-8 message and enforce the size limit."""
    data = message.encode("utf-8")
    if len(data) > max_bytes:
        raise TcpEchoError(
            "MESSAGE_TOO_LARGE",
            f"Message exceeds limit of {max_bytes} bytes (got {len(data)})",
        )
    return data


def run_echo_server(
    bind_ip: str,
    port: int,
    *,
    stop_event: Callable[[], bool] | None = None,
    ready_callback: Callable[[tuple[str, int]], None] | None = None,
    max_clients: int | None = 1,
    accept_timeout_s: float = 1.0,
) -> ExperimentResult:
    """Bind a TCP echo server to *bind_ip*:*port* (never ``0.0.0.0`` by default).

    Serves until *max_clients* have been handled (default 1) or *stop_event*
    returns True. Each connection reads one length-limited payload and echoes it.
    """
    result = ExperimentResult(
        operation="serve",
        selected_ip=bind_ip,
        requested_port=port,
    )
    started = time.perf_counter()
    if bind_ip in {"0.0.0.0", "::", ""}:
        result.success = False
        result.error_code = "BIND_ALL_FORBIDDEN"
        result.error_message = (
            "Refusing to bind to all interfaces; supply a specific IPv4 address"
        )
        result.elapsed_connection_ms = (time.perf_counter() - started) * 1000.0
        return result

    server: socket.socket | None = None
    handled = 0
    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Allow quick restarts in experiments; still bind to a specific IP.
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind((bind_ip, port))
        except OSError as exc:
            code, msg = _sanitize_os_error(exc)
            raise TcpEchoError(code, msg) from exc

        bound = server.getsockname()
        result.actual_bound_address = f"{bound[0]}:{bound[1]}"
        server.listen(1)
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
                code, msg = _sanitize_os_error(exc)
                raise TcpEchoError(code, msg) from exc

            with conn:
                conn.settimeout(DEFAULT_CONNECT_TIMEOUT_S)
                data = _recv_limited(conn)
                if data:
                    conn.sendall(data)
                handled += 1
                result.details["last_peer"] = f"{peer[0]}:{peer[1]}"
                result.details["bytes_echoed"] = len(data)

        result.success = True
        result.elapsed_connection_ms = (time.perf_counter() - started) * 1000.0
        return result
    except TcpEchoError as exc:
        result.success = False
        result.error_code = exc.code
        result.error_message = exc.message
        result.elapsed_connection_ms = (time.perf_counter() - started) * 1000.0
        return result
    finally:
        if server is not None:
            try:
                server.close()
            except OSError:
                pass


def _recv_limited(conn: socket.socket, max_bytes: int = MAX_MESSAGE_BYTES) -> bytes:
    """Read until peer half-closes / closes, enforcing *max_bytes*."""
    chunks: list[bytes] = []
    total = 0
    while True:
        try:
            block = conn.recv(RECV_BUFFER)
        except TimeoutError as exc:
            raise TcpEchoError("READ_TIMEOUT", "Timed out waiting for client data") from exc
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


def run_echo_client(
    remote_ip: str,
    port: int,
    message: str,
    *,
    timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S,
    max_message_bytes: int = MAX_MESSAGE_BYTES,
) -> ExperimentResult:
    """Connect to a TCP echo server, send *message*, and verify the echo."""
    result = ExperimentResult(
        operation="connect",
        selected_ip=remote_ip,
        requested_port=port,
    )
    started = time.perf_counter()
    sock: socket.socket | None = None
    try:
        payload = encode_message(message, max_bytes=max_message_bytes)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout_s)
        try:
            sock.connect((remote_ip, port))
        except OSError as exc:
            code, msg = _sanitize_os_error(exc)
            # Python maps timeouts to TimeoutError (OSError subclass) on some platforms.
            if isinstance(exc, TimeoutError):
                code, msg = "CONNECTION_TIMEOUT", "TCP connection timed out"
            raise TcpEchoError(code, msg) from exc

        peer = sock.getpeername()
        result.actual_bound_address = f"{peer[0]}:{peer[1]}"
        sock.sendall(payload)
        # Half-close write so a blocking server recv can finish cleanly.
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass

        received = bytearray()
        while len(received) < len(payload):
            block = sock.recv(RECV_BUFFER)
            if not block:
                break
            received.extend(block)
            if len(received) > max_message_bytes:
                raise TcpEchoError(
                    "MESSAGE_TOO_LARGE",
                    f"Echo response exceeds limit of {max_message_bytes} bytes",
                )

        if bytes(received) != payload:
            raise TcpEchoError(
                "ECHO_MISMATCH",
                "Echoed payload did not match the sent message",
            )

        result.success = True
        result.details["message_bytes"] = len(payload)
        result.elapsed_connection_ms = (time.perf_counter() - started) * 1000.0
        return result
    except TcpEchoError as exc:
        result.success = False
        result.error_code = exc.code
        result.error_message = exc.message
        result.elapsed_connection_ms = (time.perf_counter() - started) * 1000.0
        return result
    except OSError as exc:
        code, msg = _sanitize_os_error(exc)
        if isinstance(exc, TimeoutError):
            code, msg = "CONNECTION_TIMEOUT", "TCP connection timed out"
        result.success = False
        result.error_code = code
        result.error_message = msg
        result.elapsed_connection_ms = (time.perf_counter() - started) * 1000.0
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


def try_bind(bind_ip: str, port: int, *, reuse_addr: bool = False) -> ExperimentResult:
    """Attempt a bind-only probe (bind + getsockname + close) without accepting clients.

    ``reuse_addr`` defaults to False so an occupied port is reported clearly.
    """
    result = ExperimentResult(
        operation="bind_probe",
        selected_ip=bind_ip,
        requested_port=port,
    )
    started = time.perf_counter()
    if bind_ip in {"0.0.0.0", "::", ""}:
        result.success = False
        result.error_code = "BIND_ALL_FORBIDDEN"
        result.error_message = "Refusing to bind to all interfaces; supply a specific IPv4 address"
        result.elapsed_connection_ms = (time.perf_counter() - started) * 1000.0
        return result

    sock: socket.socket | None = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if reuse_addr:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((bind_ip, port))
        bound = sock.getsockname()
        result.actual_bound_address = f"{bound[0]}:{bound[1]}"
        result.success = True
        result.elapsed_connection_ms = (time.perf_counter() - started) * 1000.0
        return result
    except OSError as exc:
        code, msg = _sanitize_os_error(exc)
        result.success = False
        result.error_code = code
        result.error_message = msg
        result.elapsed_connection_ms = (time.perf_counter() - started) * 1000.0
        return result
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
