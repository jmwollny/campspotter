import json
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import node, way

import config
import scout

ORIGIN = (51.0, -1.0)


# --------------------------------------------------------------------------- #
# Geometry helpers
# --------------------------------------------------------------------------- #


def test_haversine_one_degree_of_latitude():
    assert scout.haversine_distance_m(51.0, -1.0, 52.0, -1.0) == pytest.approx(
        111_195, rel=1e-3
    )


def test_distance_to_element_inside_bbox_is_zero():
    element = way(1, {}, 50.99, -1.01, 51.01, -0.99)
    distance, point = scout.distance_to_element_m(*ORIGIN, element)
    assert distance == 0
    assert point == {"lat": 51.0, "lon": -1.0}


def test_distance_to_element_falls_back_to_point():
    distance, _ = scout.distance_to_element_m(
        51.0, -1.0, {}, fallback_lat=51.001, fallback_lon=-1.0
    )
    assert distance == pytest.approx(111.2, abs=0.5)


def test_area_from_bounds_and_size_bands():
    area = scout.calculate_way_area_from_bounds_m2(
        {"minlat": 51.0, "minlon": -1.0, "maxlat": 51.001, "maxlon": -0.999}
    )
    assert area == pytest.approx(111.32 * 70.06, rel=0.01)
    assert scout.classify_area_size_band(None) == "unknown"
    assert scout.classify_area_size_band(4_999) == "small"
    assert scout.classify_area_size_band(5_000) == "medium"
    assert scout.classify_area_size_band(50_000) == "large"


def test_nearest_point_on_way_geometry_projects_onto_segment():
    # Horizontal segment 0.001 deg north of the origin, spanning either side of it.
    geometry = [{"lat": 51.001, "lon": -1.001}, {"lat": 51.001, "lon": -0.999}]
    point, distance = scout.nearest_point_on_way_geometry(*ORIGIN, geometry)
    assert point == {"lat": 51.001, "lon": -1.0}
    assert distance == pytest.approx(111.32, abs=0.1)


def test_nearest_point_on_way_geometry_with_invalid_coordinates():
    nan = float("nan")
    geometry = [{"lat": nan, "lon": nan}, {"lat": nan, "lon": nan}]
    assert scout.nearest_point_on_way_geometry(*ORIGIN, geometry) == (None, None)


def test_nearest_point_on_way_geometry_needs_two_points():
    assert scout.nearest_point_on_way_geometry(*ORIGIN, [{"lat": 51, "lon": -1}]) == (
        None,
        None,
    )


def test_get_element_coordinate_handles_zero_values():
    # 0.0 is a valid coordinate (the Greenwich meridian runs through England).
    assert scout.get_element_coordinate({"lat": 51.5, "lon": 0.0}) == (51.5, 0.0)
    assert scout.get_element_coordinate({"center": {"lat": 51.5, "lon": 0.0}}) == (
        51.5,
        0.0,
    )
    assert scout.get_element_coordinate(
        {"bounds": {"minlat": 1, "maxlat": 3, "minlon": -1, "maxlon": 1}}
    ) == (2, 0)
    assert scout.get_element_coordinate({}) is None


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "tags, expected",
    [
        ({"natural": "wood"}, True),
        ({"landuse": "forest"}, True),
        ({"natural": "tree_group"}, True),
        ({"natural": "wood", "amenity": "school"}, False),
        (
            {"building": "hotel", "tourism": "hotel"},
            False,
        ),  # used to be treated as a camping target
        ({"natural": "water"}, False),
        ({"building": "yes"}, False),
    ],
)
def test_is_target_site(tags, expected):
    assert scout.is_target_site(tags) is expected


@pytest.mark.parametrize(
    "tags, expected",
    [
        ({"barrier": "fence"}, "BARRIER"),
        ({"railway": "rail"}, "RAILWAY"),
        ({"amenity": "school"}, "SCHOOL"),
        ({"leisure": "pitch"}, "PITCH"),  # used to be mislabelled PLAYGROUND
        ({"landuse": "residential"}, "RESIDENTIAL"),
        ({"amenity": "pub", "building": "yes"}, "PUB"),
        ({"building": "house"}, "BUILDING"),
    ],
)
def test_classify_red_flag(tags, expected):
    assert scout.classify_red_flag(tags) == expected


# --------------------------------------------------------------------------- #
# build_site_summaries
# --------------------------------------------------------------------------- #


