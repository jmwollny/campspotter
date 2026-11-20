import json

import pytest
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
        "status",
        "batch",
        "status",
        "batch",
        "status",
        "final",
        "status",
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
