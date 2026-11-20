import pytest

import geo
from tests.conftest import ORIGIN, way


def test_haversine_one_degree_of_latitude():
    assert geo.haversine_distance_m(51.0, -1.0, 52.0, -1.0) == pytest.approx(
        111_195, rel=1e-3
    )


def test_distance_to_element_inside_bbox_is_zero():
    element = way(1, {}, 50.99, -1.01, 51.01, -0.99)
    distance, point = geo.distance_to_element_m(*ORIGIN, element)
    assert distance == 0
    assert point == {"lat": 51.0, "lon": -1.0}


def test_distance_to_element_falls_back_to_point():
    distance, _ = geo.distance_to_element_m(
        51.0, -1.0, {}, fallback_lat=51.001, fallback_lon=-1.0
    )
    assert distance == pytest.approx(111.2, abs=0.5)


def test_area_from_bounds_and_size_bands():
    area = geo.calculate_way_area_from_bounds_m2(
        {"minlat": 51.0, "minlon": -1.0, "maxlat": 51.001, "maxlon": -0.999}
    )
    assert area == pytest.approx(111.32 * 70.06, rel=0.01)
    assert geo.classify_area_size_band(None) == "unknown"
    assert geo.classify_area_size_band(4_999) == "small"
    assert geo.classify_area_size_band(5_000) == "medium"
    assert geo.classify_area_size_band(50_000) == "large"


def test_nearest_point_on_way_geometry_projects_onto_segment():
    # Horizontal segment 0.001 deg north of the origin, spanning either side of it.
    geometry = [{"lat": 51.001, "lon": -1.001}, {"lat": 51.001, "lon": -0.999}]
    point, distance = geo.nearest_point_on_way_geometry(*ORIGIN, geometry)
    assert point == {"lat": 51.001, "lon": -1.0}
    assert distance == pytest.approx(111.32, abs=0.1)


def test_nearest_point_on_way_geometry_with_invalid_coordinates():
    nan = float("nan")
    geometry = [{"lat": nan, "lon": nan}, {"lat": nan, "lon": nan}]
    assert geo.nearest_point_on_way_geometry(*ORIGIN, geometry) == (None, None)


def test_nearest_point_on_way_geometry_needs_two_points():
    assert geo.nearest_point_on_way_geometry(*ORIGIN, [{"lat": 51, "lon": -1}]) == (
        None,
        None,
    )


def test_get_element_coordinate_handles_zero_values():
    # 0.0 is a valid coordinate (the Greenwich meridian runs through England).
    assert geo.get_element_coordinate({"lat": 51.5, "lon": 0.0}) == (51.5, 0.0)
    assert geo.get_element_coordinate({"center": {"lat": 51.5, "lon": 0.0}}) == (
        51.5,
        0.0,
    )
    assert geo.get_element_coordinate(
        {"bounds": {"minlat": 1, "maxlat": 3, "minlon": -1, "maxlon": 1}}
    ) == (2, 0)
    assert geo.get_element_coordinate({}) is None
