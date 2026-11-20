"""Stage 3 - enrich: distance from each candidate to major roads and water."""

import logging
import math

import config
from geo import get_element_coordinate, haversine_distance_m
from overpass import call_overpass_with_retry

logger = logging.getLogger(__name__)


def compute_site_context_metrics_from_elements(lat, lon, elements):
    """Nearest major road / water distances for one site from pre-fetched elements."""
    distance_to_road = None
    distance_to_water = None
    for element in elements:
        coord = get_element_coordinate(element)
        if not coord:
            continue
        dist = haversine_distance_m(lat, lon, coord[0], coord[1])
        tags = element.get("tags", {})
        is_road = tags.get("highway") in {"motorway", "trunk", "primary", "secondary"}
        is_water = (
            tags.get("waterway") in {"river", "stream", "canal", "drain", "ditch"}
            or tags.get("natural") == "water"
        )
        if is_road and (distance_to_road is None or dist < distance_to_road):
            distance_to_road = dist
        if is_water and (distance_to_water is None or dist < distance_to_water):
            distance_to_water = dist

    return {
        "distance_to_major_road_m": round(distance_to_road, 1)
        if distance_to_road is not None
        else None,
        "distance_to_water_m": round(distance_to_water, 1)
        if distance_to_water is not None
        else None,
    }


def fetch_context_elements_for_sites(sites, radius_meters=1200):
    """Fetch roads/water once for all candidate sites using a padded bbox query."""
    site_coords = [
        (site["lat"], site["lon"])
        for site in sites
        if site.get("lat") is not None and site.get("lon") is not None
    ]
    if not site_coords:
        return []

    min_lat = min(lat for lat, _ in site_coords)
    max_lat = max(lat for lat, _ in site_coords)
    min_lon = min(lon for _, lon in site_coords)
    max_lon = max(lon for _, lon in site_coords)

    mid_lat = (min_lat + max_lat) / 2.0
    lat_padding = radius_meters / 111320.0
    lon_padding = radius_meters / max(
        1.0, 111320.0 * abs(math.cos(math.radians(mid_lat)))
    )
    south, west = min_lat - lat_padding, min_lon - lon_padding
    north, east = max_lat + lat_padding, max_lon + lon_padding
    bbox = f"{south},{west},{north},{east}"
    logger.info(
        f"Context batch bbox ({bbox}) for {len(site_coords)} sites at radius={radius_meters}m."
    )

    query = f"""
    [out:json][timeout:60];
    (
      way["highway"~"^(motorway|trunk|primary|secondary)$"]({bbox});
      way["waterway"~"^(river|stream|canal|drain|ditch)$"]({bbox});
      node["waterway"~"^(river|stream|canal|drain|ditch)$"]({bbox});
      way["natural"="water"]({bbox});
    );
    out center;
    """
    response = call_overpass_with_retry(query)
    if not response or "elements" not in response:
        logger.warning("Context batch query returned no elements payload.")
        return []
    elements = response["elements"]
    logger.info(
        f"Context batch query fetched {len(elements)} elements for {len(site_coords)} sites."
    )
    return elements


def enrich_sites_with_context_metrics(sites, max_sites=None, radius_meters=1200):
    """Add road/water distances to the nearest `max_sites` (default: the LLM candidate pool)."""
    max_sites = max_sites or config.get_settings().llm_candidate_pool_size
    target_sites = sites[:max_sites]
    context_elements = fetch_context_elements_for_sites(
        target_sites, radius_meters=radius_meters
    )
    for site in target_sites:
        if site.get("lat") is None or site.get("lon") is None:
            continue
        site.update(
            compute_site_context_metrics_from_elements(
                site["lat"], site["lon"], context_elements
            )
        )
    return sites
