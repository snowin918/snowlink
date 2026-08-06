"""Send/receive session orchestration for Experiment F (synthetic Opus audio)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from snowlink.media.audio_errors import AudioError
from snowlink.media.audio_format import float32_to_s16
from snowlink.net.adapter_models import NetworkAdapter
from snowlink.net.tcp_diagnostics import validate_ipv4
from snowlink.rtc.audio_receiver import PlaybackWorker, RemoteAudioConsumer
from snowlink.rtc.errors import WebRTCError, failure_for, format_failure_human, map_exception
from snowlink.rtc.ice_diagnostics import (
    candidate_from_aiortc,
    enrich_candidate,
    mismatch_warning,
    parse_candidate_sdp,
    selected_matches_requested_ip,
)
from snowlink.rtc.models import (
    ExperimentFConfiguration,
    ExperimentFResult,
    IceCandidateInfo,
)
from snowlink.rtc.peer_connection import (
    assert_opus_available,
    collect_local_candidate_strings,
    create_peer_connection,
    list_audio_codecs,
    prefer_audio_codec,
    require_aiortc,
    wait_ice_connected,
    wait_ice_gathering_complete,
)
from snowlink.rtc.session import _load_adapters, validate_local_ip
from snowlink.rtc.signaling import SIGNALING_WARNING, SignalingClient, SignalingServer
from snowlink.rtc.synthetic_audio import SyntheticAudioTrack
from snowlink.rtc.webrtc_metrics import ProcessResourceSampler, parse_rtc_stats_report

logger = logging.getLogger(__name__)

PLAYBACK_VOLUME_WARNING = (
    "SAFE VOLUME WARNING: A synthetic tone will play through the selected speakers. "
    "Start with low gain (default 0.25). Do not raise Windows master volume for this test."
)


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
    result: ExperimentFResult,
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

    audio_stats = getattr(parsed, "audio", None) or {}
    if isinstance(audio_stats, dict):
        for key, value in audio_stats.items():
            if value is not None and hasattr(result.audio, key):
                setattr(result.audio, key, value)

    if parsed.codec_name:
        result.audio.codec = parsed.codec_name
        result.audio.codec_payload_type = parsed.codec_payload_type

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
    result: ExperimentFResult,
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


def _finalize_candidate_match(result: ExperimentFResult, requested_ip: str | None) -> None:
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


def _fill_sender_audio_stats(result: ExperimentFResult, track: SyntheticAudioTrack) -> None:
    result.audio.signal = track.signal
    result.audio.tone_frequency_hz = track.frequency_hz
    result.audio.amplitude = track.amplitude
    result.audio.sample_rate = track.sample_rate
    result.audio.channels = track.channels
    result.audio.frame_duration_ms = track.frame_ms
    result.audio.samples_per_frame = track.samples_per_frame
    result.audio.frames_generated = track.frames_generated
    result.audio.samples_generated = track.samples_generated
    result.audio.silence_frames = track.silence_frames
    result.audio.late_generation_events = track.late_generation_events
    result.audio.max_generation_lateness_ms = track.max_generation_lateness_ms


async def run_audio_sender(config: ExperimentFConfiguration) -> ExperimentFResult:
    """Run the Experiment F sender (signaling + synthetic Opus track)."""
    require_aiortc()
    from aiortc import RTCSessionDescription

    adapters = _load_adapters()
    if not config.bind_ip:
        raise WebRTCError(failure_for("INVALID_BIND_IP", "--bind-ip is required for send."))
    validate_local_ip(config.bind_ip, adapters)

    result = ExperimentFResult(
        role="sender",
        session_name=config.session_name,
        configuration=config,
        timestamp=datetime.now(UTC).isoformat(),
        signaling_warning=SIGNALING_WARNING,
    )
    result.available_codecs = list_audio_codecs()
    print(SIGNALING_WARNING)
    print("Available audio codecs:")
    for codec in result.available_codecs:
        print(f"  - {codec.mime_type}")

    sampler = ProcessResourceSampler()
    track = SyntheticAudioTrack(
        sample_rate=config.sample_rate,
        channels=config.channels,
        frame_ms=config.frame_duration_ms,
        signal=config.signal,
        frequency_hz=config.tone_frequency_hz,
        amplitude=config.amplitude,
        pulse_interval_ms=config.pulse_interval_ms,
    )
    pc: Any | None = None
    server: SignalingServer | None = None
    stop_event = asyncio.Event()
    stats_task: asyncio.Task[None] | None = None
    media_started = asyncio.Event()
    selected_codec = "opus"

    async def handle_offer(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal pc, stats_task, selected_codec
        pc = create_peer_connection()

        def _on_conn() -> None:
            if pc is not None and pc.connectionState in {"failed", "closed", "disconnected"}:
                stop_event.set()

        pc.on("connectionstatechange")(_on_conn)

        pc.addTrack(track)
        selected_codec = prefer_audio_codec(pc, prefer="audio/opus")
        offer = RTCSessionDescription(sdp=str(payload["sdp"]), type=str(payload["type"]))
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        await wait_ice_gathering_complete(pc, timeout_s=config.timeouts.ice_gathering_s)

        result.connection.local_candidates = _candidates_from_sdp(
            collect_local_candidate_strings(pc),
            adapters,
        )
        result.audio.codec = selected_codec
        stats_task = asyncio.create_task(
            _poll_stats_loop(
                pc,
                result,
                adapters=adapters,
                stop_event=stop_event,
                sampler=sampler,
            ),
            name="audio-sender-stats",
        )
        media_started.set()
        assert pc.localDescription is not None
        return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

    try:
        assert_opus_available(prefer="audio/opus")

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
        print(f"ICE connected (state={pc.iceConnectionState}). Streaming synthetic audio...")

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

        _fill_sender_audio_stats(result, track)
        result.audio.codec = result.audio.codec or selected_codec
        result.resources = sampler.finalize()
        _finalize_candidate_match(result, config.bind_ip)

    return result


def _open_playback(config: ExperimentFConfiguration) -> tuple[Any, Any] | None:
    """Open WASAPI playback; return (player, pa) or None when playback disabled."""
    if not config.playback:
        return None
    try:
        from snowlink.media.audio_playback import AudioPlayer
        from snowlink.platform_win.audio_endpoints import resolve_playback_device
    except Exception as exc:
        raise WebRTCError(
            failure_for(
                "PLAYBACK_DEVICE_NOT_FOUND",
                "Playback support is unavailable (install audio extras).",
                exception=exc,
            )
        ) from exc

    try:
        from snowlink.platform_win.audio_endpoints import require_pyaudio

        pa = require_pyaudio().PyAudio()
        endpoint = resolve_playback_device(config.playback_device, pa=pa)
        player = AudioPlayer(
            endpoint,
            sample_rate=config.sample_rate,
            channels=config.channels,
            pa=pa,
            frames_per_buffer=int(config.sample_rate * config.frame_duration_ms / 1000),
        )
        player.open()
        player.start()
        return player, pa
    except AudioError as exc:
        code = exc.failure.code
        mapped = {
            "INVALID_PLAYBACK_DEVICE": "PLAYBACK_DEVICE_NOT_FOUND",
            "WASAPI_NOT_AVAILABLE": "PLAYBACK_DEVICE_NOT_FOUND",
            "PLAYBACK_OPEN_FAILED": "PLAYBACK_OPEN_FAILED",
            "PLAYBACK_WRITE_FAILED": "PLAYBACK_WRITE_FAILED",
        }.get(code, "PLAYBACK_OPEN_FAILED")
        raise WebRTCError(
            failure_for(mapped, exc.failure.message, exception=exc)
        ) from exc
    except Exception as exc:
        raise WebRTCError(
            failure_for(
                "PLAYBACK_OPEN_FAILED",
                "Failed to open playback device.",
                exception=exc,
            )
        ) from exc


async def run_audio_receiver(config: ExperimentFConfiguration) -> ExperimentFResult:
    """Run the Experiment F receiver (connect + optional playback)."""
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

    result = ExperimentFResult(
        role="receiver",
        session_name=config.session_name,
        configuration=config,
        timestamp=datetime.now(UTC).isoformat(),
        signaling_warning=SIGNALING_WARNING,
    )
    result.available_codecs = list_audio_codecs()
    print(SIGNALING_WARNING)
    print("Available audio codecs:")
    for codec in result.available_codecs:
        print(f"  - {codec.mime_type}")

    if config.playback and not config.muted:
        print(PLAYBACK_VOLUME_WARNING)
        result.warnings.append(PLAYBACK_VOLUME_WARNING)

    sampler = ProcessResourceSampler()
    pc: Any | None = None
    client: SignalingClient | None = None
    consumer: RemoteAudioConsumer | None = None
    playback_worker: PlaybackWorker | None = None
    player_pair: tuple[Any, Any] | None = None
    stop_event = asyncio.Event()
    stats_task: asyncio.Task[None] | None = None
    selected_codec = "opus"

    try:
        assert_opus_available(prefer="audio/opus")

        client = SignalingClient(
            remote_ip=config.remote_ip,
            port=config.signaling_port,
            source_ip=config.requested_source_ip,
            connect_timeout_s=config.timeouts.signaling_connect_s,
            read_timeout_s=config.timeouts.offer_answer_s,
        )
        await client.start()

        pc = create_peer_connection()
        track_ready = asyncio.Event()
        remote_track_box: list[Any] = []

        def _on_track(track: Any) -> None:
            if track.kind == "audio":
                remote_track_box.append(track)
                track_ready.set()

        def _on_conn() -> None:
            if pc is not None and pc.connectionState in {"failed", "closed", "disconnected"}:
                stop_event.set()

        pc.on("track")(_on_track)
        pc.on("connectionstatechange")(_on_conn)

        pc.addTransceiver("audio", direction="recvonly")
        selected_codec = prefer_audio_codec(pc, prefer="audio/opus")
        result.audio.codec = selected_codec

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
        print(f"ICE connected (state={pc.iceConnectionState}). Waiting for audio...")

        try:
            await asyncio.wait_for(track_ready.wait(), timeout=config.timeouts.remote_track_s)
        except TimeoutError as exc:
            raise _failure_with_states(
                "AUDIO_TRACK_NOT_RECEIVED",
                "Remote audio track was not received in time.",
                pc,
            ) from exc

        consumer = RemoteAudioConsumer(
            sample_rate=config.sample_rate,
            channels=config.channels,
            frame_ms=config.frame_duration_ms,
            buffer_target_ms=config.buffer_target_ms,
            expected_frequency_hz=config.tone_frequency_hz,
            signal=config.signal,
            pulse_interval_ms=config.pulse_interval_ms,
            duration_s=config.duration_s,
        )
        await consumer.start(remote_track_box[0])

        # Wait for first decoded frame.
        deadline = time.perf_counter() + config.timeouts.first_frame_s
        while consumer.first_frame_at_ns is None:
            if time.perf_counter() > deadline:
                raise _failure_with_states(
                    "FIRST_AUDIO_FRAME_TIMEOUT",
                    "No remote audio frames arrived within the first-frame timeout.",
                    pc,
                )
            if stop_event.is_set():
                raise _failure_with_states(
                    "PEER_DISCONNECTED",
                    "Peer disconnected before the first audio frame.",
                    pc,
                )
            if consumer.fatal_error is not None:
                raise consumer.fatal_error
            await asyncio.sleep(0.02)

        print("First remote audio frame received.")

        write_pcm = None
        if config.playback:
            player_pair = _open_playback(config)
            assert player_pair is not None
            player, _pa = player_pair

            def _write(pcm: Any) -> None:
                player.write_s16(float32_to_s16(pcm))

            write_pcm = _write

        playback_worker = PlaybackWorker(
            consumer.ring,
            sample_rate=config.sample_rate,
            channels=config.channels,
            frame_ms=config.frame_duration_ms,
            gain=config.gain,
            muted=config.muted,
            write_pcm=write_pcm,
            enabled=config.playback,
        )
        playback_worker.start()

        stats_task = asyncio.create_task(
            _poll_stats_loop(
                pc,
                result,
                adapters=adapters,
                stop_event=stop_event,
                sampler=sampler,
            ),
            name="audio-receiver-stats",
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
            if consumer.fatal_error is not None:
                raise consumer.fatal_error
            if playback_worker.fatal_error is not None:
                raise WebRTCError(
                    failure_for(
                        "PLAYBACK_WRITE_FAILED",
                        "Playback worker failed.",
                        exception=playback_worker.fatal_error,
                    )
                )

            if consumer.frames_received > last_seen:
                last_seen = consumer.frames_received
                last_activity = time.perf_counter()
            elif time.perf_counter() - last_activity > config.timeouts.inactivity_s:
                raise _failure_with_states(
                    "FIRST_AUDIO_FRAME_TIMEOUT",
                    "Audio inactivity timeout — no frames for too long.",
                    pc,
                )

            await asyncio.sleep(0.05)

        result.success = consumer.frames_received > 0 and pc.connectionState != "failed"

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
        if playback_worker is not None:
            playback_worker.stop(timeout=config.timeouts.shutdown_s)
            result.audio.samples_played = playback_worker.samples_played
            result.buffer.silence_samples_inserted = playback_worker.silence_samples_inserted
            result.buffer.underruns = max(
                result.buffer.underruns,
                playback_worker.underruns,
            )
        if consumer is not None:
            ring_stats = consumer.ring.stats()
            result.buffer.target_ms = consumer.buffer_target_ms
            result.buffer.capacity_ms = consumer.buffer_capacity_ms
            if consumer.fill_ms_samples:
                result.buffer.average_fill_ms = sum(consumer.fill_ms_samples) / len(
                    consumer.fill_ms_samples
                )
                result.buffer.peak_fill_ms = max(consumer.fill_ms_samples)
                result.buffer.local_receiver_buffering_delay_ms = result.buffer.average_fill_ms
            result.buffer.overruns = ring_stats.overruns
            result.buffer.dropped_samples = ring_stats.dropped_samples
            result.buffer.underruns = max(result.buffer.underruns, ring_stats.underruns)

            result.audio.frames_received = consumer.frames_received
            result.audio.samples_received = consumer.samples_received
            result.audio.frame_sample_count_mismatches = (
                consumer.frame_sample_count_mismatches
            )
            result.audio.invalid_pts_count = consumer.pts_validator.invalid_pts_count
            result.audio.missing_pts_count = consumer.pts_validator.missing_pts_count
            result.audio.received_sample_rate = consumer.received_sample_rate
            result.audio.received_channels = consumer.received_channels
            result.audio.received_format = consumer.received_format
            result.audio.sample_rate = config.sample_rate
            result.audio.channels = config.channels
            result.audio.frame_duration_ms = config.frame_duration_ms
            result.audio.samples_per_frame = consumer.samples_per_frame
            result.audio.signal = config.signal
            result.audio.tone_frequency_hz = config.tone_frequency_hz
            result.audio.amplitude = config.amplitude

            tone = consumer.tone.finalize()
            result.audio.rms_average = tone.rms_average
            result.audio.peak = tone.peak
            result.audio.clipping_count = tone.clipping_count
            result.audio.silent_frame_count = tone.silent_frame_count
            result.audio.estimated_frequency_hz = tone.estimated_frequency_hz
            if consumer.pulse is not None:
                pulse = consumer.pulse.finalize()
                result.audio.pulses_expected = pulse.pulses_expected
                result.audio.pulses_detected = pulse.pulses_detected
                result.audio.pulses_missing = pulse.pulses_missing
                result.audio.pulses_duplicate = pulse.pulses_duplicate
                result.audio.pulse_interval_variation_ms = pulse.pulse_interval_variation_ms

            await consumer.stop()

        if player_pair is not None:
            player, pa = player_pair
            try:
                player.close()
            except Exception:
                pass
            try:
                pa.terminate()
            except Exception:
                pass

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

        result.audio.codec = result.audio.codec or selected_codec
        result.resources = sampler.finalize()
        _finalize_candidate_match(result, config.requested_source_ip)

        # Soft-success: ICE wrong interface / buffer events are warnings.
        hard_errors = [
            e
            for e in result.errors
            if isinstance(e, dict)
            and e.get("code")
            not in {
                "ICE_SELECTED_WRONG_INTERFACE",
                "AUDIO_BUFFER_UNDERRUN",
                "AUDIO_BUFFER_OVERRUN",
            }
        ]
        if result.audio.frames_received > 0 and not hard_errors:
            result.success = True

        if result.buffer.underruns:
            result.warnings.append(
                f"Audio buffer underruns={result.buffer.underruns} "
                f"(silence inserted; local receiver buffering delay metric)."
            )
        if result.buffer.overruns:
            result.warnings.append(
                f"Audio buffer overruns={result.buffer.overruns} "
                f"(dropped_samples={result.buffer.dropped_samples})."
            )

    return result
