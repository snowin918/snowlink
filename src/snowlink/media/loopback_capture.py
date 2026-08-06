"""WASAPI loopback capture via PyAudioWPatch."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import numpy as np

from snowlink.media.audio_errors import AudioError, AudioFailure, failure_for, map_exception
from snowlink.media.audio_format import NativeSampleFormat, bytes_to_float32
from snowlink.media.audio_ring_buffer import AudioRingBuffer
from snowlink.platform_win.audio_endpoints import (
    AudioEndpointInfo,
    pa_format_name,
    require_pyaudio,
)


class LoopbackCapture:
    """Owns a WASAPI loopback input stream writing float32 frames to a ring buffer."""

    def __init__(
        self,
        endpoint: AudioEndpointInfo,
        ring: AudioRingBuffer,
        *,
        pa: Any | None = None,
        frames_per_buffer: int = 960,
        sample_format: int | None = None,
        on_error: Callable[[AudioFailure], None] | None = None,
    ) -> None:
        if not endpoint.is_loopback or not endpoint.can_capture:
            raise AudioError(
                failure_for(
                    "INVALID_CAPTURE_DEVICE",
                    f"Endpoint {endpoint.index} is not a loopback capture device.",
                )
            )
        self.endpoint = endpoint
        self.ring = ring
        self._pyaudio_mod = require_pyaudio()
        self._owns_pa = pa is None
        self._pa = pa if pa is not None else self._pyaudio_mod.PyAudio()
        self._frames_per_buffer = int(frames_per_buffer)
        self._sample_format = (
            sample_format
            if sample_format is not None
            else int(self._pyaudio_mod.paFloat32)
        )
        self._on_error = on_error
        self._stream: Any | None = None
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self.callbacks = 0
        self.captured_samples = 0
        self.read_errors = 0
        self.native_sample_rate = int(endpoint.default_sample_rate) or 48000
        self.native_channels = max(1, int(endpoint.max_input_channels))
        self.native_sample_format: NativeSampleFormat = "float32"
        self.fatal_error: AudioFailure | None = None

    def open(self) -> None:
        channels = self.native_channels
        rate = self.native_sample_rate
        # Prefer float32; fall back to int16 if open fails.
        formats_to_try = [
            (int(self._pyaudio_mod.paFloat32), "float32"),
            (int(self._pyaudio_mod.paInt16), "int16"),
        ]
        if self._sample_format == int(self._pyaudio_mod.paInt16):
            formats_to_try = [
                (int(self._pyaudio_mod.paInt16), "int16"),
                (int(self._pyaudio_mod.paFloat32), "float32"),
            ]

        last_exc: BaseException | None = None
        for fmt, fmt_name in formats_to_try:
            try:
                self._stream = self._pa.open(
                    format=fmt,
                    channels=channels,
                    rate=rate,
                    input=True,
                    input_device_index=self.endpoint.index,
                    frames_per_buffer=self._frames_per_buffer,
                    stream_callback=self._callback,
                )
                self._sample_format = fmt
                self.native_sample_format = fmt_name  # type: ignore[assignment]
                self.native_channels = channels
                self.native_sample_rate = rate
                return
            except Exception as exc:
                last_exc = exc
                self._stream = None
                continue
        raise AudioError(
            failure_for(
                "CAPTURE_OPEN_FAILED",
                f"Failed to open WASAPI loopback on device {self.endpoint.index}.",
                exception=last_exc,
            )
        )

    def start(self) -> None:
        if self._stream is None:
            self.open()
        assert self._stream is not None
        self._stopped.clear()
        try:
            self._stream.start_stream()
        except Exception as exc:
            raise AudioError(
                failure_for(
                    "CAPTURE_OPEN_FAILED",
                    "Failed to start loopback capture stream.",
                    exception=exc,
                )
            ) from exc

    def stop(self) -> None:
        self._stopped.set()
        stream = self._stream
        if stream is None:
            return
        try:
            if stream.is_active():
                stream.stop_stream()
        except Exception:
            pass

    def close(self) -> None:
        self.stop()
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        if self._owns_pa:
            try:
                self._pa.terminate()
            except Exception:
                pass

    def _callback(
        self,
        in_data: bytes | None,
        frame_count: int,
        time_info: dict[str, Any],
        status: int,
    ) -> tuple[bytes | None, int]:
        del time_info
        if self._stopped.is_set():
            return (None, self._pyaudio_mod.paComplete)
        try:
            if status:
                # Non-zero PortAudio callback status — count but continue.
                self.read_errors += 1
            raw = in_data or b""
            frames = bytes_to_float32(
                raw,
                sample_format=self.native_sample_format,
                channels=self.native_channels,
            )
            if frames.shape[0] == 0 and frame_count > 0:
                frames = np.zeros(
                    (frame_count, self.native_channels), dtype=np.float32
                )
            # Channel-match ring buffer if needed (mono/stereo mismatch).
            if frames.shape[1] != self.ring.channels:
                from snowlink.media.audio_format import convert_channels

                frames = convert_channels(
                    frames,
                    source_channels=frames.shape[1],
                    target_channels=self.ring.channels,
                )
            self.ring.write(frames)
            self.callbacks += 1
            self.captured_samples += int(frames.shape[0])
        except Exception as exc:
            self.read_errors += 1
            failure = map_exception(exc)
            if "disconnect" in str(exc).lower() or "invalid" in str(exc).lower():
                failure = failure_for(
                    "DEVICE_DISCONNECTED",
                    "Capture device disconnected or became invalid.",
                    exception=exc,
                )
            self.fatal_error = failure
            if self._on_error is not None:
                self._on_error(failure)
            self._stopped.set()
            return (None, self._pyaudio_mod.paComplete)
        return (None, self._pyaudio_mod.paContinue)


def pa_format_label(pa_mod: Any, fmt: int) -> str:
    return pa_format_name(pa_mod, fmt)


def wait_capture_activity(
    capture: LoopbackCapture,
    *,
    timeout_s: float = 2.0,
) -> bool:
    """Return True if at least one capture callback ran within *timeout_s*."""
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        if capture.callbacks > 0:
            return True
        if capture.fatal_error is not None:
            return False
        time.sleep(0.02)
    return capture.callbacks > 0
