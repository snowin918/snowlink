"""wait_answer must survive poll timeouts without cancelling the shared future."""

from __future__ import annotations

import asyncio

import pytest

from snowlink.net.signaling_server import WsSignalingServer
from snowlink.security.pairing import PairingAuthority


@pytest.mark.asyncio
async def test_wait_answer_timeout_does_not_cancel_future() -> None:
    pairing = PairingAuthority(session_id="sess-wait", code="123456")

    async def offer_factory() -> dict[str, str]:
        return {"sdp": "v=0", "type": "offer"}

    async def approval_handler(_info: object) -> bool:
        return True

    server = WsSignalingServer(
        bind_ip="127.0.0.1",
        port=0,
        pairing=pairing,
        offer_factory=offer_factory,
        approval_handler=approval_handler,
        auto_approve=True,
    )

    with pytest.raises(TimeoutError):
        await server.wait_answer(timeout_s=0.05)

    assert server._answer_future is not None
    assert not server._answer_future.cancelled()
    assert not server._answer_future.done()

    server._answer_future.set_result({"sdp": "v=0", "type": "answer"})
    answer = await server.wait_answer(timeout_s=0.5)
    assert answer["type"] == "answer"
