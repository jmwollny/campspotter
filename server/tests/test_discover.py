import pytest

import discover


def test_scout_query_is_a_single_flat_union(monkeypatch):
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        discover,
        "call_overpass_with_retry",
        lambda query: captured.setdefault("query", query),
    )
    discover.get_camping_and_woods(51.0, -1.0, 500)
    query = captured["query"]
    assert "->." not in query
    assert query.count("(around:500,51.0,-1.0)") == 12  # 3 target + 9 red-flag clauses
    assert "out center bb;" in query


@pytest.mark.parametrize(
    "payload, expected_substring",
    [
        (None, "not responding"),
        ({"remark": "oops"}, "malformed"),
        ({"elements": []}, "Nothing found"),
    ],
)
def test_scout_agent_run_errors_are_readable(monkeypatch, payload, expected_substring):
    monkeypatch.setattr(discover, "get_camping_and_woods", lambda *args: payload)
    result = discover.scout_agent_run((51.0, -1.0), 500)
    assert isinstance(result, str) and expected_substring in result


def test_scout_agent_run_accepts_zero_longitude(monkeypatch):
    monkeypatch.setattr(
        discover, "get_camping_and_woods", lambda *args: {"elements": [{"id": 1}]}
    )
    assert discover.scout_agent_run((51.5, 0.0), 500) == [{"id": 1}]
