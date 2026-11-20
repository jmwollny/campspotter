import json

import pytest

import geo
import summarise
from tests.conftest import ORIGIN, node, way


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
    assert summarise.is_target_site(tags) is expected


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
    assert summarise.classify_red_flag(tags) == expected


def test_build_site_summaries_keeps_each_sites_own_type_and_bounds():
    """Regression: the red-flag loop used to overwrite the site's element, so every site got the
    type/bounds of the *last red flag* (e.g. a wood reported as a node with no bounds)."""
    wood = way(10, {"natural": "wood"}, 51.001, -1.001, 51.002, -0.999)
    barrier = node(20, {"barrier": "gate"}, 51.0015, -1.0)
    sites = summarise.build_site_summaries([wood, barrier], ORIGIN)
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
        for s in summarise.build_site_summaries(
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
        summarise.build_site_summaries([wood, house], ORIGIN)[0]["nearby_red_flags"]
        == []
    )
    monkeypatch.setenv("MIN_DISTANCE_TO_HAZARD", "150")
    assert (
        len(
            summarise.build_site_summaries([wood, house], ORIGIN)[0]["nearby_red_flags"]
        )
        == 1
    )


def test_origin_inside_a_wood_reports_zero_distance_and_sorts_first():
    """Regression: 0 m was turned into None (falsy) and sorted last."""
    surrounding_wood = way(1, {"natural": "wood"}, 50.99, -1.01, 51.01, -0.99)
    nearby_wood = way(2, {"natural": "wood"}, 51.02, -1.001, 51.03, -0.999)
    sites = summarise.build_site_summaries([nearby_wood, surrounding_wood], ORIGIN)
    assert [s["id"] for s in sites] == [1, 2]
    assert sites[0]["distance_to_bbox_m"] == 0


def test_build_site_summaries_without_origin_does_not_crash():
    wood = way(1, {"natural": "wood"}, 51.0, -1.0, 51.001, -0.999)
    house = node(2, {"building": "yes"}, 51.0005, -0.9995)
    sites = summarise.build_site_summaries([wood, house])
    assert sites[0]["distance_to_bbox_m"] is None
    assert len(sites[0]["nearby_red_flags"]) == 1


def test_build_site_summaries_on_real_overpass_data(real_elements):
    elements_by_key = {(e["type"], e["id"]): e for e in real_elements}
    sites = summarise.build_site_summaries(real_elements, (51.3224410, -1.8934199))

    # 11 woods. The old "any natural/tourism tag" rule also counted a phone-box book swap
    # (tourism=information, node 10245934982) as a camping site.
    assert len(sites) == 11
    assert 10245934982 not in {s["id"] for s in sites}
    for site in sites:
        element = elements_by_key[(site["type"], site["id"])]
        assert summarise.is_target_site(element.get("tags", {}))
        assert site["bounds"] == geo.normalize_bounds(element.get("bounds"))
    distances = [s["distance_to_bbox_m"] for s in sites]
    assert distances == sorted(distances)
    # Different sites see different hazards now.
    assert len({json.dumps(s["nearby_red_flags"]) for s in sites}) > 1
    json.dumps(sites)  # must be serialisable for the websocket
