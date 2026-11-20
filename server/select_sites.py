"""Stage 4 - select: score candidates with the LLM (or a heuristic) and pick the best."""

import json
import logging
import math
import time
from typing import Any

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

import config
from models import SiteRecord
from summarise import count_red_flags_by_type

logger = logging.getLogger(__name__)


DEFAULT_CRITERIA = (
    "1. Flat, even ground for comfortable sleeping and stable pitching. "
    "2. Proximity to a water source (rivers or lakes) for drinking and cooking. "
    "3. Natural shelter from wind, such as bushes, depressions, or treelines. "
    "4. Visual concealment from roads, trails, and nearby dwellings. "
    "5. Distance from livestock to avoid noise, mess, and curiosity."
)


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


def parse_json_object_from_text(text: str | None) -> dict[str, Any] | None:
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


def get_chat_client() -> tuple[OpenAI, str] | None:
    """
    Return (client, model): local Ollama when LOCAL_LLM_ENABLED (default), otherwise Gemini
    when GEMINI_API_KEY is set, otherwise None.
    """
    settings = config.get_settings()
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
    return None


def get_camping_criteria() -> str:
    """Ask the LLM for wild camping criteria; fall back to a fixed list on any failure."""
    message = (
        "What is the criteria for a good overnight wild camping spot? Make a bulleted list with no "
        "other text. Ignore any legal considerations because the intention is to arrive late, leave "
        "early and leave no trace."
    )
    chat = get_chat_client()
    if chat is None:
        return DEFAULT_CRITERIA
    llm_client, llm_model = chat

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

    chat = get_chat_client()
    logger.info(
        f"Selecting geometry candidates from {len(candidate_sites)} sites "
        f"using model '{chat[1] if chat else None}'."
    )
    if chat is None:
        return select_by_heuristic(candidate_sites, max_candidates)
    llm_client, llm_model = chat

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
    messages: list[ChatCompletionMessageParam] = [
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
