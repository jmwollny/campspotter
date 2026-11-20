import json

import pytest

import prompts
import select_sites
from tests.conftest import FakeLLM, use_llm


def make_candidates():
    return [
        {
            "id": 1,
            "type": "way",
            "terrain_description": "natural:wood",
            "area_m2": 80_000,
            "distance_to_major_road_m": 600,
            "distance_to_water_m": 200,
            "nearby_red_flags": [],
        },
        {
            "id": 2,
            "type": "way",
            "terrain_description": "landuse:forest",
            "area_m2": 2_000,
            "distance_to_major_road_m": 50,
            "distance_to_water_m": None,
            "nearby_red_flags": [],
        },
        {
            "id": 3,
            "type": "node",
            "terrain_description": "natural:tree_group",
            "area_m2": None,
            "distance_to_major_road_m": None,
            "distance_to_water_m": None,
            "nearby_red_flags": [{"type": "BUILDING"}, {"type": "BUILDING"}],
        },
    ]


def test_heuristic_prefers_big_quiet_woods():
    sites = make_candidates()
    scores = [select_sites.heuristic_score(s) for s in sites]
    assert scores[0] > scores[1]
    assert all(0 <= score <= 100 for score in scores)


def test_heuristic_penalises_red_flags_but_not_barriers():
    base = {"terrain_description": "natural:wood", "nearby_red_flags": []}
    with_buildings = {**base, "nearby_red_flags": [{"type": "BUILDING"}] * 3}
    with_barriers = {**base, "nearby_red_flags": [{"type": "BARRIER"}] * 3}
    assert select_sites.heuristic_score(with_buildings) < select_sites.heuristic_score(
        base
    )
    assert select_sites.heuristic_score(with_barriers) == select_sites.heuristic_score(
        base
    )


def test_select_without_llm_uses_heuristic():
    sites = make_candidates()
    selected = select_sites.score_and_select_sites("criteria", sites, max_candidates=2)
    assert selected[0] == 1
    assert len(selected) == 2
    assert all(s["suitability_reason"] == "heuristic fallback" for s in sites)


def test_select_normalises_string_ids_and_drops_unknown_ones(monkeypatch):
    fake = FakeLLM(
        json.dumps(
            {
                "selected_ids": ["3", 999, "1", "3", "abc"],
                "evaluations": [
                    {"id": "1", "suitability_score": "85", "reason": "big quiet wood"},
                    {"id": 3, "suitability_score": 140, "reason": "too high"},
                    {
                        "id": 2,
                        "suitability_score": "n/a",
                        "reason": "unparseable score",
                    },
                ],
            }
        )
    )
    use_llm(monkeypatch, fake)
    sites = make_candidates()
    selected = select_sites.score_and_select_sites("criteria", sites)

    assert selected == [3, 1]
    by_id = {s["id"]: s for s in sites}
    assert by_id[1]["suitability_score"] == 85
    assert by_id[1]["suitability_reason"] == "big quiet wood"
    assert by_id[3]["suitability_score"] == 100  # clamped
    assert by_id[2]["suitability_reason"] == "heuristic fallback"
    prompt = fake.calls[0]["messages"][1]["content"]
    assert '"nearby_red_flags": {"BUILDING": 2}' in prompt


def test_select_falls_back_when_llm_returns_no_valid_ids(monkeypatch):
    use_llm(
        monkeypatch, FakeLLM(json.dumps({"selected_ids": [12345], "evaluations": []}))
    )
    selected = select_sites.score_and_select_sites(
        "criteria", make_candidates(), max_candidates=1
    )
    assert selected == [1]


@pytest.mark.parametrize(
    "fake",
    [FakeLLM("I can't answer that"), FakeLLM(error=ConnectionError("ollama down"))],
)
def test_select_falls_back_when_llm_fails(monkeypatch, fake):
    use_llm(monkeypatch, fake)
    sites = make_candidates()
    assert select_sites.score_and_select_sites("criteria", sites)[0] == 1
    assert all(s["suitability_reason"] == "heuristic fallback" for s in sites)


def test_select_respects_candidate_pool_size(monkeypatch):
    monkeypatch.setenv("LLM_CANDIDATE_POOL_SIZE", "2")
    sites = make_candidates()
    select_sites.score_and_select_sites("criteria", sites)
    assert "suitability_score" not in sites[2]


def test_select_with_no_sites_returns_empty(monkeypatch):
    fake = FakeLLM("{}")
    use_llm(monkeypatch, fake)
    assert select_sites.score_and_select_sites("criteria", []) == []
    assert fake.calls == []


def test_criteria_falls_back_on_error_and_empty_reply(monkeypatch):
    use_llm(monkeypatch, FakeLLM(error=TimeoutError()))
    assert select_sites.get_camping_criteria() == prompts.DEFAULT_CRITERIA
    use_llm(monkeypatch, FakeLLM("   "))
    assert select_sites.get_camping_criteria() == prompts.DEFAULT_CRITERIA
    use_llm(monkeypatch, FakeLLM("- flat ground"))
    assert select_sites.get_camping_criteria() == "- flat ground"
