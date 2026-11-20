import asyncio

import pytest

import pipeline
from models import SearchRequest, ServerMessage


def run(request: SearchRequest) -> list[ServerMessage]:
    messages: list[ServerMessage] = []

    async def emit(message: ServerMessage) -> None:
        messages.append(message)

    asyncio.run(pipeline.run_search(request, emit))
    return messages


def test_happy_path_emits_every_stage(fake_pipeline):
    messages = run(SearchRequest(lat=51.0, lon=-1.0, radius=800))
    assert [m.type for m in messages] == [
        "status",
        "batch",
        "status",
        "batch",
        "status",
        "final",
        "status",
    ]
    final = messages[-2]
    assert final.type == "final" and final.refined_ids == [7]
    assert fake_pipeline["scout"] == ((51.0, -1.0), 800)


def test_discover_error_is_emitted_and_stops(fake_pipeline, monkeypatch):
    monkeypatch.setattr(pipeline, "discover_elements", lambda o, r: "Overpass is down")
    monkeypatch.setattr(
        pipeline, "summarise_sites", lambda e, o: pytest.fail("should stop")
    )
    messages = run(SearchRequest(lat=51.0, lon=-1.0))
    assert messages[-1].type == "error"
    assert messages[-1].model_dump() == {"type": "error", "msg": "Overpass is down"}


def test_no_woods_found_is_reported_and_stops(fake_pipeline, monkeypatch):
    monkeypatch.setattr(pipeline, "summarise_sites", lambda e, o: [])
    monkeypatch.setattr(
        pipeline, "score_and_select_sites", lambda s: pytest.fail("LLM not needed")
    )
    messages = run(SearchRequest(lat=51.0, lon=-1.0, radius=300))
    assert messages[-1].type == "error"
    assert "No woods or forests found within 300 m" in messages[-1].model_dump()["msg"]


def test_stage_exceptions_propagate_to_the_caller(fake_pipeline, monkeypatch):
    def boom(sites):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(pipeline, "enrich_sites", boom)
    with pytest.raises(RuntimeError, match="kaboom"):
        run(SearchRequest(lat=51.0, lon=-1.0))
