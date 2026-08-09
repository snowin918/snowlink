"""DXcam local screen-capture pipeline for Experiment C.

Pipeline::

    DXcam grab (worker thread)
    -> LatestFrameSlot (depth 1; overwrites counted)
    -> optional letterbox scale
    -> optional OpenCV preview
    -> metrics collector

Cursor support: DXGI does not expose cursor compositing in DXcam. WinRT supports
cursor capture via the ``DXCAM_WINRT_CURSOR_CAPTURE`` environment variable; that
compatibility knob is isolated in :func:`_apply_winrt_cursor_env`.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from snowlink.media.capture_errors import (
    CaptureError,
    CaptureFailure,
    failure_for,
    map_exception,
)
from snowlink.media.capture_metrics import (
    ProcessResourceSampler,
    TimingAccumulator,
    elapsed_s,
)
from snowlink.media.capture_models import (
    CaptureConfiguration,
    CaptureStats,
    ExperimentCResult,
    RenderStats,
    utc_now_iso,
)
from snowlink.media.frame_slot import LatestFrameSlot, SlotItem
from snowlink.media.scaling import scale_frame_letterbox
from snowlink.platform_win.monitors import (
    MonitorInfo,
    get_monitor,
    is_windows,
    probe_backend_availability,
)

# Isolated WinRT compatibility knobs (DXcam documents env-based control).
_WINRT_CURSOR_ENV = "DXCAM_WINRT_CURSOR_CAPTURE"
# Yellow capture border is a Windows WinRT indicator; prefer off for private LAN share.
_WINRT_BORDER_ENV = "DXCAM_WINRT_BORDER_REQUIRED"


@dataclass(slots=True)
class _WorkerStats:
    frames_captured: int = 0
    null_frames: int = 0
    duplicate_frames: int = 0
    unexpected_error: CaptureFailure | None = None


def require_dxcam() -> Any:
    try:
        import dxcam

    except ModuleNotFoundError as exc:
        raise CaptureError(
            failure_for(
                "DXCAM_NOT_INSTALLED",
                "DXcam is not installed in this environment.",
                exception=exc,
            )
        ) from exc
    return dxcam


def ensure_backend_available(backend: str) -> None:
    availability = probe_backend_availability()
    if not availability.get(backend, False):
        raise CaptureError(
            failure_for(
                "BACKEND_UNAVAILABLE",
                f"Capture backend {backend!r} is not available on this machine.",
            )
        )


def _apply_winrt_cursor_env(*, enabled: bool) -> str | None:
    """Set WinRT cursor env var; return previous value (or None if unset)."""
    previous = os.environ.get(_WINRT_CURSOR_ENV)
    os.environ[_WINRT_CURSOR_ENV] = "1" if enabled else "0"
    return previous


def _restore_env(name: str, previous: str | None) -> None:
    if previous is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = previous


def resolve_cursor_policy(
    config: CaptureConfiguration,
) -> tuple[bool, CaptureFailure | None]:
    """Return (cursor_enabled, optional soft-failure if unsupported)."""
    if not config.cursor_requested:
        return False, None
    if config.backend == "winrt":
        return True, None
    return False, failure_for(
        "UNSUPPORTED_CURSOR_CAPTURE",
        "Cursor capture is not supported by the DXGI backend in DXcam; "
        "use --backend winrt for cursor compositing.",
    )


def create_camera(
    monitor: MonitorInfo,
    config: CaptureConfiguration,
    *,
    dxcam_module: Any | None = None,
) -> Any:
    """Create a DXcam camera for the mapped monitor output."""
    dxcam = dxcam_module or require_dxcam()
    ensure_backend_available(config.backend)
    if monitor.dxcam is None:
        raise CaptureError(
            failure_for(
                "INVALID_MONITOR",
                f"Monitor {monitor.index} has no mapped DXcam device/output index.",
            )
        )

    cursor_enabled, cursor_failure = resolve_cursor_policy(config)
    if cursor_failure is not None and config.cursor_requested:
        # Hard-fail when the operator explicitly asked for an unsupported feature.
        raise CaptureError(cursor_failure)

    previous_cursor_env: str | None = None
    previous_border_env: str | None = None
    if config.backend == "winrt":
        previous_cursor_env = _apply_winrt_cursor_env(enabled=cursor_enabled)
        # Ask DXcam/WinRT to omit the yellow capture border when the OS allows it.
        previous_border_env = os.environ.get(_WINRT_BORDER_ENV)
        os.environ[_WINRT_BORDER_ENV] = "0"

    try:
        camera = dxcam.create(
            device_idx=monitor.dxcam.device_idx,
            output_idx=monitor.dxcam.output_idx,
            output_color="BGR",
            max_buffer_len=2,
            backend=config.backend,
            processor_backend="cv2",
        )
    except CaptureError:
        raise
    except ModuleNotFoundError as exc:
        missing = str(exc)
        if config.backend == "winrt" or "winrt" in missing.lower():
            raise CaptureError(
                failure_for(
                    "BACKEND_UNAVAILABLE",
                    "WinRT capture dependencies are missing from this build. "
                    "Use the DXGI backend (Settings → Capture backend), or rebuild "
                    "with dxcam[winrt] fully bundled.",
                    exception=exc,
                )
            ) from exc
        raise CaptureError(
            failure_for(
                "CAPTURE_INITIALIZATION_FAILED",
                "Failed to create DXcam capture session.",
                exception=exc,
            )
        ) from exc
    except Exception as exc:
        raise CaptureError(
            failure_for(
                "CAPTURE_INITIALIZATION_FAILED",
                "Failed to create DXcam capture session.",
                exception=exc,
            )
        ) from exc
    finally:
        if config.backend == "winrt":
            _restore_env(_WINRT_CURSOR_ENV, previous_cursor_env)
            _restore_env(_WINRT_BORDER_ENV, previous_border_env)

    return camera


def create_camera_with_fallback(
    monitor: MonitorInfo,
    config: CaptureConfiguration,
    *,
    dxcam_module: Any | None = None,
) -> tuple[Any, str]:
    """Create a camera; if WinRT deps are missing, fall back to DXGI.

    Returns ``(camera, effective_backend)``.
    """
    try:
        return create_camera(monitor, config, dxcam_module=dxcam_module), config.backend
    except CaptureError as exc:
        if config.backend != "winrt":
            raise
        cause = exc.__cause__
        message = str(getattr(getattr(exc, "failure", None), "message", "") or exc)
        missing_winrt = isinstance(cause, ModuleNotFoundError) or (
            "winrt" in message.lower() and "missing" in message.lower()
        )
        if not missing_winrt:
            raise
        # Portable builds often omit winrt-* wheels even when Settings ask for winrt.
        from dataclasses import replace

        dxgi_config = replace(config, backend="dxgi", cursor_requested=False)
        camera = create_camera(monitor, dxgi_config, dxcam_module=dxcam_module)
        return camera, "dxgi"


def release_camera(camera: Any) -> None:
    if camera is None:
        return
    try:
        if getattr(camera, "is_capturing", False):
            camera.stop()
    except Exception:
        pass
    try:
        camera.release()
    except Exception:
        pass


class ScreenCaptureSession:
    """Owns the capture worker, frame slot, and shutdown sequencing."""

    def __init__(
        self,
        config: CaptureConfiguration,
        *,
        monitor: MonitorInfo | None = None,
        camera: Any | None = None,
        grabber: Callable[[], Any] | None = None,
    ) -> None:
        if not is_windows() and camera is None and grabber is None:
            raise CaptureError(
                failure_for(
                    "CAPTURE_INITIALIZATION_FAILED",
                    "Screen capture requires Windows 11 (or a injected test grabber).",
                )
            )
        self.config = config
        self.monitor = monitor
        self._camera = camera
        self._grabber = grabber
        self._owns_camera = camera is None and grabber is None
        self._effective_backend = str(config.backend)
        self.slot: LatestFrameSlot[Any] = LatestFrameSlot()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._worker_stats = _WorkerStats()
        self._last_frame_id: int | None = None
        self._native_width = 0
        self._native_height = 0
        self.timings = TimingAccumulator()
        self.resources = ProcessResourceSampler()
        self._started_ns = 0
        self._last_capture_ns: int | None = None

    def start(self) -> None:
        if self._grabber is None:
            if self.monitor is None:
                self.monitor = get_monitor(self.config.monitor)
            if self._camera is None:
                camera, effective_backend = create_camera_with_fallback(
                    self.monitor, self.config
                )
                self._camera = camera
                if effective_backend != self.config.backend:
                    # Keep session config truthful for stats / UI without rewriting
                    # the frozen dataclass in place (replace via object.__setattr__
                    # is unnecessary — store on the session instead).
                    self._effective_backend = effective_backend
            self._native_width = int(getattr(self._camera, "width", 0) or 0)
            self._native_height = int(getattr(self._camera, "height", 0) or 0)

            def _grab() -> Any:
                # new_frame_only=False is required for continuous capture when the
                # desktop is idle; otherwise grab() returns None until damage occurs.
                assert self._camera is not None
                return self._camera.grab(new_frame_only=False)

            self._grabber = _grab

        self._stop.clear()
        self._started_ns = time.perf_counter_ns()
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="snowlink-dxcam-capture",
            daemon=True,
        )
        self._thread.start()

    def _capture_loop(self) -> None:
        target_interval_s = 1.0 / float(self.config.requested_fps)
        assert self._grabber is not None
        while not self._stop.is_set():
            loop_start = time.perf_counter_ns()
            try:
                frame = self._grabber()
            except Exception as exc:
                self._worker_stats.unexpected_error = map_exception(exc)
                break

            captured_at = time.perf_counter_ns()
            if self._last_capture_ns is not None:
                self.timings.add_capture_interval_ns(
                    captured_at - self._last_capture_ns
                )
            self._last_capture_ns = captured_at

            if frame is None:
                self._worker_stats.null_frames += 1
            else:
                # Detect obvious duplicate object identity (rare); hash of id only.
                frame_id = id(frame)
                if self._last_frame_id is not None and frame_id == self._last_frame_id:
                    self._worker_stats.duplicate_frames += 1
                self._last_frame_id = frame_id
                try:
                    # Own a copy so DXcam can reuse its buffer on the next grab.
                    owned = frame.copy()
                except Exception:
                    owned = frame
                if self._native_width == 0 or self._native_height == 0:
                    try:
                        self._native_height = int(owned.shape[0])
                        self._native_width = int(owned.shape[1])
                    except Exception:
                        pass
                self._worker_stats.frames_captured += 1
                self.slot.publish(owned, captured_at_ns=captured_at)

            # Pace without blocking indefinitely on the consumer.
            elapsed = (time.perf_counter_ns() - loop_start) / 1_000_000_000.0
            sleep_for = target_interval_s - elapsed
            if sleep_for > 0:
                # Short waits so stop responds quickly.
                self._stop.wait(timeout=min(sleep_for, 0.05))

    def request_stop(self) -> None:
        self._stop.set()
        self.slot.close()

    def shutdown(self, *, join_timeout_s: float = 5.0) -> None:
        """Ordered shutdown: stop worker → release DXcam → join → close slot."""
        self.request_stop()
        if self._owns_camera:
            release_camera(self._camera)
            self._camera = None
        if self._thread is not None:
            self._thread.join(timeout=join_timeout_s)
            self._thread = None
        self.slot.close()

    @property
    def stop_requested(self) -> bool:
        return self._stop.is_set()

    def build_partial_result(
        self,
        *,
        frames_rendered: int,
        success: bool,
        errors: list[CaptureFailure],
        details: dict[str, Any] | None = None,
    ) -> ExperimentCResult:
        duration = elapsed_s(self._started_ns) if self._started_ns else 0.0
        capture_fps = (
            self._worker_stats.frames_captured / duration if duration > 0 else 0.0
        )
        render_fps = frames_rendered / duration if duration > 0 else 0.0
        return ExperimentCResult(
            started_at_utc=utc_now_iso(),  # overwritten by caller when known
            completed_at_utc=utc_now_iso(),
            success=success,
            configuration=self.config,
            capture=CaptureStats(
                native_width=self._native_width,
                native_height=self._native_height,
                frames_captured=self._worker_stats.frames_captured,
                actual_fps=round(capture_fps, 4),
                null_frames=self._worker_stats.null_frames,
                duplicate_frames=self._worker_stats.duplicate_frames,
                overwritten_frames=self.slot.overwritten_count,
            ),
            render=RenderStats(
                frames_rendered=frames_rendered,
                actual_fps=round(render_fps, 4),
            ),
            timing_ms=self.timings.to_timing_stats(),
            resources=self.resources.finalize(),
            errors=[e.to_dict() for e in errors],
            details={
                "monitor_index": self.config.monitor,
                "experiment_duration_s": round(duration, 3),
                "logical_monitor": (
                    {
                        "name": self.monitor.name,
                        "left": self.monitor.left,
                        "top": self.monitor.top,
                        "width": self.monitor.width,
                        "height": self.monitor.height,
                        "dxcam_device_idx": (
                            self.monitor.dxcam.device_idx if self.monitor.dxcam else None
                        ),
                        "dxcam_output_idx": (
                            self.monitor.dxcam.output_idx if self.monitor.dxcam else None
                        ),
                    }
                    if self.monitor is not None
                    else None
                ),
                **(details or {}),
            },
        )


def _overlay_stats(frame: Any, lines: list[str], *, cv2: Any) -> Any:
    out = frame
    y = 24
    for line in lines:
        cv2.putText(
            out,
            line,
            (12, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 80),
            1,
            cv2.LINE_AA,
        )
        y += 22
    return out


def _import_cv2() -> Any:
    try:
        import cv2
    except ModuleNotFoundError as exc:
        raise CaptureError(
            failure_for(
                "PREVIEW_INITIALIZATION_FAILED",
                "OpenCV (cv2) is not installed.",
                exception=exc,
            )
        ) from exc
    return cv2


def run_capture_session(
    config: CaptureConfiguration,
    *,
    started_at: str | None = None,
    honor_duration: bool = True,
) -> tuple[int, ExperimentCResult]:
    """Run preview and/or timed benchmark for *config*.

    Shutdown order:
    1. signal capture worker to stop
    2. stop/release DXcam
    3. join capture thread
    4. close preview resources
    5. finalize metrics (caller writes JSON)

    When *honor_duration* is False (interactive preview), the loop runs until
    Escape, window close, or Ctrl+C (still bounded by ``duration_s`` as a safety
    cap when *honor_duration* is True).
    """
    started = started_at or utc_now_iso()
    errors: list[CaptureFailure] = []
    session: ScreenCaptureSession | None = None
    frames_rendered = 0
    exit_code = 0
    cv2: Any | None = None
    window_name = "Snowlink Experiment C"
    preview_opened = False
    result: ExperimentCResult | None = None

    try:
        if config.show_preview:
            cv2 = _import_cv2()

        session = ScreenCaptureSession(config)
        session.start()
        # Warm up: wait briefly for first frame.
        if not session.slot.wait_for_frame(timeout=5.0):
            if session._worker_stats.unexpected_error is not None:
                raise CaptureError(session._worker_stats.unexpected_error)
            raise CaptureError(
                failure_for(
                    "CAPTURE_FRAME_TIMEOUT",
                    "No frames were captured within 5 seconds of start.",
                )
            )

        deadline_ns: int | None = None
        if honor_duration:
            deadline_ns = time.perf_counter_ns() + int(
                config.duration_s * 1_000_000_000
            )

        last_resource_sample = 0.0

        if config.show_preview and cv2 is not None:
            try:
                cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
                cv2.resizeWindow(
                    window_name,
                    config.requested_width,
                    config.requested_height,
                )
                preview_opened = True
            except Exception as exc:
                raise CaptureError(
                    failure_for(
                        "PREVIEW_INITIALIZATION_FAILED",
                        "Failed to open the OpenCV preview window.",
                        exception=exc,
                    )
                ) from exc

        while not session.stop_requested:
            if deadline_ns is not None and time.perf_counter_ns() >= deadline_ns:
                break
            if session._worker_stats.unexpected_error is not None:
                raise CaptureError(session._worker_stats.unexpected_error)

            item = session.slot.take(clear=True)
            now = time.perf_counter_ns()
            if now / 1_000_000_000.0 - last_resource_sample >= 0.5:
                session.resources.sample()
                last_resource_sample = now / 1_000_000_000.0

            if item is None:
                if config.show_preview and cv2 is not None:
                    key = cv2.waitKey(1) & 0xFF
                    if key == 27:  # Escape
                        break
                    try:
                        if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                            break
                    except Exception:
                        break
                else:
                    time.sleep(0.001)
                continue

            frames_rendered += 1
            frame_age_ns = now - item.captured_at_ns
            session.timings.add_frame_age_ns(frame_age_ns)

            scale_start = time.perf_counter_ns()
            try:
                display = scale_frame_letterbox(
                    item.payload,
                    config.requested_width,
                    config.requested_height,
                    cv2_module=cv2,
                )
            except CaptureError as exc:
                errors.append(exc.failure)
                exit_code = 2
                break
            scale_ns = time.perf_counter_ns() - scale_start
            session.timings.add_scale_ns(scale_ns)
            session.timings.add_capture_to_preview_ns(
                time.perf_counter_ns() - item.captured_at_ns
            )

            if config.show_preview and cv2 is not None:
                duration = elapsed_s(session._started_ns)
                cap_fps = (
                    session._worker_stats.frames_captured / duration
                    if duration > 0
                    else 0.0
                )
                ren_fps = frames_rendered / duration if duration > 0 else 0.0
                overlay = [
                    f"backend={config.backend} monitor={config.monitor}",
                    f"capture_fps={cap_fps:.1f} preview_fps={ren_fps:.1f}",
                    f"dropped={session.slot.overwritten_count} "
                    f"null={session._worker_stats.null_frames}",
                    f"frame_age_ms={frame_age_ns / 1_000_000.0:.1f} "
                    f"(local approx)",
                    "Esc / close window to stop",
                ]
                shown = _overlay_stats(display, overlay, cv2=cv2)
                cv2.imshow(window_name, shown)
                key = cv2.waitKey(1) & 0xFF
                if key == 27:
                    break
                try:
                    if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                        break
                except Exception:
                    break

        if session._worker_stats.unexpected_error is not None and exit_code == 0:
            errors.append(session._worker_stats.unexpected_error)
            exit_code = 2

        success = exit_code == 0 and session._worker_stats.frames_captured > 0
        result = session.build_partial_result(
            frames_rendered=frames_rendered,
            success=success,
            errors=errors,
        )
        if not success and exit_code == 0:
            exit_code = 2

    except CaptureError as exc:
        errors.append(exc.failure)
        exit_code = 2
    except KeyboardInterrupt:
        errors.append(
            failure_for(
                "UNEXPECTED_CAPTURE_ERROR",
                "Interrupted by Ctrl+C; shutting down capture cleanly.",
                likely_cause="Operator pressed Ctrl+C.",
                suggested_next_step="Re-run the command when ready.",
            )
        )
        exit_code = 130
    except Exception as exc:
        errors.append(map_exception(exc))
        exit_code = 2
    finally:
        if session is not None:
            session.shutdown()
        if preview_opened and cv2 is not None:
            try:
                cv2.destroyWindow(window_name)
            except Exception:
                pass
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass

    if result is None:
        if session is not None:
            result = session.build_partial_result(
                frames_rendered=frames_rendered,
                success=False,
                errors=errors,
            )
        else:
            result = ExperimentCResult(
                started_at_utc=started,
                completed_at_utc=utc_now_iso(),
                success=False,
                configuration=config,
                errors=[e.to_dict() for e in errors],
            )
    result.started_at_utc = started
    result.completed_at_utc = utc_now_iso()
    return exit_code, result


# Re-export SlotItem for type checkers / tests that import from this module.
__all__ = [
    "ScreenCaptureSession",
    "SlotItem",
    "create_camera",
    "ensure_backend_available",
    "release_camera",
    "require_dxcam",
    "resolve_cursor_policy",
    "run_capture_session",
]
