"""Integration-style tests for Experiment B diagnostics (single host)."""

from __future__ import annotations

import socket
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from tests.fixtures.adapters import make_adapter, sample_adapter_set

from snowlink.net.tcp_diagnostics import run_diagnostic_client, run_diagnostic_server
from snowlink.net.tcp_echo import MAX_MESSAGE_BYTES

pytestmark = pytest.mark.integration


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_source_ip_validation_rejects_unassigned() -> None:
    adapters = sample_adapter_set()
    result = run_diagnostic_client(
        "127.0.0.1",
        _free_port(),
        session_name="vpn-off-off",
        source_ip="192.168.9.9",
        adapters=adapters,
        timeout_s=0.5,
    )
    assert result.success is False
    assert result.error is not None
    assert result.error["code"] == "IP_NOT_ASSIGNED"


def test_source_ip_validation_rejects_invalid() -> None:
    result = run_diagnostic_client(
        "127.0.0.1",
        3847,
        session_name="vpn-off-off",
        source_ip="not-an-ip",
        timeout_s=0.5,
    )
    assert result.success is False
    assert result.error is not None
    assert result.error["code"] == "INVALID_LOCAL_IP"


def test_invalid_remote_ip() -> None:
    result = run_diagnostic_client(
        "bad-remote",
        3847,
        session_name="vpn-off-off",
        timeout_s=0.5,
    )
    assert result.success is False
    assert result.error is not None
    assert result.error["code"] == "INVALID_REMOTE_IP"


def test_local_source_socket_binding_and_echo() -> None:
    port = _free_port()
    ready = threading.Event()

    def server() -> None:
        run_diagnostic_server(
            "127.0.0.1",
            port,
            session_name="vpn-off-off",
            max_clients=1,
            ready_callback=lambda _b: ready.set(),
        )

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    assert ready.wait(timeout=5.0)

    loopback_adapters = [
        make_adapter(
            adapter_id="{lo}",
            friendly_name="Loopback",
            description="Software Loopback Interface 1",
            interface_type=24,
            interface_type_name="SOFTWARE_LOOPBACK",
            ipv4=(("127.0.0.1", 8),),
        )
    ]
    result = run_diagnostic_client(
        "127.0.0.1",
        port,
        session_name="vpn-off-off",
        source_ip="127.0.0.1",
        adapters=loopback_adapters,
        timeout_s=2.0,
    )
    thread.join(timeout=5.0)

    assert result.success is True
    assert result.local is not None
    assert result.local.requested_source_ip == "127.0.0.1"
    assert result.local.actual_source_ip == "127.0.0.1"
    assert result.local.actual_source_port is not None
    assert result.timing_ms.connect_ms is not None
    assert result.timing_ms.echo_round_trip_ms is not None
    assert result.timing_ms.total_ms is not None
    assert result.error is None


def test_connection_refusal() -> None:
    port = _free_port()
    result = run_diagnostic_client(
        "127.0.0.1",
        port,
        session_name="vpn-off-off",
        timeout_s=1.0,
    )
    assert result.success is False
    assert result.error is not None
    assert result.error["code"] in {
        "CONNECTION_REFUSED",
        "CONNECTION_TIMEOUT",
        "UNKNOWN_SOCKET_ERROR",
    }


def test_timeout_handling_with_mock() -> None:
    with patch("snowlink.net.tcp_diagnostics.socket.socket") as sock_cls:
        sock = MagicMock()
        sock_cls.return_value = sock
        sock.connect.side_effect = TimeoutError()
        result = run_diagnostic_client(
            "192.0.2.1",
            3847,
            session_name="vpn-on-on",
            timeout_s=0.2,
        )
    assert result.success is False
    assert result.error is not None
    assert result.error["code"] == "CONNECTION_TIMEOUT"
    assert "possible_causes" in result.error
    assert result.timing_ms.connect_ms is not None


