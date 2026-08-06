"""Send/receive session orchestration for Experiment E."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from snowlink.net.adapter_models import NetworkAdapter
from snowlink.net.tcp_diagnostics import resolve_local_endpoint, validate_ipv4
from snowlink.platform_win.adapters import enumerate_adapters, is_windows
from snowlink.rtc.errors import WebRTCError, failure_for, format_failure_human, map_exception
from snowlink.rtc.ice_diagnostics import (
    candidate_from_aiortc,
    enrich_candidate,
    mismatch_warning,
    parse_candidate_sdp,
    selected_matches_requested_ip,
)
from snowlink.rtc.models import (
    ExperimentEConfiguration,
    ExperimentEResult,
    IceCandidateInfo,
)
from snowlink.rtc.peer_connection import (
    assert_preferred_video_codec_available,
    collect_local_candidate_strings,
    create_peer_connection,
    list_video_codecs,
    prefer_video_codec,
    require_aiortc,
    wait_ice_connected,
    wait_ice_gathering_complete,
)
from snowlink.rtc.preview import RemoteVideoConsumer, run_preview_loop
from snowlink.rtc.signaling import SIGNALING_WARNING, SignalingClient, SignalingServer
from snowlink.rtc.synthetic_video import SyntheticVideoTrack
from snowlink.rtc.webrtc_metrics import (
    InterArrivalTracker,
    ProcessResourceSampler,
    SequenceTracker,
    estimate_clock_offset_ms,
    fps_from_count,
    parse_rtc_stats_report,
)

logger = logging.getLogger(__name__)


def _load_adapters() -> list[NetworkAdapter]:
    if is_windows():
        try:
            return list(enumerate_adapters())
        except Exception:
            return []
    return []


def validate_local_ip(ip: str, adapters: Sequence[NetworkAdapter] | None = None) -> None:
    """Validate *ip* is a dotted IPv4 assigned to a local adapter."""
    adapters = list(adapters) if adapters is not None else _load_adapters()
    try:
        validate_ipv4(ip, kind="local")
    except ValueError as exc:
        raise WebRTCError(
            failure_for("INVALID_BIND_IP", f"Invalid IPv4 address: {ip!r}", exception=exc)
        ) from exc
    try:
        resolve_local_endpoint(adapters, ip)
    except ValueError as exc:
        # Same-machine loopback experiments are allowed even when adapter
        # enumeration is unavailable (e.g. non-Windows unit hosts).
        if ip == "127.0.0.1":
            return
        code = str(exc.args[0]) if exc.args else ""
        if code == "INVALID_LOCAL_IP":
            raise WebRTCError(
                failure_for("INVALID_BIND_IP", f"Invalid IPv4 address: {ip!r}", exception=exc)
            ) from exc
        raise WebRTCError(
            failure_for(
                "IP_NOT_ASSIGNED",
                f"IPv4 address is not assigned to a local adapter: {ip}",
                exception=exc,
            )
        ) from exc


def _peer_states(pc: Any) -> tuple[str | None, str | None, str | None]:
    return (
        str(getattr(pc, "signalingState", None)),
        str(getattr(pc, "iceConnectionState", None)),
        str(getattr(pc, "connectionState", None)),
    )


def _failure_with_states(code: str, message: str, pc: Any | None) -> WebRTCError:
    if pc is None:
        return WebRTCError(failure_for(code, message))
    sig, ice, peer = _peer_states(pc)
    return WebRTCError(
        failure_for(
            code,
            message,
            signaling_state=sig,
            ice_state=ice,
            peer_state=peer,
        )
    )


def _candidates_from_sdp(
    sdp_lines: list[str],
    adapters: Sequence[NetworkAdapter],
) -> list[IceCandidateInfo]:
    out: list[IceCandidateInfo] = []
    for line in sdp_lines:
        info = parse_candidate_sdp(line)
        enrich_candidate(info, adapters)
        out.append(info)
    return out


def _apply_stats_to_result(
    result: ExperimentEResult,
    parsed: Any,
    *,
    adapters: Sequence[NetworkAdapter],
) -> None:
    net = parsed.network
    for attr in (
        "bytes_sent",
        "bytes_received",
        "packets_sent",
        "packets_received",
        "packets_lost",
        "jitter_ms",
        "current_rtt_ms",
        "estimated_bitrate_bps",
        "remote_inbound_packets_lost",
    ):
        value = getattr(net, attr, None)
        if value is not None:
            setattr(result.network, attr, value)

    for attr in (
        "frames_encoded",
        "frames_sent",
        "frames_decoded",
        "frames_dropped",
        "key_frames",
        "width",
        "height",
        "codec",
        "codec_payload_type",
    ):
        value = getattr(parsed.video, attr, None)
        if value is not None:
            setattr(result.video, attr, value)

    by_id: dict[str, Any] = {}
    for item in parsed.raw_candidates:
        item_id = getattr(item, "id", None)
        if item_id is None and isinstance(item, dict):
            item_id = item.get("id")
        if item_id:
            by_id[str(item_id)] = item

    if parsed.local_candidate_id and parsed.local_candidate_id in by_id:
        result.connection.selected_local_candidate = candidate_from_aiortc(
            by_id[parsed.local_candidate_id],
            adapters,
        )
    if parsed.remote_candidate_id and parsed.remote_candidate_id in by_id:
        result.connection.selected_remote_candidate = candidate_from_aiortc(
            by_id[parsed.remote_candidate_id],
            adapters,
        )


async def _poll_stats_loop(
    pc: Any,
    result: ExperimentEResult,
    *,
    adapters: Sequence[NetworkAdapter],
    stop_event: asyncio.Event,
    sampler: ProcessResourceSampler,
    interval_s: float = 1.0,
) -> None:
    while not stop_event.is_set():
        sampler.sample()
        try:
            report = await pc.getStats()
            parsed = parse_rtc_stats_report(report)
            _apply_stats_to_result(result, parsed, adapters=adapters)
        except Exception:
            logger.debug("getStats failed", exc_info=True)
        sig, ice, peer = _peer_states(pc)
        result.connection.signaling_state = sig
        result.connection.ice_state = ice
        result.connection.peer_state = peer
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
            break
        except TimeoutError:
            continue


def _finalize_candidate_match(result: ExperimentEResult, requested_ip: str | None) -> None:
    selected = result.connection.selected_local_candidate
    match = selected_matches_requested_ip(selected, requested_ip)
    result.connection.candidate_matches_requested_lan_ip = match
    warning = mismatch_warning(selected, requested_ip)
    if warning:
        result.connection.warnings.append(warning)
        if warning not in result.warnings:
            result.warnings.append(warning)
        result.errors.append(
            failure_for(
                "ICE_SELECTED_WRONG_INTERFACE",
                warning,
                ice_state=result.connection.ice_state,
                peer_state=result.connection.peer_state,
                signaling_state=result.connection.signaling_state,
            ).to_dict()
        )


async def run_sender(config: ExperimentEConfiguration) -> ExperimentEResult:
    """Run the Experiment E sender (signaling + synthetic VP8 track)."""
    require_aiortc()
    from aiortc import RTCSessionDescription

    adapters = _load_adapters()
    if not config.bind_ip:
        raise WebRTCError(failure_for("INVALID_BIND_IP", "--bind-ip is required for send."))
    validate_local_ip(config.bind_ip, adapters)

    result = ExperimentEResult(
        role="sender",
        session_name=config.session_name,
        configuration=config,
        timestamp=datetime.now(UTC).isoformat(),
        signaling_warning=SIGNALING_WARNING,
    )
    result.available_codecs = list_video_codecs()
    print(SIGNALING_WARNING)
    print("Available video codecs:")
    for codec in result.available_codecs:
        print(f"  - {codec.mime_type}")

    sampler = ProcessResourceSampler()
    track = SyntheticVideoTrack(width=config.width, height=config.height, fps=config.fps)
    pc: Any | None = None
    server: SignalingServer | None = None
    stop_event = asyncio.Event()
    stats_task: asyncio.Task[None] | None = None
    media_started = asyncio.Event()
    selected_codec = "VP8"

    async def handle_offer(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal pc, stats_task, selected_codec
        pc = create_peer_connection()

        def _on_conn() -> None:
            if pc is not None and pc.connectionState in {"failed", "closed", "disconnected"}:
                stop_event.set()

        pc.on("connectionstatechange")(_on_conn)

        pc.addTrack(track)
        selected_codec = prefer_video_codec(
            pc,
            prefer="video/VP8",
            allow_h264_fallback=config.allow_h264_fallback,
        )
        offer = RTCSessionDescription(sdp=str(payload["sdp"]), type=str(payload["type"]))
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        await wait_ice_gathering_complete(pc, timeout_s=config.timeouts.ice_gathering_s)

        result.connection.local_candidates = _candidates_from_sdp(
            collect_local_candidate_strings(pc),
            adapters,
        )
        result.video.codec = selected_codec
        stats_task = asyncio.create_task(
            _poll_stats_loop(
                pc,
                result,
                adapters=adapters,
                stop_event=stop_event,
                sampler=sampler,
            ),
            name="sender-stats",
        )
        media_started.set()
        assert pc.localDescription is not None
        return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

    try:
        # Fail fast if VP8 is missing before accepting connections.
        assert_preferred_video_codec_available(
            prefer="video/VP8",
            allow_h264_fallback=config.allow_h264_fallback,
        )

        server = SignalingServer(
            bind_ip=config.bind_ip,
            port=config.signaling_port,
            offer_handler=handle_offer,
        )
        await server.start()
        print(f"Signaling listening on http://{config.bind_ip}:{config.signaling_port}/")
        print(f"Waiting for receiver offer (duration={config.duration_s}s, Ctrl+C to stop)...")

        try:
            await asyncio.wait_for(media_started.wait(), timeout=config.duration_s)
        except TimeoutError as exc:
            raise WebRTCError(
                failure_for(
                    "SIGNALING_TIMEOUT",
                    "No receiver connected before the sender duration elapsed.",
                    exception=exc,
                )
            ) from exc

        assert pc is not None
        await wait_ice_connected(pc, timeout_s=config.timeouts.ice_connection_s)
        print(f"ICE connected (state={pc.iceConnectionState}). Streaming synthetic video...")

        start = time.perf_counter()
        while not stop_event.is_set():
            if time.perf_counter() - start >= config.duration_s:
                break
            if pc.connectionState == "failed":
                raise _failure_with_states(
                    "ICE_CONNECTION_FAILED",
                    "Peer connection failed during media.",
                    pc,
                )
            if pc.connectionState in {"closed", "disconnected"}:
                break
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=0.5)
            except TimeoutError:
                continue

        result.success = pc.iceConnectionState in {"connected", "completed"} or (
            track.frames_generated > 0 and pc.connectionState != "failed"
        )
    except asyncio.CancelledError:
        raise
    except WebRTCError as exc:
        result.errors.append(exc.failure.to_dict())
        result.success = False
        print(format_failure_human(exc.failure))
    except Exception as exc:
        failure = map_exception(exc)
        result.errors.append(failure.to_dict())
        result.success = False
        print(format_failure_human(failure))
    finally:
        stop_event.set()
        track.stop()
        if stats_task is not None:
            stats_task.cancel()
            try:
                await stats_task
            except (asyncio.CancelledError, Exception):
                pass
        if pc is not None:
            sig, ice, peer = _peer_states(pc)
            result.connection.signaling_state = sig
            result.connection.ice_state = ice
            result.connection.peer_state = peer
            try:
                report = await pc.getStats()
                _apply_stats_to_result(
                    result, parse_rtc_stats_report(report), adapters=adapters
                )
            except Exception:
                pass
            try:
                await asyncio.wait_for(pc.close(), timeout=config.timeouts.shutdown_s)
            except Exception:
                pass
        if server is not None:
            await server.close()

        result.video.frames_generated = track.frames_generated
        result.video.frames_skipped_by_schedule = track.frames_skipped
        result.video.requested_fps = float(config.fps)
        result.video.width = config.width
        result.video.height = config.height
        result.video.codec = result.video.codec or selected_codec
        if track.frames_generated > 0:
            result.video.actual_generated_fps = fps_from_count(
                track.frames_generated,
                max(config.duration_s, 0.001),
            )
        result.resources = sampler.finalize()
        _finalize_candidate_match(result, config.bind_ip)

    return result


async def run_receiver(config: ExperimentEConfiguration) -> ExperimentEResult:
    """Run the Experiment E receiver (connect to sender signaling + render)."""
    require_aiortc()
    from aiortc import RTCSessionDescription

    adapters = _load_adapters()
    if not config.remote_ip:
        raise WebRTCError(
            failure_for("INVALID_BIND_IP", "--remote-ip is required for receive.")
        )
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

    result = ExperimentEResult(
        role="receiver",
        session_name=config.session_name,
        configuration=config,
        timestamp=datetime.now(UTC).isoformat(),
        signaling_warning=SIGNALING_WARNING,
    )
    result.available_codecs = list_video_codecs()
    print(SIGNALING_WARNING)
    print("Available video codecs:")
    for codec in result.available_codecs:
        print(f"  - {codec.mime_type}")

    sampler = ProcessResourceSampler()
    pc: Any | None = None
    client: SignalingClient | None = None
    consumer: RemoteVideoConsumer | None = None
    stop_event = asyncio.Event()
    stats_task: asyncio.Task[None] | None = None
    preview_task: asyncio.Future[int] | None = None
    seq_tracker = SequenceTracker()
    inter_arrival = InterArrivalTracker()
    render_times_ms: list[float] = []
    frames_rendered = 0
    selected_codec = "VP8"
    media_start_ns: int | None = None

    try:
        client = SignalingClient(
            remote_ip=config.remote_ip,
            port=config.signaling_port,
            source_ip=config.requested_source_ip,
            connect_timeout_s=config.timeouts.signaling_connect_s,
            read_timeout_s=config.timeouts.offer_answer_s,
        )
        await client.start()

        # Optional clock-offset estimate via signaling ping/pong.
        try:
            ping_samples = await client.clock_ping(rounds=6)
            offset_ms, unc_ms = estimate_clock_offset_ms(
                [(s.t0, s.t1, s.t2, s.t3) for s in ping_samples]
            )
            if offset_ms is not None:
                result.video.approximate_one_way_delay_uncertainty_ms = unc_ms
                result.warnings.append(
                    "Clock-offset estimate from signaling ping/pong is approximate; "
                    "do not treat it as exact glass-to-glass latency. "
                    f"offset_ms≈{offset_ms:.2f}, uncertainty_ms≈{unc_ms}."
                )
        except WebRTCError:
            pass

        pc = create_peer_connection()

        track_ready = asyncio.Event()
        remote_track_box: list[Any] = []

        def _on_track(track: Any) -> None:
            if track.kind == "video":
                remote_track_box.append(track)
                track_ready.set()

        def _on_conn() -> None:
            if pc is not None and pc.connectionState in {"failed", "closed", "disconnected"}:
                stop_event.set()

        pc.on("track")(_on_track)
        pc.on("connectionstatechange")(_on_conn)

        pc.addTransceiver("video", direction="recvonly")
        selected_codec = prefer_video_codec(
            pc,
            prefer="video/VP8",
            allow_h264_fallback=config.allow_h264_fallback,
        )
        result.video.codec = selected_codec

        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        await wait_ice_gathering_complete(pc, timeout_s=config.timeouts.ice_gathering_s)
        result.connection.local_candidates = _candidates_from_sdp(
            collect_local_candidate_strings(pc),
            adapters,
        )

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
        print(f"ICE connected (state={pc.iceConnectionState}). Waiting for video...")

        try:
            await asyncio.wait_for(track_ready.wait(), timeout=config.timeouts.first_frame_s)
        except TimeoutError as exc:
            raise _failure_with_states(
                "VIDEO_TRACK_NOT_RECEIVED",
                "Remote video track was not received in time.",
                pc,
            ) from exc

        consumer = RemoteVideoConsumer()
        await consumer.start(remote_track_box[0])

        # Wait for first decoded frame.
        deadline = time.perf_counter() + config.timeouts.first_frame_s
        while consumer.first_frame_at_ns is None:
            if time.perf_counter() > deadline:
                raise _failure_with_states(
                    "VIDEO_FRAME_TIMEOUT",
                    "No remote video frames arrived within the first-frame timeout.",
                    pc,
                )
            if stop_event.is_set():
                raise _failure_with_states(
                    "PEER_DISCONNECTED",
                    "Peer disconnected before the first video frame.",
                    pc,
                )
            await asyncio.sleep(0.05)

        media_start_ns = time.perf_counter_ns()
        print("First remote frame received.")

        stats_task = asyncio.create_task(
            _poll_stats_loop(
                pc,
                result,
                adapters=adapters,
                stop_event=stop_event,
                sampler=sampler,
            ),
            name="receiver-stats",
        )

        loop = asyncio.get_running_loop()
        preview_stop = asyncio.Event()

        def _recv_fps() -> float | None:
            if media_start_ns is None:
                return None
            elapsed = (time.perf_counter_ns() - media_start_ns) / 1e9
            return fps_from_count(consumer.frames_received if consumer else 0, elapsed)

        if config.preview:
            preview_task = loop.run_in_executor(
                None,
                lambda: run_preview_loop(
                    consumer.slot,
                    window_name="Snowlink Experiment E",
                    stop_event=preview_stop,
                    get_fps=_recv_fps,
                ),
            )

        start = time.perf_counter()
        last_activity = time.perf_counter()
        last_seen = consumer.frames_received

        while not stop_event.is_set():
            if time.perf_counter() - start >= config.duration_s:
                break
            if pc.connectionState == "failed":
                raise _failure_with_states(
                    "ICE_CONNECTION_FAILED",
                    "Peer connection failed during media.",
                    pc,
                )
            if pc.connectionState in {"closed", "disconnected"}:
                raise _failure_with_states(
                    "PEER_DISCONNECTED",
                    "Remote peer disconnected.",
                    pc,
                )

            if not config.preview:
                # Headless metrics path: consume the latest-frame slot here.
                # When preview is enabled, only the preview thread takes frames.
                item = consumer.slot.take(clear=True)
                if item is not None:
                    inter_arrival.observe_now()
                    if item.payload.sequence is not None:
                        seq_tracker.observe(item.payload.sequence)
                    t0 = time.perf_counter_ns()
                    _ = item.payload.bgr.shape
                    render_times_ms.append((time.perf_counter_ns() - t0) / 1e6)
                    frames_rendered += 1
                    last_activity = time.perf_counter()

            if consumer.frames_received > last_seen:
                last_seen = consumer.frames_received
                last_activity = time.perf_counter()
            elif time.perf_counter() - last_activity > config.timeouts.inactivity_s:
                raise _failure_with_states(
                    "VIDEO_FRAME_TIMEOUT",
                    "Video inactivity timeout — no frames for too long.",
                    pc,
                )

            if preview_task is not None and preview_task.done():
                break

            await asyncio.sleep(0.01 if config.preview else 0.001)

        result.success = (
            consumer.frames_received > 0
            and pc.iceConnectionState in {"connected", "completed", "checking"}
        ) or (consumer.frames_received > 0 and not result.errors)

    except asyncio.CancelledError:
        raise
    except WebRTCError as exc:
        result.errors.append(exc.failure.to_dict())
        result.success = False
        print(format_failure_human(exc.failure))
    except Exception as exc:
        failure = map_exception(exc)
        result.errors.append(failure.to_dict())
        result.success = False
        print(format_failure_human(failure))
    finally:
        stop_event.set()
        if preview_task is not None:
            # Signal preview thread to exit via slot close.
            if consumer is not None:
                consumer.slot.close()
            try:
                rendered = await asyncio.wait_for(preview_task, timeout=2.0)
                frames_rendered = max(frames_rendered, rendered)
            except Exception:
                pass
        if consumer is not None:
            result.video.latest_frame_overwrites = consumer.slot.overwritten_count
            result.video.frames_received = max(
                result.video.frames_received,
                consumer.frames_received,
            )
            if consumer.frames_decoded:
                result.video.frames_decoded = consumer.frames_decoded
            if consumer.first_frame_at_ns is not None and media_start_ns is not None:
                # first_frame_latency relative to media start is ~0; keep None cross-machine.
                pass
            await consumer.stop()
        if stats_task is not None:
            stats_task.cancel()
            try:
                await stats_task
            except (asyncio.CancelledError, Exception):
                pass
        if pc is not None:
            sig, ice, peer = _peer_states(pc)
            result.connection.signaling_state = sig
            result.connection.ice_state = ice
            result.connection.peer_state = peer
            try:
                report = await pc.getStats()
                _apply_stats_to_result(
                    result, parse_rtc_stats_report(report), adapters=adapters
                )
            except Exception:
                pass
            try:
                await asyncio.wait_for(pc.close(), timeout=config.timeouts.shutdown_s)
            except Exception:
                pass
        if client is not None:
            await client.close()

        result.video.frames_rendered = frames_rendered
        result.video.duplicate_sequences = seq_tracker.duplicate_sequences
        result.video.missing_sequences = seq_tracker.missing_sequences
        result.video.out_of_order_sequences = seq_tracker.out_of_order_sequences
        result.video.requested_fps = float(config.fps)
        result.video.width = result.video.width or config.width
        result.video.height = result.video.height or config.height
        result.video.codec = result.video.codec or selected_codec
        result.video.inter_arrival_average_ms = inter_arrival.average_ms()
        result.video.inter_arrival_p95_ms = inter_arrival.p95_ms()
        if render_times_ms:
            result.video.render_processing_average_ms = sum(render_times_ms) / len(
                render_times_ms
            )
        if media_start_ns is not None:
            elapsed = (time.perf_counter_ns() - media_start_ns) / 1e9
            result.video.received_fps = fps_from_count(result.video.frames_received, elapsed)
            result.video.rendered_fps = fps_from_count(frames_rendered, elapsed)
        result.resources = sampler.finalize()
        _finalize_candidate_match(result, config.requested_source_ip)

        # Soft-success: ICE wrong interface is a warning, not necessarily failure.
        hard_errors = [
            e
            for e in result.errors
            if isinstance(e, dict) and e.get("code") != "ICE_SELECTED_WRONG_INTERFACE"
        ]
        if result.video.frames_received > 0 and not hard_errors:
            result.success = True

    return result
