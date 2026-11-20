"""Stage 4 - select: score candidates with the LLM (or a heuristic) and pick the best."""

import json
import logging
import math
from typing import Any

import config
from llm_client import (
    ChatMessage,
    LLMUnavailable,
    complete,
    parse_json_object_from_text,
)
from models import SiteRecord
from prompts import (
    CRITERIA_PROMPT,
    DEFAULT_CRITERIA,
    SELECTION_SYSTEM_TEMPLATE,
    SELECTION_USER_TEMPLATE,
)
from summarise import count_red_flags_by_type

logger = logging.getLogger(__name__)


def heuristic_score(site: SiteRecord) -> float:
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


def select_by_heuristic(sites: list[SiteRecord], max_candidates: int) -> list[int]:
    for site in sites:
        site["suitability_score"] = heuristic_score(site)
        site["suitability_reason"] = "heuristic fallback"
    ranked = sorted(sites, key=lambda site: site["suitability_score"], reverse=True)
    return [site["id"] for site in ranked[:max_candidates]]


def to_int_id(value: Any) -> int | None:
    """LLMs often echo ids as strings ("123"); normalise to int, or None if not an id."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def to_score(value: Any) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(score):
        return None
    return max(0.0, min(100.0, score))


def get_camping_criteria() -> str:
    """Ask the LLM for wild camping criteria; fall back to a fixed list on any failure."""
    try:
        content = complete(
            [{"role": "user", "content": CRITERIA_PROMPT}], purpose="criteria"
        ).strip()
    except LLMUnavailable:
        return DEFAULT_CRITERIA
    except Exception as exc:
        logger.warning(
            f"LLM criteria retrieval failed ({exc}); using default criteria."
        )
        return DEFAULT_CRITERIA
    return content or DEFAULT_CRITERIA


def score_and_select_sites(
    criteria: str, sites: list[SiteRecord], max_candidates: int = 3
) -> list[int]:
    """
    Score the nearest candidate sites (sets suitability_score/suitability_reason on them) and
    return up to `max_candidates` ids to fetch full geometry for.
    """
    candidate_sites = sites[: config.get_settings().llm_candidate_pool_size]
    if not candidate_sites:
        return []

    logger.info(f"Scoring {len(candidate_sites)} candidate sites.")

    prompt_payload = [
        {
            "id": site.get("id"),
            "type": site.get("type"),
            "terrain_description": site.get("terrain_description"),
            "area_m2": site.get("area_m2"),
            "distance_to_origin_m": site.get("distance_to_bbox_m"),
            "distance_to_major_road_m": site.get("distance_to_major_road_m"),
            "distance_to_water_m": site.get("distance_to_water_m"),
            "nearby_red_flags": count_red_flags_by_type(site.get("nearby_red_flags")),
        }
        for site in candidate_sites
    ]
    messages: list[ChatMessage] = [
        {
            "role": "system",
            "content": SELECTION_SYSTEM_TEMPLATE.format(criteria=criteria),
        },
        {
            "role": "user",
            "content": SELECTION_USER_TEMPLATE.format(
                max_candidates=max_candidates,
                candidates_json=json.dumps(prompt_payload),
            ),
        },
    ]
    try:
        content = complete(messages, purpose="selection")
    except LLMUnavailable:
        return select_by_heuristic(candidate_sites, max_candidates)
    except Exception as exc:
        logger.warning(f"LLM selection failed ({exc}); using heuristic fallback.")
        return select_by_heuristic(candidate_sites, max_candidates)

    parsed = parse_json_object_from_text(content)
    if not parsed:
        logger.warning(
            f"Could not parse LLM response ({content[:300]!r}); using heuristic fallback."
        )
        return select_by_heuristic(candidate_sites, max_candidates)

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
            site["suitability_score"] = heuristic_score(site)
            site["suitability_reason"] = "heuristic fallback"

    # Only accept ids that were actually offered; LLMs sometimes invent or repeat them.
    candidate_ids = {site.get("id") for site in candidate_sites}
    selected_ids: list[int] = []
    for raw_id in parsed.get("selected_ids") or []:
        site_id = to_int_id(raw_id)
        if (
            site_id is not None
            and site_id in candidate_ids
            and site_id not in selected_ids
        ):
            selected_ids.append(site_id)

    if not selected_ids:
        ranked = sorted(
            candidate_sites, key=lambda site: site["suitability_score"], reverse=True
        )
        selected_ids = [site["id"] for site in ranked]
    return selected_ids[:max_candidates]
