"""Secondary windows for an active Share / View session."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from snowlink.ui.widgets.stats_panel import StatsPanel


class NativeVideoSurface(QWidget):
    """Qt layout participant backed by a stable child HWND."""

    surface_changed = Signal(bool)
    input_event = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._legacy_pixmap: QPixmap | None = None

    def setPixmap(self, pixmap: QPixmap) -> None:  # noqa: N802
        """Paint only legacy Python frames; native rendering never calls this."""
        self._legacy_pixmap = pixmap
        self.update()

    def paintEvent(self, event: Any) -> None:  # noqa: N802
        if self._legacy_pixmap is None:
            return super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        scaled = self._legacy_pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        painter.drawPixmap(
            (self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2, scaled
        )

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
        p = event.position()
        self.input_event.emit(
            {
                "kind": 1,
                "x": int(p.x()),
                "y": int(p.y()),
                "width": self.width(),
                "height": self.height(),
            }
        )
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        self.setFocus()
        self._mouse_button(event, True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        self._mouse_button(event, False)
        super().mouseReleaseEvent(event)

    def _mouse_button(self, event: Any, down: bool) -> None:
        buttons = {
            Qt.MouseButton.LeftButton: 1,
            Qt.MouseButton.RightButton: 2,
            Qt.MouseButton.MiddleButton: 3,
        }
        code = buttons.get(event.button())
        if code:
            self.input_event.emit({"kind": 2, "code": code, "down": down})

    def wheelEvent(self, event: Any) -> None:  # noqa: N802
        self.input_event.emit({"kind": 3, "delta": event.angleDelta().y()})
        super().wheelEvent(event)

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802
        if not event.isAutoRepeat():
            self.input_event.emit({"kind": 4, "code": event.nativeVirtualKey() & 255, "down": True})
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: Any) -> None:  # noqa: N802
        if not event.isAutoRepeat():
            self.input_event.emit(
                {"kind": 4, "code": event.nativeVirtualKey() & 255, "down": False}
            )
            super().keyReleaseEvent(event)

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.surface_changed.emit(self.isVisible())

    def showEvent(self, event: Any) -> None:  # noqa: N802
        super().showEvent(event)
        self.surface_changed.emit(True)

    def hideEvent(self, event: Any) -> None:  # noqa: N802
        super().hideEvent(event)
        self.surface_changed.emit(False)


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
        placeholder = self._video
        self._video = NativeVideoSurface()
        self._video.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self._video.setMinimumHeight(240)
        self._video.setStyleSheet("background:#000;")
        layout.replaceWidget(placeholder, self._video)
        placeholder.deleteLater()

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

    @property
    def native_video_handle(self) -> int:
        return int(self._video.winId())

    @property
    def native_video_surface(self) -> NativeVideoSurface:
        return self._video

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
            self.layout().insertWidget(1, self._video, 1)
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
        lay.addWidget(self._video)
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self._last_pixmap is not None:
            screen = win.screen()
            size = screen.availableGeometry().size() if screen is not None else self._video.size()
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
            self.layout().insertWidget(1, self._video, 1)
            self._fullscreen_window.close()
            self._fullscreen_window = None
            self._fullscreen_label = None
        if self._on_disconnect is not None:
            self._on_disconnect()
        super().closeEvent(event)
