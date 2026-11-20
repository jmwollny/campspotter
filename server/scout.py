"""
Campspotter scouting pipeline.

1. Query OpenStreetMap (via Overpass) for woodland around a point, plus "red flags"
   (buildings, barriers, schools, railways...) that make a spot less suitable.
2. Summarise each candidate site: size, distance from the route, nearby red flags.
3. Enrich the nearest candidates with distance to major roads and water.
4. Ask an LLM (local Ollama or Gemini) to score them and pick the best few,
   falling back to a simple heuristic when no LLM is available.
5. Fetch full polygons for the chosen sites.
"""

import json
import logging
import math
import random
import time
from itertools import pairwise
from pathlib import Path

import requests
from openai import OpenAI

from config import get_settings

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s [%(levelname)s] %(message)s",
    force=True,
)
logger = logging.getLogger(__name__)

OVERPASS_USER_AGENT = "campspotter/1.0 (+https://github.com/jmwollny/campspotter)"

TARGET_NATURAL_VALUES = {"wood", "tree_group"}

DEFAULT_CRITERIA = (
    "1. Flat, even ground for comfortable sleeping and stable pitching. "
    "2. Proximity to a water source (rivers or lakes) for drinking and cooking. "
    "3. Natural shelter from wind, such as bushes, depressions, or treelines. "
    "4. Visual concealment from roads, trails, and nearby dwellings. "
    "5. Distance from livestock to avoid noise, mess, and curiosity."
)


def candidate_pool_size():
    """How many of the nearest sites get enriched and sent to the LLM."""
    return get_settings().llm_candidate_pool_size


# --------------------------------------------------------------------------- #
# Overpass
# --------------------------------------------------------------------------- #


def get_overpass_mirrors():
    # overpass.kumi.systems is not a default: it often hangs until the read timeout and
    # has returned incomplete results. Add it via OVERPASS_URLS if you want it.
    return list(get_settings().overpass_urls)


def sleep_with_jitter(min_seconds=0.5, max_seconds=1.5):
    delay = random.uniform(min_seconds, max_seconds)
    logger.info(f"Waiting {delay:.2f}s before next Overpass mirror retry.")
    time.sleep(delay)


def write_overpass_debug_query(text):
    """Append Overpass queries/responses to a file for copy/paste debugging (DEBUG only)."""
    debug_filename = get_settings().overpass_query_debug_file
    debug_path = Path(__file__).resolve().parent / debug_filename
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with debug_path.open("a", encoding="utf-8") as debug_file:
        debug_file.write(f"\n--- {timestamp} ---\n")
        debug_file.write((text or "").strip())
        debug_file.write("\n")
    logger.debug(f"Appended Overpass query to {debug_path}")


def call_overpass_with_retry(query):
    """
    POST a query to each Overpass mirror in turn; return the JSON payload or None.
    The public servers often answer 502/429 "at capacity" and ask clients to back off
    exponentially, so the mirror list is retried for OVERPASS_MAX_ROUNDS rounds with a
    doubling pause (OVERPASS_BACKOFF_S, 2x, 4x...) between rounds.
    """
    settings = get_settings()
    mirrors = get_overpass_mirrors()
    max_rounds = settings.overpass_max_rounds
    backoff_s = settings.overpass_backoff_s
    logger.info(
        f"Overpass request starting across {len(mirrors)} mirrors (query_size={len(query or '')} chars)."
    )
    if logger.isEnabledFor(logging.DEBUG):
        write_overpass_debug_query(query)

    for round_index in range(max_rounds):
        if round_index:
            delay = backoff_s * (2 ** (round_index - 1))
            logger.info(
                f"All Overpass mirrors failed; backing off {delay:.0f}s (round {round_index + 1}/{max_rounds})."
            )
            time.sleep(delay)
        payload, retryable = _try_overpass_mirrors(query, mirrors)
        if payload is not None or not retryable:
            return payload
    logger.error("Overpass request failed on all mirrors.")
    return None


