import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import config
import llm_client
import overpass
import select_sites

FIXTURES = Path(__file__).parent / "fixtures"

ORIGIN = (51.0, -1.0)


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch, tmp_path):
    """Tests must never depend on the developer's server/.env or hit the network."""
    for name in config.ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(
        "LOCAL_LLM_ENABLED", "false"
    )  # no LLM unless a test provides one
    # If DEBUG logging is on, Overpass queries are logged to this file: keep it out of the repo.
    monkeypatch.setenv(
        "OVERPASS_QUERY_DEBUG_FILE", str(tmp_path / "overpass_debug.txt")
    )
    # Read settings fresh on every call so tests can change the environment mid-test.
    monkeypatch.setattr(config, "get_settings", config.Settings.from_env)
    monkeypatch.setattr(overpass.time, "sleep", lambda _seconds: None)

    def no_network(*args, **kwargs):
        raise AssertionError("tests must not make real HTTP requests")

    monkeypatch.setattr(overpass.requests, "post", no_network)


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


@pytest.fixture
def fake_pipeline(monkeypatch):
    """Replace every stage the pipeline calls with an instant fake. Returns a call log."""
    import pipeline

    calls: dict[str, object] = {}
    site = {"id": 7, "type": "way", "lat": 51.0, "lon": -1.0, "distance_to_bbox_m": 10}

    def discover_elements(origin, radius):
        calls["scout"] = (origin, radius)
        return [{"id": 7}]

    monkeypatch.setattr(pipeline, "discover_elements", discover_elements)
    monkeypatch.setattr(
        pipeline, "summarise_sites", lambda elements, origin: [dict(site)]
    )
    monkeypatch.setattr(pipeline, "enrich_sites", lambda s: True)
    monkeypatch.setattr(
        pipeline, "score_and_select_sites", lambda s: select_sites.Selection([7])
    )
    monkeypatch.setattr(pipeline, "add_outlines", lambda s, origin, ids: s)
    return calls


class FakeLLM:
    """
    Stands in for the OpenAI client: returns `content` or raises `error`. A list of
    contents gives successive replies (the last one repeats).
    """

    def __init__(self, content=None, error=None):
        self.content, self.error, self.calls = content, error, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        content = self.content
        if isinstance(content, list):
            content = content[min(len(self.calls), len(content)) - 1]
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def use_llm(monkeypatch, fake):
    """Make llm_client talk to `fake` instead of a real provider."""
    chat = llm_client.ChatClient(cast(Any, fake), "fake-model", "ollama")
    monkeypatch.setattr(llm_client, "get_chat_client", lambda: chat)
