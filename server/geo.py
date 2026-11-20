"""Geometry helpers: distances, areas and bounding boxes on OSM elements."""

import math
from collections.abc import Mapping, Sequence
from itertools import pairwise

from models import BoundsDict, Coordinate, LatLonDict, OsmElement


def get_element_coordinate(element: OsmElement) -> Coordinate | None:
    """(lat, lon) of an Overpass element from its point, center or bounds; None if unknown."""
    lat, lon = element.get("lat"), element.get("lon")
    if lat is not None and lon is not None:
        return lat, lon
    center = element.get("center") or {}
    lat, lon = center.get("lat"), center.get("lon")
    if lat is not None and lon is not None:
        return lat, lon
    bounds = element.get("bounds") or {}
    if all(
        bounds.get(key) is not None for key in ("minlat", "maxlat", "minlon", "maxlon")
    ):
        return (bounds["minlat"] + bounds["maxlat"]) / 2.0, (
            bounds["minlon"] + bounds["maxlon"]
        ) / 2.0
    return None


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two coordinates."""
    earth_radius_m = 6371000.0
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    )
    return earth_radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def bounds_values(
    bounds: Mapping[str, float] | None,
) -> tuple[float, float, float, float] | None:
    """(minlat, minlon, maxlat, maxlon) from an Overpass bounds dict, or None if incomplete."""
    if not bounds:
        return None
    minlat, minlon = bounds.get("minlat"), bounds.get("minlon")
    maxlat, maxlon = bounds.get("maxlat"), bounds.get("maxlon")
    if minlat is None or minlon is None or maxlat is None or maxlon is None:
        return None
    return minlat, minlon, maxlat, maxlon


def normalize_bounds(bounds: Mapping[str, float] | None) -> BoundsDict | None:
    values = bounds_values(bounds)
    if values is None:
        return None
    minlat, minlon, maxlat, maxlon = values
    return {
        "minlat": round(minlat, 6),
        "minlon": round(minlon, 6),
        "maxlat": round(maxlat, 6),
        "maxlon": round(maxlon, 6),
    }


def distance_to_element_m(
    origin_lat: float,
    origin_lon: float,
    element: OsmElement,
    fallback_lat: float | None = None,
    fallback_lon: float | None = None,
) -> tuple[float | None, LatLonDict | None]:
    """
    Distance from a point to the nearest point of an element's bounding box (0 if inside),
    falling back to point distance when bounds are unavailable. Returns (metres, {lat, lon}).
    """
    values = bounds_values(element.get("bounds"))
    if values is not None:
        minlat, minlon, maxlat, maxlon = values
        nearest_lat = clamp(origin_lat, minlat, maxlat)
        nearest_lon = clamp(origin_lon, minlon, maxlon)
        distance = haversine_distance_m(
            origin_lat, origin_lon, nearest_lat, nearest_lon
        )
        return distance, {"lat": round(nearest_lat, 6), "lon": round(nearest_lon, 6)}

    if fallback_lat is not None and fallback_lon is not None:
        distance = haversine_distance_m(
            origin_lat, origin_lon, fallback_lat, fallback_lon
        )
        return distance, {"lat": round(fallback_lat, 6), "lon": round(fallback_lon, 6)}

    return None, None


def nearest_point_on_way_geometry(
    origin_lat: float, origin_lon: float, geometry: Sequence[Mapping[str, float]]
) -> tuple[LatLonDict | None, float | None]:
    """
    Nearest point on a way polyline/polygon to the origin, using a local equirectangular
    projection (accurate enough at these distances). Returns ({lat, lon}, metres).
    """
    if not geometry or len(geometry) < 2:
        return None, None

    meters_per_deg_lat = 111320.0
    meters_per_deg_lon = 111320.0 * math.cos(math.radians(origin_lat))

    xy_points = [
        (
            (point["lon"] - origin_lon) * meters_per_deg_lon,
            (point["lat"] - origin_lat) * meters_per_deg_lat,
        )
        for point in geometry
    ]
    min_distance_sq = float("inf")
    nearest_xy = None

    for (x1, y1), (x2, y2) in pairwise(xy_points):
        dx, dy = x2 - x1, y2 - y1
        segment_len_sq = dx * dx + dy * dy
        t = (
            0.0
            if segment_len_sq == 0
            else clamp((-x1 * dx - y1 * dy) / segment_len_sq, 0.0, 1.0)
        )
        proj_x, proj_y = x1 + t * dx, y1 + t * dy
        distance_sq = proj_x * proj_x + proj_y * proj_y
        if distance_sq < min_distance_sq:
            min_distance_sq = distance_sq
            nearest_xy = (proj_x, proj_y)

    if nearest_xy is None:  # e.g. NaN coordinates: no segment compared as nearer
        return None, None

    nearest_lat = origin_lat + nearest_xy[1] / meters_per_deg_lat
    nearest_lon = origin_lon + (
        nearest_xy[0] / meters_per_deg_lon if meters_per_deg_lon else 0.0
    )
    return {"lat": round(nearest_lat, 6), "lon": round(nearest_lon, 6)}, math.sqrt(
        min_distance_sq
    )


def bbox_area_m2(
    bounds: Mapping[str, float] | None,
) -> float | None:
    """Fast approximate area (m^2) from an Overpass bounding box (overestimates non-rectangles)."""
    values = bounds_values(bounds)
    if values is None:
        return None
    minlat, minlon, maxlat, maxlon = values

    mid_lat_rad = math.radians((minlat + maxlat) / 2.0)
    height_m = (maxlat - minlat) * 111320.0
    width_m = (maxlon - minlon) * 111320.0 * math.cos(mid_lat_rad)
    if height_m <= 0 or width_m <= 0:
        return None
    return height_m * width_m


def classify_area_size_band(area_m2: float | None) -> str:
    if area_m2 is None:
        return "unknown"
    if area_m2 < 5000:
        return "small"
    if area_m2 < 50000:
        return "medium"
    return "large"
