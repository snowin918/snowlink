"""Home page — primary navigation into Share / View / Diagnostics."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class HomePage(QWidget):
    navigate = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 40, 32, 32)
        layout.setSpacing(16)

        title = QLabel("Snowlink")
        title.setObjectName("brandTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "Private LAN screen and system-audio share for Windows 11.\n"
            "Phase 1: screen-only Share / View over LAN (pairing and audio later)."
        )
        subtitle.setObjectName("brandSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        warn = QLabel(
            "Screen Share/View works without pairing codes yet — use only on a "
            "trusted private LAN. Diagnostics still runs Phase 0 Experiments A–F."
        )
        warn.setObjectName("warningBanner")
        warn.setWordWrap(True)
        layout.addWidget(warn)

        layout.addSpacing(8)
        for key, label, primary in (
            ("share", "Share This Computer", True),
            ("view", "View Another Computer", False),
            ("diagnostics", "Diagnostics / Phase 0 Tests", False),
        ):
            btn = QPushButton(label)
            if primary:
                btn.setObjectName("primaryButton")
            btn.setMinimumHeight(44)
            btn.clicked.connect(lambda _c=False, k=key: self.navigate.emit(k))
            layout.addWidget(btn)

        settings = QPushButton("Settings (coming later)")
        settings.setEnabled(False)
        layout.addWidget(settings)
        layout.addStretch(1)
