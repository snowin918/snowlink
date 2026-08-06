"""Experiment-only HTTP signaling for synthetic WebRTC video (not production).

WARNING: Experiment-only signaling: no production authentication.
Use only on your private LAN.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from snowlink.rtc.errors import WebRTCError, failure_for
from snowlink.rtc.models import MAX_SIGNALING_BODY_BYTES

SIGNALING_WARNING = (
    "Experiment-only signaling: no production authentication. Use only on your private LAN."
)

OfferHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class ClockPingSample:
    t0: float
    t1: float
    t2: float
    t3: float


@dataclass
class SignalingServer:
    """Small aiohttp server bound to a single IPv4 for offer/answer exchange."""

    bind_ip: str
    port: int
    offer_handler: OfferHandler
    max_body_bytes: int = MAX_SIGNALING_BODY_BYTES
    _app: Any = field(default=None, init=False, repr=False)
    _runner: Any = field(default=None, init=False, repr=False)
    _site: Any = field(default=None, init=False, repr=False)
    _busy: bool = field(default=False, init=False)
    _closed: bool = field(default=False, init=False)
    _session_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def start(self) -> None:
        try:
            from aiohttp import web
        except ImportError as exc:
            raise WebRTCError(
                failure_for(
                    "UNEXPECTED_WEBRTC_ERROR",
                    "aiohttp is not installed (required for experiment signaling).",
                    exception=exc,
                )
            ) from exc

        app = web.Application(client_max_size=max(self.max_body_bytes, MAX_SIGNALING_BODY_BYTES))
        app.router.add_get("/health", self._health)
        app.router.add_post("/offer", self._offer)
        app.router.add_post("/ping", self._ping)
        self._app = app
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        try:
            self._site = web.TCPSite(self._runner, host=self.bind_ip, port=self.port)
            await self._site.start()
            # Resolve ephemeral port when bind port was 0.
            server = getattr(self._site, "_server", None)
            if server is not None and getattr(server, "sockets", None):
                sock = server.sockets[0]
                self.port = int(sock.getsockname()[1])
        except OSError as exc:
            await self.close()
            raise WebRTCError(
                failure_for(
                    "SIGNALING_BIND_FAILED",
                    f"Failed to bind signaling server to {self.bind_ip}:{self.port}.",
                    exception=exc,
                )
            ) from exc

    async def _health(self, request: Any) -> Any:
        from aiohttp import web

        _ = request
        return web.json_response(
            {
                "ok": True,
                "warning": SIGNALING_WARNING,
                "busy": self._busy,
            }
        )

    async def _ping(self, request: Any) -> Any:
        from aiohttp import web

        if self._closed:
            return web.json_response({"error": "closed"}, status=503)
        try:
            body = await request.read()
        except Exception as exc:
            return web.json_response({"error": f"read failed: {exc}"}, status=400)
        if len(body) > self.max_body_bytes:
            return web.json_response({"error": "body too large"}, status=413)
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return web.json_response({"error": "malformed json"}, status=400)
        t0 = data.get("t0")
        if not isinstance(t0, (int, float)):
            return web.json_response({"error": "t0 required"}, status=400)
        t1 = time.perf_counter()
        t2 = time.perf_counter()
        return web.json_response({"t0": float(t0), "t1": t1, "t2": t2})

    async def _offer(self, request: Any) -> Any:
        from aiohttp import web

        if self._closed:
            return web.json_response(
                {"error": "signaling closed", "code": "OFFER_REJECTED"},
                status=503,
            )
        async with self._session_lock:
            if self._busy:
                return web.json_response(
                    {
                        "error": "only one active receiver is accepted",
                        "code": "OFFER_REJECTED",
                    },
                    status=409,
                )
            try:
                body = await request.read()
            except Exception as exc:
                return web.json_response(
                    {"error": f"read failed: {exc}", "code": "MALFORMED_SDP"},
                    status=400,
                )
            if len(body) > self.max_body_bytes:
                return web.json_response(
                    {"error": "body too large", "code": "MALFORMED_SDP"},
                    status=413,
                )
            try:
                data = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return web.json_response(
                    {"error": "malformed json", "code": "MALFORMED_SDP"},
                    status=400,
                )
            if not isinstance(data, dict):
                return web.json_response(
                    {"error": "json object required", "code": "MALFORMED_SDP"},
                    status=400,
                )
            sdp = data.get("sdp")
            sdp_type = data.get("type")
            if not isinstance(sdp, str) or not sdp.strip():
                return web.json_response(
                    {"error": "sdp string required", "code": "MALFORMED_SDP"},
                    status=400,
                )
            if not isinstance(sdp_type, str) or sdp_type.lower() != "offer":
                return web.json_response(
                    {"error": "type must be 'offer'", "code": "MALFORMED_SDP"},
                    status=400,
                )
            # Mark busy before releasing the lock so a second client gets 409
            # while offer handling is in progress.
            self._busy = True

        try:
            answer = await self.offer_handler(
                {"sdp": sdp, "type": sdp_type, "client": data.get("client")}
            )
        except WebRTCError as exc:
            self._busy = False
            return web.json_response(
                {"error": exc.failure.message, "code": exc.failure.code},
                status=400,
            )
        except Exception as exc:
            self._busy = False
            return web.json_response(
                {
                    "error": f"offer handling failed: {type(exc).__name__}",
                    "code": "UNEXPECTED_WEBRTC_ERROR",
                },
                status=500,
            )
        return web.json_response(answer)

    def release_busy(self) -> None:
        self._busy = False

    async def close(self) -> None:
        self._closed = True
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


@dataclass
class SignalingClient:
    """HTTP client for Experiment E offer/answer and optional clock ping."""

    remote_ip: str
    port: int
    source_ip: str | None = None
    connect_timeout_s: float = 5.0
    read_timeout_s: float = 10.0
    max_body_bytes: int = MAX_SIGNALING_BODY_BYTES
    _session: Any = field(default=None, init=False, repr=False)

    def _base_url(self) -> str:
        return f"http://{self.remote_ip}:{self.port}"

    async def start(self) -> None:
        try:
            import aiohttp
        except ImportError as exc:
            raise WebRTCError(
                failure_for(
                    "UNEXPECTED_WEBRTC_ERROR",
                    "aiohttp is not installed (required for experiment signaling).",
                    exception=exc,
                )
            ) from exc

        timeout = aiohttp.ClientTimeout(
            total=None,
            connect=self.connect_timeout_s,
            sock_connect=self.connect_timeout_s,
            sock_read=self.read_timeout_s,
        )
        # Local address binding for signaling TCP when source_ip is provided.
        connector = aiohttp.TCPConnector(
            local_addr=(self.source_ip, 0) if self.source_ip else None
        )
        self._session = aiohttp.ClientSession(timeout=timeout, connector=connector)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self._session is None:
            raise WebRTCError(
                failure_for(
                    "SIGNALING_CONNECTION_FAILED",
                    "Signaling client session is not started.",
                )
            )
        url = self._base_url() + path
        body = json.dumps(payload).encode("utf-8")
        if len(body) > self.max_body_bytes:
            raise WebRTCError(
                failure_for(
                    "MALFORMED_SDP",
                    f"Signaling body exceeds {self.max_body_bytes} bytes.",
                )
            )
        try:
            async with self._session.post(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
            ) as resp:
                raw = await resp.read()
                if len(raw) > self.max_body_bytes:
                    raise WebRTCError(
                        failure_for(
                            "MALFORMED_SDP",
                            "Signaling response exceeds size limit.",
                        )
                    )
                try:
                    data = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise WebRTCError(
                        failure_for(
                            "MALFORMED_SDP",
                            "Signaling response was not valid JSON.",
                            exception=exc,
                        )
                    ) from exc
                if resp.status >= 400:
                    code = "OFFER_REJECTED"
                    if isinstance(data, dict) and isinstance(data.get("code"), str):
                        code = data["code"]
                    message = (
                        str(data.get("error"))
                        if isinstance(data, dict) and data.get("error")
                        else f"HTTP {resp.status}"
                    )
                    raise WebRTCError(failure_for(code, message))
                if not isinstance(data, dict):
                    raise WebRTCError(
                        failure_for("MALFORMED_SDP", "Signaling response must be a JSON object.")
                    )
                return data
        except WebRTCError:
            raise
        except TimeoutError as exc:
            raise WebRTCError(
                failure_for(
                    "SIGNALING_TIMEOUT",
                    f"Signaling request to {url} timed out.",
                    exception=exc,
                )
            ) from exc
        except OSError as exc:
            raise WebRTCError(
                failure_for(
                    "SIGNALING_CONNECTION_FAILED",
                    f"Could not connect to signaling at {url}.",
                    exception=exc,
                )
            ) from exc
        except Exception as exc:
            # aiohttp raises ClientConnectorError etc.
            name = type(exc).__name__
            if "Timeout" in name:
                raise WebRTCError(
                    failure_for(
                        "SIGNALING_TIMEOUT",
                        f"Signaling request to {url} timed out.",
                        exception=exc,
                    )
                ) from exc
            raise WebRTCError(
                failure_for(
                    "SIGNALING_CONNECTION_FAILED",
                    f"Signaling connection failed ({name}).",
                    exception=exc,
                )
            ) from exc

    async def exchange_offer(self, offer: dict[str, Any]) -> dict[str, Any]:
        answer = await self.post_json("/offer", offer)
        sdp = answer.get("sdp")
        sdp_type = answer.get("type")
        if not isinstance(sdp, str) or not sdp.strip():
            raise WebRTCError(
                failure_for("ANSWER_REJECTED", "Answer missing sdp string.")
            )
        if not isinstance(sdp_type, str) or sdp_type.lower() != "answer":
            raise WebRTCError(
                failure_for("ANSWER_REJECTED", "Answer type must be 'answer'.")
            )
        return {"sdp": sdp, "type": sdp_type}

    async def clock_ping(self, rounds: int = 8) -> list[ClockPingSample]:
        samples: list[ClockPingSample] = []
        for _ in range(rounds):
            t0 = time.perf_counter()
            data = await self.post_json("/ping", {"t0": t0})
            t3 = time.perf_counter()
            try:
                samples.append(
                    ClockPingSample(
                        t0=float(data["t0"]),
                        t1=float(data["t1"]),
                        t2=float(data["t2"]),
                        t3=t3,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return samples
