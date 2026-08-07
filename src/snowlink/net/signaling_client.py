"""WebSocket signaling client (viewer): pairing + SDP exchange."""

from __future__ import annotations

import logging
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
