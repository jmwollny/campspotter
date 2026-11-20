import json
from pathlib import Path

import pytest

import scout

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    """Tests must never depend on the developer's server/.env or hit the network."""
    for name in (
        "LOCAL_LLM_ENABLED",
        "GEMINI_API_KEY",
        "OLLAMA_MODEL",
        "GEMINI_MODEL",
        "LLM_CANDIDATE_POOL_SIZE",
        "MIN_DISTANCE_TO_HAZARD",
        "OVERPASS_URLS",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(
        "LOCAL_LLM_ENABLED", "false"
    )  # no LLM unless a test provides one
    monkeypatch.setattr(scout.time, "sleep", lambda _seconds: None)

    def no_network(*args, **kwargs):
        raise AssertionError("tests must not make real HTTP requests")

    monkeypatch.setattr(scout.requests, "post", no_network)


@pytest.fixture
def real_elements():
    return json.loads((FIXTURES / "overpass_kaw_51.322_-1.893_r800.json").read_text())


def way(id, tags, minlat, minlon, maxlat, maxlon):
    return {
        "type": "way",
        "id": id,
        "tags": tags,
        "bounds": {
            "minlat": minlat,
            "minlon": minlon,
            "maxlat": maxlat,
            "maxlon": maxlon,
        },
        "center": {"lat": (minlat + maxlat) / 2, "lon": (minlon + maxlon) / 2},
    }


def node(id, tags, lat, lon):
    return {"type": "node", "id": id, "tags": tags, "lat": lat, "lon": lon}
