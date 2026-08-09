"""Live stream statistics panel for Share / View pages."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QCheckBox, QGroupBox, QLabel, QVBoxLayout, QWidget

from snowlink.ui.widgets.collapsible import wire_collapsible_group


class StatsPanel(QGroupBox):
    """Collapsible connection-details panel (collapsed by default).

    When expanded, shows a compact summary. Check **Show all metrics** for
    the full list (loss, drops, CPU, RSS, …).
    """

    def __init__(
        self,
        title: str = "Connection details",
        parent: Any = None,
        *,
        collapsed: bool = True,
    ) -> None:
        super().__init__(title, parent)
        layout = QVBoxLayout(self)
        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        self._show_all = QCheckBox("Show all metrics")
        self._show_all.setChecked(False)
        self._show_all.toggled.connect(self._refresh_label)
        body_layout.addWidget(self._show_all)
        self._label = QLabel("No active session.")
        self._label.setObjectName("statsPanel")
        self._label.setWordWrap(True)
        body_layout.addWidget(self._label)
        layout.addWidget(self._body)
        self._last_state: Any = None
        wire_collapsible_group(self, self._body, checked=not collapsed)
        self.toggled.connect(self._on_toggled)

    def clear(self) -> None:
        self._last_state = None
        self._label.setText("No active session.")

    def update_from_state(self, state: Any) -> None:
        self._last_state = state
        self._refresh_label()

    def _on_toggled(self, checked: bool) -> None:
        if checked:
            self._refresh_label()

    def _refresh_label(self) -> None:
        if not self.isChecked():
            return
        state = self._last_state
        if state is None:
            self._label.setText("No active session.")
            return
        stats = getattr(state, "stats", None)
        if stats is None:
            self._label.setText("No active session.")
            return
        lines = getattr(stats, "format_lines", None)
        if callable(lines):
            self._label.setText("\n".join(lines(compact=not self._show_all.isChecked())))
        else:
            self._label.setText(str(stats))
