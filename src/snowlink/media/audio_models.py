"""Audio configuration and Experiment D result models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from snowlink.media.audio_errors import AudioError, failure_for

SCHEMA_VERSION = 1
EXPERIMENT_NAME = "experiment_d_audio_loopback"

# Target format for later Snowlink / WebRTC integration.
TARGET_SAMPLE_RATE = 48_000
TARGET_CHANNELS = 2
DEFAULT_FRAME_MS = 20
DEFAULT_BUFFER_MS = 160
DEFAULT_GAIN = 0.7
SAMPLES_PER_FRAME_48K_20MS = 960  # per channel

MIN_DURATION_S = 1
MAX_DURATION_S = 3600
MIN_SAMPLE_RATE = 8_000
MAX_SAMPLE_RATE = 192_000
MIN_CHANNELS = 1
MAX_CHANNELS = 8
MIN_FRAME_MS = 5
MAX_FRAME_MS = 100
MIN_BUFFER_MS = 40
MAX_BUFFER_MS = 1000
MIN_GAIN = 0.0
MAX_GAIN = 1.0

OutputSampleFormat = Literal["s16", "fltp"]
DEFAULT_OUTPUT_SAMPLE_FORMAT: OutputSampleFormat = "s16"

PipelineMode = Literal["monitor", "playback", "benchmark", "latency"]


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class AudioConfiguration:
    """Validated Experiment D pipeline configuration."""

    capture_device: str = "default"
    playback_device: str = "default"
    target_sample_rate: int = TARGET_SAMPLE_RATE
    target_channels: int = TARGET_CHANNELS
    frame_duration_ms: int = DEFAULT_FRAME_MS
    buffer_capacity_ms: int = DEFAULT_BUFFER_MS
    duration_s: int = 60
    gain: float = DEFAULT_GAIN
    muted: bool = False
    output_sample_format: OutputSampleFormat = DEFAULT_OUTPUT_SAMPLE_FORMAT
    mode: PipelineMode = "benchmark"
    enable_playback: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "capture_device": self.capture_device,
            "playback_device": self.playback_device,
            "target_sample_rate": self.target_sample_rate,
            "target_channels": self.target_channels,
            "frame_duration_ms": self.frame_duration_ms,
            "buffer_capacity_ms": self.buffer_capacity_ms,
            "duration_s": self.duration_s,
            "gain": self.gain,
            "muted": self.muted,
            "output_sample_format": self.output_sample_format,
            "mode": self.mode,
            "enable_playback": self.enable_playback,
        }


def validate_audio_configuration(
    *,
    capture_device: str = "default",
    playback_device: str = "default",
    sample_rate: int = TARGET_SAMPLE_RATE,
    channels: int = TARGET_CHANNELS,
    frame_ms: int = DEFAULT_FRAME_MS,
    buffer_ms: int = DEFAULT_BUFFER_MS,
    duration: int = 60,
    gain: float = DEFAULT_GAIN,
    muted: bool = False,
    output_sample_format: str = DEFAULT_OUTPUT_SAMPLE_FORMAT,
    mode: PipelineMode = "benchmark",
    enable_playback: bool | None = None,
) -> AudioConfiguration:
    """Validate CLI/config values and return an immutable configuration."""
    if not isinstance(capture_device, str) or not capture_device.strip():
        raise AudioError(
            failure_for(
                "INVALID_CAPTURE_DEVICE",
                f"Capture device must be a non-empty string, got {capture_device!r}.",
            )
        )
    if not isinstance(playback_device, str) or not playback_device.strip():
        raise AudioError(
            failure_for(
                "INVALID_PLAYBACK_DEVICE",
                f"Playback device must be a non-empty string, got {playback_device!r}.",
            )
        )
    if (
        not isinstance(sample_rate, int)
        or isinstance(sample_rate, bool)
        or not (MIN_SAMPLE_RATE <= sample_rate <= MAX_SAMPLE_RATE)
    ):
        raise AudioError(
            failure_for(
                "INVALID_CONFIGURATION",
                f"Sample rate must be an integer in [{MIN_SAMPLE_RATE}, {MAX_SAMPLE_RATE}], "
                f"got {sample_rate!r}.",
            )
        )
    if (
        not isinstance(channels, int)
        or isinstance(channels, bool)
        or not (MIN_CHANNELS <= channels <= MAX_CHANNELS)
    ):
        raise AudioError(
            failure_for(
                "INVALID_CONFIGURATION",
                f"Channels must be an integer in [{MIN_CHANNELS}, {MAX_CHANNELS}], "
                f"got {channels!r}.",
            )
        )
    if (
        not isinstance(frame_ms, int)
        or isinstance(frame_ms, bool)
        or not (MIN_FRAME_MS <= frame_ms <= MAX_FRAME_MS)
    ):
        raise AudioError(
            failure_for(
                "INVALID_CONFIGURATION",
                f"Frame duration must be an integer in [{MIN_FRAME_MS}, {MAX_FRAME_MS}] ms, "
                f"got {frame_ms!r}.",
            )
        )
    if (
        not isinstance(buffer_ms, int)
        or isinstance(buffer_ms, bool)
        or not (MIN_BUFFER_MS <= buffer_ms <= MAX_BUFFER_MS)
    ):
        raise AudioError(
            failure_for(
                "INVALID_CONFIGURATION",
                f"Buffer capacity must be an integer in [{MIN_BUFFER_MS}, {MAX_BUFFER_MS}] ms, "
                f"got {buffer_ms!r}.",
            )
        )
    if buffer_ms < frame_ms * 2:
        raise AudioError(
            failure_for(
                "INVALID_CONFIGURATION",
                f"Buffer capacity ({buffer_ms} ms) should be at least 2x frame duration "
                f"({frame_ms} ms).",
            )
        )
    if (
        not isinstance(duration, int)
        or isinstance(duration, bool)
        or not (MIN_DURATION_S <= duration <= MAX_DURATION_S)
    ):
        raise AudioError(
            failure_for(
                "INVALID_CONFIGURATION",
                f"Duration must be an integer in [{MIN_DURATION_S}, {MAX_DURATION_S}] "
                f"seconds, got {duration!r}.",
            )
        )
    if not isinstance(gain, (int, float)) or isinstance(gain, bool):
        raise AudioError(
            failure_for(
                "INVALID_CONFIGURATION",
                f"Gain must be a number in [{MIN_GAIN}, {MAX_GAIN}], got {gain!r}.",
            )
        )
    gain_f = float(gain)
    if not (MIN_GAIN <= gain_f <= MAX_GAIN):
        raise AudioError(
            failure_for(
                "INVALID_CONFIGURATION",
                f"Gain must be in [{MIN_GAIN}, {MAX_GAIN}], got {gain_f!r}.",
            )
        )
    fmt = output_sample_format.strip().lower()
    if fmt not in ("s16", "fltp"):
        raise AudioError(
            failure_for(
                "UNSUPPORTED_AUDIO_FORMAT",
                f"Unsupported output sample format {output_sample_format!r}; "
                "use 's16' or 'fltp'.",
            )
        )
    play = enable_playback if enable_playback is not None else mode != "monitor"
    return AudioConfiguration(
        capture_device=capture_device.strip(),
        playback_device=playback_device.strip(),
        target_sample_rate=sample_rate,
        target_channels=channels,
        frame_duration_ms=frame_ms,
        buffer_capacity_ms=buffer_ms,
        duration_s=duration,
        gain=gain_f,
        muted=bool(muted),
        output_sample_format=fmt,  # type: ignore[arg-type]
        mode=mode,
        enable_playback=bool(play),
    )


@dataclass(slots=True)
class CaptureAudioStats:
    device_index: int | None = None
    device_name: str = ""
    native_sample_rate: int = 0
    native_channels: int = 0
    native_sample_format: str = ""
    captured_samples: int = 0
    captured_frames: int = 0
    capture_callbacks: int = 0
    non_silent_frames: int = 0
    silence_frames: int = 0
    peak_level: float = 0.0
    rms_average: float = 0.0
    read_errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ConversionStats:
    output_sample_rate: int = TARGET_SAMPLE_RATE
    output_channels: int = TARGET_CHANNELS
    output_sample_format: str = DEFAULT_OUTPUT_SAMPLE_FORMAT
    converted_samples: int = 0
    frame_duration_ms: int = DEFAULT_FRAME_MS
    actual_frame_samples: int = SAMPLES_PER_FRAME_48K_20MS
    last_pts: int = -1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PlaybackStats:
    device_index: int | None = None
    device_name: str = ""
    played_samples: int = 0
    playback_writes: int = 0
    write_errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BufferStats:
    capacity_ms: float = 0.0
    average_fill_ms: float | None = None
    peak_fill_ms: float | None = None
    underruns: int = 0
    overruns: int = 0
    dropped_samples: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AudioTimingStatsMs:
    processing_average: float | None = None
    processing_p50: float | None = None
    processing_p95: float | None = None
    queue_delay_average: float | None = None
    queue_delay_p50: float | None = None
    queue_delay_p95: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ResourceStats:
    cpu_percent_average: float | None = None
    cpu_percent_peak: float | None = None
    memory_mb_start: float | None = None
    memory_mb_end: float | None = None
    memory_mb_peak: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExperimentDResult:
    """Schema v1 result for Experiment D WASAPI loopback runs."""

    experiment: str = EXPERIMENT_NAME
    schema_version: int = SCHEMA_VERSION
    started_at_utc: str = field(default_factory=utc_now_iso)
    completed_at_utc: str | None = None
    success: bool = False
    configuration: AudioConfiguration | None = None
    capture: CaptureAudioStats = field(default_factory=CaptureAudioStats)
    conversion: ConversionStats = field(default_factory=ConversionStats)
    playback: PlaybackStats = field(default_factory=PlaybackStats)
    buffer: BufferStats = field(default_factory=BufferStats)
    timing_ms: AudioTimingStatsMs = field(default_factory=AudioTimingStatsMs)
    resources: ResourceStats = field(default_factory=ResourceStats)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(
        default_factory=lambda: [
            "queue_delay_* is approximate local pipeline queue delay (ring-buffer "
            "fill), not true end-to-end or glass-to-glass audio latency.",
            "Ordinary captured silence is not an error; underruns mean missing data.",
            "Protected/DRM audio may capture as silence on some Windows configurations.",
        ]
    )
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment,
            "schema_version": self.schema_version,
            "started_at_utc": self.started_at_utc,
            "completed_at_utc": self.completed_at_utc,
            "success": self.success,
            "configuration": (
                self.configuration.to_dict() if self.configuration else None
            ),
            "capture": self.capture.to_dict(),
            "conversion": self.conversion.to_dict(),
            "playback": self.playback.to_dict(),
            "buffer": self.buffer.to_dict(),
            "timing_ms": self.timing_ms.to_dict(),
            "resources": self.resources.to_dict(),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "notes": list(self.notes),
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentDResult:
        cfg_raw = data.get("configuration")
        configuration = None
        if isinstance(cfg_raw, dict):
            configuration = validate_audio_configuration(
                capture_device=str(cfg_raw.get("capture_device", "default")),
                playback_device=str(cfg_raw.get("playback_device", "default")),
                sample_rate=int(cfg_raw.get("target_sample_rate", TARGET_SAMPLE_RATE)),
                channels=int(cfg_raw.get("target_channels", TARGET_CHANNELS)),
                frame_ms=int(cfg_raw.get("frame_duration_ms", DEFAULT_FRAME_MS)),
                buffer_ms=int(cfg_raw.get("buffer_capacity_ms", DEFAULT_BUFFER_MS)),
                duration=int(cfg_raw.get("duration_s", 60)),
                gain=float(cfg_raw.get("gain", DEFAULT_GAIN)),
                muted=bool(cfg_raw.get("muted", False)),
                output_sample_format=str(
                    cfg_raw.get("output_sample_format", DEFAULT_OUTPUT_SAMPLE_FORMAT)
                ),
                mode=str(cfg_raw.get("mode", "benchmark")),  # type: ignore[arg-type]
                enable_playback=bool(cfg_raw.get("enable_playback", True)),
            )
        cap = data.get("capture") or {}
        conv = data.get("conversion") or {}
        play = data.get("playback") or {}
        buf = data.get("buffer") or {}
        tim = data.get("timing_ms") or {}
        res = data.get("resources") or {}
        return cls(
            experiment=str(data.get("experiment", EXPERIMENT_NAME)),
            schema_version=int(data.get("schema_version", 0)),
            started_at_utc=str(data.get("started_at_utc", "")),
            completed_at_utc=data.get("completed_at_utc"),
            success=bool(data.get("success", False)),
            configuration=configuration,
            capture=CaptureAudioStats(
                device_index=cap.get("device_index"),
                device_name=str(cap.get("device_name", "")),
                native_sample_rate=int(cap.get("native_sample_rate", 0)),
                native_channels=int(cap.get("native_channels", 0)),
                native_sample_format=str(cap.get("native_sample_format", "")),
                captured_samples=int(cap.get("captured_samples", 0)),
                captured_frames=int(cap.get("captured_frames", 0)),
                capture_callbacks=int(cap.get("capture_callbacks", 0)),
                non_silent_frames=int(cap.get("non_silent_frames", 0)),
                silence_frames=int(cap.get("silence_frames", 0)),
                peak_level=float(cap.get("peak_level", 0.0)),
                rms_average=float(cap.get("rms_average", 0.0)),
                read_errors=int(cap.get("read_errors", 0)),
            ),
            conversion=ConversionStats(
                output_sample_rate=int(conv.get("output_sample_rate", TARGET_SAMPLE_RATE)),
                output_channels=int(conv.get("output_channels", TARGET_CHANNELS)),
                output_sample_format=str(
                    conv.get("output_sample_format", DEFAULT_OUTPUT_SAMPLE_FORMAT)
                ),
                converted_samples=int(conv.get("converted_samples", 0)),
                frame_duration_ms=int(conv.get("frame_duration_ms", DEFAULT_FRAME_MS)),
                actual_frame_samples=int(
                    conv.get("actual_frame_samples", SAMPLES_PER_FRAME_48K_20MS)
                ),
                last_pts=int(conv.get("last_pts", -1)),
            ),
            playback=PlaybackStats(
                device_index=play.get("device_index"),
                device_name=str(play.get("device_name", "")),
                played_samples=int(play.get("played_samples", 0)),
                playback_writes=int(play.get("playback_writes", 0)),
                write_errors=int(play.get("write_errors", 0)),
            ),
            buffer=BufferStats(
                capacity_ms=float(buf.get("capacity_ms", 0.0)),
                average_fill_ms=buf.get("average_fill_ms"),
                peak_fill_ms=buf.get("peak_fill_ms"),
                underruns=int(buf.get("underruns", 0)),
                overruns=int(buf.get("overruns", 0)),
                dropped_samples=int(buf.get("dropped_samples", 0)),
            ),
            timing_ms=AudioTimingStatsMs(
                processing_average=tim.get("processing_average"),
                processing_p50=tim.get("processing_p50"),
                processing_p95=tim.get("processing_p95"),
                queue_delay_average=tim.get("queue_delay_average"),
                queue_delay_p50=tim.get("queue_delay_p50"),
                queue_delay_p95=tim.get("queue_delay_p95"),
            ),
            resources=ResourceStats(
                cpu_percent_average=res.get("cpu_percent_average"),
                cpu_percent_peak=res.get("cpu_percent_peak"),
                memory_mb_start=res.get("memory_mb_start"),
                memory_mb_end=res.get("memory_mb_end"),
                memory_mb_peak=res.get("memory_mb_peak"),
            ),
            errors=[e for e in (data.get("errors") or []) if isinstance(e, dict)],
            warnings=[str(w) for w in (data.get("warnings") or [])],
            notes=list(data.get("notes") or []),
            details=dict(data.get("details") or {}),
        )
