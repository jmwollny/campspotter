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
    selection = select_sites.score_and_select_sites(sites, max_candidates=2)
    assert selection.ids[0] == 1
    assert len(selection.ids) == 2
    assert selection.fallback_reason == "no LLM is configured"
    assert all(s["suitability_reason"] == "heuristic fallback" for s in sites)


def test_select_uses_llm_scores_and_drops_unknown_ids(monkeypatch):
    fake = FakeLLM(
        json.dumps(
            {
                "selected_ids": ["3", 999, "1", "3"],
                "evaluations": [
                    {"id": "1", "suitability_score": "85", "reason": "big quiet wood"},
                    {"id": 3, "suitability_score": 140, "reason": "too high"},
                ],
            }
        )
    )
    use_llm(monkeypatch, fake)
    sites = make_candidates()
    selection = select_sites.score_and_select_sites(sites)

    assert selection.ids == [3, 1]
    assert (
        selection.fallback_reason is None
    )  # 999 was never offered; the repeated 3 counts once
    by_id = {s["id"]: s for s in sites}
    assert by_id[1]["suitability_score"] == 85
    assert by_id[1]["suitability_reason"] == "big quiet wood"
    assert by_id[3]["suitability_score"] == 100  # clamped
    assert by_id[2]["suitability_reason"] == "heuristic fallback"  # not evaluated
    assert len(fake.calls) == 1
    system, user = (m["content"] for m in fake.calls[0]["messages"])
    assert prompts.CAMPING_CRITERIA in system
    assert '"nearby_red_flags": {"BUILDING": 2}' in user
    response_format = fake.calls[0]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "SelectionResponse"


def test_invalid_reply_is_retried_once_with_a_stricter_prompt(monkeypatch):
    bad = json.dumps({"selected_ids": ["abc"], "evaluations": []})
    good = json.dumps(
        {"selected_ids": [2], "evaluations": [{"id": 2, "suitability_score": 70}]}
    )
    fake = FakeLLM([bad, good])
    use_llm(monkeypatch, fake)
    sites = make_candidates()

    assert select_sites.score_and_select_sites(sites) == select_sites.Selection([2])
    assert len(fake.calls) == 2
    retry_messages = fake.calls[1]["messages"]
    assert retry_messages[:2] == fake.calls[0]["messages"]
    assert retry_messages[2] == {"role": "assistant", "content": bad}
    assert retry_messages[3]["role"] == "user"
    assert "selected_ids.0" in retry_messages[3]["content"]  # says what was wrong
    assert '"SelectionResponse"' in retry_messages[3]["content"]  # includes the schema


@pytest.mark.parametrize(
    "replies",
    [
        ["I can't answer that", "still no JSON"],
        ['{"evaluations": [{"id": 1, "suitability_score": "n/a"}]}'] * 2,
    ],
)
def test_two_invalid_replies_fall_back_to_the_heuristic(monkeypatch, replies):
    fake = FakeLLM(replies)
    use_llm(monkeypatch, fake)
    sites = make_candidates()
    selection = select_sites.score_and_select_sites(sites)
    assert selection.ids[0] == 1
    assert selection.fallback_reason == "the LLM's replies weren't usable"
    assert len(fake.calls) == 2
    assert all(s["suitability_reason"] == "heuristic fallback" for s in sites)


def test_provider_errors_fall_back_without_a_retry(monkeypatch):
    fake = FakeLLM(error=ConnectionError("ollama down"))
    use_llm(monkeypatch, fake)
    sites = make_candidates()
    selection = select_sites.score_and_select_sites(sites)
    assert selection.ids[0] == 1
    assert selection.fallback_reason == "the LLM request failed"
    assert len(fake.calls) == 1
    assert all(s["suitability_reason"] == "heuristic fallback" for s in sites)


def test_select_falls_back_when_llm_returns_no_valid_ids(monkeypatch):
    use_llm(
        monkeypatch, FakeLLM(json.dumps({"selected_ids": [12345], "evaluations": []}))
    )
    selected = select_sites.score_and_select_sites(
        make_candidates(), max_candidates=1
    ).ids
    assert selected == [1]


def test_select_respects_candidate_pool_size(monkeypatch):
    monkeypatch.setenv("LLM_CANDIDATE_POOL_SIZE", "2")
    sites = make_candidates()
    select_sites.score_and_select_sites(sites)
    assert "suitability_score" not in sites[2]


def test_select_with_no_sites_returns_empty(monkeypatch):
    fake = FakeLLM("{}")
    use_llm(monkeypatch, fake)
    assert select_sites.score_and_select_sites([]) == select_sites.Selection([])
    assert fake.calls == []
