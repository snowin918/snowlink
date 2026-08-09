"""Home page — this PC identity, share status, and past session history."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from snowlink.session_history import (
    SessionHistoryEntry,
    format_history_label,
    load_history,
)
from snowlink.ui.paths import logo_png
from snowlink.ui.widgets.collapsible import wrap_in_scroll

_PHASE_STATUS: dict[str, str] = {
    "idle": "Not sharing.",
    "starting": "Starting…",
    "waiting_for_viewer": "Waiting for a connection…",
    "awaiting_approval": "Incoming connection — Accept or Deny in the popup.",
    "negotiating": "Connecting…",
    "sharing": "Connected — sharing.",
    "reconnecting": "Reconnecting…",
    "stopping": "Stopping…",
    "failed": "Share failed.",
}


class HomePage(QWidget):
    navigate = Signal(str)
    start_sharing = Signal()
    stop_sharing = Signal()
    reconnect_requested = Signal(object)  # SessionHistoryEntry

    def __init__(self) -> None:
        super().__init__()
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        logo = QLabel()
        png = logo_png()
        if png is not None:
            pix = QPixmap(str(png))
            if not pix.isNull():
                logo.setPixmap(
                    pix.scaled(
                        28,
                        28,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        header.addWidget(logo)
        title = QLabel("Snowlink")
        title.setObjectName("brandTitle")
        header.addWidget(title)
        header.addStretch(1)
        layout.addLayout(header)

        tip = QLabel(
            "This PC’s address and code are shown below. Give them to the other "
            "computer (View). Sharing options are in Settings."
        )
        tip.setObjectName("warningBanner")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        identity = QGroupBox("This computer")
        form = QFormLayout(identity)
        self._this_pc_ip = QLabel("—")
        self._this_pc_ip.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        form.addRow("Address", self._this_pc_ip)
        self._port_label = QLabel("3847")
        self._port_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        form.addRow("Port", self._port_label)
        self._code_label = QLabel("—")
        self._code_label.setObjectName("pairingCode")
        self._code_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        form.addRow("Pairing code", self._code_label)
        self._status = QLabel("Not sharing.")
        self._status.setObjectName("hint")
        self._status.setWordWrap(True)
        form.addRow("Status", self._status)
        self._sharing_indicator = QLabel("")
        self._sharing_indicator.setObjectName("sharingIndicator")
        self._sharing_indicator.setVisible(False)
        form.addRow("", self._sharing_indicator)
        layout.addWidget(identity)

        row = QHBoxLayout()
        self._share_btn = QPushButton("Start Sharing")
        self._share_btn.setObjectName("primaryButton")
        self._share_btn.clicked.connect(self.start_sharing.emit)
        row.addWidget(self._share_btn)
        self._stop_btn = QPushButton("Stop Sharing")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self.stop_sharing.emit)
        row.addWidget(self._stop_btn)
        view_btn = QPushButton("View Another Computer")
        view_btn.clicked.connect(lambda: self.navigate.emit("view"))
        row.addWidget(view_btn)
        row.addStretch(1)
        layout.addLayout(row)

        hist_box = QGroupBox("Recent connections")
        hist_layout = QVBoxLayout(hist_box)
        self._history = QListWidget()
        self._history.setMinimumHeight(160)
        self._history.itemActivated.connect(self._on_history_activated)
        self._history.itemDoubleClicked.connect(self._on_history_activated)
        hist_layout.addWidget(self._history)
        hist_hint = QLabel("Double-click a Viewed entry to reconnect.")
        hist_hint.setObjectName("hint")
        hist_layout.addWidget(hist_hint)
        clear_btn = QPushButton("Clear history")
        clear_btn.clicked.connect(self._clear_history)
        hist_layout.addWidget(clear_btn)
        layout.addWidget(hist_box, stretch=1)

        wrap_in_scroll(self, content)
        self.reload_history()

    def set_identity(
        self,
        *,
        bind_ip: str | None = None,
        port: int | None = None,
        pairing_code: str | None = None,
    ) -> None:
        if bind_ip is not None:
            self._this_pc_ip.setText(bind_ip or "—")
        if port is not None:
            self._port_label.setText(str(port))
        if pairing_code is not None:
            self._code_label.setText(str(pairing_code) if pairing_code else "—")

    def set_sharing_running(self, running: bool) -> None:
        self._share_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)

    def apply_session_state(self, state: Any | None) -> None:
        if state is None:
            self._status.setText("Not sharing.")
            self._sharing_indicator.setVisible(False)
            self.set_sharing_running(False)
            return
        code = getattr(state, "pairing_code", None)
        if code:
            self._code_label.setText(str(code))
        bind = getattr(state, "bind_ip", None)
        if bind:
            self._this_pc_ip.setText(str(bind))
        port = getattr(state, "port", None)
        if port:
            self._port_label.setText(str(port))
        phase = str(getattr(state, "phase", "") or "")
        detail = str(getattr(state, "detail", "") or "").strip()
        mapped = _PHASE_STATUS.get(phase)
        if phase == "awaiting_approval" and detail:
            self._status.setText(detail)
        elif mapped:
            self._status.setText(mapped)
        elif detail:
            self._status.setText(detail)
        else:
            self._status.setText(phase or "Not sharing.")
        sharing = phase in {
            "starting",
            "waiting_for_viewer",
            "awaiting_approval",
            "negotiating",
            "sharing",
            "reconnecting",
        }
        self.set_sharing_running(sharing or bool(getattr(state, "sharing_active", False)))
        self._sharing_indicator.setVisible(
            phase in {"waiting_for_viewer", "awaiting_approval", "negotiating", "sharing"}
        )
        if self._sharing_indicator.isVisible():
            self._sharing_indicator.setText(
                "● SHARING — this computer’s screen may be visible"
            )

    def reload_history(self) -> None:
        self._history.clear()
        for entry in load_history():
            item = QListWidgetItem(format_history_label(entry))
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self._history.addItem(item)
        if self._history.count() == 0:
            empty = QListWidgetItem("No past connections yet.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._history.addItem(empty)

    def _on_history_activated(self, item: QListWidgetItem) -> None:
        entry = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(entry, SessionHistoryEntry) and entry.role == "view":
            self.reconnect_requested.emit(entry)

    def _clear_history(self) -> None:
        from snowlink.session_history import save_history

        save_history([])
        self.reload_history()
