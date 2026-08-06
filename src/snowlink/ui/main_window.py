"""Main window with stacked Home / Share / View / Diagnostics pages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from snowlink import __version__
from snowlink.ui.pages.diagnostics import DiagnosticsPage
from snowlink.ui.pages.home import HomePage
from snowlink.ui.pages.share import SharePage
from snowlink.ui.pages.view import ViewPage


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Snowlink {__version__}")
        self.resize(1040, 720)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        nav = QWidget()
        nav.setFixedWidth(200)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(12, 16, 12, 16)
        nav_layout.setSpacing(8)

        brand = QLabel("Snowlink")
        brand.setObjectName("brandTitle")
        brand.setStyleSheet("font-size: 20px; font-weight: 700;")
        nav_layout.addWidget(brand)
        sub = QLabel("LAN share shell")
        sub.setObjectName("brandSubtitle")
        nav_layout.addWidget(sub)
        nav_layout.addSpacing(12)

        self._stack = QStackedWidget()
        self._home = HomePage()
        self._share = SharePage()
        self._view = ViewPage()
        self._diagnostics = DiagnosticsPage()
        self._stack.addWidget(self._home)
        self._stack.addWidget(self._share)
        self._stack.addWidget(self._view)
        self._stack.addWidget(self._diagnostics)

        self._nav_buttons: list[QPushButton] = []
        for index, label in enumerate(("Home", "Share", "View", "Diagnostics")):
            btn = QPushButton(label)
            btn.setObjectName("navButton")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, i=index: self._goto(i))
            nav_layout.addWidget(btn)
            self._nav_buttons.append(btn)
        nav_layout.addStretch(1)

        layout.addWidget(nav)
        layout.addWidget(self._stack, 1)

        self._home.navigate.connect(self._goto_name)
        self.statusBar().showMessage(
            "Phase 0 shell — LAN screen share needs Phase 1 media (not ready yet)."
        )
        self._goto(0)

    def _goto(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_buttons):
            btn.setProperty("active", i == index)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _goto_name(self, name: str) -> None:
        mapping = {"home": 0, "share": 1, "view": 2, "diagnostics": 3}
        self._goto(mapping.get(name.lower(), 0))
