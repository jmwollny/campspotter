import pytest

import enrich


def test_enrichment_covers_the_whole_llm_pool(monkeypatch):
    """Regression: enrichment was hard-coded to 10 sites while the LLM pool could be larger."""
    monkeypatch.setenv("LLM_CANDIDATE_POOL_SIZE", "12")
    monkeypatch.setattr(
        enrich,
        "fetch_roads_and_water",
        lambda sites, radius_meters: [
            {
                "type": "way",
                "tags": {"highway": "primary"},
                "center": {"lat": 51.0, "lon": -1.0},
            },
        ],
    )
    sites = [{"id": i, "lat": 51.0 + i * 0.001, "lon": -1.0} for i in range(15)]
    enrich.enrich_sites(sites)
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
    metrics = enrich.road_and_water_distances(51.0, -1.0, elements)
    assert metrics["distance_to_major_road_m"] == pytest.approx(111.2, abs=0.5)
    assert metrics["distance_to_water_m"] == pytest.approx(210, abs=2)


@pytest.mark.parametrize(
    "response", [None, {}, {"remark": "busy"}, {"elements": "not a list"}]
)
def test_context_fetch_tolerates_bad_overpass_responses(monkeypatch, response):
    monkeypatch.setattr(enrich, "call_overpass_with_retry", lambda query: response)
    sites = [{"id": 1, "lat": 51.0, "lon": -1.0}]
    assert enrich.fetch_roads_and_water(sites) == []
