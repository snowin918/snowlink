#!/usr/bin/env python3
"""Experiment B — two-machine TCP connectivity with VPN scenarios.

Phase 0 validation. Reuses Experiment A adapter bind + TCP echo primitives.
Does not modify VPN or Windows Firewall settings.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from snowlink.net.adapter_selection import (  # noqa: E402
    annotate_adapters,
    select_preferred_endpoint,
)
from snowlink.net.experiment_b_models import (  # noqa: E402
    KNOWN_SESSION_NAMES,
    SESSION_MATRIX,
    validate_session_name,
)
from snowlink.net.experiment_b_results import (  # noqa: E402
    SchemaVersionError,
    format_summary_table,
    summarize_results,
    write_result,
)
from snowlink.net.socket_errors import SocketFailure, format_failure_human  # noqa: E402
from snowlink.net.tcp_diagnostics import (  # noqa: E402
    run_diagnostic_client,
    run_diagnostic_server,
)
from snowlink.net.tcp_echo import DEFAULT_PORT  # noqa: E402
from snowlink.platform_win.adapters import (  # noqa: E402
    AdapterEnumerationError,
    enumerate_adapters,
    is_windows,
)

DEFAULT_RESULTS_DIR = Path("experiment-results") / "experiment-b"

GUIDE_TEXT = """
Snowlink Experiment B - two-machine TCP while VPNs may be enabled
=================================================================

Purpose
-------
Verify whether two Windows 11 PCs on the same physical LAN can complete a
TCP echo (stand-in for later signaling) under four VPN combinations.
Snowlink never disables, bypasses, or reconfigures VPN or Windows Firewall.

Roles
-----
* Computer A (server / sharer stand-in): runs `serve` bound to its physical LAN IPv4.
* Computer B (client / viewer stand-in): runs `connect` to Computer A's LAN IPv4.

Finding the physical LAN IPv4
-----------------------------
On each PC:

  python experiments/experiment_a_adapter_bind.py list

Choose an adapter marked PREFERRED (physical_ethernet or physical_wifi) with a
private IPv4 (10/8, 172.16/12, 192.168/16). Do not use VPN, Hyper-V, WSL, or
loopback addresses for the primary path.

VPN test matrix (pass --session-name exactly)
---------------------------------------------
  vpn-off-off   Computer A VPN Off, Computer B VPN Off
  vpn-on-off    Computer A VPN On,  Computer B VPN Off
  vpn-off-on    Computer A VPN Off, Computer B VPN On
  vpn-on-on     Computer A VPN On,  Computer B VPN On

Record for each scenario
------------------------
* session name
* Computer A LAN IP and adapter category
* Computer B source IP (and --source-ip if used)
* success or failure
* error code (if any)
* connect / echo timings from the JSON result
* whether a Windows Firewall prompt appeared

