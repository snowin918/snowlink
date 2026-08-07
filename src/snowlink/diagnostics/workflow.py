"""Ordered connectivity checklist (PLAN §6.5)."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from snowlink.constants import DEFAULT_SIGNALING_PORT
from snowlink.net.adapter_models import NetworkAdapter, OperationalStatus
from snowlink.net.adapter_selection import annotate_adapters, find_endpoint_by_ip
from snowlink.net.tcp_diagnostics import validate_ipv4
from snowlink.platform_win.firewall import FIREWALL_SETUP_HINT, probe_firewall_rules

StepStatus = Literal["pass", "fail", "warn", "skip"]


@dataclass(slots=True)
class DiagnosticStepResult:
    step: int
    name: str
    status: StepStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LiveSessionSnapshot:
    """Optional live Share/View state for ICE / media checklist steps."""

    ice_state: str | None = None
    frames: int = 0
    audio_frames: int = 0
    phase: str | None = None
    connection_state: str | None = None


@dataclass(slots=True)
class DiagnosticReport:
    selected_ip: str
    port: int
    steps: list[DiagnosticStepResult] = field(default_factory=list)
    overall: StepStatus = "fail"
    vpn_doc_hint: str = "docs/vpn-lan-access.md"

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_ip": self.selected_ip,
            "port": self.port,
            "overall": self.overall,
            "vpn_doc_hint": self.vpn_doc_hint,
            "steps": [s.to_dict() for s in self.steps],
        }

    def format_text(self) -> str:
        lines = [
            f"Connectivity checklist — {self.selected_ip}:{self.port}",
            f"Overall: {self.overall.upper()}",
            "",
        ]
        for step in self.steps:
            lines.append(
                f"{step.step}. [{step.status.upper()}] {step.name}: {step.message}"
            )
        lines.append("")
        lines.append(f"VPN / LAN guidance: {self.vpn_doc_hint}")
        return "\n".join(lines)


def _score_overall(steps: Sequence[DiagnosticStepResult]) -> StepStatus:
    statuses = [s.status for s in steps if s.status != "skip"]
    if not statuses:
        return "skip"
    if any(s == "fail" for s in statuses):
        return "fail"
    if any(s == "warn" for s in statuses):
        return "warn"
    return "pass"


def _check_ip_active(
    selected_ip: str,
    adapters: Sequence[NetworkAdapter],
) -> DiagnosticStepResult:
    try:
        validate_ipv4(selected_ip, kind="local")
    except ValueError:
        return DiagnosticStepResult(
            1,
            "Selected IP active",
            "fail",
            f"Invalid IPv4 address: {selected_ip!r}",
            {"code": "INVALID_LOCAL_IP"},
        )
    annotated = annotate_adapters(list(adapters))
    try:
        endpoint = find_endpoint_by_ip(annotated, selected_ip)
    except ValueError:
        return DiagnosticStepResult(
            1,
            "Selected IP active",
            "fail",
            f"{selected_ip} is not assigned to any local adapter.",
            {"code": "IP_NOT_ASSIGNED"},
        )
    adapter = endpoint.adapter
    status = adapter.operational_status
    up = status in {OperationalStatus.UP, OperationalStatus.UNKNOWN} or str(status).lower() in {
        "up",
        "unknown",
    }
    cat = (
        adapter.category.value
        if hasattr(adapter.category, "value")
        else str(adapter.category)
    )
    if not up:
        return DiagnosticStepResult(
            1,
            "Selected IP active",
            "fail",
            f"{selected_ip} is on {adapter.friendly_name} but interface is not up ({status}).",
            {"adapter": adapter.friendly_name, "category": cat, "status": str(status)},
        )
    return DiagnosticStepResult(
        1,
        "Selected IP active",
        "pass",
        f"{selected_ip} is active on {adapter.friendly_name} [{cat}].",
        {"adapter": adapter.friendly_name, "category": cat, "status": str(status)},
    )


def _check_bind(selected_ip: str, port: int) -> DiagnosticStepResult:
    sock: socket.socket | None = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((selected_ip, port))
        sock.listen(1)
        bound = sock.getsockname()
        return DiagnosticStepResult(
            2,
            "Signaling TCP bind",
            "pass",
            f"Opened TCP listener on {bound[0]}:{bound[1]}.",
            {"bound_ip": bound[0], "bound_port": bound[1], "code": None},
        )
    except OSError as exc:
        winerr = getattr(exc, "winerror", None)
        code = "BIND_FAILED"
        if getattr(exc, "errno", None) in {98, 48, 10048} or winerr == 10048:
            code = "PORT_IN_USE"
        return DiagnosticStepResult(
            2,
            "Signaling TCP bind",
            "fail",
            f"Could not bind {selected_ip}:{port} ({type(exc).__name__}). "
            "Address may not be local or the port is in use.",
            {"code": code, "errno": getattr(exc, "errno", None), "winerror": winerr},
        )
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def _check_getsockname(bind_step: DiagnosticStepResult) -> DiagnosticStepResult:
    if bind_step.status != "pass":
        return DiagnosticStepResult(
            3,
            "Listen address (getsockname)",
            "skip",
            "Skipped because bind test did not succeed.",
            {},
        )
    bound_ip = bind_step.details.get("bound_ip")
    bound_port = bind_step.details.get("bound_port")
    return DiagnosticStepResult(
        3,
        "Listen address (getsockname)",
        "pass",
        f"Listener reported getsockname() = {bound_ip}:{bound_port}.",
        {"getsockname": f"{bound_ip}:{bound_port}"},
    )


async def _probe_signaling_handshake(
    selected_ip: str,
    port: int,
    *,
    remote_ip: str | None,
) -> DiagnosticStepResult:
    """Probe hello → pairing_challenge path (local loopback or remote)."""
    target = remote_ip or selected_ip
    try:
        from snowlink.net.signaling_server import WsSignalingServer
        from snowlink.security.pairing import PairingAuthority
        from snowlink.security.secrets import generate_session_id
    except Exception as exc:  # noqa: BLE001
        return DiagnosticStepResult(
            4,
            "Signaling handshake",
            "fail",
            f"Signaling modules unavailable: {exc}",
            {"code": "SIGNALING_UNAVAILABLE"},
        )

    # Remote-only probe when remote_ip differs: just try TCP connect + hello via client.
    if remote_ip and remote_ip != selected_ip:
        return await _remote_hello_probe(remote_ip, port, source_ip=selected_ip)

    server: WsSignalingServer | None = None
    try:
        from aiohttp import ClientSession, ClientTimeout

        pairing = PairingAuthority(session_id=generate_session_id(), code="000000")

        async def _deny(_info: Any) -> bool:
            return False

        async def _no_offer() -> dict[str, str]:
            raise RuntimeError("offer not used in diagnostics probe")

        server = WsSignalingServer(
            bind_ip=selected_ip,
            port=port,
            pairing=pairing,
            offer_factory=_no_offer,
            approval_handler=_deny,
            auto_approve=False,
        )
        await server.start()
        listen = f"{selected_ip}:{server.port}"

        timeout = ClientTimeout(total=5.0, connect=3.0, sock_connect=3.0)
        async with ClientSession(timeout=timeout) as session:
            async with session.ws_connect(
                f"ws://{selected_ip}:{server.port}/ws",
                heartbeat=10.0,
            ) as ws:
                from snowlink.net.messages import HelloPayload, make_envelope, parse_envelope

                await ws.send_json(
                    make_envelope(
                        session_id="pending",
                        msg_type="hello",
                        payload=HelloPayload(),
                    ).model_dump(mode="json")
                )
                msg = await asyncio.wait_for(ws.receive(), timeout=3.0)
                data = getattr(msg, "data", None)
                if data is None:
                    return DiagnosticStepResult(
                        4,
                        "Signaling handshake",
                        "fail",
                        "WebSocket connected but no hello_ack received.",
                        {"code": "HANDSHAKE_NO_ACK", "listen": listen},
                    )
                env = parse_envelope(
                    data if isinstance(data, (str, bytes)) else str(data)
                )
                if env.type != "hello_ack":
                    return DiagnosticStepResult(
                        4,
                        "Signaling handshake",
                        "fail",
                        f"Expected hello_ack, got {env.type!r}.",
                        {"code": "HANDSHAKE_UNEXPECTED", "type": env.type},
                    )
                msg2 = await asyncio.wait_for(ws.receive(), timeout=3.0)
                data2 = getattr(msg2, "data", None)
                env2 = parse_envelope(
                    data2 if isinstance(data2, (str, bytes)) else str(data2)
                )
                if env2.type != "pairing_challenge":
                    return DiagnosticStepResult(
                        4,
                        "Signaling handshake",
                        "warn",
                        f"hello_ack ok but expected pairing_challenge, got {env2.type!r}.",
                        {"listen": listen, "type": env2.type},
                    )
        return DiagnosticStepResult(
            4,
            "Signaling handshake",
            "pass",
            f"Local handshake ok (hello → pairing_challenge) on {listen}.",
            {"listen": listen, "target": target},
        )
    except Exception as exc:  # noqa: BLE001
        return DiagnosticStepResult(
            4,
            "Signaling handshake",
            "fail",
            f"Handshake probe failed: {type(exc).__name__}: {exc}. "
            f"Check firewall and VPN LAN allow ({FIREWALL_SETUP_HINT})",
            {"code": "HANDSHAKE_FAILED", "error": str(exc)},
        )
    finally:
        if server is not None:
            try:
                await server.close()
            except Exception:
                pass


async def _remote_hello_probe(
    remote_ip: str,
    port: int,
    *,
    source_ip: str | None,
) -> DiagnosticStepResult:
    try:
        from aiohttp import ClientSession, ClientTimeout, TCPConnector

        from snowlink.net.messages import HelloPayload, make_envelope, parse_envelope

        timeout = ClientTimeout(total=6.0, connect=4.0, sock_connect=4.0)
        connector = TCPConnector(local_addr=(source_ip, 0) if source_ip else None)
        async with ClientSession(timeout=timeout, connector=connector) as session:
            async with session.ws_connect(
                f"ws://{remote_ip}:{port}/ws",
                heartbeat=10.0,
            ) as ws:
                await ws.send_json(
                    make_envelope(
                        session_id="pending",
                        msg_type="hello",
                        payload=HelloPayload(),
                    ).model_dump(mode="json")
                )
                msg = await asyncio.wait_for(ws.receive(), timeout=4.0)
                raw = msg.data
                if not isinstance(raw, (str, bytes)):
                    raw = str(raw)
                env = parse_envelope(raw)
                if env.type != "hello_ack":
                    return DiagnosticStepResult(
                        4,
                        "Signaling handshake",
                        "fail",
                        f"Remote peer responded with {env.type!r}, not hello_ack.",
                        {"remote": f"{remote_ip}:{port}"},
                    )
        return DiagnosticStepResult(
            4,
            "Signaling handshake",
            "pass",
            f"Remote signaling hello_ack from {remote_ip}:{port}.",
            {"remote": f"{remote_ip}:{port}"},
        )
    except Exception as exc:  # noqa: BLE001
        return DiagnosticStepResult(
            4,
            "Signaling handshake",
            "fail",
            f"Could not complete remote handshake to {remote_ip}:{port} "
            f"({type(exc).__name__}). Often firewall or VPN LAN block — "
            f"see docs/vpn-lan-access.md.",
            {"code": "FIREWALL_TIMEOUT", "error": str(exc)},
        )


def _check_ice(live: LiveSessionSnapshot | None) -> DiagnosticStepResult:
    if live is None or not live.ice_state:
        return DiagnosticStepResult(
            5,
            "WebRTC ICE",
            "skip",
            "No live session snapshot. Start Share/View, then re-run with live state, "
            "or treat this step as pending until media connects.",
            {},
        )
    ice = live.ice_state.lower()
    if ice in {"connected", "completed"}:
        return DiagnosticStepResult(
            5,
            "WebRTC ICE",
            "pass",
            f"ICE state is {live.ice_state}.",
            {"ice_state": live.ice_state, "connection_state": live.connection_state},
        )
    if ice in {"checking", "new"}:
        return DiagnosticStepResult(
            5,
            "WebRTC ICE",
            "warn",
            f"ICE still {live.ice_state}; wait for connected/completed.",
            {"ice_state": live.ice_state},
        )
    return DiagnosticStepResult(
        5,
        "WebRTC ICE",
        "fail",
        f"ICE state is {live.ice_state} (want connected/completed).",
        {"code": "ICE_FAILED", "ice_state": live.ice_state},
    )


def _check_media(live: LiveSessionSnapshot | None) -> DiagnosticStepResult:
    if live is None:
        return DiagnosticStepResult(
            6,
            "Media frames",
            "skip",
            "No live session snapshot — start Share/View to verify frames arrive.",
            {},
        )
    if live.frames > 0 or live.audio_frames > 0:
        return DiagnosticStepResult(
            6,
            "Media frames",
            "pass",
            f"Media flowing (video_frames={live.frames}, audio_frames={live.audio_frames}).",
            {"frames": live.frames, "audio_frames": live.audio_frames, "phase": live.phase},
        )
    if live.phase in {"sharing", "viewing", "negotiating", "waiting_for_video"}:
        return DiagnosticStepResult(
            6,
            "Media frames",
            "warn",
            f"Session phase={live.phase} but no frames counted yet.",
            {"phase": live.phase, "code": "NO_MEDIA"},
        )
    return DiagnosticStepResult(
        6,
        "Media frames",
        "skip",
        f"Session phase={live.phase or 'idle'}; media check not applicable yet.",
        {"phase": live.phase},
    )


def _check_firewall(port: int) -> DiagnosticStepResult:
    result = probe_firewall_rules(port=port)
    if result.rule_present is True:
        status: StepStatus = "pass"
    elif result.rule_present is False:
        status = "warn"
    else:
        status = "warn"
    return DiagnosticStepResult(
        7,
        "Windows Firewall",
        status,
        result.message,
        {
            "rule_present": result.rule_present,
            **result.details,
            "setup_hint": result.setup_hint,
        },
    )


async def run_connectivity_checklist_async(
    *,
    selected_ip: str,
    port: int = DEFAULT_SIGNALING_PORT,
    adapters: Sequence[NetworkAdapter] | None = None,
    remote_ip: str | None = None,
    live: LiveSessionSnapshot | None = None,
    skip_handshake: bool = False,
) -> DiagnosticReport:
    """Run PLAN §6.5 steps 1–7 in order."""
    from snowlink.platform_win.adapters import enumerate_adapters, is_windows

    if adapters is None:
        if is_windows():
            try:
                adapters = list(enumerate_adapters())
            except Exception:
                adapters = []
        else:
            adapters = []

    steps: list[DiagnosticStepResult] = []
    steps.append(_check_ip_active(selected_ip, adapters))
    bind_step = _check_bind(selected_ip, port)
    steps.append(bind_step)
    steps.append(_check_getsockname(bind_step))

    if skip_handshake or bind_step.status == "fail":
        steps.append(
            DiagnosticStepResult(
                4,
                "Signaling handshake",
                "skip",
                "Skipped (bind failed or handshake disabled).",
                {},
            )
        )
    else:
        # Prefer ephemeral port for local handshake if main port is in use after our close —
        # we already closed bind; use the configured port.
        steps.append(
            await _probe_signaling_handshake(
                selected_ip, port, remote_ip=remote_ip
            )
        )

    steps.append(_check_ice(live))
    steps.append(_check_media(live))
    steps.append(_check_firewall(port))

    report = DiagnosticReport(
        selected_ip=selected_ip,
        port=port,
        steps=steps,
        overall=_score_overall(steps),
    )
    return report


def run_connectivity_checklist(
    *,
    selected_ip: str,
    port: int = DEFAULT_SIGNALING_PORT,
    adapters: Sequence[NetworkAdapter] | None = None,
    remote_ip: str | None = None,
    live: LiveSessionSnapshot | None = None,
    skip_handshake: bool = False,
) -> DiagnosticReport:
    """Synchronous wrapper for :func:`run_connectivity_checklist_async`."""
    return asyncio.run(
        run_connectivity_checklist_async(
            selected_ip=selected_ip,
            port=port,
            adapters=adapters,
            remote_ip=remote_ip,
            live=live,
            skip_handshake=skip_handshake,
        )
    )
