"""ctypes bindings for the Snowlink native engine C ABI."""

from __future__ import annotations

import ctypes
import logging
from dataclasses import dataclass
from typing import Any

from snowlink.constants import NATIVE_MEDIA_PORT_MAX, NATIVE_MEDIA_PORT_MIN
from snowlink.native_engine.loader import find_engine_dll, load_engine_dll

logger = logging.getLogger(__name__)

SNOWLINK_OK = 0
SNOWLINK_ERR_NOT_IMPLEMENTED = -4


class NativeEngineUnavailable(RuntimeError):
    """Raised when the native DLL cannot be loaded."""


class NativeEngineError(RuntimeError):
    """Raised when a native engine call returns a non-OK status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"native engine error {status}: {message}")
        self.status = status
        self.message = message


class _CaptureConfig(ctypes.Structure):
    _fields_ = [
        ("monitor_index", ctypes.c_int32),
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
        ("target_fps", ctypes.c_int32),
        ("backend", ctypes.c_int32),
        ("display_id", ctypes.c_uint64),
    ]


class _StreamConfig(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
        ("target_fps", ctypes.c_int32),
        ("bitrate_bps", ctypes.c_int32),
    ]


class _TransportConfig(ctypes.Structure):
    _fields_ = [
        ("bind_address", ctypes.c_char_p),
        ("port_min", ctypes.c_uint16),
        ("port_max", ctypes.c_uint16),
        ("mtu", ctypes.c_uint32),
        ("frame_queue_limit", ctypes.c_uint32),
        ("nack_packet_limit", ctypes.c_uint32),
    ]


class _InputEvent(ctypes.Structure):
    _fields_ = [
        ("kind", ctypes.c_uint8),
        ("code", ctypes.c_uint8),
        ("down", ctypes.c_uint8),
        ("reserved", ctypes.c_uint8),
        ("x", ctypes.c_int32),
        ("y", ctypes.c_int32),
        ("delta", ctypes.c_int32),
        ("sequence", ctypes.c_uint64),
    ]


class _EngineStats(ctypes.Structure):
    _fields_ = [
        ("capture_fps", ctypes.c_double),
        ("encode_fps", ctypes.c_double),
        ("decode_fps", ctypes.c_double),
        ("render_fps", ctypes.c_double),
        ("bitrate_bps", ctypes.c_int64),
        ("frames_captured", ctypes.c_uint64),
        ("frames_encoded", ctypes.c_uint64),
        ("frames_dropped", ctypes.c_uint64),
        ("frames_decoded", ctypes.c_uint64),
        ("capture_latency_ms", ctypes.c_double),
        ("encode_latency_ms", ctypes.c_double),
        ("decode_latency_ms", ctypes.c_double),
        ("render_latency_ms", ctypes.c_double),
        ("network_rtt_ms", ctypes.c_double),
        ("send_bitrate", ctypes.c_double),
        ("packets_sent", ctypes.c_uint64),
        ("packets_dropped", ctypes.c_uint64),
        ("transport_frames_dropped", ctypes.c_uint64),
        ("transport_errors", ctypes.c_uint64),
        ("transport_queue_depth", ctypes.c_uint32),
        ("estimated_loss", ctypes.c_double),
    ]


@dataclass(frozen=True, slots=True)
class NativeEngineStats:
    capture_fps: float
    encode_fps: float
    decode_fps: float
    render_fps: float
    bitrate_bps: int
    frames_captured: int
    frames_encoded: int
    frames_dropped: int
    frames_decoded: int
    capture_latency_ms: float
    encode_latency_ms: float
    decode_latency_ms: float
    render_latency_ms: float
    network_rtt_ms: float
    send_bitrate: float
    packets_sent: int
    packets_dropped: int
    transport_frames_dropped: int
    transport_errors: int
    transport_queue_depth: int
    estimated_loss: float


def _bind(dll: ctypes.CDLL) -> None:
    dll.snowlink_engine_version.restype = ctypes.c_char_p
    dll.snowlink_engine_version.argtypes = []

    dll.snowlink_engine_create.restype = ctypes.c_int32
    dll.snowlink_engine_create.argtypes = [ctypes.POINTER(ctypes.c_void_p)]

    dll.snowlink_engine_destroy.restype = ctypes.c_int32
    dll.snowlink_engine_destroy.argtypes = [ctypes.c_void_p]

    dll.snowlink_engine_initialize.restype = ctypes.c_int32
    dll.snowlink_engine_initialize.argtypes = [ctypes.c_void_p]

    dll.snowlink_engine_shutdown.restype = ctypes.c_int32
    dll.snowlink_engine_shutdown.argtypes = [ctypes.c_void_p]

    dll.snowlink_engine_start_capture.restype = ctypes.c_int32
    dll.snowlink_engine_start_capture.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_CaptureConfig),
    ]

    dll.snowlink_engine_stop_capture.restype = ctypes.c_int32
    dll.snowlink_engine_stop_capture.argtypes = [ctypes.c_void_p]

    dll.snowlink_engine_start_stream.restype = ctypes.c_int32
    dll.snowlink_engine_start_stream.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_StreamConfig),
    ]

    dll.snowlink_engine_stop_stream.restype = ctypes.c_int32
    dll.snowlink_engine_stop_stream.argtypes = [ctypes.c_void_p]

    dll.snowlink_engine_connect_transport.restype = ctypes.c_int32
    dll.snowlink_engine_connect_transport.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_TransportConfig),
    ]
    dll.snowlink_engine_create_transport_offer.restype = ctypes.c_int32
    dll.snowlink_engine_create_transport_offer.argtypes = [ctypes.c_void_p]
    for name in ("snowlink_engine_get_local_sdp", "snowlink_engine_get_local_sdp_type"):
        fn = getattr(dll, name)
        fn.restype = ctypes.c_int32
        fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
    dll.snowlink_engine_set_remote_sdp.restype = ctypes.c_int32
    dll.snowlink_engine_set_remote_sdp.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
    ]
    dll.snowlink_engine_start_receiver.restype = ctypes.c_int32
    dll.snowlink_engine_start_receiver.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint64,
        ctypes.POINTER(_TransportConfig),
    ]
    for name in (
        "snowlink_engine_create_receiver_answer",
        "snowlink_engine_stop_receiver",
        "snowlink_engine_receiver_resize",
    ):
        fn = getattr(dll, name)
        fn.restype = ctypes.c_int32
        fn.argtypes = [ctypes.c_void_p]
    dll.snowlink_engine_receiver_set_visible.restype = ctypes.c_int32
    dll.snowlink_engine_receiver_set_visible.argtypes = [ctypes.c_void_p, ctypes.c_int32]
    dll.snowlink_engine_send_input.restype = ctypes.c_int32
    dll.snowlink_engine_send_input.argtypes = [ctypes.c_void_p, ctypes.POINTER(_InputEvent)]
    dll.snowlink_engine_set_remote_input_enabled.restype = ctypes.c_int32
    dll.snowlink_engine_set_remote_input_enabled.argtypes = [ctypes.c_void_p, ctypes.c_int32]
    dll.snowlink_engine_get_decoder_name.restype = ctypes.c_int32
    dll.snowlink_engine_get_decoder_name.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    dll.snowlink_engine_get_decoder_status.restype = ctypes.c_int32
    dll.snowlink_engine_get_decoder_status.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int32),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_double),
    ]

    dll.snowlink_engine_set_target_fps.restype = ctypes.c_int32
    dll.snowlink_engine_set_target_fps.argtypes = [ctypes.c_void_p, ctypes.c_int32]

    dll.snowlink_engine_set_bitrate.restype = ctypes.c_int32
    dll.snowlink_engine_set_bitrate.argtypes = [ctypes.c_void_p, ctypes.c_int32]

    dll.snowlink_engine_set_resolution.restype = ctypes.c_int32
    dll.snowlink_engine_set_resolution.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int32,
        ctypes.c_int32,
    ]

    dll.snowlink_engine_set_capture_cursor_in_video.restype = ctypes.c_int32
    dll.snowlink_engine_set_capture_cursor_in_video.argtypes = [ctypes.c_void_p, ctypes.c_int32]

    dll.snowlink_engine_get_capture_status.restype = ctypes.c_int32
    dll.snowlink_engine_get_capture_status.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_CaptureStatus),
    ]

    dll.snowlink_engine_request_keyframe.restype = ctypes.c_int32
    dll.snowlink_engine_request_keyframe.argtypes = [ctypes.c_void_p]

    dll.snowlink_engine_get_stats.restype = ctypes.c_int32
    dll.snowlink_engine_get_stats.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_EngineStats),
    ]

    dll.snowlink_engine_get_state.restype = ctypes.c_int32
    dll.snowlink_engine_get_state.argtypes = [ctypes.c_void_p]

    dll.snowlink_engine_last_error.restype = ctypes.c_char_p
    dll.snowlink_engine_last_error.argtypes = [ctypes.c_void_p]


def is_native_engine_available() -> bool:
    return find_engine_dll() is not None


def probe_native_engine() -> dict[str, Any]:
    """Load DLL, initialize, fetch version/stats, shutdown. Safe for diagnostics."""
    engine = NativeEngine.create()
    try:
        engine.initialize()
        stats = engine.get_stats()
        return {
            "available": True,
            "version": engine.version(),
            "state": engine.state(),
            "stats": stats,
        }
    finally:
        engine.shutdown()
        engine.destroy()


class _CaptureStatus(ctypes.Structure):
    _fields_ = [
        ("borderless_capture_available", ctypes.c_int32),
        ("borderless_capture_granted", ctypes.c_int32),
        ("capture_border_active", ctypes.c_int32),
        ("capture_cursor_in_video", ctypes.c_int32),
        ("capture_active", ctypes.c_int32),
        ("access_lost", ctypes.c_int32),
        ("device_lost", ctypes.c_int32),
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
    ]


@dataclass(frozen=True, slots=True)
class NativeCaptureStatus:
    borderless_capture_available: bool
    borderless_capture_granted: bool
    capture_border_active: bool
    capture_cursor_in_video: bool
    capture_active: bool
    access_lost: bool
    device_lost: bool
    width: int
    height: int


class NativeEngine:
    """Thin ownership wrapper around ``SnowlinkEngine*``."""

    def __init__(self, handle: int, dll: ctypes.CDLL) -> None:
        self._handle = handle
        self._dll = dll
        self._alive = True

    @classmethod
    def create(cls) -> NativeEngine:
        try:
            dll = load_engine_dll()
        except (FileNotFoundError, OSError) as exc:
            raise NativeEngineUnavailable(str(exc)) from exc
        _bind(dll)
        handle = ctypes.c_void_p()
        status = int(dll.snowlink_engine_create(ctypes.byref(handle)))
        if status != SNOWLINK_OK or not handle.value:
            raise NativeEngineError(status, "snowlink_engine_create failed")
        return cls(int(handle.value), dll)

    def _check(self, status: int, *, allow_not_implemented: bool = False) -> int:
        if status == SNOWLINK_OK:
            return status
        if allow_not_implemented and status == SNOWLINK_ERR_NOT_IMPLEMENTED:
            return status
        msg = self.last_error()
        raise NativeEngineError(status, msg)

    def version(self) -> str:
        raw = self._dll.snowlink_engine_version()
        return raw.decode("utf-8") if raw else ""

    def initialize(self) -> None:
        self._ensure_alive()
        self._check(int(self._dll.snowlink_engine_initialize(self._handle)))

    def shutdown(self) -> None:
        if not self._alive:
            return
        self._check(int(self._dll.snowlink_engine_shutdown(self._handle)))

    def destroy(self) -> None:
        if not self._alive:
            return
        status = int(self._dll.snowlink_engine_destroy(self._handle))
        self._alive = False
        self._handle = 0
        if status != SNOWLINK_OK:
            raise NativeEngineError(status, "snowlink_engine_destroy failed")

    def start_capture(
        self,
        *,
        monitor_index: int = 0,
        width: int = 0,
        height: int = 0,
        target_fps: int = 30,
        backend: int = 0,
        display_id: int = 0,
    ) -> int:
        self._ensure_alive()
        cfg = _CaptureConfig(monitor_index, width, height, target_fps, backend, display_id)
        return self._check(
            int(self._dll.snowlink_engine_start_capture(self._handle, ctypes.byref(cfg))),
            allow_not_implemented=True,
        )

    def stop_capture(self) -> None:
        self._ensure_alive()
        self._check(int(self._dll.snowlink_engine_stop_capture(self._handle)))

    def start_stream(
        self,
        *,
        width: int = 1280,
        height: int = 720,
        target_fps: int = 30,
        bitrate_bps: int = 2_500_000,
    ) -> int:
        self._ensure_alive()
        cfg = _StreamConfig(width, height, target_fps, bitrate_bps)
        return self._check(
            int(self._dll.snowlink_engine_start_stream(self._handle, ctypes.byref(cfg))),
            allow_not_implemented=True,
        )

    def connect(
        self,
        *,
        bind_address: str,
        port_min: int = NATIVE_MEDIA_PORT_MIN,
        port_max: int = NATIVE_MEDIA_PORT_MAX,
        mtu: int = 1200,
        frame_queue_limit: int = 2,
        nack_packet_limit: int = 256,
    ) -> None:
        """Initialize native ICE/DTLS-SRTP transport; media stays in C++."""
        self._ensure_alive()
        cfg = _TransportConfig(
            bind_address.encode("utf-8"),
            port_min,
            port_max,
            mtu,
            frame_queue_limit,
            nack_packet_limit,
        )
        self._check(
            int(self._dll.snowlink_engine_connect_transport(self._handle, ctypes.byref(cfg)))
        )

    def create_offer(self) -> None:
        self._ensure_alive()
        self._check(int(self._dll.snowlink_engine_create_transport_offer(self._handle)))

    def local_description(self) -> dict[str, str] | None:
        """Return gathered SDP, or None while host ICE gathering is in progress."""
        self._ensure_alive()
        values: list[str] = []
        for name in ("snowlink_engine_get_local_sdp", "snowlink_engine_get_local_sdp_type"):
            fn = getattr(self._dll, name)
            required = int(fn(self._handle, None, 0))
            if required == 1:
                return None
            if required <= 0:
                self._check(required)
            buffer = ctypes.create_string_buffer(required)
            self._check(int(fn(self._handle, buffer, required)))
            values.append(buffer.value.decode("utf-8"))
        return {"sdp": values[0], "type": values[1]}

    def set_remote_description(self, *, sdp: str, sdp_type: str = "answer") -> None:
        self._ensure_alive()
        self._check(
            int(
                self._dll.snowlink_engine_set_remote_sdp(
                    self._handle, sdp.encode("utf-8"), sdp_type.encode("ascii")
                )
            )
        )

    def start_receiver(self, *, hwnd: int, bind_address: str = "") -> None:
        self._ensure_alive()
        cfg = _TransportConfig(
            bind_address.encode(),
            NATIVE_MEDIA_PORT_MIN,
            NATIVE_MEDIA_PORT_MAX,
            1200,
            2,
            256,
        )
        self._check(
            int(
                self._dll.snowlink_engine_start_receiver(self._handle, int(hwnd), ctypes.byref(cfg))
            )
        )

    def create_receiver_answer(self) -> None:
        self._check(int(self._dll.snowlink_engine_create_receiver_answer(self._handle)))

    def stop_receiver(self) -> None:
        self._check(int(self._dll.snowlink_engine_stop_receiver(self._handle)))

    def receiver_resize(self) -> None:
        self._check(int(self._dll.snowlink_engine_receiver_resize(self._handle)))

    def receiver_set_visible(self, visible: bool) -> None:
        self._check(int(self._dll.snowlink_engine_receiver_set_visible(self._handle, int(visible))))

    def send_input(
        self,
        *,
        kind: int,
        code: int = 0,
        down: bool = False,
        x: int = 0,
        y: int = 0,
        delta: int = 0,
        sequence: int = 0,
    ) -> None:
        event = _InputEvent(kind, code, int(down), 0, x, y, delta, sequence)
        # A channel which is still opening is not an authorization failure; UI
        # input is simply ignored until DTLS/SCTP is ready.
        status = int(self._dll.snowlink_engine_send_input(self._handle, ctypes.byref(event)))
        if status < 0:
            self._check(status)

    def set_remote_input_enabled(self, enabled: bool) -> None:
        self._ensure_alive()
        self._check(
            int(self._dll.snowlink_engine_set_remote_input_enabled(self._handle, int(enabled)))
        )

    def decoder_status(self) -> dict[str, Any]:
        required = int(self._dll.snowlink_engine_get_decoder_name(self._handle, None, 0))
        name = ctypes.create_string_buffer(max(required, 1))
        if required > 0:
            self._check(
                int(self._dll.snowlink_engine_get_decoder_name(self._handle, name, required))
            )
        hardware = ctypes.c_int32()
        width = ctypes.c_uint32()
        height = ctypes.c_uint32()
        fps = ctypes.c_double()
        self._check(
            int(
                self._dll.snowlink_engine_get_decoder_status(
                    self._handle,
                    ctypes.byref(hardware),
                    ctypes.byref(width),
                    ctypes.byref(height),
                    ctypes.byref(fps),
                )
            )
        )
        return {
            "decoder_name": name.value.decode(errors="replace"),
            "hardware_accelerated": bool(hardware.value),
            "decoded_width": width.value,
            "decoded_height": height.value,
            "decode_fps": fps.value,
        }

    def stop_stream(self) -> None:
        self._ensure_alive()
        self._check(int(self._dll.snowlink_engine_stop_stream(self._handle)))

    def set_target_fps(self, fps: int) -> None:
        self._ensure_alive()
        self._check(int(self._dll.snowlink_engine_set_target_fps(self._handle, int(fps))))

    def set_bitrate(self, bitrate_bps: int) -> None:
        self._ensure_alive()
        self._check(int(self._dll.snowlink_engine_set_bitrate(self._handle, int(bitrate_bps))))

    def set_resolution(self, width: int, height: int) -> None:
        self._ensure_alive()
        self._check(
            int(self._dll.snowlink_engine_set_resolution(self._handle, int(width), int(height)))
        )

    def request_keyframe(self) -> int:
        self._ensure_alive()
        return self._check(
            int(self._dll.snowlink_engine_request_keyframe(self._handle)),
            allow_not_implemented=True,
        )

    def set_capture_cursor_in_video(self, enabled: bool) -> int:
        self._ensure_alive()
        return self._check(
            int(self._dll.snowlink_engine_set_capture_cursor_in_video(self._handle, int(enabled)))
        )

    def get_capture_status(self) -> NativeCaptureStatus:
        self._ensure_alive()
        raw = _CaptureStatus()
        self._check(
            int(self._dll.snowlink_engine_get_capture_status(self._handle, ctypes.byref(raw)))
        )
        return NativeCaptureStatus(
            borderless_capture_available=bool(raw.borderless_capture_available),
            borderless_capture_granted=bool(raw.borderless_capture_granted),
            capture_border_active=bool(raw.capture_border_active),
            capture_cursor_in_video=bool(raw.capture_cursor_in_video),
            capture_active=bool(raw.capture_active),
            access_lost=bool(raw.access_lost),
            device_lost=bool(raw.device_lost),
            width=int(raw.width),
            height=int(raw.height),
        )

    def get_stats(self) -> NativeEngineStats:
        self._ensure_alive()
        raw = _EngineStats()
        self._check(int(self._dll.snowlink_engine_get_stats(self._handle, ctypes.byref(raw))))
        return NativeEngineStats(
            capture_fps=float(raw.capture_fps),
            encode_fps=float(raw.encode_fps),
            decode_fps=float(raw.decode_fps),
            render_fps=float(raw.render_fps),
            bitrate_bps=int(raw.bitrate_bps),
            frames_captured=int(raw.frames_captured),
            frames_encoded=int(raw.frames_encoded),
            frames_dropped=int(raw.frames_dropped),
            frames_decoded=int(raw.frames_decoded),
            capture_latency_ms=float(raw.capture_latency_ms),
            encode_latency_ms=float(raw.encode_latency_ms),
            decode_latency_ms=float(raw.decode_latency_ms),
            render_latency_ms=float(raw.render_latency_ms),
            network_rtt_ms=float(raw.network_rtt_ms),
            send_bitrate=float(raw.send_bitrate),
            packets_sent=int(raw.packets_sent),
            packets_dropped=int(raw.packets_dropped),
            transport_frames_dropped=int(raw.transport_frames_dropped),
            transport_errors=int(raw.transport_errors),
            transport_queue_depth=int(raw.transport_queue_depth),
            estimated_loss=float(raw.estimated_loss),
        )

    def state(self) -> int:
        self._ensure_alive()
        return int(self._dll.snowlink_engine_get_state(self._handle))

    def last_error(self) -> str:
        self._ensure_alive()
        raw = self._dll.snowlink_engine_last_error(self._handle)
        if not raw:
            return ""
        return raw.decode("utf-8", errors="replace")

    def _ensure_alive(self) -> None:
        if not self._alive:
            raise NativeEngineError(-5, "engine handle already destroyed")

    def __enter__(self) -> NativeEngine:
        self.initialize()
        return self

    def __exit__(self, *exc: object) -> None:
        try:
            self.shutdown()
        finally:
            self.destroy()
