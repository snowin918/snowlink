"""Integration: second viewer is rejected while slot is taken."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("aiohttp")
pytest.importorskip("aiortc")

from snowlink.net.signaling_server import WsSignalingServer
from snowlink.security.pairing import PairingAuthority, PairingRequestInfo
from snowlink.security.secrets import generate_session_id


@pytest.mark.asyncio
async def test_second_viewer_slot_taken() -> None:
    pairing = PairingAuthority(session_id=generate_session_id(), code="424242")
    offers = 0

    async def offer_factory() -> dict[str, str]:
        nonlocal offers
        offers += 1
        if offers > 1:
            from snowlink.rtc.errors import WebRTCError, failure_for

            raise WebRTCError(
                failure_for(
                    "VIEWER_SLOT_TAKEN",
                    "A viewer is already connected to this share session.",
                )
            )
        return {"sdp": "v=0", "type": "offer"}

    async def approve(_info: PairingRequestInfo) -> bool:
        return True

    server = WsSignalingServer(
        bind_ip="127.0.0.1",
        port=0,
        pairing=pairing,
        offer_factory=offer_factory,
        approval_handler=approve,
        auto_approve=True,
    )
    await server.start()
    assert server.port > 0

    from snowlink.net.signaling_client import WsSignalingClient

    client1 = WsSignalingClient(
        remote_ip="127.0.0.1",
        port=server.port,
        pairing_code="424242",
    )
    await client1.connect_and_pair()
    # Mark viewer taken as the real share path does after auth.
    server._viewer_taken = True  # noqa: SLF001

    client2 = WsSignalingClient(
        remote_ip="127.0.0.1",
        port=server.port,
        pairing_code="424242",
    )
    with pytest.raises(Exception):
        await client2.connect_and_pair()

    await client1.close()
    await client2.close()
    await server.close()
