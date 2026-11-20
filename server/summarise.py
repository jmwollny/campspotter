"""Stage 2 - summarise: turn OSM elements into candidate sites with nearby red flags."""

from typing import Any

import config
from geo import (
    bbox_area_m2,
    classify_area_size_band,
    distance_to_element_m,
    get_element_coordinate,
    normalize_bounds,
)
from models import Coordinate, OsmElement, OsmTags, SiteRecord

TARGET_NATURAL_VALUES = {"wood", "tree_group"}


def is_target_site(tags: OsmTags) -> bool:
    """True for woodland/forest (what the target query asks for); everything else is a red flag."""
    if tags.get("amenity") == "school" or tags.get("leisure") == "pitch":
        return False
    return (
        tags.get("natural") in TARGET_NATURAL_VALUES
        or tags.get("landuse") == "forest"
        or tags.get("tourism") == "camp_site"
    )


def classify_red_flag(tags: OsmTags) -> str:
    """Short label for a red flag, e.g. BARRIER, SCHOOL, RAILWAY, RESIDENTIAL, BUILDING."""
    if "barrier" in tags:
        return "BARRIER"
    if tags.get("railway"):
        return "RAILWAY"
    for key in ("amenity", "leisure", "man_made", "landuse"):
        if tags.get(key):
            return str(tags[key]).upper()
    return "BUILDING"


def summarise_sites(
    elements: list[OsmElement], origin_coordinate: Coordinate | None = None
) -> list[SiteRecord]:
    """
    Turn raw Overpass elements into compact candidate-site records, nearest first.
    Each site lists red flags within MIN_DISTANCE_TO_HAZARD metres of the site itself.
    """
    if not elements:
        return []

    hazard_radius_m = config.get_settings().min_distance_to_hazard_m
    target_sites = []
    red_flags = []

    for element in elements:
        coordinate = get_element_coordinate(element)
        if coordinate is None:
            continue
        tags = element.get("tags", {})
        item = {
            "lat": coordinate[0],
            "lon": coordinate[1],
            "tags": tags,
            "element": element,
        }
        if is_target_site(tags):
            target_sites.append(item)
        else:
            item["flag_type"] = classify_red_flag(tags)
            red_flags.append(item)

    summaries = []
    for site in target_sites:
        site_element = site["element"]
        tags = site["tags"]

        terrain_parts = [
            f"{key}:{tags[key]}"
            for key in ("tourism", "natural", "landuse", "name")
            if tags.get(key)
        ]
        area_m2 = (
            bbox_area_m2(site_element.get("bounds"))
            if site_element.get("type") == "way"
            else None
        )

        distance_to_bbox_m = None
        nearest_bbox_point = None
        if origin_coordinate:
            distance_to_bbox_m, nearest_bbox_point = distance_to_element_m(
                origin_coordinate[0],
                origin_coordinate[1],
                site_element,
                fallback_lat=site["lat"],
                fallback_lon=site["lon"],
            )

        # Red flags measured from the flag to the site's bounding box (not to the search origin).
        hazards = []
        for flag in red_flags:
            distance_m, _ = distance_to_element_m(
                flag["lat"],
                flag["lon"],
                site_element,
                fallback_lat=site["lat"],
                fallback_lon=site["lon"],
            )
            if distance_m is not None and distance_m < hazard_radius_m:
                hazards.append(
                    {
                        "type": flag["flag_type"],
                        "distance_to_red_flag_m": round(distance_m),
                        "tag": flag["tags"].get("barrier")
                        or flag["tags"].get("amenity")
                        or "structure",
                    }
                )
        hazards.sort(key=lambda hazard: hazard["distance_to_red_flag_m"])

        summaries.append(
            {
                "id": site_element.get("id"),
                "type": site_element.get("type"),
                "lat": round(site["lat"], 6),
                "lon": round(site["lon"], 6),
                "terrain_description": ", ".join(terrain_parts)
                if terrain_parts
                else "unknown",
                "area_m2": round(area_m2, 1) if area_m2 is not None else None,
                "area_size_band": classify_area_size_band(area_m2),
                "distance_to_bbox_m": round(distance_to_bbox_m, 1)
                if distance_to_bbox_m is not None
                else None,
                "nearby_red_flags": hazards,
                "bounds": normalize_bounds(site_element.get("bounds")),
                "nearest_bbox_point": nearest_bbox_point,
            }
        )

    summaries.sort(key=site_sort_key)
    return summaries


def site_sort_key(site: SiteRecord) -> tuple[float, float]:
    """Nearest first, then largest first. Missing values sort last."""
    distance = site.get("distance_to_bbox_m")
    area = site.get("area_m2")
    return (
        distance if distance is not None else float("inf"),
        -(area if area is not None else 0),
    )


def count_red_flags_by_type(hazards: list[dict[str, Any]] | None) -> dict[str, int]:
    """{'BUILDING': 3, 'BARRIER': 1} style counts, for the LLM prompt."""
    counts: dict[str, int] = {}
    for hazard in hazards or []:
        counts[hazard["type"]] = counts.get(hazard["type"], 0) + 1
    return counts
