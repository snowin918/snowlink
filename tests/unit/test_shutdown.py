"""Unit tests for shutdown coordinator."""

from __future__ import annotations

from snowlink.shutdown import ShutdownCoordinator


def test_shutdown_runs_hooks_lifo() -> None:
    order: list[str] = []
    coord = ShutdownCoordinator()
    coord.register("a", lambda: order.append("a"))
    coord.register("b", lambda: order.append("b"))
    coord.shutdown(flush_logging=False)
    assert order == ["b", "a"]
    assert coord.completed is True


def test_shutdown_swallows_hook_errors() -> None:
    coord = ShutdownCoordinator()

    def boom() -> None:
        raise RuntimeError("nope")

    coord.register("boom", boom)
    coord.shutdown(flush_logging=False)
    assert coord.completed is True
