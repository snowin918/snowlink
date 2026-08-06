"""Integration tests for bind-to-IP TCP echo."""

from __future__ import annotations

import socket
import threading
import time

import pytest

from snowlink.net.tcp_echo import (
    MAX_MESSAGE_BYTES,
    encode_message,
    run_echo_client,
    run_echo_server,
    try_bind,
)

pytestmark = pytest.mark.integration


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_successful_local_echo() -> None:
    port = _free_port()
    ready = threading.Event()
    bound_box: list[tuple[str, int]] = []

    def on_ready(bound: tuple[str, int]) -> None:
        bound_box.append(bound)
        ready.set()

    server_result: list[object] = []

    def server() -> None:
        server_result.append(
            run_echo_server(
                "127.0.0.1",
                port,
                ready_callback=on_ready,
                max_clients=1,
            )
        )

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    assert ready.wait(timeout=5.0)
    assert bound_box[0] == ("127.0.0.1", port)

    client = run_echo_client("127.0.0.1", port, "snowlink-test")
    thread.join(timeout=5.0)

    assert client.success is True
    assert client.error_code is None
    assert client.actual_bound_address == f"127.0.0.1:{port}"
    assert server_result
    serve = server_result[0]
    assert getattr(serve, "success") is True
    assert getattr(serve, "actual_bound_address") == f"127.0.0.1:{port}"


def test_invalid_local_bind_address() -> None:
    result = try_bind("203.0.113.1", _free_port())  # TEST-NET-3, not local
    assert result.success is False
    assert result.error_code in {"ADDR_NOT_AVAILABLE", "OS_ERROR_10049", "OS_ERROR_99"}
    assert result.error_message


def test_occupied_tcp_port() -> None:
    port = _free_port()
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", port))
    holder.listen(1)
    try:
        result = try_bind("127.0.0.1", port)
        assert result.success is False
        assert result.error_code in {"PORT_IN_USE", "OS_ERROR_10048", "OS_ERROR_98"}
        assert result.error_message
    finally:
        holder.close()


def test_connection_refused() -> None:
    port = _free_port()
    # Nothing listening.
    result = run_echo_client("127.0.0.1", port, "ping", timeout_s=1.0)
    assert result.success is False
    assert result.error_code in {
        "CONNECTION_REFUSED",
        "CONNECTION_TIMEOUT",
        "OS_ERROR_10061",
        "OS_ERROR_111",
    }


def test_connection_timeout() -> None:
    # TEST-NET-1 is non-routable blackhole for this purpose; may refuse or time out.
    result = run_echo_client("192.0.2.1", 3847, "ping", timeout_s=0.5)
    assert result.success is False
    assert result.error_code in {
        "CONNECTION_TIMEOUT",
        "CONNECTION_REFUSED",
        "CONNECTION_RESET",
        "HOST_UNREACHABLE",
        "OS_ERROR_10060",
        "OS_ERROR_10051",
        "OS_ERROR_10065",
        "OS_ERROR_10054",
        "OS_ERROR_101",
        "OS_ERROR_113",
    }
    assert result.elapsed_connection_ms is not None


def test_message_size_limit_encode() -> None:
    with pytest.raises(Exception) as excinfo:
        encode_message("x" * (MAX_MESSAGE_BYTES + 1))
    assert getattr(excinfo.value, "code", "") == "MESSAGE_TOO_LARGE"


def test_message_size_limit_client() -> None:
    result = run_echo_client(
        "127.0.0.1",
        _free_port(),
        "x" * (MAX_MESSAGE_BYTES + 1),
        timeout_s=0.5,
    )
    assert result.success is False
    assert result.error_code == "MESSAGE_TOO_LARGE"


def test_clean_socket_shutdown() -> None:
    port = _free_port()
    ready = threading.Event()

    def server() -> None:
        run_echo_server(
            "127.0.0.1",
            port,
            ready_callback=lambda _b: ready.set(),
            max_clients=1,
        )

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    assert ready.wait(timeout=5.0)
    assert run_echo_client("127.0.0.1", port, "shutdown-check").success is True
    thread.join(timeout=5.0)

    # Port should be reusable shortly after clean close.
    deadline = time.time() + 2.0
    last_error: OSError | None = None
    while time.time() < deadline:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", port))
            probe.close()
            break
        except OSError as exc:
            last_error = exc
            probe.close()
            time.sleep(0.05)
    else:
        pytest.fail(f"port not released after shutdown: {last_error}")


@pytest.mark.skipif(
    __import__("sys").platform != "win32",
    reason="Windows GetAdaptersAddresses enumeration only",
)
def test_windows_adapter_enumeration_smoke() -> None:
    from snowlink.platform_win.adapters import enumerate_adapters

    adapters = enumerate_adapters()
    assert isinstance(adapters, list)
    # At least loopback should exist on Windows.
    assert any(a.ipv4_addresses for a in adapters)
