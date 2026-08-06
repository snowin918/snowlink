"""Phase 1 screen-share session: DXcam → ScreenVideoTrack → HTTP signaling + host ICE.

Experiment-style HTTP signaling (no pairing). Use only on a private LAN.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from snowlink.media.capture_models import (
    DEFAULT_PRESET,
    CaptureConfiguration,
    PresetName,
    resolve_preset,
)
from snowlink.media.screen_capture import ScreenCaptureSession
from snowlink.media.video_track import ScreenVideoTrack
from snowlink.net.adapter_models import NetworkAdapter
from snowlink.net.adapter_selection import select_preferred_endpoint
from snowlink.net.tcp_diagnostics import validate_ipv4
from snowlink.platform_win.adapters import enumerate_adapters, is_windows
from snowlink.rtc.errors import WebRTCError, failure_for, format_failure_human, map_exception
from snowlink.rtc.models import TimeoutConfig
from snowlink.rtc.peer_connection import (
    assert_preferred_video_codec_available,
    create_peer_connection,
    prefer_video_codec,
    require_aiortc,
    wait_ice_connected,
    wait_ice_gathering_complete,
)
from snowlink.rtc.preview import RemoteVideoConsumer, run_preview_loop
from snowlink.rtc.session import validate_local_ip
from snowlink.rtc.signaling import SIGNALING_WARNING, SignalingClient, SignalingServer

logger = logging.getLogger(__name__)

DEFAULT_SIGNALING_PORT = 3847


@dataclass(frozen=True, slots=True)
class ScreenShareConfiguration:
    """Share-side configuration for Phase 1 screen streaming."""

    bind_ip: str
    signaling_port: int = DEFAULT_SIGNALING_PORT
    monitor: int = 0
    backend: Literal["dxgi", "winrt"] = "dxgi"
    preset: PresetName = "balanced"
    width: int = DEFAULT_PRESET.width
    height: int = DEFAULT_PRESET.height
    fps: int = DEFAULT_PRESET.fps
    allow_h264_fallback: bool = False
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)

    @classmethod
    def from_preset(
        cls,
        *,
        bind_ip: str,
        signaling_port: int = DEFAULT_SIGNALING_PORT,
        monitor: int = 0,
        backend: Literal["dxgi", "winrt"] = "dxgi",
        preset: str = "low",
        allow_h264_fallback: bool = False,
    ) -> ScreenShareConfiguration:
        resolved = resolve_preset(preset)
        return cls(
            bind_ip=bind_ip,
            signaling_port=signaling_port,
            monitor=monitor,
            backend=backend,
            preset=resolved.name,
            width=resolved.width,
            height=resolved.height,
            fps=resolved.fps,
            allow_h264_fallback=allow_h264_fallback,
        )

    def capture_config(self) -> CaptureConfiguration:
        return CaptureConfiguration(
            monitor=self.monitor,
            backend=self.backend,
            requested_fps=self.fps,
            requested_width=self.width,
            requested_height=self.height,
            duration_s=3600,
            show_preview=False,
            preset_name=self.preset,
        )


@dataclass(frozen=True, slots=True)
class ScreenViewConfiguration:
    """View-side configuration for Phase 1 screen streaming."""

    remote_ip: str
    signaling_port: int = DEFAULT_SIGNALING_PORT
    requested_source_ip: str | None = None
    preview: bool = True
    allow_h264_fallback: bool = False
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)


@dataclass(slots=True)
class ScreenSessionState:
    """Mutable status snapshot for UI / CLI."""

    role: Literal["share", "view"]
    phase: str = "idle"
    detail: str = ""
    bind_ip: str | None = None
    remote_ip: str | None = None
    port: int | None = None
    ice_state: str | None = None
    frames: int = 0
    error: str | None = None


StateCallback = Callable[[ScreenSessionState], None]


def _load_adapters() -> list[NetworkAdapter]:
    if is_windows():
        try:
            return list(enumerate_adapters())
        except Exception:
            return []
    return []


def _notify(cb: StateCallback | None, state: ScreenSessionState) -> None:
    if cb is None:
        return
    try:
        cb(state)
    except Exception:
        logger.exception("Screen session state callback failed")


async def run_screen_share(
    config: ScreenShareConfiguration,
    *,
    stop_event: asyncio.Event | None = None,
    on_state: StateCallback | None = None,
    capture_session: ScreenCaptureSession | None = None,
    grabber: Callable[[], Any] | None = None,
) -> ScreenSessionState:
    """Bind HTTP signaling, start DXcam, and answer viewer offers with screen video."""
    require_aiortc()
    from aiortc import RTCSessionDescription

    adapters = _load_adapters()
    validate_local_ip(config.bind_ip, adapters)
    stop = stop_event or asyncio.Event()
    state = ScreenSessionState(
        role="share",
        phase="starting",
        bind_ip=config.bind_ip,
        port=config.signaling_port,
        detail=SIGNALING_WARNING,
    )
    _notify(on_state, state)

    owns_capture = capture_session is None
    capture = capture_session
    track: ScreenVideoTrack | None = None
    pc: Any | None = None
    server: SignalingServer | None = None
    media_started = asyncio.Event()

    try:
        assert_preferred_video_codec_available(
            prefer="video/VP8",
            allow_h264_fallback=config.allow_h264_fallback,
        )

        if capture is None:
            capture = ScreenCaptureSession(
                config.capture_config(),
                grabber=grabber,
            )
            capture.start()

        track = ScreenVideoTrack(
            capture.slot,
            width=config.width,
            height=config.height,
            fps=config.fps,
            scale=True,
            session_epoch_ns=time.perf_counter_ns(),
        )

        async def handle_offer(payload: dict[str, Any]) -> dict[str, Any]:
            nonlocal pc
            if pc is not None:
                raise WebRTCError(
                    failure_for(
                        "VIEWER_SLOT_TAKEN",
                        "A viewer is already connected to this share session.",
                    )
                )
            pc = create_peer_connection()

            def _on_conn() -> None:
                if pc is not None and pc.connectionState in {
                    "failed",
                    "closed",
                    "disconnected",
                }:
                    stop.set()

            pc.on("connectionstatechange")(_on_conn)
            assert track is not None
            pc.addTrack(track)
            prefer_video_codec(
                pc,
                prefer="video/VP8",
                allow_h264_fallback=config.allow_h264_fallback,
            )
            offer = RTCSessionDescription(sdp=str(payload["sdp"]), type=str(payload["type"]))
            await pc.setRemoteDescription(offer)
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            await wait_ice_gathering_complete(pc, timeout_s=config.timeouts.ice_gathering_s)
            media_started.set()
            state.phase = "negotiating"
            state.detail = "Answered viewer offer; waiting for ICE"
            _notify(on_state, state)
            assert pc.localDescription is not None
            return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

        server = SignalingServer(
            bind_ip=config.bind_ip,
            port=config.signaling_port,
            offer_handler=handle_offer,
        )
        await server.start()
        state.phase = "waiting_for_viewer"
        state.detail = (
            f"Listening on http://{config.bind_ip}:{config.signaling_port}/ — "
            "waiting for viewer"
        )
        _notify(on_state, state)
        print(SIGNALING_WARNING)
        print(state.detail)

        while not stop.is_set() and not media_started.is_set():
            try:
                await asyncio.wait_for(media_started.wait(), timeout=0.5)
            except TimeoutError:
                continue

        if stop.is_set() and not media_started.is_set():
            state.phase = "stopped"
            state.detail = "Share stopped before a viewer connected"
            _notify(on_state, state)
            return state

        assert pc is not None
        await wait_ice_connected(pc, timeout_s=config.timeouts.ice_connection_s)
        state.phase = "sharing"
        state.ice_state = str(pc.iceConnectionState)
        state.detail = f"ICE {pc.iceConnectionState}; streaming screen"
        _notify(on_state, state)
        print(state.detail)

        while not stop.is_set():
            if pc.connectionState == "failed":
                raise WebRTCError(
                    failure_for(
                        "ICE_CONNECTION_FAILED",
                        "Peer connection failed during screen share.",
                        ice_state=str(pc.iceConnectionState),
                    )
                )
            if pc.connectionState in {"closed", "disconnected"}:
                break
            state.frames = track.frames_generated if track else 0
            state.ice_state = str(pc.iceConnectionState)
            _notify(on_state, state)
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.5)
            except TimeoutError:
                continue

        state.phase = "stopping"
        state.detail = "Stopping share"
        _notify(on_state, state)
    except asyncio.CancelledError:
        raise
    except WebRTCError as exc:
        state.phase = "failed"
        state.error = format_failure_human(exc.failure)
        state.detail = state.error
        _notify(on_state, state)
        print(state.error)
    except Exception as exc:
        failure = map_exception(exc)
        state.phase = "failed"
        state.error = format_failure_human(failure)
        state.detail = state.error
        _notify(on_state, state)
        print(state.error)
    finally:
        stop.set()
        if track is not None:
            track.stop()
        if pc is not None:
            try:
                await asyncio.wait_for(pc.close(), timeout=config.timeouts.shutdown_s)
            except Exception:
                pass
        if server is not None:
            await server.close()
        if owns_capture and capture is not None:
            capture.shutdown()
        if state.phase not in {"failed"}:
            state.phase = "stopped"
            state.detail = "Share stopped"
        _notify(on_state, state)

    return state


async def run_screen_view(
    config: ScreenViewConfiguration,
    *,
    stop_event: asyncio.Event | None = None,
    on_state: StateCallback | None = None,
    on_frame: Callable[[Any], None] | None = None,
    preview_window_name: str = "Snowlink View",
) -> ScreenSessionState:
    """Connect to a sharer, receive screen video, optionally preview / emit frames."""
    require_aiortc()
    from aiortc import RTCSessionDescription

    adapters = _load_adapters()
    try:
        validate_ipv4(config.remote_ip, kind="remote")
    except ValueError as exc:
        raise WebRTCError(
            failure_for(
                "INVALID_BIND_IP",
                f"Invalid remote IPv4 address: {config.remote_ip!r}",
                exception=exc,
            )
        ) from exc
    if config.requested_source_ip:
        validate_local_ip(config.requested_source_ip, adapters)

    stop = stop_event or asyncio.Event()
    state = ScreenSessionState(
        role="view",
        phase="connecting",
        remote_ip=config.remote_ip,
        port=config.signaling_port,
        detail=SIGNALING_WARNING,
    )
    _notify(on_state, state)

    pc: Any | None = None
    client: SignalingClient | None = None
    consumer: RemoteVideoConsumer | None = None
    preview_task: asyncio.Future[int] | None = None
    frame_task: asyncio.Task[None] | None = None
    preview_stop = asyncio.Event()

    try:
        client = SignalingClient(
            remote_ip=config.remote_ip,
            port=config.signaling_port,
            source_ip=config.requested_source_ip,
            connect_timeout_s=config.timeouts.signaling_connect_s,
            read_timeout_s=config.timeouts.offer_answer_s,
        )
        await client.start()
        state.phase = "negotiating"
        state.detail = f"Connected to signaling {config.remote_ip}:{config.signaling_port}"
        _notify(on_state, state)

        pc = create_peer_connection()
        track_ready = asyncio.Event()
        remote_track_box: list[Any] = []

        def _on_track(track: Any) -> None:
            if track.kind == "video":
                remote_track_box.append(track)
                track_ready.set()

        def _on_conn() -> None:
            if pc is not None and pc.connectionState in {
                "failed",
                "closed",
                "disconnected",
            }:
                stop.set()

        pc.on("track")(_on_track)
        pc.on("connectionstatechange")(_on_conn)
        pc.addTransceiver("video", direction="recvonly")
        prefer_video_codec(
            pc,
            prefer="video/VP8",
            allow_h264_fallback=config.allow_h264_fallback,
        )

        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        await wait_ice_gathering_complete(pc, timeout_s=config.timeouts.ice_gathering_s)
        assert pc.localDescription is not None
        answer = await asyncio.wait_for(
            client.exchange_offer(
                {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
            ),
            timeout=config.timeouts.offer_answer_s,
        )
        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
        )

        await wait_ice_connected(pc, timeout_s=config.timeouts.ice_connection_s)
        state.phase = "waiting_for_video"
        state.ice_state = str(pc.iceConnectionState)
        state.detail = f"ICE {pc.iceConnectionState}; waiting for video"
        _notify(on_state, state)

        try:
            await asyncio.wait_for(track_ready.wait(), timeout=config.timeouts.first_frame_s)
        except TimeoutError as exc:
            raise WebRTCError(
                failure_for(
                    "VIDEO_TRACK_NOT_RECEIVED",
                    "Remote video track was not received in time.",
                    ice_state=str(pc.iceConnectionState),
                )
            ) from exc

        consumer = RemoteVideoConsumer()
        await consumer.start(remote_track_box[0])

        deadline = time.perf_counter() + config.timeouts.first_frame_s
        while consumer.first_frame_at_ns is None:
            if time.perf_counter() > deadline:
                raise WebRTCError(
                    failure_for(
                        "VIDEO_FRAME_TIMEOUT",
                        "No remote video frames arrived within the first-frame timeout.",
                        ice_state=str(pc.iceConnectionState),
                    )
                )
            if stop.is_set():
                break
            await asyncio.sleep(0.05)

        state.phase = "viewing"
        state.detail = "Receiving remote screen"
        _notify(on_state, state)
        print(state.detail)

        loop = asyncio.get_running_loop()

        if on_frame is not None and consumer is not None:

            async def _emit_frames() -> None:
                assert consumer is not None
                assert on_frame is not None
                while not stop.is_set() and not consumer.slot.closed:
                    item = consumer.slot.take(clear=False)
                    if item is not None:
                        try:
                            on_frame(item.payload.bgr)
                        except Exception:
                            logger.exception("on_frame callback failed")
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=0.03)
                    except TimeoutError:
                        continue

            frame_task = asyncio.create_task(_emit_frames(), name="screen-view-frames")

        if config.preview and on_frame is None:
            preview_task = loop.run_in_executor(
                None,
                lambda: run_preview_loop(
                    consumer.slot,
                    window_name=preview_window_name,
                    stop_event=preview_stop,
                ),
            )

        while not stop.is_set():
            if pc.connectionState == "failed":
                raise WebRTCError(
                    failure_for(
                        "ICE_CONNECTION_FAILED",
                        "Peer connection failed while viewing.",
                        ice_state=str(pc.iceConnectionState),
                    )
                )
            if pc.connectionState in {"closed", "disconnected"}:
                break
            state.frames = consumer.frames_received if consumer else 0
            state.ice_state = str(pc.iceConnectionState)
            _notify(on_state, state)
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.5)
            except TimeoutError:
                continue

        preview_stop.set()
        state.phase = "stopping"
        state.detail = "Stopping view"
        _notify(on_state, state)
    except asyncio.CancelledError:
        raise
    except WebRTCError as exc:
        state.phase = "failed"
        state.error = format_failure_human(exc.failure)
        state.detail = state.error
        _notify(on_state, state)
        print(state.error)
    except Exception as exc:
        failure = map_exception(exc)
        state.phase = "failed"
        state.error = format_failure_human(failure)
        state.detail = state.error
        _notify(on_state, state)
        print(state.error)
    finally:
        stop.set()
        if frame_task is not None:
            frame_task.cancel()
            try:
                await frame_task
            except (asyncio.CancelledError, Exception):
                pass
        if consumer is not None:
            await consumer.stop()
        if preview_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(preview_task), timeout=2.0)
            except Exception:
                pass
        if pc is not None:
            try:
                await asyncio.wait_for(pc.close(), timeout=config.timeouts.shutdown_s)
            except Exception:
                pass
        if client is not None:
            await client.close()
        if state.phase not in {"failed"}:
            state.phase = "stopped"
            state.detail = "View stopped"
        _notify(on_state, state)

    return state


def preferred_lan_ipv4(adapters: list[NetworkAdapter] | None = None) -> str | None:
    """Return the auto-selected physical LAN IPv4, if any."""
    adapters = adapters if adapters is not None else _load_adapters()
    try:
        selected = select_preferred_endpoint(adapters)
    except Exception:
        return None
    if selected is None:
        return None
    return selected.ipv4
