"""Structured capture errors for Experiment C (DXcam screen capture)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CaptureFailure:
    """Machine-readable capture failure with safe operator guidance."""

    code: str
    message: str
    likely_cause: str = ""
    suggested_next_step: str = ""
    exception_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_CAUSES: dict[str, str] = {
    "DXCAM_NOT_INSTALLED": (
        "The dxcam package is not installed in the active Python environment."
    ),
    "BACKEND_UNAVAILABLE": (
        "The requested DXcam capture backend is not supported or failed to initialize "
        "on this machine."
    ),
    "INVALID_MONITOR": (
        "The requested monitor index does not match an enumerated display."
    ),
    "CAPTURE_INITIALIZATION_FAILED": (
        "DXcam could not create or start a capture session for the selected monitor."
    ),
    "CAPTURE_FRAME_TIMEOUT": (
        "No usable frames were produced within the expected capture interval."
    ),
    "MONITOR_DISCONNECTED": (
        "The selected monitor became unavailable while capture was running."
    ),
    "SCALING_FAILED": (
        "Frame scaling to the requested output dimensions failed."
    ),
    "PREVIEW_INITIALIZATION_FAILED": (
        "The OpenCV preview window could not be created or displayed."
    ),
    "UNSUPPORTED_CURSOR_CAPTURE": (
        "Cursor capture was requested for a backend that does not support it."
    ),
    "UNEXPECTED_CAPTURE_ERROR": (
        "An unexpected exception occurred in the capture pipeline."
    ),
    "INVALID_CONFIGURATION": (
        "One or more capture configuration values are outside the allowed ranges."
    ),
}

_ACTIONS: dict[str, str] = {
    "DXCAM_NOT_INSTALLED": (
        'Install capture dependencies with: pip install -e ".[capture]"'
    ),
    "BACKEND_UNAVAILABLE": (
        "Re-run `list` to see available backends; try `dxgi`, or install "
        "`dxcam[winrt]` for WinRT."
    ),
    "INVALID_MONITOR": (
        "Run `list` and pass a valid --monitor index from that output."
    ),
    "CAPTURE_INITIALIZATION_FAILED": (
        "Confirm the monitor is connected, try the other backend, and ensure no "
        "other exclusive capture client is holding Desktop Duplication."
    ),
    "CAPTURE_FRAME_TIMEOUT": (
        "Retry with a lower FPS / resolution, or switch backends (dxgi vs winrt)."
    ),
    "MONITOR_DISCONNECTED": (
        "Reconnect the display and re-run `list` before capturing again."
    ),
    "SCALING_FAILED": (
        "Use smaller --width/--height values, or omit scaling by matching native size."
    ),
    "PREVIEW_INITIALIZATION_FAILED": (
        "Install opencv-python (GUI build), ensure a desktop session is active, "
        "and retry; use `benchmark --no-preview` for headless runs."
    ),
    "UNSUPPORTED_CURSOR_CAPTURE": (
        "Omit --show-cursor, or use the winrt backend where cursor capture is supported."
    ),
    "UNEXPECTED_CAPTURE_ERROR": (
        "Re-run with --json, capture the error code, and retry after a clean process exit."
    ),
    "INVALID_CONFIGURATION": (
        "Adjust --fps, --width, --height, --duration, --monitor, or --backend to valid values."
    ),
}


def failure_for(
    code: str,
    message: str,
    *,
    exception: BaseException | None = None,
    likely_cause: str | None = None,
    suggested_next_step: str | None = None,
) -> CaptureFailure:
    """Build a :class:`CaptureFailure` with standard cause/action text."""
    return CaptureFailure(
        code=code,
        message=message,
        likely_cause=likely_cause if likely_cause is not None else _CAUSES.get(code, ""),
        suggested_next_step=(
            suggested_next_step
            if suggested_next_step is not None
            else _ACTIONS.get(code, _ACTIONS["UNEXPECTED_CAPTURE_ERROR"])
        ),
        exception_type=type(exception).__name__ if exception is not None else None,
    )


def map_exception(exc: BaseException) -> CaptureFailure:
    """Map a generic exception onto a structured capture failure."""
    if isinstance(exc, CaptureError):
        return exc.failure
    text = str(exc).lower()
    name = type(exc).__name__
    if isinstance(exc, ModuleNotFoundError) and "dxcam" in str(exc).lower():
        return failure_for(
            "DXCAM_NOT_INSTALLED",
            "DXcam is not installed.",
            exception=exc,
        )
    if "backend" in text or "unsupported backend" in text:
        return failure_for(
            "BACKEND_UNAVAILABLE",
            f"Capture backend unavailable ({name}).",
            exception=exc,
        )
    if "monitor" in text or "output" in text and "index" in text:
        return failure_for(
            "INVALID_MONITOR",
            f"Monitor selection failed ({name}).",
            exception=exc,
        )
    return failure_for(
        "UNEXPECTED_CAPTURE_ERROR",
        f"Unexpected capture error ({name}).",
        exception=exc,
    )


def format_failure_human(failure: CaptureFailure) -> str:
    """Render a multi-line operator-facing explanation."""
    lines = [f"{failure.code}: {failure.message}"]
    if failure.likely_cause:
        lines.extend(["", f"Likely cause: {failure.likely_cause}"])
    if failure.suggested_next_step:
        lines.extend(["", f"Suggested next step: {failure.suggested_next_step}"])
    if failure.exception_type:
        lines.append(f"Exception type: {failure.exception_type}")
    return "\n".join(lines)


class CaptureError(Exception):
    """Exception carrying a structured :class:`CaptureFailure`."""

    def __init__(self, failure: CaptureFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure
