"""CLI for Phase 1 screen-only share / view (HTTP signaling + DXcam)."""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from collections.abc import Sequence
from typing import Any


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Snowlink Phase 1 screen share / view (no pairing yet)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    share = sub.add_parser("share", help="Share this computer's screen")
    share.add_argument("--bind-ip", default=None, help="LAN IPv4 to bind (default: auto)")
    share.add_argument("--port", type=int, default=3847)
    share.add_argument("--monitor", type=int, default=0)
    share.add_argument("--backend", choices=("dxgi", "winrt"), default="dxgi")
    share.add_argument(
        "--preset",
        choices=("low", "balanced", "high"),
        default="low",
        help="Quality preset (default low — Balanced may miss 30 FPS on software path)",
    )
    share.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Seconds to share (0 = until Ctrl+C)",
    )

    view = sub.add_parser("view", help="View a remote screen share")
    view.add_argument("--remote-ip", required=True)
    view.add_argument("--port", type=int, default=3847)
    view.add_argument("--source-ip", default=None, help="Optional local bind for signaling")
    view.add_argument("--no-preview", action="store_true")
    view.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Seconds to view (0 = until Ctrl+C / window close)",
    )
    return parser


async def _run_share(args: argparse.Namespace) -> int:
    from snowlink.rtc.screen_session import (
        ScreenShareConfiguration,
        preferred_lan_ipv4,
        run_screen_share,
    )

    bind_ip = args.bind_ip or preferred_lan_ipv4()
    if not bind_ip:
        print("Could not auto-select a LAN IPv4; pass --bind-ip.", file=sys.stderr)
        return 2

    config = ScreenShareConfiguration.from_preset(
        bind_ip=bind_ip,
        signaling_port=args.port,
        monitor=args.monitor,
        backend=args.backend,
        preset=args.preset,
    )
    stop = asyncio.Event()

    def _handle_sig(*_args: Any) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_sig)
        except NotImplementedError:
            signal.signal(sig, lambda *_a: stop.set())

    async def _duration_watch() -> None:
        if args.duration and args.duration > 0:
            await asyncio.sleep(args.duration)
            stop.set()

    watcher = asyncio.create_task(_duration_watch())
    try:
        state = await run_screen_share(config, stop_event=stop)
    finally:
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass

    return 0 if state.phase in {"stopped", "sharing"} or state.error is None else 1


async def _run_view(args: argparse.Namespace) -> int:
    from snowlink.rtc.screen_session import ScreenViewConfiguration, run_screen_view

    config = ScreenViewConfiguration(
        remote_ip=args.remote_ip,
        signaling_port=args.port,
        requested_source_ip=args.source_ip,
        preview=not args.no_preview,
    )
    stop = asyncio.Event()

    def _handle_sig(*_args: Any) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_sig)
        except NotImplementedError:
            signal.signal(sig, lambda *_a: stop.set())

    async def _duration_watch() -> None:
        if args.duration and args.duration > 0:
            await asyncio.sleep(args.duration)
            stop.set()

    watcher = asyncio.create_task(_duration_watch())
    try:
        state = await run_screen_view(config, stop_event=stop)
    finally:
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass

    return 0 if state.error is None else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "share":
        return asyncio.run(_run_share(args))
    if args.command == "view":
        return asyncio.run(_run_view(args))
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