def test_build_site_summaries_keeps_each_sites_own_type_and_bounds():
    """Regression: the red-flag loop used to overwrite the site's element, so every site got the
    type/bounds of the *last red flag* (e.g. a wood reported as a node with no bounds)."""
    wood = way(10, {"natural": "wood"}, 51.001, -1.001, 51.002, -0.999)
    barrier = node(20, {"barrier": "gate"}, 51.0015, -1.0)
    sites = scout.build_site_summaries([wood, barrier], ORIGIN)
    assert len(sites) == 1
    assert sites[0]["type"] == "way"
    assert sites[0]["bounds"] == {
        "minlat": 51.001,
        "minlon": -1.001,
        "maxlat": 51.002,
        "maxlon": -0.999,
    }


def test_red_flags_are_measured_from_each_site_not_the_origin():
    """Regression: hazards used to be measured from the search origin, so every site got the same list."""
    near_wood = way(1, {"natural": "wood"}, 51.0005, -1.0005, 51.001, -0.9995)
    far_wood = way(
        2, {"natural": "wood"}, 51.009, -1.0005, 51.0095, -0.9995
    )  # ~1 km north
    house_by_far_wood = way(3, {"building": "house"}, 51.0096, -1.0001, 51.0097, -1.0)
    sites = {
        s["id"]: s
        for s in scout.build_site_summaries(
            [near_wood, far_wood, house_by_far_wood], ORIGIN
        )
    }

    assert sites[1]["nearby_red_flags"] == []
    assert [h["type"] for h in sites[2]["nearby_red_flags"]] == ["BUILDING"]
    assert sites[2]["nearby_red_flags"][0]["distance_to_red_flag_m"] < 50


def test_hazard_radius_is_configurable(monkeypatch):
    wood = way(1, {"natural": "wood"}, 51.0005, -1.0005, 51.001, -0.9995)
    house = node(
        2, {"building": "house"}, 51.002, -1.0
    )  # ~110 m north of the wood's edge
    monkeypatch.setenv("MIN_DISTANCE_TO_HAZARD", "50")
    assert (
        scout.build_site_summaries([wood, house], ORIGIN)[0]["nearby_red_flags"] == []
    )
    monkeypatch.setenv("MIN_DISTANCE_TO_HAZARD", "150")
    assert (
        len(scout.build_site_summaries([wood, house], ORIGIN)[0]["nearby_red_flags"])
        == 1
    )


def test_origin_inside_a_wood_reports_zero_distance_and_sorts_first():
    """Regression: 0 m was turned into None (falsy) and sorted last."""
    surrounding_wood = way(1, {"natural": "wood"}, 50.99, -1.01, 51.01, -0.99)
    nearby_wood = way(2, {"natural": "wood"}, 51.02, -1.001, 51.03, -0.999)
    sites = scout.build_site_summaries([nearby_wood, surrounding_wood], ORIGIN)
    assert [s["id"] for s in sites] == [1, 2]
    assert sites[0]["distance_to_bbox_m"] == 0


def test_build_site_summaries_without_origin_does_not_crash():
    wood = way(1, {"natural": "wood"}, 51.0, -1.0, 51.001, -0.999)
    house = node(2, {"building": "yes"}, 51.0005, -0.9995)
    sites = scout.build_site_summaries([wood, house])
    assert sites[0]["distance_to_bbox_m"] is None
    assert len(sites[0]["nearby_red_flags"]) == 1


def test_build_site_summaries_on_real_overpass_data(real_elements):
    elements_by_key = {(e["type"], e["id"]): e for e in real_elements}
    sites = scout.build_site_summaries(real_elements, (51.3224410, -1.8934199))

    # 11 woods. The old "any natural/tourism tag" rule also counted a phone-box book swap
    # (tourism=information, node 10245934982) as a camping site.
    assert len(sites) == 11
    assert 10245934982 not in {s["id"] for s in sites}
    for site in sites:
        element = elements_by_key[(site["type"], site["id"])]
        assert scout.is_target_site(element.get("tags", {}))
        assert site["bounds"] == scout.normalize_bounds(element.get("bounds"))
    distances = [s["distance_to_bbox_m"] for s in sites]
    assert distances == sorted(distances)
    # Different sites see different hazards now.
    assert len({json.dumps(s["nearby_red_flags"]) for s in sites}) > 1
    json.dumps(sites)  # must be serialisable for the websocket


# --------------------------------------------------------------------------- #
# Scoring / LLM selection
# --------------------------------------------------------------------------- #


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
    scores = [scout.compute_heuristic_suitability(s) for s in sites]
    assert scores[0] > scores[1]
    assert all(0 <= score <= 100 for score in scores)


def test_heuristic_penalises_red_flags_but_not_barriers():
    base = {"terrain_description": "natural:wood", "nearby_red_flags": []}
    with_buildings = {**base, "nearby_red_flags": [{"type": "BUILDING"}] * 3}
    with_barriers = {**base, "nearby_red_flags": [{"type": "BARRIER"}] * 3}
    assert scout.compute_heuristic_suitability(
        with_buildings
    ) < scout.compute_heuristic_suitability(base)
    assert scout.compute_heuristic_suitability(
        with_barriers
    ) == scout.compute_heuristic_suitability(base)


