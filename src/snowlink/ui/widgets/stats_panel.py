"""Live stream statistics panel for Share / View pages."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout


class StatsPanel(QGroupBox):
    """Displays :class:`~snowlink.stats.SessionStats` as a compact text block."""

    def __init__(self, title: str = "Stream statistics", parent: Any = None) -> None:
        super().__init__(title, parent)
        layout = QVBoxLayout(self)
        self._label = QLabel("No active session.")
        self._label.setObjectName("statsPanel")
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

    def clear(self) -> None:
        self._label.setText("No active session.")

    def update_from_state(self, state: Any) -> None:
        stats = getattr(state, "stats", None)
        if stats is None:
            self.clear()
            return
        lines = getattr(stats, "format_lines", None)
        if callable(lines):
            self._label.setText("\n".join(lines()))
        else:
            self._label.setText(str(stats))
