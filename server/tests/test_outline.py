from typing import Any

import pytest
from conftest import ORIGIN

import outline


def test_refine_sites_adds_geometry_for_selected_ways_only(monkeypatch):
    requested = []

    def fake_fetch(way_ids):
        requested.extend(way_ids)
        return {1: [{"lat": 51.001, "lon": -1.001}, {"lat": 51.001, "lon": -0.999}]}

    monkeypatch.setattr(outline, "fetch_way_geometries", fake_fetch)
    sites: list[dict[str, Any]] = [
        {"id": 1, "type": "way", "distance_to_bbox_m": 500},
        {"id": 2, "type": "node", "distance_to_bbox_m": 50},
        {"id": 3, "type": "way", "distance_to_bbox_m": 70},
    ]
    outline.refine_sites_with_way_geometry(sites, ORIGIN, ["1", 2])
    assert requested == [1]
    assert sites[0]["distance_to_bbox_m"] == pytest.approx(111.3, abs=0.1)
    assert len(sites[0]["geometry"]) == 2
    assert "geometry" not in sites[1] and "geometry" not in sites[2]