@pytest.mark.parametrize(
    "text, expected",
    [
        ('```json\n{"selected_ids": [1]}\n```', {"selected_ids": [1]}),
        ('Sure! {"a": {"b": 2}} hope that helps', {"a": {"b": 2}}),
        ("no json here", None),
        ("{not valid}", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_json_object_from_text(text, expected):
    assert scout.parse_json_object_from_text(text) == expected


class FakeLLM:
    def __init__(self, content=None, error=None):
        self.content, self.error, self.calls = content, error, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def use_llm(monkeypatch, fake):
    monkeypatch.setattr(scout, "get_chat_client", lambda: (fake, "fake-model"))


def test_select_without_llm_uses_heuristic():
    sites = make_candidates()
    selected = scout.llm_select_geom_candidates("criteria", sites, max_candidates=2)
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
    selected = scout.llm_select_geom_candidates("criteria", sites)

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
    selected = scout.llm_select_geom_candidates(
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
    assert scout.llm_select_geom_candidates("criteria", sites)[0] == 1
    assert all(s["suitability_reason"] == "heuristic fallback" for s in sites)


def test_select_respects_candidate_pool_size(monkeypatch):
    monkeypatch.setenv("LLM_CANDIDATE_POOL_SIZE", "2")
    sites = make_candidates()
    scout.llm_select_geom_candidates("criteria", sites)
    assert "suitability_score" not in sites[2]


def test_select_with_no_sites_returns_empty(monkeypatch):
    fake = FakeLLM("{}")
    use_llm(monkeypatch, fake)
    assert scout.llm_select_geom_candidates("criteria", []) == []
    assert fake.calls == []


def test_criteria_falls_back_on_error_and_empty_reply(monkeypatch):
    use_llm(monkeypatch, FakeLLM(error=TimeoutError()))
    assert scout.llm_wild_camping_criteria() == scout.DEFAULT_CRITERIA
    use_llm(monkeypatch, FakeLLM("   "))
    assert scout.llm_wild_camping_criteria() == scout.DEFAULT_CRITERIA
    use_llm(monkeypatch, FakeLLM("- flat ground"))
    assert scout.llm_wild_camping_criteria() == "- flat ground"


def test_get_chat_client_selection(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_ENABLED", "true")
    monkeypatch.setenv("OLLAMA_MODEL", "my-model")
    client, model = scout.get_chat_client()
    assert model == "my-model" and "11434" in str(client.base_url)

    monkeypatch.setenv("LOCAL_LLM_ENABLED", "false")
    assert scout.get_chat_client() == (None, None)

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client, model = scout.get_chat_client()
    assert model == config.DEFAULT_GEMINI_MODEL and "googleapis" in str(client.base_url)


# --------------------------------------------------------------------------- #
# Overpass / pipeline
# --------------------------------------------------------------------------- #


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code, self._payload, self.text = status_code, payload, text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def test_overpass_tries_next_mirror_on_failure(monkeypatch):
    monkeypatch.setenv(
        "OVERPASS_URLS", "https://a.example, https://b.example ,https://c.example"
    )
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        if url == "https://a.example":
            raise scout.requests.exceptions.ConnectTimeout("dead mirror")
        if url == "https://b.example":
            return FakeResponse(502, text="at capacity")
        return FakeResponse(200, {"elements": [{"id": 1}]})

    monkeypatch.setattr(scout.requests, "post", fake_post)
    assert scout.call_overpass_with_retry("query") == {"elements": [{"id": 1}]}
    assert calls == ["https://a.example", "https://b.example", "https://c.example"]


def test_overpass_stops_on_syntax_error(monkeypatch):
    monkeypatch.setenv("OVERPASS_URLS", "https://a.example,https://b.example")
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return FakeResponse(400, text="parse error")

    monkeypatch.setattr(scout.requests, "post", fake_post)
    assert scout.call_overpass_with_retry("bad query") is None
    assert calls == ["https://a.example"]


def test_overpass_backs_off_exponentially_when_all_mirrors_are_busy(monkeypatch):
    monkeypatch.setenv("OVERPASS_URLS", "https://a.example")
    monkeypatch.setenv("OVERPASS_MAX_ROUNDS", "4")
    monkeypatch.setenv("OVERPASS_BACKOFF_S", "2")
    sleeps: list[float] = []
    attempts: list[str] = []
    monkeypatch.setattr(scout.time, "sleep", sleeps.append)

    def fake_post(url, **kwargs):
        attempts.append(url)
        if len(attempts) < 4:
            return FakeResponse(502, text="at capacity")
        return FakeResponse(200, {"elements": []})

    monkeypatch.setattr(scout.requests, "post", fake_post)
    assert scout.call_overpass_with_retry("query") == {"elements": []}
    assert sleeps == [2, 4, 8]


def test_overpass_gives_up_after_max_rounds(monkeypatch):
    monkeypatch.setenv("OVERPASS_URLS", "https://a.example,https://b.example")
    monkeypatch.setenv("OVERPASS_MAX_ROUNDS", "2")
    attempts: list[str] = []

    def fake_post(url, **kwargs):
        attempts.append(url)
        return FakeResponse(429)

    monkeypatch.setattr(scout.requests, "post", fake_post)
    assert scout.call_overpass_with_retry("query") is None
    assert len(attempts) == 4


def test_scout_query_is_a_single_flat_union(monkeypatch):
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        scout,
        "call_overpass_with_retry",
        lambda query: captured.setdefault("query", query),
    )
    scout.get_camping_and_woods(51.0, -1.0, 500)
    query = captured["query"]
    assert "->." not in query
    assert query.count("(around:500,51.0,-1.0)") == 12  # 3 target + 9 red-flag clauses
    assert "out center bb;" in query


def test_default_mirror_order_tries_reliable_mirror_first():
    assert scout.get_overpass_mirrors()[0] == "https://overpass-api.de/api/interpreter"


@pytest.mark.parametrize(
    "payload, expected_substring",
    [
        (None, "not responding"),
        ({"remark": "oops"}, "malformed"),
        ({"elements": []}, "Nothing found"),
    ],
)
def test_scout_agent_run_errors_are_readable(monkeypatch, payload, expected_substring):
    monkeypatch.setattr(scout, "get_camping_and_woods", lambda *args: payload)
    result = scout.scout_agent_run((51.0, -1.0), 500)
    assert isinstance(result, str) and expected_substring in result


def test_scout_agent_run_accepts_zero_longitude(monkeypatch):
    monkeypatch.setattr(
        scout, "get_camping_and_woods", lambda *args: {"elements": [{"id": 1}]}
    )
    assert scout.scout_agent_run((51.5, 0.0), 500) == [{"id": 1}]


def test_enrichment_covers_the_whole_llm_pool(monkeypatch):
    """Regression: enrichment was hard-coded to 10 sites while the LLM pool could be larger."""
    monkeypatch.setenv("LLM_CANDIDATE_POOL_SIZE", "12")
    monkeypatch.setattr(
        scout,
        "fetch_context_elements_for_sites",
        lambda sites, radius_meters: [
            {
                "type": "way",
                "tags": {"highway": "primary"},
                "center": {"lat": 51.0, "lon": -1.0},
            },
        ],
    )
    sites = [{"id": i, "lat": 51.0 + i * 0.001, "lon": -1.0} for i in range(15)]
    scout.enrich_sites_with_context_metrics(sites)
    assert all("distance_to_major_road_m" in s for s in sites[:12])
    assert not any("distance_to_major_road_m" in s for s in sites[12:])
    assert sites[0]["distance_to_major_road_m"] == 0


def test_context_metrics_pick_nearest_road_and_water():
    elements = [
        {"tags": {"highway": "primary"}, "center": {"lat": 51.002, "lon": -1.0}},
        {"tags": {"highway": "secondary"}, "center": {"lat": 51.001, "lon": -1.0}},
        {
            "tags": {"highway": "footway"},
            "center": {"lat": 51.0, "lon": -1.0},
        },  # ignored
        {"tags": {"waterway": "stream"}, "lat": 51.0, "lon": -1.003},
    ]
    metrics = scout.compute_site_context_metrics_from_elements(51.0, -1.0, elements)
    assert metrics["distance_to_major_road_m"] == pytest.approx(111.2, abs=0.5)
    assert metrics["distance_to_water_m"] == pytest.approx(210, abs=2)


def test_refine_sites_adds_geometry_for_selected_ways_only(monkeypatch):
    requested = []

    def fake_fetch(way_ids):
        requested.extend(way_ids)
        return {1: [{"lat": 51.001, "lon": -1.001}, {"lat": 51.001, "lon": -0.999}]}

    monkeypatch.setattr(scout, "fetch_way_geometries", fake_fetch)
    sites: list[dict[str, Any]] = [
        {"id": 1, "type": "way", "distance_to_bbox_m": 500},
        {"id": 2, "type": "node", "distance_to_bbox_m": 50},
        {"id": 3, "type": "way", "distance_to_bbox_m": 70},
    ]
    scout.refine_sites_with_way_geometry(sites, ORIGIN, ["1", 2])
    assert requested == [1]
    assert sites[0]["distance_to_bbox_m"] == pytest.approx(111.3, abs=0.1)
    assert len(sites[0]["geometry"]) == 2
    assert "geometry" not in sites[1] and "geometry" not in sites[2]