def test_echo_mismatch_detected() -> None:
    port = _free_port()
    ready = threading.Event()

    def evil_server() -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(1)
        ready.set()
        conn, _peer = srv.accept()
        with conn:
            _ = conn.recv(65536)
            conn.sendall(b"not-the-echo")
        srv.close()

    thread = threading.Thread(target=evil_server, daemon=True)
    thread.start()
    assert ready.wait(timeout=5.0)
    result = run_diagnostic_client(
        "127.0.0.1",
        port,
        session_name="vpn-off-off",
        timeout_s=2.0,
    )
    thread.join(timeout=5.0)
    assert result.success is False
    assert result.error is not None
    assert result.error["code"] == "ECHO_MISMATCH"


def test_message_too_large() -> None:
    result = run_diagnostic_client(
        "127.0.0.1",
        _free_port(),
        session_name="vpn-off-off",
        message="x" * (MAX_MESSAGE_BYTES + 1),
        timeout_s=0.5,
    )
    assert result.success is False
    assert result.error is not None
    assert result.error["code"] == "MESSAGE_TOO_LARGE"


def test_client_and_server_clean_shutdown() -> None:
    port = _free_port()
    ready = threading.Event()

    def server() -> None:
        run_diagnostic_server(
            "127.0.0.1",
            port,
            session_name="vpn-off-off",
            max_clients=1,
            ready_callback=lambda _b: ready.set(),
        )

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    assert ready.wait(timeout=5.0)
    assert run_diagnostic_client(
        "127.0.0.1",
        port,
        session_name="vpn-off-off",
        timeout_s=2.0,
    ).success
    thread.join(timeout=5.0)

    # Port reusable after clean close.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
    finally:
        probe.close()


def test_bind_all_forbidden_without_override() -> None:
    outcome = run_diagnostic_server(
        "0.0.0.0",
        _free_port(),
        session_name="vpn-off-off",
        max_clients=0,
        allow_bind_all=False,
    )
    assert outcome.result.success is False
    assert outcome.result.error is not None
    assert outcome.result.error["code"] == "BIND_ALL_FORBIDDEN"


def test_source_bind_failure_does_not_fallback() -> None:
    """If bind to source_ip fails, connect must not proceed on another address."""
    with patch("snowlink.net.tcp_diagnostics.socket.socket") as sock_cls:
        sock = MagicMock()
        sock_cls.return_value = sock
        err = OSError("not available")
        err.errno = 10049
        err.winerror = 10049  # type: ignore[attr-defined]
        sock.bind.side_effect = err
        result = run_diagnostic_client(
            "192.168.1.25",
            3847,
            session_name="vpn-on-on",
            source_ip="192.168.1.30",
            adapters=[
                make_adapter(
                    adapter_id="{eth}",
                    ipv4=(("192.168.1.30", 24),),
                )
            ],
            timeout_s=0.5,
        )
    assert result.success is False
    assert result.error is not None
    assert result.error["code"] in {"BIND_FAILED", "IP_NOT_ASSIGNED"}
    sock.connect.assert_not_called()


def test_cli_writes_result_file(tmp_path: Path) -> None:
    import importlib.util

    module_path = (
        Path(__file__).resolve().parents[2]
        / "experiments"
        / "experiment_b_two_machine_tcp.py"
    )
    spec = importlib.util.spec_from_file_location("experiment_b_cli", module_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    port = _free_port()
    ready = threading.Event()

    def server() -> None:
        run_diagnostic_server(
            "127.0.0.1",
            port,
            session_name="vpn-off-off",
            max_clients=1,
            ready_callback=lambda _b: ready.set(),
        )

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    assert ready.wait(timeout=5.0)

    code = mod.main(
        [
            "--results-dir",
            str(tmp_path),
            "connect",
            "--ip",
            "127.0.0.1",
            "--port",
            str(port),
            "--session-name",
            "vpn-off-off",
        ]
    )
    thread.join(timeout=5.0)
    assert code == 0
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
