"""Stage 5 - outline: fetch full polygons for the chosen sites."""

import logging

from geo import nearest_point_on_way_geometry
from overpass import call_overpass_with_retry
from select_sites import to_int_id

logger = logging.getLogger(__name__)


def fetch_way_geometries(way_ids):
    """Fetch full geometry for a list of OSM way ids -> {id: [{lat, lon}, ...]}."""
    if not way_ids:
        return {}

    ids_csv = ",".join(str(way_id) for way_id in way_ids)
    logger.info("Fetching way geometries for " + ids_csv)
    query = f"""
    [out:json][timeout:90];
    way(id:{ids_csv});
    out geom;
    """
    response = call_overpass_with_retry(query)
    if not response or "elements" not in response:
        return {}

    return {
        element["id"]: element.get("geometry", [])
        for element in response["elements"]
        if element.get("type") == "way" and element.get("id") is not None
    }


def refine_sites_with_way_geometry(sites, origin_coordinate, selected_site_ids):
    """Fetch full polygons for the selected ways and refine their nearest-point distance."""
    if not sites or not origin_coordinate or not selected_site_ids:
        return sites

    selected_id_set = {to_int_id(site_id) for site_id in selected_site_ids} - {None}
    way_ids = [
        site["id"]
        for site in sites
        if site.get("type") == "way" and site.get("id") in selected_id_set
    ]
    geometry_by_id = fetch_way_geometries(way_ids)
    if not geometry_by_id:
        return sites

    for site in sites:
        way_geometry = geometry_by_id.get(site.get("id"))
        if site.get("type") != "way" or not way_geometry:
            continue

        nearest_point, distance_m = nearest_point_on_way_geometry(
            origin_coordinate[0],
            origin_coordinate[1],
            way_geometry,
        )
        if nearest_point:
            site["nearest_bbox_point"] = nearest_point
        if distance_m is not None:
            site["distance_to_bbox_m"] = round(distance_m, 1)
        site["geometry"] = [
            {"lat": round(point["lat"], 6), "lon": round(point["lon"], 6)}
            for point in way_geometry
            if "lat" in point and "lon" in point
        ]

    return sites