Typical commands
----------------
Computer A:

  python experiments/experiment_b_two_machine_tcp.py serve `
    --ip <A-LAN-IP> --port 3847 --session-name vpn-off-off --serve-forever

Computer B:

  python experiments/experiment_b_two_machine_tcp.py connect `
    --ip <A-LAN-IP> --port 3847 --session-name vpn-off-off `
    --source-ip <B-LAN-IP> --timeout 5

Optional --source-ip binds the client to that local IPv4 before connect so the
path originates from the physical LAN adapter (no silent fallback).

Common failure symptoms
-----------------------
* CONNECTION_REFUSED — nothing listening, or active refuse / wrong bind IP.
* CONNECTION_TIMEOUT — silent drop; often firewall or VPN blocking LAN
  (likely causes only — not a certainty).
* NETWORK_UNREACHABLE / HOST_UNREACHABLE — routing / VPN route table issues.
* Wrong source IP in results — client used VPN path; set --source-ip to LAN.
* ECHO_MISMATCH — unexpected service on the port.

See docs/vpn-lan-access.md for the full runbook.
""".strip()


def _load_adapters_optional() -> list[Any]:
    if not is_windows():
        return []
    try:
        return annotate_adapters(enumerate_adapters())
    except AdapterEnumerationError:
        return []


def _results_dir(args: argparse.Namespace) -> Path:
    return Path(args.results_dir)


def cmd_guide(_args: argparse.Namespace) -> int:
    print(GUIDE_TEXT)
    print()
    print("Known session names:")
    for name in sorted(KNOWN_SESSION_NAMES):
        a, b = SESSION_MATRIX[name]
        print(f"  {name:12}  A VPN={a:3}  B VPN={b}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        session = validate_session_name(
            args.session_name,
            allow_custom=args.allow_custom_session,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    adapters = _load_adapters_optional()
    bind_ip = args.ip
    if not bind_ip:
        preferred = select_preferred_endpoint(adapters) if adapters else None
        if preferred is None:
            print(
                "ERROR: pass --ip with a local LAN IPv4 "
                "(no preferred adapter available).",
                file=sys.stderr,
            )
            return 2
        bind_ip = preferred.ipv4

    stop = threading.Event()

    def on_ready(bound: tuple[str, int]) -> None:
        line = f"Listening on {bound[0]}:{bound[1]} (getsockname)"
        print(line if not args.json else line, file=sys.stderr if args.json else sys.stdout)
        if not args.json:
            print("Accepting diagnostic clients (Ctrl+C to stop)...")

    if not args.json:
        match = next(
            (
                a
                for a in adapters
                for addr in a.ipv4_addresses
                if addr.address == bind_ip
            ),
            None,
        )
        if match is not None:
            print(
                f"Selected adapter: {match.friendly_name} "
                f"[{match.category.value}]  ip={bind_ip}"
            )
        print(f"Session: {session}")
        print(f"Binding diagnostic TCP server to {bind_ip}:{args.port}")

    try:
        outcome = run_diagnostic_server(
            bind_ip,
            args.port,
            session_name=session,
            adapters=adapters,
            max_clients=None if args.serve_forever else args.max_clients,
            stop_event=stop.is_set,
            ready_callback=on_ready,
            allow_bind_all=args.allow_bind_all,
            client_timeout_s=args.timeout,
        )
    except KeyboardInterrupt:
        stop.set()
        print("\nStopped.", file=sys.stderr)
        return 0

    result = outcome.result
    path = write_result(result, _results_dir(args))
    result.details["result_file"] = str(path)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        if result.success:
            print(f"Serve finished OK  bound={outcome.actual_bound_address}")
            for conn in outcome.connections:
                print(
                    f"  peer={conn.peer_ip}:{conn.peer_port}  "
                    f"at={conn.connected_at_utc}  bytes={conn.bytes_echoed}  "
                    f"test_id={conn.test_id}"
                )
            print(f"Result file: {path}")
        else:
            err = result.error or {}
            failure = SocketFailure(
                code=str(err.get("code", "UNKNOWN_SOCKET_ERROR")),
                message=str(err.get("message", "Serve failed")),
                os_error=err.get("os_error"),
                possible_causes=tuple(err.get("possible_causes") or ()),
                suggested_action=str(err.get("suggested_action") or ""),
            )
            print(format_failure_human(failure), file=sys.stderr)
            print(f"Result file: {path}", file=sys.stderr)
    return 0 if result.success else 1


def cmd_connect(args: argparse.Namespace) -> int:
    try:
        session = validate_session_name(
            args.session_name,
            allow_custom=args.allow_custom_session,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    adapters = _load_adapters_optional()
    result = run_diagnostic_client(
        args.ip,
        args.port,
        session_name=session,
        source_ip=args.source_ip,
        adapters=adapters or None,
        timeout_s=args.timeout,
    )
    path = write_result(result, _results_dir(args))
    result.details["result_file"] = str(path)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    elif result.success:
        timing = result.timing_ms
        print("Connect OK — echo verified")
        print(f"  session:     {result.session_name}")
        print(f"  test_id:     {result.test_id}")
        if result.local:
            print(
                f"  source:      {result.local.actual_source_ip}:"
                f"{result.local.actual_source_port}"
            )
            if result.local.adapter_name:
                print(
                    f"  adapter:     {result.local.adapter_name} "
                    f"[{result.local.adapter_category}]"
                )
        if result.remote:
            print(f"  destination: {result.remote.ip}:{result.remote.port}")
        print(
            f"  timing_ms:   connect={timing.connect_ms:.1f}  "
            f"echo={timing.echo_round_trip_ms:.1f}  total={timing.total_ms:.1f}"
            if timing.connect_ms is not None
            and timing.echo_round_trip_ms is not None
            and timing.total_ms is not None
            else f"  timing_ms:   {timing.to_dict()}"
        )
        print(f"  result file: {path}")
    else:
        err = result.error or {}
        failure = SocketFailure(
            code=str(err.get("code", "UNKNOWN_SOCKET_ERROR")),
            message=str(err.get("message", "Connect failed")),
            os_error=err.get("os_error"),
            possible_causes=tuple(err.get("possible_causes") or ()),
            suggested_action=str(err.get("suggested_action") or ""),
        )
        print(format_failure_human(failure), file=sys.stderr)
        print(f"Result file: {path}", file=sys.stderr)
    return 0 if result.success else 1


def cmd_summarize(args: argparse.Namespace) -> int:
    results_dir = _results_dir(args)
    try:
        rows = summarize_results(results_dir)
    except SchemaVersionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(format_summary_table(rows))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Experiment B: two-machine TCP connectivity under VPN scenarios",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON on stdout",
    )
    parser.add_argument(
        "--results-dir",
        default=str(DEFAULT_RESULTS_DIR),
        help=f"Directory for JSON results (default {DEFAULT_RESULTS_DIR})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    guide_p = sub.add_parser("guide", help="Print two-machine test instructions")
    guide_p.set_defaults(func=cmd_guide)

    serve_p = sub.add_parser("serve", help="Diagnostic TCP echo server on a LAN IPv4")
    serve_p.add_argument("--ip", help="Local IPv4 to bind (required unless auto-select works)")
    serve_p.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve_p.add_argument(
        "--session-name",
        required=True,
        help="Scenario name (vpn-off-off, vpn-on-off, vpn-off-on, vpn-on-on)",
    )
    serve_p.add_argument(
        "--allow-custom-session",
        action="store_true",
        help="Allow a session name outside the VPN matrix",
    )
    serve_p.add_argument(
        "--serve-forever",
        action="store_true",
        help="Accept clients until Ctrl+C",
    )
    serve_p.add_argument(
        "--max-clients",
        type=int,
        default=1,
        help="Stop after N clients when not --serve-forever (default 1)",
    )
    serve_p.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Per-connection read timeout seconds",
    )
    serve_p.add_argument(
        "--allow-bind-all",
        action="store_true",
        help="Development override: allow binding 0.0.0.0 (not for VPN tests)",
    )
    serve_p.set_defaults(func=cmd_serve)

    conn_p = sub.add_parser("connect", help="Diagnostic TCP echo client")
    conn_p.add_argument("--ip", required=True, help="Remote (Computer A) LAN IPv4")
    conn_p.add_argument("--port", type=int, default=DEFAULT_PORT)
    conn_p.add_argument("--session-name", required=True)
    conn_p.add_argument("--allow-custom-session", action="store_true")
    conn_p.add_argument(
        "--source-ip",
        help="Bind client to this local IPv4 before connect (no silent fallback)",
    )
    conn_p.add_argument("--timeout", type=float, default=5.0)
    conn_p.set_defaults(func=cmd_connect)

    sum_p = sub.add_parser("summarize", help="Summarize saved client JSON results")
    sum_p.set_defaults(func=cmd_summarize)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