def _try_overpass_mirrors(query, mirrors):
    """One pass over the mirrors -> (payload or None, whether retrying could help)."""
    settings = get_settings()
    retry_min_delay_s = settings.overpass_retry_min_delay_s
    retry_max_delay_s = settings.overpass_retry_max_delay_s
    # Short connect timeout so a dead mirror fails fast; generous read timeout for big queries.
    timeout = (settings.overpass_connect_timeout_s, settings.overpass_read_timeout_s)

    for index, url in enumerate(mirrors):
        mirror_start = time.perf_counter()
        try:
            logger.info(f"Overpass request -> {url}")
            response = requests.post(
                url,
                data={"data": query},
                headers={
                    "Accept": "application/json,text/plain,*/*",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "User-Agent": OVERPASS_USER_AGENT,
                },
                timeout=timeout,
            )
            elapsed = time.perf_counter() - mirror_start
            logger.info(
                f"Overpass response <- {url} status={response.status_code} elapsed={elapsed:.2f}s"
            )
            if response.status_code == 200:
                payload = response.json()
                elements = (
                    payload.get("elements", []) if isinstance(payload, dict) else []
                )
                logger.info(f"Overpass success from {url}: elements={len(elements)}")
                if logger.isEnabledFor(logging.DEBUG):
                    write_overpass_debug_query(json.dumps(payload, indent=2))
                return payload, False
            if response.status_code == 400:
                # A syntax error will fail on every mirror, so stop here.
                logger.error(
                    f"Overpass query syntax error (400): {response.text[:500]}"
                )
                return None, False
            logger.warning(
                f"Overpass mirror returned status={response.status_code} at {url}. "
                f"Response excerpt: {(response.text or '')[:300]}"
            )
        except requests.exceptions.Timeout as exc:
            logger.warning(f"Overpass request timeout for {url}: {exc}")
        except requests.exceptions.RequestException as exc:
            logger.warning(f"Overpass request failed for {url}: {exc}")
        except ValueError as exc:
            logger.warning(f"Overpass response JSON decode failed for {url}: {exc}")
        if index < len(mirrors) - 1:
            sleep_with_jitter(retry_min_delay_s, retry_max_delay_s)
    return None, True


def get_camping_and_woods(lat, lon, radius_meters=2000):
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


def scout_agent_run(coordinate, radius):
    """Return a list of Overpass elements, or an error string for the UI."""
    if not coordinate or any(value is None for value in coordinate):
        return "Error: Invalid coordinate passed from Parser."

    logger.info(
        f"Running Overpass scout query at lat={coordinate[0]}, lon={coordinate[1]}, radius={radius}m."
    )
    results = get_camping_and_woods(coordinate[0], coordinate[1], radius)

    if not results:
        logger.error("Scout query failed: no response payload returned from Overpass.")
        return "OpenStreetMap (Overpass) is not responding right now. Please try again in a minute."

    if "elements" not in results:
        logger.error(
            f"Scout query failed: malformed Overpass response keys={list(results.keys())}"
        )
        return "Scout query failed: malformed Overpass response (missing 'elements')."

    element_count = len(results["elements"])
    logger.info(f"Scout query completed with {element_count} elements.")
    if element_count == 0:
        return "Nothing found in OpenStreetMap here. Try increasing the search radius."

    return results["elements"]


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


# --------------------------------------------------------------------------- #
# Site summaries
# --------------------------------------------------------------------------- #


def get_element_coordinate(element):
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


def is_target_site(tags):
    """True for woodland/forest (what the target query asks for); everything else is a red flag."""
    if tags.get("amenity") == "school" or tags.get("leisure") == "pitch":
        return False
    return (
        tags.get("natural") in TARGET_NATURAL_VALUES
        or tags.get("landuse") == "forest"
        or tags.get("tourism") == "camp_site"
    )


