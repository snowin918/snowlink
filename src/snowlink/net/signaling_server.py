"""WebSocket signaling server (sharer): pairing gate + SDP exchange."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from snowlink.constants import (
    MAX_SIGNALING_MESSAGE_BYTES,
    PAIRING_APPROVAL_TIMEOUT_S,
    PROTOCOL_VERSION,
)
from snowlink.net.messages import (
    Envelope,
    ErrorPayload,
    HelloAckPayload,
    HelloPayload,
    PairingChallengePayload,
    PairingResponsePayload,
    PairingResultPayload,
    SdpPayload,
    make_envelope,
    parse_envelope,
    typed_payload,
)
from snowlink.net.protocol import MEDIA_READY_STATES, SignalingState
from snowlink.rtc.errors import WebRTCError, failure_for
from snowlink.security.pairing import (
    PairingAuthority,
    PairingRequestInfo,
    PairingResultStatus,
)
from snowlink.security.secrets import generate_session_secret

logger = logging.getLogger(__name__)

ApprovalHandler = Callable[[PairingRequestInfo], Awaitable[bool]]
OfferFactory = Callable[[], Awaitable[dict[str, str]]]


@dataclass
class WsSignalingServer:
    """aiohttp WebSocket server bound to a selected LAN IPv4."""

    bind_ip: str
    port: int
    pairing: PairingAuthority
    offer_factory: OfferFactory
    approval_handler: ApprovalHandler
    auto_approve: bool = False
    max_message_bytes: int = MAX_SIGNALING_MESSAGE_BYTES
    approval_timeout_s: float = PAIRING_APPROVAL_TIMEOUT_S
    _app: Any = field(default=None, init=False, repr=False)
    _runner: Any = field(default=None, init=False, repr=False)
    _site: Any = field(default=None, init=False, repr=False)
    _state: SignalingState = field(default=SignalingState.CLOSED, init=False)
    _viewer_taken: bool = field(default=False, init=False)
    _closed: bool = field(default=False, init=False)
    _session_secret: str | None = field(default=None, init=False)
    _authenticated: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _answer_future: asyncio.Future[dict[str, str]] | None = field(
        default=None, init=False, repr=False
    )
    _ws: Any = field(default=None, init=False, repr=False)
    _handler_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)

    @property
    def state(self) -> SignalingState:
        return self._state

    @property
    def session_secret(self) -> str | None:
        return self._session_secret

    async def start(self) -> None:
        try:
            from aiohttp import web
        except ImportError as exc:
            raise WebRTCError(
                failure_for(
                    "UNEXPECTED_WEBRTC_ERROR",
                    "aiohttp is not installed (required for WebSocket signaling).",
                    exception=exc,
                )
            ) from exc

        app = web.Application(client_max_size=self.max_message_bytes)
        app.router.add_get("/ws", self._ws_handler)
        app.router.add_get("/health", self._health)
        self._app = app
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        try:
            self._site = web.TCPSite(self._runner, host=self.bind_ip, port=self.port)
            await self._site.start()
            server = getattr(self._site, "_server", None)
            if server is not None and getattr(server, "sockets", None):
                sock = server.sockets[0]
                self.port = int(sock.getsockname()[1])
        except OSError as exc:
            await self.close()
            raise WebRTCError(
                failure_for(
                    "SIGNALING_BIND_FAILED",
                    f"Failed to bind WebSocket signaling to {self.bind_ip}:{self.port}.",
                    exception=exc,
                )
            ) from exc
        self._state = SignalingState.LISTENING

    async def _health(self, request: Any) -> Any:
        from aiohttp import web

        _ = request
        return web.json_response(
            {
                "ok": True,
                "protocol": PROTOCOL_VERSION,
                "state": self._state.value,
                "viewer_taken": self._viewer_taken,
            }
        )

    async def _ws_handler(self, request: Any) -> Any:
        from aiohttp import web

        if self._closed:
            raise web.HTTPServiceUnavailable(text="signaling closed")
        if self._viewer_taken:
            ws_reject = web.WebSocketResponse()
            await ws_reject.prepare(request)
            await self._send(
                ws_reject,
                make_envelope(
                    session_id=self.pairing.session_id,
                    msg_type="error",
                    payload=ErrorPayload(
                        code="VIEWER_SLOT_TAKEN",
                        message="A viewer is already connected.",
                    ),
                ),
            )
            await ws_reject.close()
            return ws_reject

        ws = web.WebSocketResponse(max_msg_size=self.max_message_bytes)
        await ws.prepare(request)
        self._viewer_taken = True
        self._ws = ws
        remote = request.remote or "unknown"
        self._state = SignalingState.HANDSHAKE
        try:
            await self._run_session(ws, remote_addr=str(remote))
        except Exception:
            logger.exception("WebSocket signaling session failed")
        finally:
            self._ws = None
            if not self._authenticated.is_set():
                self._viewer_taken = False
            if self._state not in {SignalingState.CLOSING, SignalingState.CLOSED}:
                self._state = SignalingState.LISTENING
            try:
                await ws.close()
            except Exception:
                pass
        return ws

    async def _run_session(self, ws: Any, *, remote_addr: str) -> None:
        from aiohttp import WSMsgType

        hello = await self._recv_typed(ws, expected="hello")
        hello_payload = typed_payload(hello)
        assert isinstance(hello_payload, HelloPayload)
        await self._send(
            ws,
            make_envelope(
                session_id=self.pairing.session_id,
                msg_type="hello_ack",
                payload=HelloAckPayload(),
            ),
        )

        self._state = SignalingState.AUTHENTICATING
        try:
            nonce, expiry_ms = self.pairing.issue_challenge()
        except TimeoutError:
            await self._send(
                ws,
                make_envelope(
                    session_id=self.pairing.session_id,
                    msg_type="pairing_result",
                    payload=PairingResultPayload(
                        status="expired",
                        message="Pairing code expired before challenge.",
                    ),
                ),
            )
            return

        await self._send(
            ws,
            make_envelope(
                session_id=self.pairing.session_id,
                msg_type="pairing_challenge",
                payload=PairingChallengePayload(nonce=nonce, expiry_ms=expiry_ms),
            ),
        )

        response_env = await self._recv_typed(ws, expected="pairing_response")
        response = typed_payload(response_env)
        assert isinstance(response, PairingResponsePayload)
        status = self.pairing.validate_response(
            code=response.code,
            nonce=response.nonce,
            remote_addr=remote_addr,
        )
        if status != PairingResultStatus.OK:
            result_status = {
                PairingResultStatus.DENIED: "denied",
                PairingResultStatus.EXPIRED: "expired",
                PairingResultStatus.RATE_LIMITED: "rate_limited",
                PairingResultStatus.INVALID: "invalid",
            }.get(status, "invalid")
            await self._send(
                ws,
                make_envelope(
                    session_id=self.pairing.session_id,
                    msg_type="pairing_result",
                    payload=PairingResultPayload(
                        status=result_status,  # type: ignore[arg-type]
                        message=f"Pairing {result_status}.",
                    ),
                ),
            )
            self._viewer_taken = False
            return

        info = PairingRequestInfo(
            remote_addr=remote_addr,
            code_matched=True,
            session_id=self.pairing.session_id,
        )
        approved = self.auto_approve
        if not approved:
            try:
                approved = await asyncio.wait_for(
                    self.approval_handler(info),
                    timeout=self.approval_timeout_s,
                )
            except TimeoutError:
                approved = False

        if not approved:
            await self._send(
                ws,
                make_envelope(
                    session_id=self.pairing.session_id,
                    msg_type="pairing_result",
                    payload=PairingResultPayload(
                        status="denied",
                        message="Sharer denied the pairing request.",
                    ),
                ),
            )
            self._viewer_taken = False
            return

        self._session_secret = generate_session_secret()
        self.pairing.mark_consumed()
        await self._send(
            ws,
            make_envelope(
                session_id=self.pairing.session_id,
                msg_type="pairing_result",
                payload=PairingResultPayload(
                    status="ok",
                    session_secret=self._session_secret,
                    message="Paired.",
                ),
            ),
        )
        self._state = SignalingState.AUTHENTICATED
        self._authenticated.set()

        # Sharer creates the offer after auth (PLAN §4.1 / §11).
        self._state = SignalingState.MEDIA_SIGNALING
        loop = asyncio.get_running_loop()
        if self._answer_future is None or self._answer_future.done():
            self._answer_future = loop.create_future()
        offer = await self.offer_factory()
        await self._send(
            ws,
            make_envelope(
                session_id=self.pairing.session_id,
                msg_type="offer",
                payload=SdpPayload(sdp=offer["sdp"], sdp_type="offer"),
            ),
        )

        while not ws.closed:
            msg = await ws.receive()
            if msg.type in {WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED}:
                break
            if msg.type == WSMsgType.ERROR:
                break
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                envelope = self._parse_raw(msg.data)
            except Exception as exc:
                await self._send_error(ws, "MALFORMED_MESSAGE", str(exc))
                continue
            if envelope.type == "answer":
                if self._state not in MEDIA_READY_STATES:
                    await self._send_error(ws, "UNAUTHORIZED", "Not authenticated.")
                    continue
                payload = typed_payload(envelope)
                assert isinstance(payload, SdpPayload)
                if payload.sdp_type != "answer":
                    await self._send_error(ws, "MALFORMED_SDP", "Expected answer.")
                    continue
                if self._answer_future is not None and not self._answer_future.done():
                    self._answer_future.set_result(
                        {"sdp": payload.sdp, "type": payload.sdp_type}
                    )
            elif envelope.type == "disconnect":
                break
            elif envelope.type == "error":
                logger.warning("Viewer signaling error: %s", envelope.payload)
            elif envelope.type == "ice_candidate":
                # Non-trickle MVP (intentional): ignore trickle candidates.
                # Peers gather ICE to completion and embed candidates in SDP.
                # See snowlink.rtc.ice_policy.TRICKLE_ICE_ENABLED.
                continue
            else:
                await self._send_error(
                    ws,
                    "UNEXPECTED_MESSAGE",
                    f"Unexpected type {envelope.type} after auth.",
                )

    async def wait_authenticated(self, timeout_s: float | None = None) -> None:
        if timeout_s is None:
            await self._authenticated.wait()
        else:
            await asyncio.wait_for(self._authenticated.wait(), timeout=timeout_s)

    async def wait_answer(self, timeout_s: float) -> dict[str, str]:
        # Shield so wait_for timeouts do not cancel the shared answer future;
        # otherwise the next poll raises CancelledError and share exits early.
        if self._answer_future is None or self._answer_future.cancelled():
            loop = asyncio.get_running_loop()
            self._answer_future = loop.create_future()
        return await asyncio.wait_for(
            asyncio.shield(self._answer_future),
            timeout=timeout_s,
        )

    async def close(self) -> None:
        self._closed = True
        self._state = SignalingState.CLOSING
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._site is not None:
            try:
                await self._site.stop()
            except Exception:
                pass
            self._site = None
        if self._runner is not None:
            try:
                await self._runner.cleanup()
            except Exception:
                pass
            self._runner = None
        self._state = SignalingState.CLOSED

    def _parse_raw(self, raw: str | bytes) -> Envelope:
        if isinstance(raw, str):
            data = raw.encode("utf-8")
        else:
            data = raw
        if len(data) > self.max_message_bytes:
            raise ValueError("message exceeds size limit")
        return parse_envelope(data)

    async def _recv_typed(self, ws: Any, *, expected: str) -> Envelope:
        from aiohttp import WSMsgType

        while True:
            msg = await ws.receive()
            if msg.type in {WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED}:
                raise WebRTCError(
                    failure_for(
                        "SIGNALING_CONNECTION_FAILED",
                        "WebSocket closed during handshake.",
                    )
                )
            if msg.type == WSMsgType.ERROR:
                raise WebRTCError(
                    failure_for(
                        "SIGNALING_CONNECTION_FAILED",
                        "WebSocket error during handshake.",
                    )
                )
            if msg.type != WSMsgType.TEXT:
                continue
            envelope = self._parse_raw(msg.data)
            if envelope.session_id and envelope.session_id != self.pairing.session_id:
                # Allow empty/unknown session_id on first hello from viewer.
                if expected != "hello":
                    await self._send_error(ws, "SESSION_MISMATCH", "Wrong session_id.")
                    continue
            if envelope.type != expected:
                await self._send_error(
                    ws,
                    "UNEXPECTED_MESSAGE",
                    f"Expected {expected}, got {envelope.type}.",
                )
                continue
            return envelope

    async def _send(self, ws: Any, envelope: Envelope) -> None:
        await ws.send_str(envelope.model_dump_json())

    async def _send_error(self, ws: Any, code: str, message: str) -> None:
        try:
            await self._send(
                ws,
                make_envelope(
                    session_id=self.pairing.session_id,
                    msg_type="error",
                    payload=ErrorPayload(code=code, message=message),
                ),
            )
        except Exception:
            logger.debug("Failed to send signaling error", exc_info=True)
