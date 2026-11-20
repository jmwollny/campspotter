from typing import Any

import pytest

import outline
from tests.conftest import ORIGIN


def test_add_outlines_only_for_selected_ways(monkeypatch):
    requested = []

    def fake_fetch(way_ids):
        requested.extend(way_ids)
        return {1: [{"lat": 51.001, "lon": -1.001}, {"lat": 51.001, "lon": -0.999}]}

    monkeypatch.setattr(outline, "fetch_outlines", fake_fetch)
    sites: list[dict[str, Any]] = [
        {"id": 1, "type": "way", "distance_to_bbox_m": 500},
        {"id": 2, "type": "node", "distance_to_bbox_m": 50},
        {"id": 3, "type": "way", "distance_to_bbox_m": 70},
    ]
    outline.add_outlines(sites, ORIGIN, ["1", 2])
    assert requested == [1]
    assert sites[0]["distance_to_bbox_m"] == pytest.approx(111.3, abs=0.1)
    assert len(sites[0]["geometry"]) == 2
    assert "geometry" not in sites[1] and "geometry" not in sites[2]
