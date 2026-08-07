"""Entry point for ``python -m snowlink`` / the ``snowlink`` console script."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Launch GUI by default, or Phase 1 screen CLI with ``share`` / ``view``."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in {"share", "view"}:
        from snowlink.cli_screen import main as screen_main

        return int(screen_main(args))

    try:
        from snowlink.ui.app import run_app
    except ImportError as exc:
        print(
            "Snowlink GUI requires PySide6.\n"
            "Install with:\n"
            '  pip install -e ".[ui]"\n'
            "For local capture preview and Phase 0 diagnostics also install "
            "capture/audio/webrtc extras as needed, e.g.:\n"
            '  pip install -e ".[dev,ui,capture,audio,webrtc]"\n'
            "\nPhase 3 screen CLI (no GUI):\n"
            "  python -m snowlink share --bind-ip <LAN_IP> --auto-approve\n"
            "  python -m snowlink view --remote-ip <LAN_IP> --pairing-code <CODE>\n"
            f"\nImport error: {exc}",
            file=sys.stderr,
        )
        return 2
    return int(run_app())


if __name__ == "__main__":
    raise SystemExit(main())