def classify_red_flag(tags):
    """Short label for a red flag, e.g. BARRIER, SCHOOL, RAILWAY, RESIDENTIAL, BUILDING."""
    if "barrier" in tags:
        return "BARRIER"
    if tags.get("railway"):
        return "RAILWAY"
    for key in ("amenity", "leisure", "man_made", "landuse"):
        if tags.get(key):
            return str(tags[key]).upper()
    return "BUILDING"


def build_site_summaries(elements, origin_coordinate=None):
    """
    Turn raw Overpass elements into compact candidate-site records, nearest first.
    Each site lists red flags within MIN_DISTANCE_TO_HAZARD metres of the site itself.
    """
    if not elements:
        return []

    hazard_radius_m = get_settings().min_distance_to_hazard_m
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
            calculate_way_area_from_bounds_m2(site_element.get("bounds"))
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


def site_sort_key(site):
    """Nearest first, then largest first. Missing values sort last."""
    distance = site.get("distance_to_bbox_m")
    area = site.get("area_m2")
    return (
        distance if distance is not None else float("inf"),
        -(area if area is not None else 0),
    )


def summarise_red_flags(hazards):
    """{'BUILDING': 3, 'BARRIER': 1} style counts, for the LLM prompt."""
    counts: dict[str, int] = {}
    for hazard in hazards or []:
        counts[hazard["type"]] = counts.get(hazard["type"], 0) + 1
    return counts


# --------------------------------------------------------------------------- #
# Context enrichment (roads / water)
# --------------------------------------------------------------------------- #


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
    max_sites = max_sites or candidate_pool_size()
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


# --------------------------------------------------------------------------- #
# Scoring (LLM with heuristic fallback)
# --------------------------------------------------------------------------- #


def compute_heuristic_suitability(site):
    """Fallback 0-100 suitability score when the LLM is unavailable."""
    score = 50.0
    area_m2 = site.get("area_m2")
    road_m = site.get("distance_to_major_road_m")
    water_m = site.get("distance_to_water_m")
    terrain = (site.get("terrain_description") or "").lower()
    hazards = site.get("nearby_red_flags") or []

    if area_m2 is not None:
        score += min(20.0, area_m2 / 5000.0)
    if road_m is not None:
        if road_m < 100:
            score -= 20
        elif road_m < 250:
            score -= 8
        else:
            score += 8
    if water_m is not None:
        if water_m < 30:
            score -= 10
        elif water_m <= 500:
            score += 8
    if "wood" in terrain or "forest" in terrain or "scrub" in terrain:
        score += 10
    if "camp_site" in terrain:
        score += 5
    non_barrier_hazards = [
        hazard for hazard in hazards if hazard.get("type") != "BARRIER"
    ]
    score -= min(15.0, 3.0 * len(non_barrier_hazards))

    return max(0.0, min(100.0, round(score, 1)))


def apply_heuristic_scores(sites, max_candidates):
    for site in sites:
        site["suitability_score"] = compute_heuristic_suitability(site)
        site["suitability_reason"] = "heuristic fallback"
    ranked = sorted(sites, key=lambda site: site["suitability_score"], reverse=True)
    return [site["id"] for site in ranked[:max_candidates]]


