"""Stage 4 - select: score candidates with the LLM (or a heuristic) and pick the best."""

import json
import logging
from dataclasses import dataclass
from typing import Any

import config
from llm_client import ChatMessage, LLMError, LLMUnavailable, complete_json
from models import SelectionResponse, SiteRecord
from prompts import SELECTION_SYSTEM_PROMPT, SELECTION_USER_TEMPLATE
from summarise import count_red_flags_by_type

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Selection:
    """The chosen site ids, best first, and why the heuristic was used (if it was)."""

    ids: list[int]
    fallback_reason: str | None = None


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


def score_and_select_sites(
    sites: list[SiteRecord], max_candidates: int = 3
) -> Selection:
    """
    Score the nearest candidate sites (sets suitability_score/suitability_reason on them) and
    choose up to `max_candidates` of them. Falls back to the heuristic if the LLM can't help.
    """
    candidate_sites = sites[: config.get_settings().llm_candidate_pool_size]
    if not candidate_sites:
        return Selection([])

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
            "content": SELECTION_SYSTEM_PROMPT,
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
        reply = complete_json(messages, SelectionResponse, purpose="selection")
    except LLMUnavailable as exc:
        return Selection(
            select_by_heuristic(candidate_sites, max_candidates), exc.reason
        )
    except (
        Exception
    ) as exc:  # LLMRequestFailed, LLMReplyInvalid, or anything unexpected
        reason = exc.reason if isinstance(exc, LLMError) else LLMError.reason
        logger.warning(f"LLM selection failed ({exc}); using heuristic fallback.")
        return Selection(select_by_heuristic(candidate_sites, max_candidates), reason)

    evaluations = {evaluation.id: evaluation for evaluation in reply.evaluations}
    for site in candidate_sites:
        evaluation = evaluations.get(site["id"])
        if evaluation is not None:
            site["suitability_score"] = evaluation.suitability_score
            site["suitability_reason"] = evaluation.reason
        else:
            site["suitability_score"] = heuristic_score(site)
            site["suitability_reason"] = "heuristic fallback"

    # Only accept ids that were actually offered; LLMs sometimes invent or repeat them.
    candidate_ids = {site.get("id") for site in candidate_sites}
    selected_ids: list[int] = []
    for site_id in reply.selected_ids:
        if site_id in candidate_ids and site_id not in selected_ids:
            selected_ids.append(site_id)

    if not selected_ids:
        ranked = sorted(
            candidate_sites, key=lambda site: site["suitability_score"], reverse=True
        )
        selected_ids = [site["id"] for site in ranked]
    return Selection(selected_ids[:max_candidates])
