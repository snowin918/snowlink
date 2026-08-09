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


def test_app_shutdown_helpers_register_and_run() -> None:
    from snowlink import shutdown as shutdown_mod

    # Isolate process-wide coordinator for this test.
    original = shutdown_mod._APP_COORDINATOR
    shutdown_mod._APP_COORDINATOR = ShutdownCoordinator()
    try:
        called: list[str] = []
        shutdown_mod.register_app_shutdown("x", lambda: called.append("x"))
        shutdown_mod.register_app_shutdown("y", lambda: called.append("y"))
        shutdown_mod.run_app_shutdown()
        assert called == ["y", "x"]
        assert shutdown_mod.get_app_shutdown_coordinator().completed is True
    finally:
        shutdown_mod._APP_COORDINATOR = original
