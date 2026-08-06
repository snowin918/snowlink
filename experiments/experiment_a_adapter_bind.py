#!/usr/bin/env python3
"""Experiment A — adapter enumeration, classification, and bind-to-IP TCP echo.

Phase 0 validation only. Not the application architecture.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# Allow running without editable install: add src/ to path when needed.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from snowlink.net.adapter_models import NetworkAdapter, SelectedEndpoint  # noqa: E402
from snowlink.net.adapter_selection import (  # noqa: E402
    annotate_adapters,
    find_adapter_by_id,
    find_endpoint_by_ip,
    select_preferred_endpoint,
)
from snowlink.net.tcp_echo import (  # noqa: E402
    DEFAULT_PORT,
    ExperimentResult,
    run_echo_client,
    run_echo_server,
)
from snowlink.platform_win.adapters import (  # noqa: E402
    AdapterEnumerationError,
    enumerate_adapters,
    is_windows,
)


def _print_human_adapters(adapters: Sequence[NetworkAdapter]) -> None:
    print(f"Adapters found: {len(adapters)}")
    print("-" * 72)
    for idx, adapter in enumerate(adapters, start=1):
        pref = "PREFERRED" if adapter.preferred else "not-preferred"
        print(f"[{idx}] {adapter.friendly_name}")
        print(f"    id:          {adapter.adapter_id}")
        print(f"    description: {adapter.description}")
        print(f"    status:      {adapter.operational_status.value}")
        print(f"    ifType:      {adapter.interface_type} ({adapter.interface_type_name})")
        print(f"    tunnelType:  {adapter.tunnel_type} ({adapter.tunnel_type_name})")
        if adapter.physical_medium_type is not None:
            print(
                f"    medium:      {adapter.physical_medium_type}"
                f" ({adapter.physical_medium_name})"
            )
        if adapter.speed_bps is not None:
            print(f"    speed_bps:   {adapter.speed_bps}")
        print(
            f"    category:    {adapter.category.value}  [{pref}]  "
            f"score={adapter.preference_score}"
        )
        if adapter.ipv4_addresses:
            for addr in adapter.ipv4_addresses:
                flags: list[str] = []
                if addr.is_private:
                    flags.append("private")
                if addr.is_loopback:
                    flags.append("loopback")
                prefix = f"/{addr.prefix_length}" if addr.prefix_length is not None else ""
                flag_s = f" ({', '.join(flags)})" if flags else ""
                print(f"    ipv4:        {addr.address}{prefix}{flag_s}")
        else:
            print("    ipv4:        (none)")
        print()


def _load_adapters() -> list[NetworkAdapter]:
    if not is_windows():
        raise AdapterEnumerationError(
            "Experiment A adapter listing requires Windows (GetAdaptersAddresses)"
        )
    return enumerate_adapters()


def cmd_list(args: argparse.Namespace) -> int:
    try:
        adapters = _load_adapters()
    except AdapterEnumerationError as exc:
        err_text = str(exc)
        result = ExperimentResult(
            operation="list",
            success=False,
            error_code="ENUMERATION_FAILED",
            error_message=err_text,
        )
        _emit(
            result,
            args.json,
            human_extra=lambda: print(f"ERROR: {err_text}", file=sys.stderr),
        )
        return 1

    preferred = select_preferred_endpoint(adapters)
    result = ExperimentResult(
        operation="list",
        success=True,
        selected_adapter=preferred.adapter.to_dict() if preferred else None,
        selected_ip=preferred.ipv4 if preferred else None,
        details={
            "adapter_count": len(adapters),
            "adapters": [a.to_dict() for a in adapters],
            "auto_selected": preferred.to_dict() if preferred else None,
        },
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        _print_human_adapters(adapters)
        if preferred:
            print(
                f"Auto-selected (preferred): {preferred.ipv4} "
                f"on {preferred.adapter.friendly_name} "
                f"[{preferred.adapter.category.value}]"
            )
        else:
            print("Auto-selected (preferred): (none — use manual --ip / --adapter-id)")
    return 0


def _resolve_endpoint(
    args: argparse.Namespace,
    adapters: Sequence[NetworkAdapter],
) -> SelectedEndpoint:
    if getattr(args, "adapter_id", None):
        return find_adapter_by_id(adapters, args.adapter_id, ipv4=getattr(args, "ip", None))
    if getattr(args, "ip", None):
        return find_endpoint_by_ip(adapters, args.ip)
    preferred = select_preferred_endpoint(adapters)
    if preferred is None:
        raise ValueError(
            "No preferred physical LAN IPv4 found; pass --ip or --adapter-id explicitly"
        )
    return preferred


def cmd_serve(args: argparse.Namespace) -> int:
    adapters: list[NetworkAdapter] = []
    selected: SelectedEndpoint | None = None
    bind_ip = args.ip
    try:
        if is_windows():
            adapters = annotate_adapters(_load_adapters())
            if args.adapter_id or args.ip:
                selected = _resolve_endpoint(args, adapters)
                bind_ip = selected.ipv4
            else:
                selected = select_preferred_endpoint(adapters)
                if selected is None:
                    raise ValueError(
                        "No preferred physical LAN IPv4 found; pass --ip explicitly"
                    )
                bind_ip = selected.ipv4
        elif not bind_ip:
            raise ValueError("Non-Windows hosts must pass --ip explicitly")
    except (AdapterEnumerationError, ValueError) as exc:
        err_text = str(exc)
        result = ExperimentResult(
            operation="serve",
            selected_ip=bind_ip,
            requested_port=args.port,
            success=False,
            error_code="SELECTION_FAILED",
            error_message=err_text,
        )
        _emit(
            result,
            args.json,
            human_extra=lambda: print(f"ERROR: {err_text}", file=sys.stderr),
        )
        return 1

    assert bind_ip is not None

    stop = threading.Event()

    def on_ready(bound: tuple[str, int]) -> None:
        msg = f"Listening on {bound[0]}:{bound[1]} (getsockname)"
        if args.json:
            print(msg, file=sys.stderr)
        else:
            print(msg)
            print("Waiting for a client (Ctrl+C to stop)...")

    if not args.json:
        if selected is not None:
            print(
                f"Selected adapter: {selected.adapter.friendly_name} "
                f"[{selected.adapter.category.value}]"
            )
        print(f"Binding TCP echo server to {bind_ip}:{args.port}")

    try:
        result = run_echo_server(
            bind_ip,
            args.port,
            stop_event=stop.is_set,
            ready_callback=on_ready,
            max_clients=None if args.serve_forever else 1,
        )
    except KeyboardInterrupt:
        stop.set()
        result = ExperimentResult(
            operation="serve",
            selected_adapter=selected.adapter.to_dict() if selected else None,
            selected_ip=bind_ip,
            requested_port=args.port,
            success=True,
            details={"stopped": "keyboard_interrupt"},
        )
        if not args.json:
            print("\nStopped.")
        else:
            print(json.dumps(result.to_dict(), indent=2))
        return 0

    if selected is not None:
        result.selected_adapter = selected.adapter.to_dict()
    result.selected_ip = bind_ip
    _emit(result, args.json, human_extra=lambda: _print_serve_human(result))
    return 0 if result.success else 1


def _print_serve_human(result: ExperimentResult) -> None:
    if result.success:
        print(f"Serve OK  bound={result.actual_bound_address}")
        if result.details:
            print(f"Details: {result.details}")
    else:
        print(
            f"Serve FAILED  code={result.error_code}  message={result.error_message}",
            file=sys.stderr,
        )


def cmd_connect(args: argparse.Namespace) -> int:
    result = run_echo_client(
        args.ip,
        args.port,
        args.message,
        timeout_s=args.timeout,
    )
    _emit(
        result,
        args.json,
        human_extra=lambda: _print_connect_human(result, args.message),
    )
    return 0 if result.success else 1


def _print_connect_human(result: ExperimentResult, message: str) -> None:
    if result.success:
        elapsed = result.elapsed_connection_ms
        elapsed_s = f"{elapsed:.1f} ms" if elapsed is not None else "n/a"
        print(f"Connect OK  peer={result.actual_bound_address}  echo verified")
        print(f"Message: {message!r}  elapsed={elapsed_s}")
    else:
        print(
            f"Connect FAILED  code={result.error_code}  message={result.error_message}",
            file=sys.stderr,
        )


def _emit(
    result: ExperimentResult,
    as_json: bool,
    human_extra: Any = None,
) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), indent=2))
    elif human_extra is not None:
        human_extra()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Experiment A: Windows adapter enumeration + bind-to-IP TCP echo",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON result",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    list_p = sub.add_parser("list", help="Enumerate and classify adapters")
    list_p.set_defaults(func=cmd_list)

    serve_p = sub.add_parser("serve", help="TCP echo server bound to a selected IPv4")
    serve_p.add_argument("--ip", help="IPv4 address to bind (manual override)")
    serve_p.add_argument("--adapter-id", help="Adapter identifier to select")
    serve_p.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"TCP port (default {DEFAULT_PORT})",
    )
    serve_p.add_argument(
        "--serve-forever",
        action="store_true",
        help="Accept clients until Ctrl+C (default: handle one client then exit)",
    )
    serve_p.set_defaults(func=cmd_serve)

    conn_p = sub.add_parser("connect", help="TCP echo client")
    conn_p.add_argument("--ip", required=True, help="Remote IPv4 address")
    conn_p.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"TCP port (default {DEFAULT_PORT})",
    )
    conn_p.add_argument(
        "--message",
        default="snowlink-test",
        help="UTF-8 payload to echo (length-limited)",
    )
    conn_p.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Connection timeout in seconds (default 5)",
    )
    conn_p.set_defaults(func=cmd_connect)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
