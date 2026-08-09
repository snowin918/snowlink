"""Collapsible Advanced / details helpers for compact windows."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGroupBox, QScrollArea, QVBoxLayout, QWidget


def wire_collapsible_group(group: QGroupBox, body: QWidget, *, checked: bool = False) -> None:
    """Checkable group that truly collapses (no reserved height when closed)."""
    group.setCheckable(True)
    group.setChecked(checked)

    def _apply(on: bool) -> None:
        body.setVisible(on)
        body.setMaximumHeight(16777215 if on else 0)
        group.updateGeometry()
        parent = group.parentWidget()
        if parent is not None:
            parent.updateGeometry()

    group.toggled.connect(_apply)
    _apply(checked)


def wrap_in_scroll(page: QWidget, content: QWidget) -> None:
    """Install a scroll area as the page root so Advanced sections can expand."""
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    scroll = QScrollArea(page)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setWidget(content)
    outer.addWidget(scroll)
