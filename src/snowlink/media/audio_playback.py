"""Local WASAPI playback for Experiment D."""

from __future__ import annotations

import threading
from typing import Any

import numpy as np
from numpy.typing import NDArray

from snowlink.media.audio_errors import AudioError, AudioFailure, failure_for, map_exception
from snowlink.media.audio_format import AudioFrame, float32_to_s16
from snowlink.platform_win.audio_endpoints import AudioEndpointInfo, require_pyaudio


class AudioPlayer:
    """Blocking write-based playback stream at a fixed target format."""

    def __init__(
        self,
        endpoint: AudioEndpointInfo,
        *,
        sample_rate: int,
        channels: int,
        pa: Any | None = None,
        frames_per_buffer: int = 960,
    ) -> None:
        if not endpoint.can_playback:
            raise AudioError(
                failure_for(
                    "INVALID_PLAYBACK_DEVICE",
                    f"Endpoint {endpoint.index} cannot be used for playback.",
                )
            )
        self.endpoint = endpoint
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self._pyaudio_mod = require_pyaudio()
        self._owns_pa = pa is None
        self._pa = pa if pa is not None else self._pyaudio_mod.PyAudio()
        self._frames_per_buffer = int(frames_per_buffer)
        self._stream: Any | None = None
        self._lock = threading.Lock()
        self.writes = 0
        self.played_samples = 0
        self.write_errors = 0
        self.fatal_error: AudioFailure | None = None

    def open(self) -> None:
        try:
            self._stream = self._pa.open(
                format=self._pyaudio_mod.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                output=True,
                output_device_index=self.endpoint.index,
                frames_per_buffer=self._frames_per_buffer,
            )
        except Exception as exc:
            raise AudioError(
                failure_for(
                    "PLAYBACK_OPEN_FAILED",
                    f"Failed to open playback on device {self.endpoint.index}.",
                    exception=exc,
                )
            ) from exc

    def start(self) -> None:
        if self._stream is None:
            self.open()
        assert self._stream is not None
        try:
            if not self._stream.is_active():
                self._stream.start_stream()
        except Exception as exc:
            raise AudioError(
                failure_for(
                    "PLAYBACK_OPEN_FAILED",
                    "Failed to start playback stream.",
                    exception=exc,
                )
            ) from exc

    def write_frame(self, frame: AudioFrame) -> None:
        """Write one AudioFrame (s16 or float32) to the playback device."""
        with self._lock:
            if self._stream is None:
                raise AudioError(
                    failure_for(
                        "PLAYBACK_WRITE_FAILED",
                        "Playback stream is not open.",
                    )
                )
            try:
                pcm = _frame_to_s16_bytes(frame, channels=self.channels)
                self._stream.write(pcm)
                self.writes += 1
                self.played_samples += int(frame.sample_count)
            except Exception as exc:
                self.write_errors += 1
                failure = map_exception(exc)
                text = str(exc).lower()
                if "disconnect" in text or "invalid" in text or "unanticipated" in text:
                    failure = failure_for(
                        "DEVICE_DISCONNECTED",
                        "Playback device disconnected or became invalid.",
                        exception=exc,
                    )
                else:
                    failure = failure_for(
                        "PLAYBACK_WRITE_FAILED",
                        "Writing PCM to the playback stream failed.",
                        exception=exc,
                    )
                self.fatal_error = failure
                raise AudioError(failure) from exc

    def write_s16(self, samples: NDArray[np.int16]) -> None:
        frame = AudioFrame(
            pts=0,
            samples=samples,
            sample_rate=self.sample_rate,
            channels=self.channels,
            sample_format="s16",
            is_silence=False,
            is_underrun_padding=False,
        )
        self.write_frame(frame)

    def stop(self) -> None:
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


def _frame_to_s16_bytes(frame: AudioFrame, *, channels: int) -> bytes:
    samples = frame.samples
    if samples.ndim == 1:
        samples = samples.reshape(-1, 1)
    if samples.shape[1] != channels:
        # Simple trim/pad
        out = np.zeros((samples.shape[0], channels), dtype=samples.dtype)
        n = min(channels, samples.shape[1])
        out[:, :n] = samples[:, :n]
        samples = out
    if frame.sample_format == "s16" or samples.dtype == np.int16:
        return np.ascontiguousarray(samples, dtype=np.int16).tobytes()
    return float32_to_s16(samples).tobytes()
