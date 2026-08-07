"""Ordered application / session teardown."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

TeardownHook = Callable[[], None]


class ShutdownCoordinator:
    """Run teardown hooks in registration order (LIFO for nested resources).

    Typical order for a share session: stop capture → close peer → stop
    signaling server → flush logs.
    """

    def __init__(self) -> None:
        self._hooks: list[tuple[str, TeardownHook]] = []
        self._done = False

    def register(self, name: str, hook: TeardownHook) -> None:
        self._hooks.append((name, hook))

    def clear(self) -> None:
        self._hooks.clear()
        self._done = False

    @property
    def completed(self) -> bool:
        return self._done

    def shutdown(self, *, flush_logging: bool = True) -> None:
        """Execute hooks newest-first; never raise to callers."""
        errors: list[str] = []
        while self._hooks:
            name, hook = self._hooks.pop()
            try:
                hook()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Shutdown hook %s failed", name)
                errors.append(f"{name}: {exc}")
        if flush_logging:
            _flush_logging()
        self._done = True
        if errors:
            logger.warning("Shutdown completed with %d hook error(s)", len(errors))


def _flush_logging() -> None:
    root = logging.getLogger()
    for handler in root.handlers:
        try:
            handler.flush()
        except Exception:
            pass


# Process-wide coordinator for app exit.
_APP_COORDINATOR = ShutdownCoordinator()


def get_app_shutdown_coordinator() -> ShutdownCoordinator:
    return _APP_COORDINATOR


def register_app_shutdown(name: str, hook: TeardownHook) -> None:
    _APP_COORDINATOR.register(name, hook)


def run_app_shutdown() -> None:
    _APP_COORDINATOR.shutdown(flush_logging=True)


async def close_peer_connection(pc: Any, *, timeout_s: float = 5.0) -> None:
    """Best-effort async close for an aiortc peer connection."""
    import asyncio

    if pc is None:
        return
    try:
        await asyncio.wait_for(pc.close(), timeout=timeout_s)
    except Exception:
        logger.debug("Peer connection close ignored", exc_info=True)
