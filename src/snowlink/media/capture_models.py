"""Capture configuration, presets, and Experiment C result models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from snowlink.media.capture_errors import CaptureError, failure_for

SCHEMA_VERSION = 1
EXPERIMENT_NAME = "experiment_c_screen_capture"

BackendName = Literal["dxgi", "winrt"]
KNOWN_BACKENDS: tuple[BackendName, ...] = ("dxgi", "winrt")

MIN_FPS = 1
MAX_FPS = 120
MIN_DURATION_S = 1
MAX_DURATION_S = 3600
MIN_DIMENSION = 1
MAX_DIMENSION = 7680  # 8K-ish practical upper bound for experiment args

PresetName = Literal["low", "balanced", "high"]


@dataclass(frozen=True, slots=True)
class QualityPreset:
    name: PresetName
    width: int
    height: int
    fps: int


PRESETS: dict[PresetName, QualityPreset] = {
    "low": QualityPreset(name="low", width=854, height=480, fps=15),
    "balanced": QualityPreset(name="balanced", width=1280, height=720, fps=30),
    "high": QualityPreset(name="high", width=1920, height=1080, fps=30),
}

DEFAULT_PRESET: QualityPreset = PRESETS["balanced"]


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class CaptureConfiguration:
    """Validated capture/preview/benchmark configuration."""

    monitor: int = 0
    backend: BackendName = "dxgi"
    requested_fps: int = DEFAULT_PRESET.fps
    requested_width: int = DEFAULT_PRESET.width
    requested_height: int = DEFAULT_PRESET.height
    duration_s: int = 60
    cursor_requested: bool = False
    show_preview: bool = True
    preset_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "monitor": self.monitor,
            "backend": self.backend,
            "requested_fps": self.requested_fps,
            "requested_width": self.requested_width,
            "requested_height": self.requested_height,
            "duration_s": self.duration_s,
            "cursor_requested": self.cursor_requested,
            "show_preview": self.show_preview,
            "preset_name": self.preset_name,
        }


def resolve_preset(name: str) -> QualityPreset:
    key = name.strip().lower()
    if key not in PRESETS:
        known = ", ".join(PRESETS)
        raise CaptureError(
            failure_for(
                "INVALID_CONFIGURATION",
                f"Unknown preset {name!r}. Known presets: {known}.",
            )
        )
    return PRESETS[key]  # key narrowed by membership check above


def validate_backend(name: str) -> BackendName:
    normalized = name.strip().lower()
    if normalized not in KNOWN_BACKENDS:
        known = ", ".join(KNOWN_BACKENDS)
        raise CaptureError(
            failure_for(
                "BACKEND_UNAVAILABLE",
                f"Unknown backend {name!r}. Supported names: {known}.",
            )
        )
    return normalized  # narrowed by membership check above


def validate_capture_configuration(
    *,
    monitor: int,
    backend: str,
    fps: int,
    width: int,
    height: int,
    duration: int,
    cursor_requested: bool = False,
    show_preview: bool = True,
    preset_name: str | None = None,
) -> CaptureConfiguration:
    """Validate CLI/config values and return an immutable configuration."""
    if not isinstance(monitor, int) or isinstance(monitor, bool) or monitor < 0:
        raise CaptureError(
            failure_for(
                "INVALID_MONITOR",
                f"Monitor index must be a non-negative integer, got {monitor!r}.",
            )
        )
    backend_name = validate_backend(backend)

    if not isinstance(fps, int) or isinstance(fps, bool) or not (MIN_FPS <= fps <= MAX_FPS):
        raise CaptureError(
            failure_for(
                "INVALID_CONFIGURATION",
                f"FPS must be an integer in [{MIN_FPS}, {MAX_FPS}], got {fps!r}.",
            )
        )
    if (
        not isinstance(width, int)
        or isinstance(width, bool)
        or not (MIN_DIMENSION <= width <= MAX_DIMENSION)
    ):
        raise CaptureError(
            failure_for(
                "INVALID_CONFIGURATION",
                f"Width must be an integer in [{MIN_DIMENSION}, {MAX_DIMENSION}], "
                f"got {width!r}.",
            )
        )
    if (
        not isinstance(height, int)
        or isinstance(height, bool)
        or not (MIN_DIMENSION <= height <= MAX_DIMENSION)
    ):
        raise CaptureError(
            failure_for(
                "INVALID_CONFIGURATION",
                f"Height must be an integer in [{MIN_DIMENSION}, {MAX_DIMENSION}], "
                f"got {height!r}.",
            )
        )
    if (
        not isinstance(duration, int)
        or isinstance(duration, bool)
        or not (MIN_DURATION_S <= duration <= MAX_DURATION_S)
    ):
        raise CaptureError(
            failure_for(
                "INVALID_CONFIGURATION",
                f"Duration must be an integer in [{MIN_DURATION_S}, {MAX_DURATION_S}] "
                f"seconds, got {duration!r}.",
            )
        )

    return CaptureConfiguration(
        monitor=monitor,
        backend=backend_name,
        requested_fps=fps,
        requested_width=width,
        requested_height=height,
        duration_s=duration,
        cursor_requested=bool(cursor_requested),
        show_preview=bool(show_preview),
        preset_name=preset_name,
    )


@dataclass(slots=True)
class CaptureStats:
    native_width: int = 0
    native_height: int = 0
    frames_captured: int = 0
    actual_fps: float = 0.0
    null_frames: int = 0
    duplicate_frames: int = 0
    overwritten_frames: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RenderStats:
    frames_rendered: int = 0
    actual_fps: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TimingStatsMs:
    capture_interval_average: float | None = None
    capture_interval_p50: float | None = None
    capture_interval_p95: float | None = None
    capture_interval_p99: float | None = None
    frame_age_average: float | None = None
    frame_age_p50: float | None = None
    frame_age_p95: float | None = None
    frame_age_p99: float | None = None
    scale_average: float | None = None
    scale_p50: float | None = None
    scale_p95: float | None = None
    capture_to_preview_average: float | None = None
    capture_to_preview_p95: float | None = None

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
class ExperimentCResult:
    """Schema v1 result for Experiment C local screen-capture runs."""

    experiment: str = EXPERIMENT_NAME
    schema_version: int = SCHEMA_VERSION
    started_at_utc: str = field(default_factory=utc_now_iso)
    completed_at_utc: str | None = None
    success: bool = False
    configuration: CaptureConfiguration | None = None
    capture: CaptureStats = field(default_factory=CaptureStats)
    render: RenderStats = field(default_factory=RenderStats)
    timing_ms: TimingStatsMs = field(default_factory=TimingStatsMs)
    resources: ResourceStats = field(default_factory=ResourceStats)
    errors: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(
        default_factory=lambda: [
            "frame_age_* and capture_to_preview_* are approximate local "
            "measurements (capture timestamp to render/consume), not glass-to-glass "
            "latency.",
            "Scaling policy: fit inside requested WxH while preserving aspect ratio; "
            "letterbox with black bars when needed (no stretch).",
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
            "render": self.render.to_dict(),
            "timing_ms": self.timing_ms.to_dict(),
            "resources": self.resources.to_dict(),
            "errors": list(self.errors),
            "notes": list(self.notes),
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentCResult:
        cfg_raw = data.get("configuration")
        configuration = None
        if isinstance(cfg_raw, dict):
            configuration = CaptureConfiguration(
                monitor=int(cfg_raw.get("monitor", 0)),
                backend=validate_backend(str(cfg_raw.get("backend", "dxgi"))),
                requested_fps=int(cfg_raw.get("requested_fps", DEFAULT_PRESET.fps)),
                requested_width=int(
                    cfg_raw.get("requested_width", DEFAULT_PRESET.width)
                ),
                requested_height=int(
                    cfg_raw.get("requested_height", DEFAULT_PRESET.height)
                ),
                duration_s=int(cfg_raw.get("duration_s", 60)),
                cursor_requested=bool(cfg_raw.get("cursor_requested", False)),
                show_preview=bool(cfg_raw.get("show_preview", True)),
                preset_name=cfg_raw.get("preset_name"),
            )
        cap_raw = data.get("capture") or {}
        ren_raw = data.get("render") or {}
        tim_raw = data.get("timing_ms") or {}
        res_raw = data.get("resources") or {}
        return cls(
            experiment=str(data.get("experiment", EXPERIMENT_NAME)),
            schema_version=int(data.get("schema_version", 0)),
            started_at_utc=str(data.get("started_at_utc", "")),
            completed_at_utc=data.get("completed_at_utc"),
            success=bool(data.get("success", False)),
            configuration=configuration,
            capture=CaptureStats(
                native_width=int(cap_raw.get("native_width", 0)),
                native_height=int(cap_raw.get("native_height", 0)),
                frames_captured=int(cap_raw.get("frames_captured", 0)),
                actual_fps=float(cap_raw.get("actual_fps", 0.0)),
                null_frames=int(cap_raw.get("null_frames", 0)),
                duplicate_frames=int(cap_raw.get("duplicate_frames", 0)),
                overwritten_frames=int(cap_raw.get("overwritten_frames", 0)),
            ),
            render=RenderStats(
                frames_rendered=int(ren_raw.get("frames_rendered", 0)),
                actual_fps=float(ren_raw.get("actual_fps", 0.0)),
            ),
            timing_ms=TimingStatsMs(
                capture_interval_average=tim_raw.get("capture_interval_average"),
                capture_interval_p50=tim_raw.get("capture_interval_p50"),
                capture_interval_p95=tim_raw.get("capture_interval_p95"),
                capture_interval_p99=tim_raw.get("capture_interval_p99"),
                frame_age_average=tim_raw.get("frame_age_average"),
                frame_age_p50=tim_raw.get("frame_age_p50"),
                frame_age_p95=tim_raw.get("frame_age_p95"),
                frame_age_p99=tim_raw.get("frame_age_p99"),
                scale_average=tim_raw.get("scale_average"),
                scale_p50=tim_raw.get("scale_p50"),
                scale_p95=tim_raw.get("scale_p95"),
                capture_to_preview_average=tim_raw.get("capture_to_preview_average"),
                capture_to_preview_p95=tim_raw.get("capture_to_preview_p95"),
            ),
            resources=ResourceStats(
                cpu_percent_average=res_raw.get("cpu_percent_average"),
                cpu_percent_peak=res_raw.get("cpu_percent_peak"),
                memory_mb_start=res_raw.get("memory_mb_start"),
                memory_mb_end=res_raw.get("memory_mb_end"),
                memory_mb_peak=res_raw.get("memory_mb_peak"),
            ),
            errors=[e for e in (data.get("errors") or []) if isinstance(e, dict)],
            notes=list(data.get("notes") or []),
            details=dict(data.get("details") or {}),
        )
