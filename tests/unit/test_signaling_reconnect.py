"""Unit tests for viewer signaling backoff / retry helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from snowlink.net.signaling_client import WsSignalingClient, signaling_backoff_s
from snowlink.rtc.errors import WebRTCError, failure_for


def test_signaling_backoff_grows_then_caps() -> None:
    assert signaling_backoff_s(1, initial_s=0.5, maximum_s=8.0) == 0.5
    assert signaling_backoff_s(2, initial_s=0.5, maximum_s=8.0) == 1.0
    assert signaling_backoff_s(3, initial_s=0.5, maximum_s=8.0) == 2.0
    assert signaling_backoff_s(10, initial_s=0.5, maximum_s=8.0) == 8.0


@pytest.mark.asyncio
async def test_connect_and_pair_with_retry_succeeds_after_transient_failure() -> None:
    client = WsSignalingClient(
        remote_ip="127.0.0.1",
        port=3847,
        pairing_code="123456",
    )
    attempts: list[int] = []

    async def _fake_connect() -> None:
        attempts.append(len(attempts) + 1)
        if len(attempts) < 2:
            raise WebRTCError(
                failure_for("SIGNALING_CONNECTION_FAILED", "transient")
            )

    with (
        patch.object(client, "connect_and_pair", new=AsyncMock(side_effect=_fake_connect)),
        patch.object(client, "close", new=AsyncMock()),
        patch("snowlink.net.signaling_client.asyncio.sleep", new=AsyncMock()),
    ):
        await client.connect_and_pair_with_retry(max_attempts=3, initial_backoff_s=0.01)

    assert attempts == [1, 2]


@pytest.mark.asyncio
async def test_connect_and_pair_with_retry_does_not_retry_pairing_reject() -> None:
    client = WsSignalingClient(
        remote_ip="127.0.0.1",
        port=3847,
        pairing_code="123456",
    )

    async def _reject() -> None:
        raise WebRTCError(failure_for("PAIRING_REJECTED", "bad code"))

    with patch.object(client, "connect_and_pair", new=AsyncMock(side_effect=_reject)):
        with pytest.raises(WebRTCError) as exc_info:
            await client.connect_and_pair_with_retry(max_attempts=5)
    assert exc_info.value.failure.code == "PAIRING_REJECTED"


@pytest.mark.asyncio
async def test_connect_and_pair_with_retry_respects_stop_event() -> None:
    client = WsSignalingClient(
        remote_ip="127.0.0.1",
        port=3847,
        pairing_code="123456",
    )
    stop = asyncio.Event()
    stop.set()

    with pytest.raises(WebRTCError) as exc_info:
        await client.connect_and_pair_with_retry(max_attempts=3, stop_event=stop)
    assert "cancelled" in str(exc_info.value).lower()
