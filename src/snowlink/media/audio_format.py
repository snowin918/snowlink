"""PCM format helpers, frame sizing, PTS, and resampling for Experiment D.

Canonical output format (documented for later WebRTC reuse)
----------------------------------------------------------
- sample rate: 48_000 Hz
- sample format: ``s16`` (default) or ``fltp``
- channel layout: stereo when possible (mono upmixed by duplication)
- frame duration: 20 ms → 960 samples per channel at 48 kHz

Audio PTS is sample-driven: starts at 0 and advances by the actual output
sample count of each emitted frame. Silence frames and underrun padding still
advance PTS. Wall-clock time is never used as the PTS source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from snowlink.media.audio_errors import AudioError, failure_for
from snowlink.media.audio_models import (
    DEFAULT_FRAME_MS,
    TARGET_CHANNELS,
    TARGET_SAMPLE_RATE,
    OutputSampleFormat,
)

NativeSampleFormat = Literal["float32", "int16", "int32", "int8", "uint8", "unknown"]


def samples_per_frame(sample_rate: int, frame_duration_ms: int) -> int:
    """Return per-channel samples for one frame at *sample_rate*."""
    if sample_rate < 1 or frame_duration_ms < 1:
        raise ValueError("sample_rate and frame_duration_ms must be >= 1")
    return int(sample_rate * frame_duration_ms // 1000)


def frame_duration_ms_for_samples(sample_rate: int, samples: int) -> float:
    if sample_rate < 1:
        raise ValueError("sample_rate must be >= 1")
    return (samples * 1000.0) / float(sample_rate)


@dataclass(slots=True)
class AudioPtsClock:
    """Sample-driven presentation timestamp clock."""

    sample_rate: int = TARGET_SAMPLE_RATE
    pts: int = 0

    def peek(self) -> int:
        return self.pts

    def advance(self, sample_count: int) -> int:
        """Advance by *sample_count* output samples; return PTS before advance."""
        if sample_count < 0:
            raise ValueError("sample_count must be >= 0")
        current = self.pts
        self.pts += sample_count
        return current

    def reset(self) -> None:
        self.pts = 0


@dataclass(frozen=True, slots=True)
class AudioFrame:
    """One complete output audio frame with sample-driven PTS."""

    pts: int
    samples: NDArray[Any]  # shape (n, channels); dtype int16 or float32
    sample_rate: int
    channels: int
    sample_format: OutputSampleFormat
    is_silence: bool
    is_underrun_padding: bool

    @property
    def sample_count(self) -> int:
        return int(self.samples.shape[0])


def convert_channels(
    frames: NDArray[np.floating[Any]],
    *,
    source_channels: int,
    target_channels: int,
) -> NDArray[np.float32]:
    """Convert interleaved float PCM between mono/stereo/(N) channel counts."""
    data = np.asarray(frames, dtype=np.float32)
    if data.ndim == 1:
        data = data.reshape(-1, 1)
        source_channels = 1
    if data.shape[1] != source_channels:
        raise ValueError(
            f"expected {source_channels} channels, got shape {data.shape}"
        )
    if source_channels == target_channels:
        return data
    if target_channels == 1:
        return np.mean(data, axis=1, keepdims=True).astype(np.float32, copy=False)
    if source_channels == 1 and target_channels >= 2:
        mono = data[:, 0:1]
        return np.repeat(mono, target_channels, axis=1)
    if source_channels > target_channels:
        return data[:, :target_channels].copy()
    # Pad extra channels with silence.
    out = np.zeros((data.shape[0], target_channels), dtype=np.float32)
    out[:, :source_channels] = data
    return out


def bytes_to_float32(
    raw: bytes,
    *,
    sample_format: NativeSampleFormat,
    channels: int,
) -> NDArray[np.float32]:
    """Decode interleaved PCM bytes to float32 in [-1, 1]."""
    if not raw:
        return np.zeros((0, channels), dtype=np.float32)
    if sample_format == "float32":
        arr = np.frombuffer(raw, dtype=np.float32)
    elif sample_format == "int16":
        arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_format == "int32":
        arr = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sample_format == "int8":
        arr = np.frombuffer(raw, dtype=np.int8).astype(np.float32) / 128.0
    elif sample_format == "uint8":
        arr = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise AudioError(
            failure_for(
                "UNSUPPORTED_AUDIO_FORMAT",
                f"Cannot decode native sample format {sample_format!r}.",
            )
        )
    if channels < 1:
        raise ValueError("channels must be >= 1")
    usable = (arr.size // channels) * channels
    if usable == 0:
        return np.zeros((0, channels), dtype=np.float32)
    return arr[:usable].reshape(-1, channels)


def float32_to_s16(frames: NDArray[np.floating[Any]]) -> NDArray[np.int16]:
    clipped = np.clip(np.asarray(frames, dtype=np.float32), -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16)


def apply_gain(
    frames: NDArray[np.floating[Any]],
    gain: float,
    *,
    muted: bool = False,
) -> NDArray[np.float32]:
    data = np.asarray(frames, dtype=np.float32)
    if muted or gain <= 0.0:
        return np.zeros_like(data)
    if gain == 1.0:
        return data
    return np.clip(data * float(gain), -1.0, 1.0)


def is_silent_frame(
    frames: NDArray[Any],
    *,
    threshold: float = 1e-4,
) -> bool:
    """Return True when frame energy is below *threshold* (valid silence)."""
    arr = np.asarray(frames, dtype=np.float32)
    if arr.size == 0:
        return True
    return float(np.max(np.abs(arr))) < threshold


def rms_level(frames: NDArray[Any]) -> float:
    arr = np.asarray(frames, dtype=np.float32)
    if arr.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(arr))))


def peak_level(frames: NDArray[Any]) -> float:
    arr = np.asarray(frames, dtype=np.float32)
    if arr.size == 0:
        return 0.0
    return float(np.max(np.abs(arr)))


def silence_frame(
    n_samples: int,
    *,
    channels: int,
    sample_format: OutputSampleFormat = "s16",
    pts: int = 0,
    sample_rate: int = TARGET_SAMPLE_RATE,
    underrun_padding: bool = False,
) -> AudioFrame:
    if sample_format == "s16":
        samples: NDArray[Any] = np.zeros((n_samples, channels), dtype=np.int16)
    else:
        samples = np.zeros((n_samples, channels), dtype=np.float32)
    return AudioFrame(
        pts=pts,
        samples=samples,
        sample_rate=sample_rate,
        channels=channels,
        sample_format=sample_format,
        is_silence=True,
        is_underrun_padding=underrun_padding,
    )


def _linear_resample(
    frames: NDArray[np.float32],
    *,
    source_rate: int,
    target_rate: int,
) -> NDArray[np.float32]:
    if source_rate == target_rate or frames.shape[0] == 0:
        return frames
    duration = frames.shape[0] / float(source_rate)
    target_n = max(1, int(round(duration * target_rate)))
    src_x = np.linspace(0.0, 1.0, frames.shape[0], endpoint=False)
    dst_x = np.linspace(0.0, 1.0, target_n, endpoint=False)
    out = np.empty((target_n, frames.shape[1]), dtype=np.float32)
    for ch in range(frames.shape[1]):
        out[:, ch] = np.interp(dst_x, src_x, frames[:, ch]).astype(np.float32)
    return out


class AudioFormatConverter:
    """Accumulate partial PCM chunks and emit fixed-duration output frames.

    Uses PyAV ``AudioResampler`` when available and rates/layouts differ;
    falls back to linear resampling for synthetic tests without PyAV.
    """

    def __init__(
        self,
        *,
        source_rate: int,
        source_channels: int,
        target_rate: int = TARGET_SAMPLE_RATE,
        target_channels: int = TARGET_CHANNELS,
        frame_duration_ms: int = DEFAULT_FRAME_MS,
        output_sample_format: OutputSampleFormat = "s16",
        prefer_pyav: bool = True,
    ) -> None:
        self.source_rate = int(source_rate)
        self.source_channels = int(source_channels)
        self.target_rate = int(target_rate)
        self.target_channels = int(target_channels)
        self.frame_duration_ms = int(frame_duration_ms)
        self.output_sample_format = output_sample_format
        self.frame_samples = samples_per_frame(self.target_rate, self.frame_duration_ms)
        self.pts_clock = AudioPtsClock(sample_rate=self.target_rate)
        self._pending = np.zeros((0, self.target_channels), dtype=np.float32)
        self.input_samples = 0
        self.output_samples = 0
        self._resampler: Any | None = None
        self._use_pyav = False
        if prefer_pyav and (
            self.source_rate != self.target_rate
            or self.source_channels != self.target_channels
        ):
            self._try_init_pyav()

    def _try_init_pyav(self) -> None:
        try:
            import av
            from av.audio.resampler import AudioResampler
        except Exception:
            self._use_pyav = False
            self._resampler = None
            return
        layout = "stereo" if self.target_channels >= 2 else "mono"
        fmt = "s16" if self.output_sample_format == "s16" else "fltp"
        try:
            self._resampler = AudioResampler(
                format=fmt,
                layout=layout,
                rate=self.target_rate,
            )
            self._av = av
            self._use_pyav = True
        except Exception as exc:
            raise AudioError(
                failure_for(
                    "RESAMPLE_FAILED",
                    "Failed to initialize PyAV AudioResampler.",
                    exception=exc,
                )
            ) from exc

    def push(self, frames: NDArray[np.floating[Any]]) -> list[AudioFrame]:
        """Accept interleaved float32 source PCM; return zero or more full frames."""
        data = np.asarray(frames, dtype=np.float32)
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        if data.shape[0] == 0:
            return []
        self.input_samples += int(data.shape[0])

        if self._use_pyav and self._resampler is not None:
            converted = self._resample_pyav(data)
        else:
            ch = convert_channels(
                data,
                source_channels=self.source_channels,
                target_channels=self.target_channels,
            )
            converted = _linear_resample(
                ch,
                source_rate=self.source_rate,
                target_rate=self.target_rate,
            )

        if converted.shape[0] == 0:
            return []
        self._pending = (
            np.concatenate([self._pending, converted], axis=0)
            if self._pending.shape[0]
            else converted
        )
        return self._emit_complete_frames()

    def flush(self) -> list[AudioFrame]:
        """Emit any remaining pending samples as a final (possibly short) frame."""
        if self._pending.shape[0] == 0:
            return []
        # Pad remainder to a full frame so PTS stays aligned for callers that
        # expect fixed-size frames; mark as silence if padded content is quiet.
        need = self.frame_samples - self._pending.shape[0]
        if need > 0:
            pad = np.zeros((need, self.target_channels), dtype=np.float32)
            chunk = np.concatenate([self._pending, pad], axis=0)
        else:
            chunk = self._pending[: self.frame_samples]
            self._pending = self._pending[self.frame_samples :]
            frames = self._pack_frame(chunk, underrun=False)
            rest = self.flush() if self._pending.shape[0] else []
            return [frames, *rest]
        self._pending = np.zeros((0, self.target_channels), dtype=np.float32)
        return [self._pack_frame(chunk, underrun=False)]

    def make_silence_frame(self, *, underrun_padding: bool = False) -> AudioFrame:
        pts = self.pts_clock.advance(self.frame_samples)
        self.output_samples += self.frame_samples
        return silence_frame(
            self.frame_samples,
            channels=self.target_channels,
            sample_format=self.output_sample_format,
            pts=pts,
            sample_rate=self.target_rate,
            underrun_padding=underrun_padding,
        )

    def _emit_complete_frames(self) -> list[AudioFrame]:
        out: list[AudioFrame] = []
        while self._pending.shape[0] >= self.frame_samples:
            chunk = self._pending[: self.frame_samples]
            self._pending = self._pending[self.frame_samples :]
            out.append(self._pack_frame(chunk, underrun=False))
        return out

    def _pack_frame(
        self,
        chunk: NDArray[np.float32],
        *,
        underrun: bool,
    ) -> AudioFrame:
        pts = self.pts_clock.advance(chunk.shape[0])
        self.output_samples += int(chunk.shape[0])
        silent = is_silent_frame(chunk)
        if self.output_sample_format == "s16":
            samples: NDArray[Any] = float32_to_s16(chunk)
        else:
            samples = chunk.astype(np.float32, copy=True)
        return AudioFrame(
            pts=pts,
            samples=samples,
            sample_rate=self.target_rate,
            channels=self.target_channels,
            sample_format=self.output_sample_format,
            is_silence=silent,
            is_underrun_padding=underrun,
        )

    def _resample_pyav(self, frames: NDArray[np.float32]) -> NDArray[np.float32]:
        assert self._resampler is not None
        av = self._av
        # Feed float planar via interleaved → reshape to planar for AudioFrame.
        layout = "stereo" if self.source_channels >= 2 else "mono"
        # Use s16 intermediate for broad resampler compatibility.
        s16 = float32_to_s16(
            convert_channels(
                frames,
                source_channels=self.source_channels,
                target_channels=min(self.source_channels, 2),
            )
        )
        src_ch = s16.shape[1]
        layout = "stereo" if src_ch >= 2 else "mono"
        try:
            frame = av.AudioFrame(
                format="s16",
                layout=layout,
                samples=s16.shape[0],
            )
            frame.sample_rate = self.source_rate
            # Interleaved s16 packed into planes expected by PyAV.
            interleaved = np.ascontiguousarray(s16)
            frame.planes[0].update(interleaved.tobytes())
            resampled = self._resampler.resample(frame)
        except Exception as exc:
            raise AudioError(
                failure_for(
                    "RESAMPLE_FAILED",
                    "PyAV resampling failed.",
                    exception=exc,
                )
            ) from exc

        chunks: list[NDArray[np.float32]] = []
        for out_frame in resampled:
            raw = bytes(out_frame.planes[0])
            if out_frame.format.name in ("s16", "s16p"):
                arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            else:
                arr = np.frombuffer(raw, dtype=np.float32)
            ch = out_frame.layout.nb_channels
            usable = (arr.size // ch) * ch
            if usable == 0:
                continue
            shaped = arr[:usable].reshape(-1, ch)
            chunks.append(
                convert_channels(
                    shaped,
                    source_channels=ch,
                    target_channels=self.target_channels,
                )
            )
        if not chunks:
            return np.zeros((0, self.target_channels), dtype=np.float32)
        return np.concatenate(chunks, axis=0)
