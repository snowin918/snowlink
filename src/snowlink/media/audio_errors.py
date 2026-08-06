"""Structured audio errors for Experiment D (WASAPI loopback)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AudioFailure:
    """Machine-readable audio failure with safe operator guidance."""

    code: str
    message: str
    likely_cause: str = ""
    suggested_next_step: str = ""
    exception_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_CAUSES: dict[str, str] = {
    "PYAUDIO_WPATCH_NOT_INSTALLED": (
        "The PyAudioWPatch package is not installed in the active Python environment."
    ),
    "WASAPI_NOT_AVAILABLE": (
        "WASAPI is not available on this system (Windows audio host API missing)."
    ),
    "NO_LOOPBACK_DEVICE": (
        "No WASAPI loopback capture endpoint was found for the selected output device."
    ),
    "INVALID_CAPTURE_DEVICE": (
        "The requested capture device index or selector is not a usable loopback endpoint."
    ),
    "INVALID_PLAYBACK_DEVICE": (
        "The requested playback device index or selector is not a usable output endpoint."
    ),
    "UNSUPPORTED_AUDIO_FORMAT": (
        "The native or target audio format is not supported by the conversion pipeline."
    ),
    "CAPTURE_OPEN_FAILED": (
        "Opening the WASAPI loopback capture stream failed."
    ),
    "PLAYBACK_OPEN_FAILED": (
        "Opening the local playback stream failed."
    ),
    "CAPTURE_READ_FAILED": (
        "Reading PCM from the loopback capture stream failed."
    ),
    "PLAYBACK_WRITE_FAILED": (
        "Writing PCM to the playback stream failed."
    ),
    "RESAMPLE_FAILED": (
        "Resampling or format conversion to the target audio format failed."
    ),
    "DEVICE_DISCONNECTED": (
        "The selected audio endpoint was removed or changed while the pipeline was running."
    ),
    "BUFFER_UNDERRUN": (
        "The audio ring buffer did not have enough samples for a playback interval."
    ),
    "BUFFER_OVERRUN": (
        "The audio ring buffer overflowed and dropped oldest samples to bound latency."
    ),
    "AUDIO_PIPELINE_TIMEOUT": (
        "The audio pipeline did not produce expected frames within the allotted time."
    ),
    "UNEXPECTED_AUDIO_ERROR": (
        "An unexpected exception occurred in the audio pipeline."
    ),
    "INVALID_CONFIGURATION": (
        "One or more audio configuration values are outside the allowed ranges."
    ),
}

_ACTIONS: dict[str, str] = {
    "PYAUDIO_WPATCH_NOT_INSTALLED": (
        'Install audio dependencies with: pip install -e ".[audio]"'
    ),
    "WASAPI_NOT_AVAILABLE": (
        "Confirm you are on Windows 11 with a working audio stack, then re-run `list`."
    ),
    "NO_LOOPBACK_DEVICE": (
        "Re-run `list`, pick a WASAPI loopback endpoint (not a microphone), and pass "
        "its index or `default`."
    ),
    "INVALID_CAPTURE_DEVICE": (
        "Run `list` and select a loopback capture endpoint marked usable for capture."
    ),
    "INVALID_PLAYBACK_DEVICE": (
        "Run `list` and select a physical output device marked usable for playback."
    ),
    "UNSUPPORTED_AUDIO_FORMAT": (
        "Try a different endpoint, or install PyAV (`av`) for resampling support."
    ),
    "CAPTURE_OPEN_FAILED": (
        "Close other exclusive audio clients, re-run `list`, and retry with a valid "
        "loopback index."
    ),
    "PLAYBACK_OPEN_FAILED": (
        "Confirm the playback device is connected and not exclusive-locked, then retry."
    ),
    "CAPTURE_READ_FAILED": (
        "Check whether the capture endpoint still exists; re-run `list` after device changes."
    ),
    "PLAYBACK_WRITE_FAILED": (
        "Check the playback device; underruns may also appear if the buffer is too small."
    ),
    "RESAMPLE_FAILED": (
        "Install/upgrade PyAV (`pip install -e \".[audio]\"`) and retry; verify native rate."
    ),
    "DEVICE_DISCONNECTED": (
        "Re-run `list` and select a currently available loopback / playback endpoint."
    ),
    "BUFFER_UNDERRUN": (
        "Increase --buffer-ms slightly, or investigate capture starvation; a few startup "
        "underruns are normal."
    ),
    "BUFFER_OVERRUN": (
        "Playback may be too slow; check CPU load and reduce other load if needed."
    ),
    "AUDIO_PIPELINE_TIMEOUT": (
        "Retry the run; if it persists, re-run `list` and verify capture produces audio."
    ),
    "UNEXPECTED_AUDIO_ERROR": (
        "Re-run with --json, capture the error code, and retry after a clean process exit."
    ),
    "INVALID_CONFIGURATION": (
        "Adjust --sample-rate, --channels, --frame-ms, --buffer-ms, --gain, or --duration."
    ),
}


def failure_for(
    code: str,
    message: str,
    *,
    exception: BaseException | None = None,
    likely_cause: str | None = None,
    suggested_next_step: str | None = None,
) -> AudioFailure:
    """Build an :class:`AudioFailure` with standard cause/action text."""
    return AudioFailure(
        code=code,
        message=message,
        likely_cause=likely_cause if likely_cause is not None else _CAUSES.get(code, ""),
        suggested_next_step=(
            suggested_next_step
            if suggested_next_step is not None
            else _ACTIONS.get(code, _ACTIONS["UNEXPECTED_AUDIO_ERROR"])
        ),
        exception_type=type(exception).__name__ if exception is not None else None,
    )


def map_exception(exc: BaseException) -> AudioFailure:
    """Map a generic exception onto a structured audio failure."""
    if isinstance(exc, AudioError):
        return exc.failure
    text = str(exc).lower()
    name = type(exc).__name__
    module_hint = str(exc).lower()
    if isinstance(exc, ModuleNotFoundError):
        if "pyaudiowpatch" in module_hint or "pyaudio" in module_hint:
            return failure_for(
                "PYAUDIO_WPATCH_NOT_INSTALLED",
                "PyAudioWPatch is not installed.",
                exception=exc,
            )
        if module_hint.endswith("'av'") or " no module named 'av'" in f" {module_hint}":
            return failure_for(
                "RESAMPLE_FAILED",
                "PyAV (av) is not installed; required for resampling.",
                exception=exc,
            )
    if "wasapi" in text and ("not available" in text or "not found" in text):
        return failure_for(
            "WASAPI_NOT_AVAILABLE",
            f"WASAPI unavailable ({name}).",
            exception=exc,
        )
    if "disconnect" in text or "device unavailable" in text or "invalid device" in text:
        return failure_for(
            "DEVICE_DISCONNECTED",
            f"Audio device disconnected or invalid ({name}).",
            exception=exc,
        )
    return failure_for(
        "UNEXPECTED_AUDIO_ERROR",
        f"Unexpected audio error ({name}).",
        exception=exc,
    )


def format_failure_human(failure: AudioFailure) -> str:
    """Render a multi-line operator-facing explanation."""
    lines = [f"{failure.code}: {failure.message}"]
    if failure.likely_cause:
        lines.extend(["", f"Likely cause: {failure.likely_cause}"])
    if failure.suggested_next_step:
        lines.extend(["", f"Suggested next step: {failure.suggested_next_step}"])
    if failure.exception_type:
        lines.append(f"Exception type: {failure.exception_type}")
    return "\n".join(lines)


class AudioError(Exception):
    """Exception carrying a structured :class:`AudioFailure`."""

    def __init__(self, failure: AudioFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure
