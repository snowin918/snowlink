"""Screen-share session: DXcam (+ optional WASAPI loopback) → WS signaling + host ICE.

Phase 3: WebSocket signaling with 6-digit pairing + on-sharer approval.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from snowlink.constants import DEFAULT_SIGNALING_PORT
from snowlink.media.audio_models import (
    DEFAULT_FRAME_MS,
    TARGET_CHANNELS,
    TARGET_SAMPLE_RATE,
)
from snowlink.media.audio_track import AudioPlaybackControls, LoopbackAudioTrack, ShareAudioCapture
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
from snowlink.net.signaling_client import WsSignalingClient
from snowlink.net.signaling_server import WsSignalingServer
from snowlink.net.tcp_diagnostics import validate_ipv4
from snowlink.platform_win.adapters import enumerate_adapters, is_windows
from snowlink.rtc.audio_receiver import PlaybackWorker, RemoteAudioConsumer
from snowlink.rtc.av_sync import AvSyncController
from snowlink.rtc.errors import WebRTCError, failure_for, format_failure_human, map_exception
from snowlink.rtc.ice_policy import apply_ice_policy_to_local_description
from snowlink.rtc.models import (
    DEFAULT_AUDIO_GAIN,
    DEFAULT_BUFFER_TARGET_MS,
    TimeoutConfig,
)
from snowlink.rtc.peer_connection import (
    assert_opus_available,
    assert_preferred_video_codec_available,
    create_peer_connection,
    prefer_audio_codec,
    prefer_video_codec,
    preferred_host_ip_of,
    require_aiortc,
    wait_ice_connected,
    wait_ice_gathering_complete,
)
from snowlink.rtc.preview import RemoteVideoConsumer, run_preview_loop
from snowlink.rtc.session import validate_local_ip
from snowlink.security.pairing import PairingAuthority, PairingRequestInfo
from snowlink.security.secrets import generate_session_id
from snowlink.stats import SessionStats, StatsSampler

logger = logging.getLogger(__name__)

ApprovalHandler = Callable[[PairingRequestInfo], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class ScreenShareConfiguration:
    """Share-side configuration for screen (+ optional system audio) streaming."""

    bind_ip: str
    signaling_port: int = DEFAULT_SIGNALING_PORT
    monitor: int = 0
    backend: Literal["dxgi", "winrt"] = "dxgi"
    preset: PresetName = "balanced"
    width: int = DEFAULT_PRESET.width
    height: int = DEFAULT_PRESET.height
    fps: int = DEFAULT_PRESET.fps
    allow_h264_fallback: bool = False
    enable_audio: bool = True
    audio_capture_device: str = "default"
    audio_sample_rate: int = TARGET_SAMPLE_RATE
    audio_channels: int = TARGET_CHANNELS
    audio_frame_ms: int = DEFAULT_FRAME_MS
    auto_approve: bool = False
    approval_handler: ApprovalHandler | None = None
    pairing_code: str | None = None
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
        enable_audio: bool = True,
        audio_capture_device: str = "default",
        auto_approve: bool = False,
        approval_handler: ApprovalHandler | None = None,
        pairing_code: str | None = None,
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
            enable_audio=enable_audio,
            audio_capture_device=audio_capture_device,
            auto_approve=auto_approve,
            approval_handler=approval_handler,
            pairing_code=pairing_code,
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
    """View-side configuration for screen (+ optional system audio) streaming."""

    remote_ip: str
    pairing_code: str
    signaling_port: int = DEFAULT_SIGNALING_PORT
    requested_source_ip: str | None = None
    preview: bool = True
    allow_h264_fallback: bool = False
    enable_audio: bool = True
    playback: bool = True
    playback_device: str = "default"
    muted: bool = False
    gain: float = DEFAULT_AUDIO_GAIN
    buffer_target_ms: int = DEFAULT_BUFFER_TARGET_MS
    playback_controls: AudioPlaybackControls | None = None
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
    pairing_code: str | None = None
    pending_approval: PairingRequestInfo | None = None
    ice_state: str | None = None
    frames: int = 0
    audio_frames: int = 0
    audio_underruns: int = 0
    muted: bool = False
    error: str | None = None
    stats: SessionStats | None = None
    sharing_active: bool = False


StateCallback = Callable[[ScreenSessionState], None]


async def _wait_ice_recovery(
    pc: Any,
    *,
    stop: asyncio.Event,
    timeout_s: float = 10.0,
) -> bool:
    """Wait for ICE/connection to leave ``disconnected`` within *timeout_s*."""
    deadline = time.perf_counter() + timeout_s
    while not stop.is_set() and time.perf_counter() < deadline:
        conn = str(pc.connectionState)
        ice = str(pc.iceConnectionState)
        if conn in {"connected", "completed"} or ice in {"connected", "completed"}:
            return True
        if conn == "failed" or ice == "failed":
            return False
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.25)
        except TimeoutError:
            continue
    return False


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
    audio_track: Any | None = None,
    audio_capture: ShareAudioCapture | None = None,
) -> ScreenSessionState:
    """Bind WS signaling, start DXcam (+ optional loopback), offer after pairing."""
    require_aiortc()
    from aiortc import RTCSessionDescription

    adapters = _load_adapters()
    validate_local_ip(config.bind_ip, adapters)
    stop = stop_event or asyncio.Event()
    session_id = generate_session_id()
    pairing = (
        PairingAuthority(session_id=session_id, code=config.pairing_code)
        if config.pairing_code
        else PairingAuthority(session_id=session_id)
    )
    state = ScreenSessionState(
        role="share",
        phase="starting",
        bind_ip=config.bind_ip,
        port=config.signaling_port,
        pairing_code=pairing.code,
        detail="Starting share session…",
    )
    _notify(on_state, state)

    owns_capture = capture_session is None
    owns_audio = audio_capture is None and audio_track is None
    capture = capture_session
    track: ScreenVideoTrack | None = None
    a_track: Any | None = audio_track
    audio_src: ShareAudioCapture | None = audio_capture
    pc: Any | None = None
    server: WsSignalingServer | None = None
    sampler = StatsSampler(width=config.width, height=config.height)
    rtc_poll_counter = 0

    async def _default_approval(info: PairingRequestInfo) -> bool:
        state.phase = "awaiting_approval"
        state.pending_approval = info
        state.detail = f"Approve viewer from {info.remote_addr}?"
        _notify(on_state, state)
        if config.approval_handler is not None:
            return await config.approval_handler(info)
        # No UI handler: deny unless auto_approve (handled by server flag).
        return False

    try:
        assert_preferred_video_codec_available(
            prefer="video/VP8",
            allow_h264_fallback=config.allow_h264_fallback,
        )
        if config.enable_audio and a_track is None:
            assert_opus_available()

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

        if config.enable_audio and a_track is None:
            if audio_src is None:
                audio_src = ShareAudioCapture.start(
                    capture_device=config.audio_capture_device,
                    sample_rate=config.audio_sample_rate,
                    channels=config.audio_channels,
                    frame_ms=config.audio_frame_ms,
                )
            a_track = LoopbackAudioTrack(audio_src)

        async def offer_factory() -> dict[str, str]:
            nonlocal pc
            if pc is not None:
                raise WebRTCError(
                    failure_for(
                        "VIEWER_SLOT_TAKEN",
                        "A viewer is already connected to this share session.",
                    )
                )
            pc = create_peer_connection(preferred_host_ip=config.bind_ip)

            def _on_conn() -> None:
                if pc is not None and pc.connectionState in {
                    "failed",
                    "closed",
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
            if a_track is not None:
                pc.addTrack(a_track)
                prefer_audio_codec(pc)
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            await wait_ice_gathering_complete(pc, timeout_s=config.timeouts.ice_gathering_s)
            apply_ice_policy_to_local_description(
                pc, preferred_host_ip_of(pc) or config.bind_ip
            )
            state.phase = "negotiating"
            state.pending_approval = None
            state.detail = "Sending offer; waiting for viewer answer"
            _notify(on_state, state)
            assert pc.localDescription is not None
            return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

        server = WsSignalingServer(
            bind_ip=config.bind_ip,
            port=config.signaling_port,
            pairing=pairing,
            offer_factory=offer_factory,
            approval_handler=_default_approval,
            auto_approve=config.auto_approve,
        )
        await server.start()
        state.phase = "waiting_for_viewer"
        media_note = "screen+audio" if a_track is not None else "screen"
        state.pairing_code = pairing.code
        state.port = server.port
        state.detail = (
            f"Listening on ws://{config.bind_ip}:{server.port}/ws — "
            f"pairing code {pairing.code} ({media_note})"
        )
        _notify(on_state, state)
        logger.info(state.detail)

        answer: dict[str, str] | None = None
        while not stop.is_set() and answer is None:
            try:
                answer = await server.wait_answer(timeout_s=0.5)
            except TimeoutError:
                continue

        if stop.is_set() and answer is None:
            state.phase = "stopped"
            state.detail = "Share stopped before a viewer connected"
            _notify(on_state, state)
            return state

        assert pc is not None and answer is not None
        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
        )
        await wait_ice_connected(pc, timeout_s=config.timeouts.ice_connection_s)
        state.phase = "sharing"
        state.sharing_active = True
        state.ice_state = str(pc.iceConnectionState)
        state.detail = (
            f"ICE {pc.iceConnectionState}; streaming "
            f"{'screen+audio' if a_track is not None else 'screen'}"
        )
        _notify(on_state, state)
        logger.info(state.detail)

        while not stop.is_set():
            if pc.connectionState == "failed":
                raise WebRTCError(
                    failure_for(
                        "ICE_CONNECTION_FAILED",
                        "Peer connection failed during screen share.",
                        ice_state=str(pc.iceConnectionState),
                    )
                )
            if pc.connectionState == "closed":
                break
            if pc.connectionState == "disconnected":
                state.phase = "reconnecting"
                state.detail = "Peer briefly disconnected; waiting to recover…"
                _notify(on_state, state)
                recovered = await _wait_ice_recovery(
                    pc, stop=stop, timeout_s=min(10.0, config.timeouts.ice_connection_s)
                )
                if not recovered:
                    raise WebRTCError(
                        failure_for(
                            "ICE_CONNECTION_FAILED",
                            "Peer did not recover after disconnect (~10s).",
                            ice_state=str(pc.iceConnectionState),
                        )
                    )
                state.phase = "sharing"
                state.detail = f"ICE recovered ({pc.iceConnectionState})"
                _notify(on_state, state)

            # Capture hotplug / worker failure
            if capture is not None:
                unexpected = getattr(capture, "_worker_stats", None)
                err = getattr(unexpected, "unexpected_error", None) if unexpected else None
                if err is not None:
                    raise WebRTCError(
                        failure_for(
                            "CAPTURE_FAILED",
                            "Screen capture failed (monitor disconnect or device error). "
                            "Stop and restart sharing after reconnecting the display.",
                            likely_cause=str(getattr(err, "message", err)),
                        )
                    )

            if audio_src is not None and audio_src.capture is not None:
                audio_fatal = audio_src.capture.fatal_error
                if audio_fatal is not None:
                    fatal_code = getattr(audio_fatal, "code", "") or ""
                    use_device_changed = fatal_code in {
                        "DEVICE_DISCONNECTED",
                        "AUDIO_DEVICE_CHANGED",
                    }
                    raise WebRTCError(
                        failure_for(
                            "AUDIO_DEVICE_CHANGED"
                            if use_device_changed
                            else "CAPTURE_FAILED",
                            "System-audio loopback capture failed. "
                            "Stop sharing, re-select the loopback device matching "
                            "your active Windows output, then Start Sharing again.",
                            likely_cause=str(
                                getattr(audio_fatal, "message", audio_fatal)
                            ),
                        )
                    )

            # Selected LAN IP disappeared (VPN route / adapter change) → fail
            if rtc_poll_counter % 8 == 0:
                adapters_now = _load_adapters()
                if adapters_now:
                    try:
                        find_endpoint = __import__(
                            "snowlink.net.adapter_selection",
                            fromlist=["find_endpoint_by_ip"],
                        ).find_endpoint_by_ip
                        find_endpoint(adapters_now, config.bind_ip)
                    except ValueError as exc:
                        raise WebRTCError(
                            failure_for(
                                "IP_NOT_ASSIGNED",
                                f"Selected IP {config.bind_ip} is no longer assigned "
                                "(VPN/route or adapter change). Stop sharing, re-select "
                                "a physical LAN adapter, and see docs/vpn-lan-access.md.",
                                exception=exc,
                                likely_cause=(
                                    "The bind address disappeared from local adapters "
                                    "(common after VPN reconnect or NIC disable)."
                                ),
                                suggested_next_step=(
                                    "Enable VPN Allow LAN / split-tunnel if needed, "
                                    "refresh adapters on Share, pick the physical LAN "
                                    "IPv4, then Start Sharing again."
                                ),
                            )
                        ) from exc

            state.frames = track.frames_generated if track else 0
            if a_track is not None:
                state.audio_frames = int(getattr(a_track, "frames_generated", 0) or 0)
            state.ice_state = str(pc.iceConnectionState)
            dropped = 0
            if track is not None:
                dropped = int(getattr(track, "stale_drops", 0) or 0)
                if capture is not None:
                    dropped += int(getattr(capture.slot, "overwritten_count", 0) or 0)
            rtc_poll_counter += 1
            if rtc_poll_counter % 4 == 0:
                try:
                    report = await pc.getStats()
                    sampler.apply_rtc_report(report)
                except Exception:
                    pass
            peak = None
            if a_track is not None:
                peak = float(getattr(a_track, "peak_level", 0.0) or 0.0)
            if (
                a_track is not None
                and state.phase == "sharing"
                and state.audio_frames > 25
                and (peak or 0.0) < 1e-4
            ):
                state.detail = (
                    "Sharing screen+audio but loopback is silent — select the "
                    "loopback for the active Windows output (see ACTIVE OUTPUT) "
                    "and play non-DRM audio on that device"
                )
            state.stats = sampler.observe_local(
                video_frames=state.frames,
                dropped_video_frames=dropped,
                audio_underruns=0,
                ice_state=state.ice_state,
                role="share",
                audio_peak=peak,
            )
            _notify(on_state, state)
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.5)
            except TimeoutError:
                continue

        state.phase = "stopping"
        state.sharing_active = False
        state.detail = "Stopping share"
        _notify(on_state, state)
    except asyncio.CancelledError:
        raise
    except WebRTCError as exc:
        state.phase = "failed"
        state.error = format_failure_human(exc.failure)
        state.detail = state.error
        _notify(on_state, state)
        logger.info(state.error)
    except Exception as exc:
        failure = map_exception(exc)
        state.phase = "failed"
        state.error = format_failure_human(failure)
        state.detail = state.error
        _notify(on_state, state)
        logger.info(state.error)
    finally:
        stop.set()
        if track is not None:
            track.stop()
        if a_track is not None:
            try:
                a_track.stop()
            except Exception:
                pass
        if pc is not None:
            try:
                await asyncio.wait_for(pc.close(), timeout=config.timeouts.shutdown_s)
            except Exception:
                pass
        if server is not None:
            await server.close()
        if owns_capture and capture is not None:
            capture.shutdown()
        if owns_audio and audio_src is not None:
            audio_src.shutdown()
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
    """Connect to a sharer, pair, receive screen video (+ optional system audio)."""
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
    controls = config.playback_controls or AudioPlaybackControls(
        muted=config.muted,
        gain=config.gain,
    )
    state = ScreenSessionState(
        role="view",
        phase="connecting",
        remote_ip=config.remote_ip,
        port=config.signaling_port,
        pairing_code=config.pairing_code,
        muted=controls.muted,
        detail=f"Connecting to ws://{config.remote_ip}:{config.signaling_port}/ws",
    )
    _notify(on_state, state)

    pc: Any | None = None
    client: WsSignalingClient | None = None
    consumer: RemoteVideoConsumer | None = None
    audio_consumer: RemoteAudioConsumer | None = None
    playback_worker: PlaybackWorker | None = None
    preview_task: asyncio.Future[int] | None = None
    frame_task: asyncio.Task[None] | None = None
    preview_stop = asyncio.Event()
    sampler = StatsSampler()
    rtc_poll_counter = 0
    av_sync = AvSyncController()

    try:
        if config.enable_audio:
            assert_opus_available()

        client = WsSignalingClient(
            remote_ip=config.remote_ip,
            port=config.signaling_port,
            pairing_code=config.pairing_code,
            source_ip=config.requested_source_ip,
            connect_timeout_s=config.timeouts.signaling_connect_s,
        )
        state.phase = "pairing"
        state.detail = "Connecting; pairing with backoff on transient failures…"
        _notify(on_state, state)

        def _on_signaling_attempt(attempt: int, err: BaseException | None) -> None:
            if err is None and attempt > 1:
                state.phase = "reconnecting"
                state.detail = f"Retrying signaling connect (attempt {attempt})…"
                _notify(on_state, state)
            elif err is not None:
                state.phase = "reconnecting"
                state.detail = (
                    f"Signaling attempt {attempt} failed; backing off before retry…"
                )
                _notify(on_state, state)

        await client.connect_and_pair_with_retry(
            max_attempts=5,
            stop_event=stop,
            on_attempt=_on_signaling_attempt,
        )

        state.phase = "negotiating"
        state.detail = "Paired; waiting for sharer offer"
        _notify(on_state, state)

        offer = await asyncio.wait_for(
            client.wait_offer(),
            timeout=config.timeouts.offer_answer_s,
        )

        pc = create_peer_connection(preferred_host_ip=config.requested_source_ip)
        track_ready = asyncio.Event()
        audio_ready = asyncio.Event()
        remote_track_box: list[Any] = []
        remote_audio_box: list[Any] = []

        def _on_track(track: Any) -> None:
            if track.kind == "video":
                remote_track_box.append(track)
                track_ready.set()
            elif track.kind == "audio" and config.enable_audio:
                remote_audio_box.append(track)
                audio_ready.set()

        def _on_conn() -> None:
            if pc is not None and pc.connectionState in {
                "failed",
                "closed",
            }:
                stop.set()

        pc.on("track")(_on_track)
        pc.on("connectionstatechange")(_on_conn)

        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=offer["sdp"], type=offer["type"])
        )
        prefer_video_codec(
            pc,
            prefer="video/VP8",
            allow_h264_fallback=config.allow_h264_fallback,
        )
        if config.enable_audio:
            prefer_audio_codec(pc)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        await wait_ice_gathering_complete(pc, timeout_s=config.timeouts.ice_gathering_s)
        apply_ice_policy_to_local_description(
            pc, preferred_host_ip_of(pc) or config.requested_source_ip
        )
        assert pc.localDescription is not None
        await client.send_answer(
            sdp=pc.localDescription.sdp,
            sdp_type=pc.localDescription.type,
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

        if config.enable_audio:
            if not remote_audio_box:
                try:
                    await asyncio.wait_for(audio_ready.wait(), timeout=2.0)
                except TimeoutError:
                    pass
            if remote_audio_box:
                audio_consumer = RemoteAudioConsumer(
                    sample_rate=TARGET_SAMPLE_RATE,
                    channels=TARGET_CHANNELS,
                    frame_ms=DEFAULT_FRAME_MS,
                    buffer_target_ms=config.buffer_target_ms,
                )
                await audio_consumer.start(remote_audio_box[0])
                if config.playback:
                    from snowlink.platform_win.audio_endpoints import resolve_playback_device

                    endpoint = resolve_playback_device(config.playback_device)
                    logger.info(
                        "Opening WASAPI playback: index=%s name=%r selector=%r",
                        endpoint.index,
                        endpoint.name,
                        config.playback_device,
                    )
                    logger.info(
                        f"Playback device: [{endpoint.index}] {endpoint.name} "
                        f"(selector={config.playback_device!r})"
                    )
                    playback_worker = PlaybackWorker(
                        audio_consumer.ring,
                        sample_rate=TARGET_SAMPLE_RATE,
                        channels=TARGET_CHANNELS,
                        frame_ms=DEFAULT_FRAME_MS,
                        gain=controls.gain,
                        muted=controls.muted,
                        enabled=True,
                        controls=controls,
                        playback_endpoint=endpoint,
                        prebuffer_ms=float(config.buffer_target_ms),
                    )
                    playback_worker.start()
            else:
                state.detail = "Receiving remote screen (no remote audio track)"

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
        if audio_consumer is not None:
            state.detail = "Receiving remote screen + system audio"
        else:
            state.detail = "Receiving remote screen"
        _notify(on_state, state)
        logger.info(state.detail)

        loop = asyncio.get_running_loop()

        if on_frame is not None and consumer is not None:

            async def _emit_frames() -> None:
                assert consumer is not None
                assert on_frame is not None
                last_seq = -1
                while not stop.is_set() and not consumer.slot.closed:
                    item = consumer.slot.take(clear=False)
                    if item is not None and int(item.sequence) != last_seq:
                        frame = item.payload
                        pts_ms = getattr(frame, "pts_ms", None)
                        if av_sync.should_paint_video(pts_ms):
                            last_seq = int(item.sequence)
                            try:
                                on_frame(frame.bgr)
                            except Exception:
                                logger.exception("on_frame callback failed")
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=0.033)
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
            if pc.connectionState == "closed":
                break
            if pc.connectionState == "disconnected":
                state.phase = "reconnecting"
                state.detail = "Connection interrupted; attempting recovery…"
                _notify(on_state, state)
                recovered = await _wait_ice_recovery(
                    pc, stop=stop, timeout_s=min(10.0, config.timeouts.ice_connection_s)
                )
                if not recovered:
                    raise WebRTCError(
                        failure_for(
                            "ICE_CONNECTION_FAILED",
                            "View session did not recover after disconnect (~10s). "
                            "Disconnect, confirm the sharer is still sharing, then Connect again.",
                            ice_state=str(pc.iceConnectionState),
                        )
                    )
                state.phase = "viewing"
                state.detail = f"ICE recovered ({pc.iceConnectionState})"
                _notify(on_state, state)

            # Signaling WS drop after media is up: keep viewing on ICE; surface status.
            if (
                client is not None
                and not client.is_connected
                and state.phase == "viewing"
                and pc.connectionState in {"connected", "completed"}
            ):
                state.detail = (
                    "Signaling WebSocket closed; media still flowing over ICE. "
                    "If video stalls, Disconnect and Connect again."
                )
                _notify(on_state, state)

            if audio_consumer is not None and audio_consumer.fatal_error is not None:
                raise audio_consumer.fatal_error
            if playback_worker is not None and playback_worker.fatal_error is not None:
                raise WebRTCError(
                    failure_for(
                        "PLAYBACK_OPEN_FAILED",
                        "Remote audio playback failed. Check the WASAPI playback "
                        "device, unmute, and retry (or disable Play remote system audio).",
                        exception=playback_worker.fatal_error,
                    )
                )

            state.frames = consumer.frames_received if consumer else 0
            if audio_consumer is not None:
                state.audio_frames = audio_consumer.frames_received
            if playback_worker is not None:
                state.audio_underruns = playback_worker.underruns
                # Prefer real playback clock over received-frame estimates.
                played = int(playback_worker.samples_played)
                if played > 0:
                    av_sync.observe_audio_samples(
                        samples=played,
                        sample_rate=TARGET_SAMPLE_RATE,
                    )
                # Treat audio as healthy once we have played data with a
                # reasonable underrun ratio (not ~1 underrun per frame).
                frames_est = max(
                    1,
                    played // max(1, int(TARGET_SAMPLE_RATE * DEFAULT_FRAME_MS / 1000)),
                )
                healthy = played > 0 and state.audio_underruns < (frames_est * 0.5)
                if av_sync.av_skew_ms is not None and abs(av_sync.av_skew_ms) > 2000.0:
                    # Broken / uncalibrated PTS — don't freeze video; AvSync
                    # also re-latches, but keep the healthy flag off until
                    # skew settles again.
                    healthy = False
                av_sync.set_audio_healthy(healthy)
            elif audio_consumer is not None and state.audio_frames > 0:
                # No playback sink — do not drive sync drops from receive-only clock.
                av_sync.set_audio_healthy(False)
            state.muted = controls.muted
            state.ice_state = str(pc.iceConnectionState)

            # Keep the status line honest: track present ≠ audible audio.
            if audio_consumer is not None and state.phase == "viewing":
                peak = float(getattr(audio_consumer, "peak_level", 0.0) or 0.0)
                if playback_worker is not None:
                    peak = max(peak, float(getattr(playback_worker, "peak_level", 0.0) or 0.0))
                if controls.muted:
                    state.detail = "Receiving remote screen (viewer muted)"
                elif state.audio_frames < 5:
                    state.detail = (
                        "Receiving remote screen; waiting for remote audio frames…"
                    )
                elif peak < 1e-4:
                    state.detail = (
                        "Remote audio is silent — on the sharer, pick the loopback "
                        "for the active Windows output and play non-DRM audio"
                    )
                elif playback_worker is not None and playback_worker.samples_played == 0:
                    state.detail = (
                        "Remote audio buffered; starting WASAPI playback…"
                    )
                else:
                    state.detail = "Receiving remote screen + system audio"

            dropped = 0
            if consumer is not None:
                dropped = int(getattr(consumer.slot, "overwritten_count", 0) or 0)
            dropped += int(av_sync.dropped_for_sync)
            rtc_poll_counter += 1
            if rtc_poll_counter % 4 == 0:
                try:
                    report = await pc.getStats()
                    sampler.apply_rtc_report(report)
                except Exception:
                    pass
                if audio_consumer is not None:
                    peak = float(getattr(audio_consumer, "peak_level", 0.0) or 0.0)
                    if playback_worker is not None:
                        peak = max(
                            peak, float(getattr(playback_worker, "peak_level", 0.0) or 0.0)
                        )
                    logger.info(
                        "view audio: frames=%s peak=%.4f underruns=%s played=%s muted=%s",
                        state.audio_frames,
                        peak,
                        state.audio_underruns,
                        getattr(playback_worker, "samples_played", 0)
                        if playback_worker is not None
                        else 0,
                        controls.muted,
                    )
            state.stats = sampler.observe_local(
                video_frames=state.frames,
                dropped_video_frames=dropped,
                audio_underruns=state.audio_underruns,
                ice_state=state.ice_state,
                role="view",
                av_skew_ms=av_sync.av_skew_ms,
                audio_peak=(
                    max(
                        float(getattr(audio_consumer, "peak_level", 0.0) or 0.0),
                        float(getattr(playback_worker, "peak_level", 0.0) or 0.0),
                    )
                    if audio_consumer is not None or playback_worker is not None
                    else None
                ),
            )
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
        logger.info(state.error)
    except Exception as exc:
        failure = map_exception(exc)
        state.phase = "failed"
        state.error = format_failure_human(failure)
        state.detail = state.error
        _notify(on_state, state)
        logger.info(state.error)
    finally:
        stop.set()
        if frame_task is not None:
            frame_task.cancel()
            try:
                await frame_task
            except (asyncio.CancelledError, Exception):
                pass
        if playback_worker is not None:
            playback_worker.stop()
        if audio_consumer is not None:
            await audio_consumer.stop()
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
