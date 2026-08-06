"""Optional smoke imports for the PySide6 UI package."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


def test_import_ui_modules() -> None:
    from snowlink.ui import argv_builders, paths
    from snowlink.ui.app import run_app
    from snowlink.ui.main_window import MainWindow
    from snowlink.ui.pages import diagnostics, home, share, view

    assert callable(run_app)
    assert MainWindow is not None
    assert home.HomePage is not None
    assert share.SharePage is not None
    assert view.ViewPage is not None
    assert diagnostics.DiagnosticsPage is not None
    assert paths.repo_root().name  # non-empty
    assert "a" in argv_builders.SCRIPT_NAMES
