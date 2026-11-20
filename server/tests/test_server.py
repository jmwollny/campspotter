import asyncio
import json
import time
from typing import cast

import pytest
from fastapi import WebSocket
from fastapi.testclient import TestClient

import models
import pipeline
import server


@pytest.fixture
def client():
    return TestClient(server.app)


def collect(client, payload):
    messages = []
    with client.websocket_connect("/ws/analyze") as ws:
        ws.send_text(payload if isinstance(payload, str) else json.dumps(payload))
        while True:
            try:
                messages.append(ws.receive_json())
            except Exception:  # server closed the socket
                break
    return messages


def test_search_streams_pipeline_messages_over_the_websocket(client, fake_pipeline):
    messages = collect(client, {"lat": 51.0, "lon": -1.0, "radius": 800})
    assert [m["type"] for m in messages] == [
        "status",  # retrieving
        "batch",
        "status",  # roads/water
        "batch",
        "status",  # scoring
        "status",  # outlines
        "final",
        "status",  # complete
    ]
    assert messages[-2]["refined_ids"] == [7]
    assert fake_pipeline["scout"] == ((51.0, -1.0), 800)


@pytest.mark.parametrize(
    "radius, expected",
    [(5, models.MIN_RADIUS_M), (10**9, models.MAX_RADIUS_M), ("750", 750)],
)
def test_radius_is_clamped(client, fake_pipeline, radius, expected):
    collect(client, {"lat": 51.0, "lon": -1.0, "radius": radius})
    assert fake_pipeline["scout"][1] == expected


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        {"lon": -1.0, "radius": 500},
        {"lat": 95, "lon": -1.0},
        {"lat": "abc", "lon": -1.0},
        {"lat": float("nan"), "lon": -1.0},
        [1, 2, 3],
    ],
)
def test_invalid_requests_get_an_error_message(client, fake_pipeline, payload):
    if not isinstance(payload, str):
        payload = json.dumps(payload)
    messages = collect(client, payload)
    assert len(messages) == 1
    assert messages[0]["type"] == "error"
    assert messages[0]["msg"].startswith("Invalid search request")
    assert "scout" not in fake_pipeline


def test_unexpected_exception_becomes_error_message(client, fake_pipeline, monkeypatch):
    def boom(sites):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(pipeline, "enrich_sites", boom)
    messages = collect(client, {"lat": 51.0, "lon": -1.0, "radius": 500})
    assert messages[-1] == {"type": "error", "msg": "kaboom"}


class DisconnectingSocket:
    """Just enough of a WebSocket for run_until_disconnected: disconnects on cue."""

    def __init__(self) -> None:
        self.closed_by_browser = asyncio.Event()

    async def receive(self) -> dict:
        await self.closed_by_browser.wait()
        return {"type": "websocket.disconnect", "code": 1000}


async def no_emit(message: models.ServerMessage) -> None:
    pass


def run_with(search, socket: DisconnectingSocket, *, disconnect_after: float | None):
    async def main():
        if disconnect_after is not None:
            asyncio.get_running_loop().call_later(
                disconnect_after, socket.closed_by_browser.set
            )
        await server.run_until_disconnected(
            cast(WebSocket, socket), models.SearchRequest(lat=51, lon=-1), emit=no_emit
        )

    asyncio.run(main())


def test_disconnecting_cancels_the_rest_of_the_search(monkeypatch):
    """Cancelling in the browser closes the socket; no later stage should run."""
    progress: list[str] = []

    async def slow_search(request, emit):
        progress.append("started")
        try:
            await asyncio.sleep(5)  # a slow stage
            progress.append("finished")
        except asyncio.CancelledError:
            progress.append("cancelled")
            raise

    monkeypatch.setattr(server, "run_search", slow_search)
    started = time.perf_counter()
    run_with(slow_search, DisconnectingSocket(), disconnect_after=0.05)
    assert progress == ["started", "cancelled"]
    assert time.perf_counter() - started < 1


def test_a_finished_search_is_not_affected(monkeypatch):
    progress: list[str] = []

    async def quick_search(request, emit):
        progress.append("finished")

    monkeypatch.setattr(server, "run_search", quick_search)
    run_with(quick_search, DisconnectingSocket(), disconnect_after=None)
    assert progress == ["finished"]


def test_search_errors_still_reach_the_endpoint(monkeypatch):
    async def failing_search(request, emit):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(server, "run_search", failing_search)
    with pytest.raises(RuntimeError, match="kaboom"):
        run_with(failing_search, DisconnectingSocket(), disconnect_after=None)
