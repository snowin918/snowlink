"""Secondary windows for an active Share / View session."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from snowlink.ui.widgets.stats_panel import StatsPanel


class ShareSessionWindow(QWidget):
    """Status window while an approved viewer is connected."""

    def __init__(
        self,
        *,
        on_stop: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._on_stop = on_stop
        self.setWindowTitle("Snowlink — Sharing")
        self.setMinimumSize(420, 280)
        self.resize(480, 320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        self._indicator = QLabel("● Connected — this computer’s screen may be visible")
        self._indicator.setObjectName("sharingIndicator")
        self._indicator.setWordWrap(True)
        layout.addWidget(self._indicator)

        self._status = QLabel("Sharing…")
        self._status.setObjectName("hint")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._stats = StatsPanel(collapsed=False)
        layout.addWidget(self._stats)

        row = QHBoxLayout()
        stop = QPushButton("Stop Sharing")
        stop.setObjectName("primaryButton")
        stop.clicked.connect(self._stop)
        row.addWidget(stop)
        row.addStretch(1)
        layout.addLayout(row)

    def update_state(self, state: Any) -> None:
        detail = str(getattr(state, "detail", "") or "").strip()
        phase = str(getattr(state, "phase", "") or "")
        self._status.setText(detail or phase or "Sharing…")
        self._stats.update_from_state(state)

    def _stop(self) -> None:
        if self._on_stop is not None:
            self._on_stop()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        # Closing the window stops the share session (AnyDesk-like).
        if self._on_stop is not None:
            self._on_stop()
        super().closeEvent(event)


class ViewSessionWindow(QWidget):
    """Video window for an active View session."""

    def __init__(
        self,
        *,
        on_disconnect: Callable[[], None] | None = None,
        on_mute_changed: Callable[[bool], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._on_disconnect = on_disconnect
        self._on_mute_changed = on_mute_changed
        self._last_pixmap: QPixmap | None = None
        self.setWindowTitle("Snowlink — Connected")
        self.setMinimumSize(640, 400)
        self.resize(960, 600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        row = QHBoxLayout()
        self._mute = QCheckBox("Mute")
        self._mute.toggled.connect(self._mute_toggled)
        row.addWidget(self._mute)
        self._fullscreen_btn = QPushButton("Fullscreen")
        self._fullscreen_btn.clicked.connect(self._toggle_fullscreen)
        row.addWidget(self._fullscreen_btn)
        disconnect = QPushButton("Disconnect")
        disconnect.clicked.connect(self._disconnect)
        row.addWidget(disconnect)
        row.addStretch(1)
        layout.addLayout(row)

        self._video = QLabel("Waiting for video…")
        self._video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._video.setMinimumHeight(240)
        self._video.setObjectName("videoPlaceholder")
        self._video.setStyleSheet(
            "background:#ECEFF1; color:#546E7A; border-radius:12px; border:1px solid #BBDEFB;"
        )
        layout.addWidget(self._video, stretch=1)

        self._status = QLabel("Connecting…")
        self._status.setObjectName("hint")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._stats = StatsPanel(collapsed=True)
        layout.addWidget(self._stats)

        self._fullscreen_window: QWidget | None = None
        self._fullscreen_label: QLabel | None = None

    def set_muted(self, muted: bool) -> None:
        self._mute.blockSignals(True)
        self._mute.setChecked(bool(muted))
        self._mute.blockSignals(False)

    def update_state(self, state: Any) -> None:
        detail = str(getattr(state, "detail", "") or "").strip()
        phase = str(getattr(state, "phase", "") or "")
        self._status.setText(detail or phase or "Connected.")
        self._stats.update_from_state(state)

    def show_frame(self, image: QImage) -> None:
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image)
        self._last_pixmap = pixmap
        scaled = pixmap.scaled(
            self._video.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self._video.setPixmap(scaled)
        if self._fullscreen_label is not None and self._fullscreen_window is not None:
            self._fullscreen_label.setPixmap(
                pixmap.scaled(
                    self._fullscreen_window.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            )

    def _mute_toggled(self, checked: bool) -> None:
        if self._on_mute_changed is not None:
            self._on_mute_changed(bool(checked))

    def _disconnect(self) -> None:
        if self._on_disconnect is not None:
            self._on_disconnect()

    def _toggle_fullscreen(self) -> None:
        if self._fullscreen_window is not None and self._fullscreen_window.isVisible():
            self._fullscreen_window.close()
            self._fullscreen_window = None
            self._fullscreen_label = None
            self._fullscreen_btn.setText("Fullscreen")
            return
        win = QWidget()
        win.setWindowTitle("Snowlink — Fullscreen")
        win.setStyleSheet("background:#000;")
        lay = QVBoxLayout(win)
        lay.setContentsMargins(0, 0, 0, 0)
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(label)
        if self._last_pixmap is not None:
            screen = win.screen()
            size = (
                screen.availableGeometry().size()
                if screen is not None
                else self._video.size()
            )
            label.setPixmap(
                self._last_pixmap.scaled(
                    size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        win.showFullScreen()
        self._fullscreen_window = win
        self._fullscreen_label = label
        self._fullscreen_btn.setText("Exit fullscreen")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._fullscreen_window is not None:
            self._fullscreen_window.close()
            self._fullscreen_window = None
            self._fullscreen_label = None
        if self._on_disconnect is not None:
            self._on_disconnect()
        super().closeEvent(event)
