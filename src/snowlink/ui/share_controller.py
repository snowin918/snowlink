"""Headless share-session controller (no Share tab — driven from Home / Settings)."""

from __future__ import annotations

import sys
from typing import Any

from PySide6.QtCore import QObject, Signal

from snowlink.ui.workers import AsyncioSessionWorker


class ShareController(QObject):
    """Runs share sessions using Settings preferences; emits state for Home."""

    approval_requested = Signal(object)
    session_state_changed = Signal(object)
    failed = Signal(str)
    finished = Signal(object)

    def __init__(
        self,
        preferences: Any | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._preferences = preferences
        self._session = AsyncioSessionWorker(self)
        self._session.state_changed.connect(self.session_state_changed.emit)
        self._session.finished.connect(self.finished.emit)
        self._session.failed.connect(self.failed.emit)
        self._session.approval_requested.connect(self.approval_requested.emit)

    @property
    def is_running(self) -> bool:
        return self._session.is_running

    def apply_preferences(self, prefs: Any | None) -> None:
        self._preferences = prefs

    def resolve_bind_ip(self) -> str | None:
        prefs = self._preferences
        preferred = getattr(prefs, "preferred_bind_ip", None) if prefs else None
        if preferred:
            return str(preferred)
        try:
            from snowlink.net.adapter_selection import (
                annotate_adapters,
                select_preferred_endpoint,
            )
            from snowlink.platform_win.adapters import enumerate_adapters, is_windows

            if not is_windows():
                return None
            adapters = annotate_adapters(enumerate_adapters())
            selected = select_preferred_endpoint(adapters)
            if selected is not None:
                return str(selected.ipv4)
        except Exception:
            return None
        return None

    def start_sharing(self) -> tuple[bool, str | None]:
        """Start sharing. Returns ``(ok, error_message)``."""
        if self._session.is_running:
            return False, None
        bind_ip = self.resolve_bind_ip()
        if not bind_ip:
            return (
                False,
                "No network address found. Open Settings and pick a network adapter.",
            )
        prefs = self._preferences
        enable_audio = bool(getattr(prefs, "enable_audio", True)) if prefs else True
        monitor = int(getattr(prefs, "share_monitor", 0) if prefs else 0)
        preset = str(getattr(prefs, "preset", "low") if prefs else "low")
        backend = str(getattr(prefs, "backend", "automatic") if prefs else "automatic")
        media_backend = str(
            getattr(prefs, "media_backend", "native_cpp") if prefs else "native_cpp"
        )
        if getattr(sys, "frozen", False):
            media_backend = "native_cpp"
        target_fps = int(getattr(prefs, "target_fps", 30) if prefs else 30)
        bitrate_bps = int(getattr(prefs, "bitrate_bps", 2_500_000) if prefs else 2_500_000)
        remote_control = bool(getattr(prefs, "remote_control_enabled", True) if prefs else True)
        port = int(getattr(prefs, "signaling_port", 3847) if prefs else 3847)
        audio_device = str(
            getattr(prefs, "audio_capture_device", "default") if prefs else "default"
        )
        worker = self._session

        def factory(stop_event: Any, on_state: Any, _on_frame: Any) -> Any:
            from snowlink.rtc.screen_session import (
                ScreenShareConfiguration,
                run_native_screen_share,
                run_screen_share,
            )

            config = ScreenShareConfiguration.from_preset(
                bind_ip=bind_ip,
                signaling_port=port,
                monitor=monitor,
                backend=backend,  # type: ignore[arg-type]
                preset=preset,
                enable_audio=enable_audio,
                audio_capture_device=audio_device,
                auto_approve=False,
                approval_handler=worker.request_approval,
                target_fps=target_fps,
                bitrate_bps=bitrate_bps,
            )
            if media_backend == "native_cpp":
                return run_native_screen_share(
                    config,
                    stop_event=stop_event,
                    on_state=on_state,
                    remote_control_enabled=remote_control,
                )
            return run_screen_share(config, stop_event=stop_event, on_state=on_state)

        try:
            self._session.start(factory)
            return True, None
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    def stop_sharing(self) -> None:
        self._session.stop()

    def respond_approval(self, approved: bool) -> None:
        self._session.respond_approval(approved)
