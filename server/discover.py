"""Stage 1 - discover: fetch woodland and red flags around a point from OpenStreetMap."""

import logging

from models import Coordinate, OsmElement, OverpassResponse
from overpass import call_overpass_with_retry

logger = logging.getLogger(__name__)


def query_woods_and_red_flags(
    lat: float, lon: float, radius_meters: float = 2000
) -> OverpassResponse | None:
    """Fetch candidate woodland ("targets") and red flags around a point."""
    lat = float(lat)
    lon = float(lon)
    around = f"around:{int(radius_meters)},{lat},{lon}"

    # One flat union: the old named sets (->.targets / ->.redflags) were only re-unioned at the end,
    # and the kumi.systems mirror returned results without any woods for that form.
    query = f"""
    [out:json][timeout:90];
    (
      // === TARGET SITES ===
      way["natural"="wood"]({around});
      way["landuse"="forest"]({around});
      node["natural"~"^(wood|tree_group)$"]({around});

      // === RED FLAGS: CRITICAL (Stay Away) ===
      way["amenity"~"school|prison|police|cemetery|hospital"]({around});
      way["landuse"~"military|allotments|quarry|residential|farmyard"]({around});
      way["leisure"~"pitch|stadium|golf_course|playground"]({around});

      // === BARRIERS (Access & Difficulty) ===
      node["barrier"]({around});
      way["barrier"]({around});

      // === RED FLAGS: NUISANCE (Noise/People) ===
      node["amenity"~"pub|restaurant|parking"]({around});
      way["man_made"~"works|sewage_works|substation"]({around});
      way["railway"="rail"]({around});

      // === BUILDINGS (General Encroachment) ===
      way["building"]({around});
    );
    out center bb;
    """
    return call_overpass_with_retry(query)


def discover_elements(
    coordinate: Coordinate | None, radius: float
) -> list[OsmElement] | str:
    """Return a list of Overpass elements, or an error string for the UI."""
    if not coordinate or any(value is None for value in coordinate):
        return "Error: Invalid coordinate passed from Parser."

    logger.info(
        f"Running Overpass scout query at lat={coordinate[0]}, lon={coordinate[1]}, radius={radius}m."
    )
    results = query_woods_and_red_flags(coordinate[0], coordinate[1], radius)

    if not results:
        logger.error("Scout query failed: no response payload returned from Overpass.")
        return "OpenStreetMap (Overpass) is not responding right now. Please try again in a minute."

    elements = results.get("elements")
    if not isinstance(elements, list):
        logger.error(
            f"Scout query failed: malformed Overpass response keys={list(results.keys())}"
        )
        return "Scout query failed: malformed Overpass response (missing 'elements')."

    logger.info(f"Scout query completed with {len(elements)} elements.")
    if not elements:
        return "Nothing found in OpenStreetMap here. Try increasing the search radius."

    return elements
