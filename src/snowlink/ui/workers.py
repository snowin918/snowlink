"""Background experiment process runner and asyncio session worker (Qt)."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QProcess, Signal
from PySide6.QtGui import QImage

from snowlink.ui.paths import experiment_process_argv


class ExperimentProcessRunner(QObject):
    """Runs ``python experiments/<script>.py …`` and streams output."""

    output = Signal(str)
    finished = Signal(int)
    started = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._on_ready_read)
        self._proc.finished.connect(self._on_finished)

    @property
    def is_running(self) -> bool:
        return self._proc.state() != QProcess.ProcessState.NotRunning

    def start(
        self,
        script: Path,
        argv: Sequence[str],
        *,
        working_directory: Path,
    ) -> None:
        if self.is_running:
            raise RuntimeError("An experiment process is already running")
        if not script.is_file():
            raise FileNotFoundError(f"Experiment script not found: {script}")

        program, args = experiment_process_argv(script, list(argv))
        display = " ".join([program, *args])
        self._proc.setWorkingDirectory(str(working_directory))
        self.started.emit(display)
        self._proc.start(program, args)
        if not self._proc.waitForStarted(5000):
            err = self._proc.errorString()
            self.output.emit(f"Failed to start process: {err}\n")
            self.finished.emit(2)

    def stop(self) -> None:
        if not self.is_running:
            return
        self.output.emit("\n[stopping process...]\n")
        self._proc.terminate()
        if not self._proc.waitForFinished(3000):
            self._proc.kill()
            self._proc.waitForFinished(3000)

    def _on_ready_read(self) -> None:
        raw = self._proc.readAllStandardOutput()
        data = bytes(raw.data()).decode("utf-8", errors="replace")
        if data:
            self.output.emit(data)

    def _on_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        self.finished.emit(int(exit_code))


Factory = Callable[
    [asyncio.Event, Callable[[Any], None], Callable[[Any], None]],
    Awaitable[Any],
]


class AsyncioSessionWorker(QObject):
    """Runs an asyncio coroutine on a dedicated thread; marshals state to Qt."""

    state_changed = Signal(object)
    frame_ready = Signal(object)  # QImage
    finished = Signal(object)  # ScreenSessionState | None
    failed = Signal(str)
    approval_requested = Signal(object)  # PairingRequestInfo

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._approval_future: asyncio.Future[bool] | None = None
        self._running = False
        # Drop frames when the GUI still has a queued paint — prevents an
        # unbounded QueuedConnection backlog of QImages over long sessions.
        self._ui_frame_lock = threading.Lock()
        self._ui_frame_pending = 0

    @property
    def is_running(self) -> bool:
        return self._running

    def mark_frame_consumed(self) -> None:
        """Call from the GUI thread after painting (or dropping) a frame."""
        with self._ui_frame_lock:
            if self._ui_frame_pending > 0:
                self._ui_frame_pending -= 1

    def start(self, factory: Factory) -> None:
        if self._running:
            raise RuntimeError("A session is already running")
        self._running = True
        self._ui_frame_pending = 0
        self._thread = threading.Thread(
            target=self._thread_main,
            args=(factory,),
            name="snowlink-asyncio-session",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        loop = self._loop
        stop_event = self._stop_event
        if loop is None or stop_event is None:
            return

        def _set() -> None:
            stop_event.set()
            fut = self._approval_future
            if fut is not None and not fut.done():
                fut.set_result(False)

        try:
            loop.call_soon_threadsafe(_set)
        except RuntimeError:
            pass

    def respond_approval(self, approved: bool) -> None:
        """Resolve a pending pairing approval from the Qt thread."""
        loop = self._loop
        if loop is None:
            return

        def _resolve() -> None:
            fut = self._approval_future
            if fut is not None and not fut.done():
                fut.set_result(bool(approved))

        try:
            loop.call_soon_threadsafe(_resolve)
        except RuntimeError:
            pass

    async def request_approval(self, info: Any) -> bool:
        """Await UI approval; emits ``approval_requested`` on the Qt side."""
        loop = asyncio.get_running_loop()
        self._approval_future = loop.create_future()
        self.approval_requested.emit(info)
        try:
            return bool(await self._approval_future)
        finally:
            self._approval_future = None

    def _thread_main(self, factory: Factory) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        stop_event = asyncio.Event()
        self._stop_event = stop_event
        final_state: Any | None = None
        try:

            def on_state(state: Any) -> None:
                self.state_changed.emit(state)

            def on_frame(bgr: Any) -> None:
                # Coalesce: if the GUI has not finished the previous paint,
                # keep only the newest frame by skipping this emit.
                with self._ui_frame_lock:
                    if self._ui_frame_pending > 0:
                        return
                    self._ui_frame_pending += 1
                image = _bgr_to_qimage(bgr)
                if image is None:
                    with self._ui_frame_lock:
                        if self._ui_frame_pending > 0:
                            self._ui_frame_pending -= 1
                    return
                self.frame_ready.emit(image)

            final_state = loop.run_until_complete(factory(stop_event, on_state, on_frame))
        except Exception as exc:  # noqa: BLE001 — surface to UI
            self.failed.emit(str(exc))
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            loop.close()
            self._loop = None
            self._stop_event = None
            self._approval_future = None
            self._ui_frame_pending = 0
            self._running = False
            self.finished.emit(final_state)


def _bgr_to_qimage(bgr: Any) -> QImage | None:
    try:
        import numpy as np
    except ImportError:
        return None
    if not isinstance(bgr, np.ndarray) or bgr.ndim != 3 or bgr.shape[2] < 3:
        return None
    height, width = int(bgr.shape[0]), int(bgr.shape[1])
    rgb = bgr[:, :, ::-1].copy()
    bytes_per_line = 3 * width
    image = QImage(rgb.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
    return image.copy()
