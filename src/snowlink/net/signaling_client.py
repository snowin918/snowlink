"""WebSocket signaling client (viewer): pairing + SDP exchange."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from snowlink.constants import MAX_SIGNALING_MESSAGE_BYTES, PROTOCOL_VERSION
from snowlink.net.messages import (
    Envelope,
    HelloPayload,
    PairingResponsePayload,
    SdpPayload,
    make_envelope,
    parse_envelope,
    typed_payload,
)
from snowlink.net.protocol import SignalingState
from snowlink.rtc.errors import WebRTCError, failure_for

logger = logging.getLogger(__name__)


def signaling_backoff_s(
    attempt: int,
    *,
    initial_s: float = 0.5,
    maximum_s: float = 8.0,
) -> float:
    """Exponential backoff for attempt index starting at 1."""
    if attempt < 1:
        attempt = 1
    return float(min(maximum_s, initial_s * (2 ** (attempt - 1))))


@dataclass
class WsSignalingClient:
    """aiohttp WebSocket client that dials the sharer's selected LAN IP."""

    remote_ip: str
    port: int
    pairing_code: str
    source_ip: str | None = None
    connect_timeout_s: float = 5.0
    max_message_bytes: int = MAX_SIGNALING_MESSAGE_BYTES
    _session: Any = field(default=None, init=False, repr=False)
    _ws: Any = field(default=None, init=False, repr=False)
    _state: SignalingState = field(default=SignalingState.CLOSED, init=False)
    session_id: str | None = field(default=None, init=False)
    session_secret: str | None = field(default=None, init=False)

    @property
    def state(self) -> SignalingState:
        return self._state

    @property
    def is_connected(self) -> bool:
        """True when the underlying WebSocket appears open."""
        ws = self._ws
        if ws is None:
            return False
        try:
            closed = getattr(ws, "closed", False)
            return not bool(closed)
        except Exception:
            return False

    def _ws_url(self) -> str:
        return f"ws://{self.remote_ip}:{self.port}/ws"

    async def connect_and_pair(self) -> None:
        """Open WebSocket, complete hello + pairing; leave socket ready for offer."""
        try:
            import aiohttp
        except ImportError as exc:
            raise WebRTCError(
                failure_for(
                    "UNEXPECTED_WEBRTC_ERROR",
                    "aiohttp is not installed (required for WebSocket signaling).",
                    exception=exc,
                )
            ) from exc

        timeout = aiohttp.ClientTimeout(
            total=None,
            connect=self.connect_timeout_s,
            sock_connect=self.connect_timeout_s,
        )
        connector = aiohttp.TCPConnector(
            local_addr=(self.source_ip, 0) if self.source_ip else None
        )
        self._session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        self._state = SignalingState.DIALING
        try:
            self._ws = await self._session.ws_connect(
                self._ws_url(),
                max_msg_size=self.max_message_bytes,
                heartbeat=30.0,
            )
        except Exception as exc:
            await self.close()
            name = type(exc).__name__
            if "Timeout" in name:
                raise WebRTCError(
                    failure_for(
                        "SIGNALING_TIMEOUT",
                        f"Timed out connecting to {self._ws_url()}.",
                        exception=exc,
                    )
                ) from exc
            raise WebRTCError(
                failure_for(
                    "SIGNALING_CONNECTION_FAILED",
                    f"Could not connect to signaling at {self._ws_url()} ({name}).",
                    exception=exc,
                )
            ) from exc

        self._state = SignalingState.HANDSHAKE
        # session_id unknown until hello_ack; use placeholder then adopt server id
        placeholder_session = "pending"
        await self._send(
            make_envelope(
                session_id=placeholder_session,
                msg_type="hello",
                payload=HelloPayload(),
            )
        )

        ack = await self._recv_typed(expected="hello_ack")
        self.session_id = ack.session_id

        self._state = SignalingState.AUTHENTICATING
        challenge = await self._recv_typed(expected="pairing_challenge")
        nonce = str(challenge.payload.get("nonce", ""))
        await self._send(
            make_envelope(
                session_id=self.session_id or placeholder_session,
                msg_type="pairing_response",
                payload=PairingResponsePayload(
                    code=self.pairing_code,
                    nonce=nonce,
                ),
            )
        )

        result = await self._recv_typed(expected="pairing_result")
        status = str(result.payload.get("status", "invalid"))
        if status != "ok":
            code = {
                "denied": "PAIRING_REJECTED",
                "expired": "PAIRING_EXPIRED",
                "rate_limited": "PAIRING_RATE_LIMITED",
                "invalid": "PAIRING_REJECTED",
            }.get(status, "PAIRING_REJECTED")
            message = str(result.payload.get("message") or f"Pairing {status}")
            await self.close()
            raise WebRTCError(failure_for(code, message))

        secret = result.payload.get("session_secret")
        self.session_secret = str(secret) if secret else None
        self._state = SignalingState.AUTHENTICATED

    async def connect_and_pair_with_retry(
        self,
        *,
        max_attempts: int = 5,
        initial_backoff_s: float = 0.5,
        max_backoff_s: float = 8.0,
        stop_event: asyncio.Event | None = None,
        on_attempt: Callable[[int, BaseException | None], None] | None = None,
    ) -> None:
        """Dial + pair with exponential backoff on transient connection failures.

        Pairing rejections / protocol errors are not retried.
        """
        last_error: BaseException | None = None
        attempts = max(1, int(max_attempts))
        for attempt in range(1, attempts + 1):
            if stop_event is not None and stop_event.is_set():
                raise WebRTCError(
                    failure_for(
                        "SIGNALING_CONNECTION_FAILED",
                        "Signaling connect cancelled before pairing completed.",
                    )
                )
            try:
                if on_attempt is not None:
                    on_attempt(attempt, None)
                await self.connect_and_pair()
                return
            except WebRTCError as exc:
                last_error = exc
                code = getattr(getattr(exc, "failure", None), "code", "") or ""
                # Auth / protocol outcomes should not spin retries.
                if code in {
                    "PAIRING_REJECTED",
                    "PAIRING_EXPIRED",
                    "PAIRING_RATE_LIMITED",
                    "PROTOCOL_MISMATCH",
                    "VIEWER_SLOT_TAKEN",
                    "UNEXPECTED_WEBRTC_ERROR",
                }:
                    raise
                if attempt >= attempts:
                    raise
                if on_attempt is not None:
                    on_attempt(attempt, exc)
                delay = signaling_backoff_s(
                    attempt,
                    initial_s=initial_backoff_s,
                    maximum_s=max_backoff_s,
                )
                logger.info(
                    "Signaling connect attempt %s/%s failed (%s); retry in %.1fs",
                    attempt,
                    attempts,
                    code or type(exc).__name__,
                    delay,
                )
                await self.close()
                try:
                    if stop_event is None:
                        await asyncio.sleep(delay)
                    else:
                        await asyncio.wait_for(stop_event.wait(), timeout=delay)
                        raise WebRTCError(
                            failure_for(
                                "SIGNALING_CONNECTION_FAILED",
                                "Signaling connect cancelled during retry backoff.",
                            )
                        )
                except TimeoutError:
                    continue
            except Exception as exc:
                last_error = exc
                if attempt >= attempts:
                    raise WebRTCError(
                        failure_for(
                            "SIGNALING_CONNECTION_FAILED",
                            f"Could not connect to signaling after {attempts} attempts.",
                            exception=exc,
                        )
                    ) from exc
                if on_attempt is not None:
                    on_attempt(attempt, exc)
                delay = signaling_backoff_s(
                    attempt,
                    initial_s=initial_backoff_s,
                    maximum_s=max_backoff_s,
                )
                await self.close()
                try:
                    if stop_event is None:
                        await asyncio.sleep(delay)
                    else:
                        await asyncio.wait_for(stop_event.wait(), timeout=delay)
                        raise WebRTCError(
                            failure_for(
                                "SIGNALING_CONNECTION_FAILED",
                                "Signaling connect cancelled during retry backoff.",
                            )
                        )
                except TimeoutError:
                    continue
        if isinstance(last_error, WebRTCError):
            raise last_error
        raise WebRTCError(
            failure_for(
                "SIGNALING_CONNECTION_FAILED",
                f"Could not connect to signaling after {attempts} attempts.",
                exception=last_error,
            )
        )

    async def wait_offer(self) -> dict[str, str]:
        envelope = await self._recv_typed(expected="offer")
        payload = typed_payload(envelope)
        assert isinstance(payload, SdpPayload)
        self._state = SignalingState.MEDIA_SIGNALING
        return {"sdp": payload.sdp, "type": payload.sdp_type}

    async def send_answer(self, *, sdp: str, sdp_type: str = "answer") -> None:
        if not self.session_id:
            raise WebRTCError(
                failure_for("SIGNALING_CONNECTION_FAILED", "No session_id after pairing.")
            )
        await self._send(
            make_envelope(
                session_id=self.session_id,
                msg_type="answer",
                payload=SdpPayload(sdp=sdp, sdp_type="answer"),
            )
        )

    async def close(self) -> None:
        self._state = SignalingState.CLOSING
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None
        self._state = SignalingState.CLOSED

    async def _send(self, envelope: Envelope) -> None:
        if self._ws is None:
            raise WebRTCError(
                failure_for("SIGNALING_CONNECTION_FAILED", "WebSocket is not connected.")
            )
        raw = envelope.model_dump_json()
        if len(raw.encode("utf-8")) > self.max_message_bytes:
            raise WebRTCError(
                failure_for(
                    "MALFORMED_SDP",
                    f"Signaling message exceeds {self.max_message_bytes} bytes.",
                )
            )
        await self._ws.send_str(raw)

    async def _recv_typed(self, *, expected: str) -> Envelope:
        from aiohttp import WSMsgType

        if self._ws is None:
            raise WebRTCError(
                failure_for("SIGNALING_CONNECTION_FAILED", "WebSocket is not connected.")
            )
        while True:
            msg = await self._ws.receive()
            if msg.type in {WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED}:
                raise WebRTCError(
                    failure_for(
                        "SIGNALING_CONNECTION_FAILED",
                        "WebSocket closed while waiting for signaling message.",
                    )
                )
            if msg.type == WSMsgType.ERROR:
                raise WebRTCError(
                    failure_for(
                        "SIGNALING_CONNECTION_FAILED",
                        "WebSocket error while receiving signaling message.",
                    )
                )
            if msg.type != WSMsgType.TEXT:
                continue
            raw = msg.data
            if isinstance(raw, str):
                data = raw.encode("utf-8")
            else:
                data = raw
            if len(data) > self.max_message_bytes:
                raise WebRTCError(
                    failure_for("MALFORMED_SDP", "Signaling message exceeds size limit.")
                )
            try:
                envelope = parse_envelope(data)
            except Exception as exc:
                raise WebRTCError(
                    failure_for(
                        "MALFORMED_SDP",
                        f"Invalid signaling message: {exc}",
                        exception=exc,
                    )
                ) from exc
            if envelope.v != PROTOCOL_VERSION:
                raise WebRTCError(
                    failure_for(
                        "PROTOCOL_MISMATCH",
                        f"Unsupported protocol version {envelope.v}.",
                    )
                )
            if envelope.type == "error":
                code = str(envelope.payload.get("code") or "SIGNALING_ERROR")
                message = str(envelope.payload.get("message") or "Signaling error")
                raise WebRTCError(failure_for(code, message))
            if envelope.type != expected:
                raise WebRTCError(
                    failure_for(
                        "UNEXPECTED_MESSAGE",
                        f"Expected {expected}, got {envelope.type}.",
                    )
                )
            return envelope
