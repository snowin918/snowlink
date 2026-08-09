"""Data models for Experiment E synthetic WebRTC video."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

SCHEMA_VERSION = 1
EXPERIMENT_NAME = "experiment_e_webrtc_video"

DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
DEFAULT_FPS = 30
DEFAULT_PORT = 3847  # Align with product DEFAULT_SIGNALING_PORT
DEFAULT_DURATION_S = 120.0

DEFAULT_SIGNALING_CONNECT_TIMEOUT_S = 5.0
DEFAULT_OFFER_ANSWER_TIMEOUT_S = 10.0
DEFAULT_ICE_GATHERING_TIMEOUT_S = 10.0
DEFAULT_ICE_CONNECTION_TIMEOUT_S = 20.0
DEFAULT_FIRST_FRAME_TIMEOUT_S = 15.0
DEFAULT_INACTIVITY_TIMEOUT_S = 30.0
DEFAULT_SHUTDOWN_TIMEOUT_S = 5.0

MAX_SIGNALING_BODY_BYTES = 256 * 1024
VIDEO_CLOCK_RATE = 90_000


@dataclass(frozen=True, slots=True)
class TimeoutConfig:
    signaling_connect_s: float = DEFAULT_SIGNALING_CONNECT_TIMEOUT_S
    offer_answer_s: float = DEFAULT_OFFER_ANSWER_TIMEOUT_S
    ice_gathering_s: float = DEFAULT_ICE_GATHERING_TIMEOUT_S
    ice_connection_s: float = DEFAULT_ICE_CONNECTION_TIMEOUT_S
    first_frame_s: float = DEFAULT_FIRST_FRAME_TIMEOUT_S
    inactivity_s: float = DEFAULT_INACTIVITY_TIMEOUT_S
    shutdown_s: float = DEFAULT_SHUTDOWN_TIMEOUT_S

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExperimentEConfiguration:
    role: str
    width: int
    height: int
    fps: int
    duration_s: float
    signaling_port: int
    codec: str = "VP8"
    bind_ip: str | None = None
    remote_ip: str | None = None
    requested_source_ip: str | None = None
    allow_h264_fallback: bool = False
    preview: bool = True
    session_name: str = "unnamed"
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timeouts"] = self.timeouts.to_dict()
        return data


@dataclass(slots=True)
class IceCandidateInfo:
    ip: str | None = None
    port: int | None = None
    protocol: str | None = None
    type: str | None = None
    foundation: str | None = None
    priority: int | None = None
    related_address: str | None = None
    related_port: int | None = None
    adapter_category: str | None = None
    raw: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ip": self.ip,
            "port": self.port,
            "protocol": self.protocol,
            "type": self.type,
            "foundation": self.foundation,
            "priority": self.priority,
            "related_address": self.related_address,
            "related_port": self.related_port,
            "adapter_category": self.adapter_category,
        }


@dataclass(slots=True)
class CandidatePairInfo:
    local: IceCandidateInfo | None = None
    remote: IceCandidateInfo | None = None
    state: str | None = None
    nominated: bool | None = None
    current_rtt_ms: float | None = None
    available_outgoing_bitrate: float | None = None
    bytes_sent: int | None = None
    bytes_received: int | None = None
    packets_sent: int | None = None
    packets_received: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "local": self.local.to_dict() if self.local else None,
            "remote": self.remote.to_dict() if self.remote else None,
            "state": self.state,
            "nominated": self.nominated,
            "current_rtt_ms": self.current_rtt_ms,
            "available_outgoing_bitrate": self.available_outgoing_bitrate,
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
            "packets_sent": self.packets_sent,
            "packets_received": self.packets_received,
        }


@dataclass(slots=True)
class ConnectionStats:
    ice_state: str | None = None
    peer_state: str | None = None
    signaling_state: str | None = None
    local_candidates: list[IceCandidateInfo] = field(default_factory=list)
    remote_candidates: list[IceCandidateInfo] = field(default_factory=list)
    selected_pair: CandidatePairInfo | None = None
    selected_local_candidate: IceCandidateInfo | None = None
    selected_remote_candidate: IceCandidateInfo | None = None
    candidate_matches_requested_lan_ip: bool | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ice_state": self.ice_state,
            "peer_state": self.peer_state,
            "signaling_state": self.signaling_state,
            "local_candidates": [c.to_dict() for c in self.local_candidates],
            "remote_candidates": [c.to_dict() for c in self.remote_candidates],
            "selected_candidate_pair": (
                self.selected_pair.to_dict() if self.selected_pair else None
            ),
            "selected_local_candidate": (
                self.selected_local_candidate.to_dict()
                if self.selected_local_candidate
                else None
            ),
            "selected_remote_candidate": (
                self.selected_remote_candidate.to_dict()
                if self.selected_remote_candidate
                else None
            ),
            "candidate_matches_requested_lan_ip": self.candidate_matches_requested_lan_ip,
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class VideoStats:
    frames_generated: int = 0
    frames_skipped_by_schedule: int = 0
    frames_encoded: int | None = None
    frames_sent: int | None = None
    frames_received: int = 0
    frames_decoded: int | None = None
    frames_rendered: int = 0
    frames_dropped: int | None = None
    key_frames: int | None = None
    requested_fps: float | None = None
    actual_generated_fps: float | None = None
    received_fps: float | None = None
    rendered_fps: float | None = None
    width: int | None = None
    height: int | None = None
    codec: str | None = None
    codec_payload_type: int | None = None
    duplicate_sequences: int = 0
    missing_sequences: int = 0
    out_of_order_sequences: int = 0
    latest_frame_overwrites: int = 0
    first_frame_latency_ms: float | None = None
    inter_arrival_average_ms: float | None = None
    inter_arrival_p95_ms: float | None = None
    render_processing_average_ms: float | None = None
    approximate_one_way_delay_ms: float | None = None
    approximate_one_way_delay_uncertainty_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class NetworkStats:
    bytes_sent: int | None = None
    bytes_received: int | None = None
    packets_sent: int | None = None
    packets_received: int | None = None
    packets_lost: int | None = None
    jitter_ms: float | None = None
    current_rtt_ms: float | None = None
    estimated_bitrate_bps: float | None = None
    remote_inbound_packets_lost: int | None = None

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
class AvailableCodec:
    mime_type: str
    clock_rate: int | None = None
    channels: int | None = None
    sdp_fmtp_line: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExperimentEResult:
    experiment: str = EXPERIMENT_NAME
    schema_version: int = SCHEMA_VERSION
    role: str = "receiver"
    success: bool = False
    timestamp: str = ""
    session_name: str = "unnamed"
    configuration: ExperimentEConfiguration | None = None
    connection: ConnectionStats = field(default_factory=ConnectionStats)
    video: VideoStats = field(default_factory=VideoStats)
    network: NetworkStats = field(default_factory=NetworkStats)
    resources: ResourceStats = field(default_factory=ResourceStats)
    available_codecs: list[AvailableCodec] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    signaling_warning: str = (
        "Experiment-only signaling: no production authentication. "
        "Use only on your private LAN."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment,
            "schema_version": self.schema_version,
            "role": self.role,
            "success": self.success,
            "timestamp": self.timestamp or datetime.now(UTC).isoformat(),
            "session_name": self.session_name,
            "configuration": self.configuration.to_dict() if self.configuration else None,
            "connection": self.connection.to_dict(),
            "video": self.video.to_dict(),
            "network": self.network.to_dict(),
            "resources": self.resources.to_dict(),
            "available_codecs": [c.to_dict() for c in self.available_codecs],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "signaling_warning": self.signaling_warning,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentEResult:
        cfg_raw = data.get("configuration")
        configuration: ExperimentEConfiguration | None = None
        if isinstance(cfg_raw, dict):
            timeouts_raw = cfg_raw.get("timeouts") or {}
            timeouts = TimeoutConfig(
                **{
                    k: float(v)
                    for k, v in timeouts_raw.items()
                    if k in TimeoutConfig.__dataclass_fields__
                }
            )
            configuration = ExperimentEConfiguration(
                role=str(cfg_raw.get("role", data.get("role", "receiver"))),
                width=int(cfg_raw.get("width", DEFAULT_WIDTH)),
                height=int(cfg_raw.get("height", DEFAULT_HEIGHT)),
                fps=int(cfg_raw.get("fps", DEFAULT_FPS)),
                duration_s=float(cfg_raw.get("duration_s", DEFAULT_DURATION_S)),
                signaling_port=int(cfg_raw.get("signaling_port", DEFAULT_PORT)),
                codec=str(cfg_raw.get("codec", "VP8")),
                bind_ip=cfg_raw.get("bind_ip"),
                remote_ip=cfg_raw.get("remote_ip"),
                requested_source_ip=cfg_raw.get("requested_source_ip"),
                allow_h264_fallback=bool(cfg_raw.get("allow_h264_fallback", False)),
                preview=bool(cfg_raw.get("preview", True)),
                session_name=str(cfg_raw.get("session_name", "unnamed")),
                timeouts=timeouts,
            )
        return cls(
            experiment=str(data.get("experiment", EXPERIMENT_NAME)),
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
            role=str(data.get("role", "receiver")),
            success=bool(data.get("success", False)),
            timestamp=str(data.get("timestamp", "")),
            session_name=str(data.get("session_name", "unnamed")),
            configuration=configuration,
            warnings=list(data.get("warnings") or []),
            errors=list(data.get("errors") or []),
            signaling_warning=str(
                data.get(
                    "signaling_warning",
                    "Experiment-only signaling: no production authentication. "
                    "Use only on your private LAN.",
                )
            ),
        )


def validate_video_configuration(
    *,
    width: int,
    height: int,
    fps: int,
    duration_s: float,
    port: int,
) -> None:
    """Raise ValueError with INVALID_CONFIGURATION semantics when values are bad."""
    if width < 16 or height < 16 or width > 3840 or height > 2160:
        raise ValueError("width/height out of allowed range (16..3840 x 16..2160)")
    if fps < 1 or fps > 120:
        raise ValueError("fps out of allowed range (1..120)")
    if duration_s <= 0 or duration_s > 86_400:
        raise ValueError("duration out of allowed range")
    if port < 1 or port > 65535:
        raise ValueError("port out of allowed range (1..65535)")


# ---------------------------------------------------------------------------
# Experiment F — synthetic WebRTC Opus audio
# ---------------------------------------------------------------------------

EXPERIMENT_F_NAME = "experiment_f_webrtc_audio"
AUDIO_CLOCK_RATE = 48_000
DEFAULT_AUDIO_PORT = 3849
DEFAULT_AUDIO_SAMPLE_RATE = 48_000
DEFAULT_AUDIO_CHANNELS = 2
DEFAULT_AUDIO_FRAME_MS = 20
DEFAULT_AUDIO_AMPLITUDE = 0.15
DEFAULT_TONE_FREQUENCY_HZ = 440.0
DEFAULT_AUDIO_GAIN = 1.0
DEFAULT_BUFFER_TARGET_MS = 80
DEFAULT_PULSE_INTERVAL_MS = 1000
SAMPLES_PER_FRAME_48K_20MS = 960

DEFAULT_REMOTE_TRACK_TIMEOUT_S = 15.0
DEFAULT_FIRST_AUDIO_FRAME_TIMEOUT_S = 10.0
DEFAULT_AUDIO_INACTIVITY_TIMEOUT_S = 5.0

AudioSignalType = Literal["sine", "silence", "pulse", "alternating"]


@dataclass(frozen=True, slots=True)
class ExperimentFTimeoutConfig:
    signaling_connect_s: float = DEFAULT_SIGNALING_CONNECT_TIMEOUT_S
    offer_answer_s: float = DEFAULT_OFFER_ANSWER_TIMEOUT_S
    ice_gathering_s: float = DEFAULT_ICE_GATHERING_TIMEOUT_S
    ice_connection_s: float = DEFAULT_ICE_CONNECTION_TIMEOUT_S
    remote_track_s: float = DEFAULT_REMOTE_TRACK_TIMEOUT_S
    first_frame_s: float = DEFAULT_FIRST_AUDIO_FRAME_TIMEOUT_S
    inactivity_s: float = DEFAULT_AUDIO_INACTIVITY_TIMEOUT_S
    shutdown_s: float = DEFAULT_SHUTDOWN_TIMEOUT_S

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExperimentFConfiguration:
    role: str
    duration_s: float
    signaling_port: int
    sample_rate: int = DEFAULT_AUDIO_SAMPLE_RATE
    channels: int = DEFAULT_AUDIO_CHANNELS
    frame_duration_ms: int = DEFAULT_AUDIO_FRAME_MS
    signal: AudioSignalType = "sine"
    tone_frequency_hz: float = DEFAULT_TONE_FREQUENCY_HZ
    amplitude: float = DEFAULT_AUDIO_AMPLITUDE
    pulse_interval_ms: int = DEFAULT_PULSE_INTERVAL_MS
    codec: str = "opus"
    bind_ip: str | None = None
    remote_ip: str | None = None
    requested_source_ip: str | None = None
    playback: bool = True
    playback_device: str = "default"
    gain: float = DEFAULT_AUDIO_GAIN
    muted: bool = False
    buffer_target_ms: int = DEFAULT_BUFFER_TARGET_MS
    session_name: str = "unnamed"
    timeouts: ExperimentFTimeoutConfig = field(default_factory=ExperimentFTimeoutConfig)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timeouts"] = self.timeouts.to_dict()
        return data


@dataclass(slots=True)
class AudioTrackStats:
    """Sender/receiver audio-track metrics for Experiment F."""

    signal: str | None = None
    tone_frequency_hz: float | None = None
    amplitude: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    frame_duration_ms: int | None = None
    samples_per_frame: int | None = None
    frames_generated: int = 0
    samples_generated: int = 0
    silence_frames: int = 0
    late_generation_events: int = 0
    max_generation_lateness_ms: float | None = None
    frames_received: int = 0
    samples_received: int = 0
    frame_sample_count_mismatches: int = 0
    invalid_pts_count: int = 0
    missing_pts_count: int = 0
    received_sample_rate: int | None = None
    received_channels: int | None = None
    received_format: str | None = None
    codec: str | None = None
    codec_payload_type: int | None = None
    samples_played: int = 0
    rms_average: float | None = None
    peak: float | None = None
    clipping_count: int = 0
    silent_frame_count: int = 0
    estimated_frequency_hz: float | None = None
    pulses_expected: int | None = None
    pulses_detected: int = 0
    pulses_missing: int = 0
    pulses_duplicate: int = 0
    pulse_interval_variation_ms: float | None = None
    # Optional WebRTC audio stats
    audio_level: float | None = None
    total_audio_energy: float | None = None
    concealed_samples: int | None = None
    silent_concealed_samples: int | None = None
    concealment_events: int | None = None
    jitter_buffer_delay_ms: float | None = None
    jitter_buffer_emitted_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AudioBufferStats:
    target_ms: float | None = None
    capacity_ms: float | None = None
    average_fill_ms: float | None = None
    peak_fill_ms: float | None = None
    underruns: int = 0
    overruns: int = 0
    dropped_samples: int = 0
    silence_samples_inserted: int = 0
    local_receiver_buffering_delay_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExperimentFResult:
    experiment: str = EXPERIMENT_F_NAME
    schema_version: int = SCHEMA_VERSION
    role: str = "receiver"
    success: bool = False
    timestamp: str = ""
    session_name: str = "unnamed"
    configuration: ExperimentFConfiguration | None = None
    connection: ConnectionStats = field(default_factory=ConnectionStats)
    audio: AudioTrackStats = field(default_factory=AudioTrackStats)
    buffer: AudioBufferStats = field(default_factory=AudioBufferStats)
    network: NetworkStats = field(default_factory=NetworkStats)
    resources: ResourceStats = field(default_factory=ResourceStats)
    available_codecs: list[AvailableCodec] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    signaling_warning: str = (
        "Experiment-only signaling: no production authentication. "
        "Use only on your private LAN."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment,
            "schema_version": self.schema_version,
            "role": self.role,
            "success": self.success,
            "timestamp": self.timestamp or datetime.now(UTC).isoformat(),
            "session_name": self.session_name,
            "configuration": self.configuration.to_dict() if self.configuration else None,
            "connection": self.connection.to_dict(),
            "audio": self.audio.to_dict(),
            "buffer": self.buffer.to_dict(),
            "network": self.network.to_dict(),
            "resources": self.resources.to_dict(),
            "available_codecs": [c.to_dict() for c in self.available_codecs],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "signaling_warning": self.signaling_warning,
        }


def validate_audio_webrtc_configuration(
    *,
    sample_rate: int,
    channels: int,
    frame_ms: int,
    duration_s: float,
    port: int,
    amplitude: float,
    gain: float,
    tone_frequency_hz: float,
) -> None:
    """Raise ValueError when Experiment F configuration values are invalid."""
    if sample_rate not in {16_000, 24_000, 48_000}:
        raise ValueError("sample_rate must be 16000, 24000, or 48000")
    if channels not in {1, 2}:
        raise ValueError("channels must be 1 or 2")
    if frame_ms < 5 or frame_ms > 60:
        raise ValueError("frame_ms out of allowed range (5..60)")
    if sample_rate * frame_ms % 1000 != 0:
        raise ValueError("sample_rate * frame_ms must yield an integer sample count")
    if duration_s <= 0 or duration_s > 86_400:
        raise ValueError("duration out of allowed range")
    if port < 1 or port > 65535:
        raise ValueError("port out of allowed range (1..65535)")
    if amplitude < 0.0 or amplitude > 1.0:
        raise ValueError("amplitude must be in [0.0, 1.0]")
    if gain < 0.0 or gain > 1.0:
        raise ValueError("gain must be in [0.0, 1.0]")
    if tone_frequency_hz <= 0 or tone_frequency_hz >= sample_rate / 2:
        raise ValueError("tone_frequency must be in (0, Nyquist)")