def parse_json_object_from_text(text):
    """Extract the outermost {...} JSON object from LLM output (which may include prose/fences)."""
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def to_int_id(value):
    """LLMs often echo ids as strings ("123"); normalise to int, or None if not an id."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def to_score(value):
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(score):
        return None
    return max(0.0, min(100.0, score))


def get_chat_client():
    """
    Return (client, model): local Ollama when LOCAL_LLM_ENABLED (default), otherwise Gemini
    when GEMINI_API_KEY is set, otherwise (None, None).
    """
    settings = get_settings()
    if settings.local_llm_enabled:
        model = settings.ollama_model
        logger.info(f"Using local Ollama model '{model}'.")
        client = OpenAI(
            base_url=settings.ollama_base_url,
            api_key=settings.ollama_api_key,
            timeout=settings.llm_timeout_s,
            max_retries=1,
        )
        return client, model

    if settings.gemini_api_key:
        model = settings.gemini_model
        logger.info(f"Using Gemini model '{model}'.")
        client = OpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=settings.gemini_api_key,
            timeout=settings.llm_timeout_s,
            max_retries=1,
        )
        return client, model

    logger.info(
        "No LLM configured (LOCAL_LLM_ENABLED is off and GEMINI_API_KEY is missing)."
    )
    return None, None


def llm_wild_camping_criteria():
    """Ask the LLM for wild camping criteria; fall back to a fixed list on any failure."""
    message = (
        "What is the criteria for a good overnight wild camping spot? Make a bulleted list with no "
        "other text. Ignore any legal considerations because the intention is to arrive late, leave "
        "early and leave no trace."
    )
    llm_client, llm_model = get_chat_client()
    if not llm_client:
        return DEFAULT_CRITERIA

    try:
        llm_start = time.perf_counter()
        response = llm_client.chat.completions.create(
            model=llm_model,
            messages=[{"role": "user", "content": message}],
            temperature=0.1,
        )
        logger.info(
            f"LLM criteria completed in {time.perf_counter() - llm_start:.2f}s."
        )
        content = (response.choices[0].message.content or "").strip()
        logger.debug(f"LLM response for wild camping criteria: {content}")
        return content or DEFAULT_CRITERIA
    except Exception as exc:
        logger.warning(
            f"LLM criteria retrieval failed ({exc}); using default criteria."
        )
        return DEFAULT_CRITERIA


def llm_select_geom_candidates(criteria, sites, max_candidates=3):
    """
    Score the nearest candidate sites (sets suitability_score/suitability_reason on them) and
    return up to `max_candidates` ids to fetch full geometry for.
    """
    candidate_sites = sites[: candidate_pool_size()]
    if not candidate_sites:
        return []

    llm_client, llm_model = get_chat_client()
    logger.info(
        f"Selecting geometry candidates from {len(candidate_sites)} sites using model '{llm_model}'."
    )
    if not llm_client:
        return apply_heuristic_scores(candidate_sites, max_candidates)

    prompt_payload = [
        {
            "id": site.get("id"),
            "type": site.get("type"),
            "terrain_description": site.get("terrain_description"),
            "area_m2": site.get("area_m2"),
            "distance_to_origin_m": site.get("distance_to_bbox_m"),
            "distance_to_major_road_m": site.get("distance_to_major_road_m"),
            "distance_to_water_m": site.get("distance_to_water_m"),
            "nearby_red_flags": summarise_red_flags(site.get("nearby_red_flags")),
        }
        for site in candidate_sites
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "You are evaluating wild camping suitability. "
                f"Use this wild camping criteria to help select the best sites: {criteria}\n"
                "Prefer discreet terrain (wood/forest/scrub) away from red flags such as buildings. "
                "Return valid JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Evaluate these candidate sites and pick up to {max_candidates} ids that should receive "
                "detailed geometry refinement.\n"
                "Schema: keys: selected_ids (array of ids), evaluations. evaluations is an array of objects "
                "with these keys - id, suitability_score (range 0-100), reason.\n"
                f"Candidate sites: {json.dumps(prompt_payload)}\n"
                "Return JSON only"
            ),
        },
    ]
    logger.debug(f"LLM select geom candidates prompt: {messages}")

    try:
        llm_start = time.perf_counter()
        response = llm_client.chat.completions.create(
            model=llm_model, messages=messages, temperature=0.1
        )
        logger.info(
            f"LLM selection completed in {time.perf_counter() - llm_start:.2f}s."
        )
        content = response.choices[0].message.content or ""
        parsed = parse_json_object_from_text(content)
        logger.debug(f"LLM response: {parsed}")
        if not parsed:
            raise ValueError(f"Could not parse LLM response: {content[:300]}")
    except Exception as exc:
        logger.warning(f"LLM selection failed ({exc}); using heuristic fallback.")
        return apply_heuristic_scores(candidate_sites, max_candidates)

    eval_map = {}
    for item in parsed.get("evaluations") or []:
        if isinstance(item, dict) and to_int_id(item.get("id")) is not None:
            eval_map[to_int_id(item.get("id"))] = item

    for site in candidate_sites:
        evaluation = eval_map.get(site.get("id"))
        score = to_score(evaluation.get("suitability_score")) if evaluation else None
        if evaluation and score is not None:
            site["suitability_score"] = score
            site["suitability_reason"] = evaluation.get("reason") or ""
        else:
            site["suitability_score"] = compute_heuristic_suitability(site)
            site["suitability_reason"] = "heuristic fallback"

    # Only accept ids that were actually offered; LLMs sometimes invent or repeat them.
    candidate_ids = {site.get("id") for site in candidate_sites}
    selected_ids = []
    for raw_id in parsed.get("selected_ids") or []:
        site_id = to_int_id(raw_id)
        if site_id in candidate_ids and site_id not in selected_ids:
            selected_ids.append(site_id)

    if not selected_ids:
        ranked = sorted(
            candidate_sites, key=lambda site: site["suitability_score"], reverse=True
        )
        selected_ids = [site["id"] for site in ranked]
    return selected_ids[:max_candidates]


# --------------------------------------------------------------------------- #
# Geometry refinement
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# Geometry helpers
# --------------------------------------------------------------------------- #


def calculate_way_area_from_bounds_m2(bounds):
    """Fast approximate area (m^2) from an Overpass bounding box (overestimates non-rectangles)."""
    if not bounds:
        return None
    minlat, minlon = bounds.get("minlat"), bounds.get("minlon")
    maxlat, maxlon = bounds.get("maxlat"), bounds.get("maxlon")
    if None in (minlat, minlon, maxlat, maxlon):
        return None

    mid_lat_rad = math.radians((minlat + maxlat) / 2.0)
    height_m = (maxlat - minlat) * 111320.0
    width_m = (maxlon - minlon) * 111320.0 * math.cos(mid_lat_rad)
    if height_m <= 0 or width_m <= 0:
        return None
    return height_m * width_m


def classify_area_size_band(area_m2):
    if area_m2 is None:
        return "unknown"
    if area_m2 < 5000:
        return "small"
    if area_m2 < 50000:
        return "medium"
    return "large"


def haversine_distance_m(lat1, lon1, lat2, lon2):
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


def clamp(value, minimum, maximum):
    return max(minimum, min(value, maximum))


def normalize_bounds(bounds):
    if not bounds:
        return None
    minlat, minlon = bounds.get("minlat"), bounds.get("minlon")
    maxlat, maxlon = bounds.get("maxlat"), bounds.get("maxlon")
    if None in (minlat, minlon, maxlat, maxlon):
        return None
    return {
        "minlat": round(minlat, 6),
        "minlon": round(minlon, 6),
        "maxlat": round(maxlat, 6),
        "maxlon": round(maxlon, 6),
    }


def distance_to_element_m(
    origin_lat, origin_lon, element, fallback_lat=None, fallback_lon=None
):
    """
    Distance from a point to the nearest point of an element's bounding box (0 if inside),
    falling back to point distance when bounds are unavailable. Returns (metres, {lat, lon}).
    """
    bounds = element.get("bounds") or {}
    minlat, minlon = bounds.get("minlat"), bounds.get("minlon")
    maxlat, maxlon = bounds.get("maxlat"), bounds.get("maxlon")

    if None not in (minlat, minlon, maxlat, maxlon):
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


def nearest_point_on_way_geometry(origin_lat, origin_lon, geometry):
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
