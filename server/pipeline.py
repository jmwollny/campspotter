"""
The search pipeline: runs each stage in order and reports progress.

    discover -> summarise -> enrich -> select -> outline

Progress and results go out through `emit`, one ServerMessage at a time, so the
pipeline doesn't know or care that it is talking to a websocket.
"""

import asyncio
from collections.abc import Awaitable, Callable

from discover import scout_agent_run
from enrich import enrich_sites_with_context_metrics
from models import (
    BatchMessage,
    ErrorMessage,
    FinalMessage,
    SearchRequest,
    ServerMessage,
    StatusMessage,
)
from outline import refine_sites_with_way_geometry
from select_sites import llm_select_geom_candidates, llm_wild_camping_criteria
from summarise import build_site_summaries

Emit = Callable[[ServerMessage], Awaitable[None]]


async def run_search(request: SearchRequest, emit: Emit) -> None:
    # Every stage makes blocking HTTP calls, so each one runs in a worker thread.
    # Calling them directly would block the event loop, which stops the server
    # answering websocket keep-alive pings and the browser drops the connection.
    origin, radius = request.origin, int(request.radius)

    # --- Stage 1 + 2: discover and summarise ---
    await emit(StatusMessage(msg="Retrieving data from OpenStreetMap..."))
    elements = await asyncio.to_thread(scout_agent_run, origin, radius)
    if isinstance(elements, str):  # human-readable error from discover
        await emit(ErrorMessage(msg=elements))
        return

    sites = await asyncio.to_thread(build_site_summaries, elements, origin)
    if not sites:
        await emit(
            ErrorMessage(
                msg=f"No woods or forests found within {radius} m. "
                "Try a larger radius or another point."
            )
        )
        return
    await emit(BatchMessage.model_validate({"sites": sites}))

    # --- Stage 3: enrich (roads/water) ---
    await emit(StatusMessage(msg="Checking context (roads/water)..."))
    enriched_sites = await asyncio.to_thread(enrich_sites_with_context_metrics, sites)
    await emit(BatchMessage.model_validate({"sites": enriched_sites}))

    # --- Stage 4 + 5: select and outline ---
    await emit(StatusMessage(msg="Scoring sites and fetching outlines..."))
    criteria = await asyncio.to_thread(llm_wild_camping_criteria)
    selected_ids = await asyncio.to_thread(
        llm_select_geom_candidates, criteria, enriched_sites
    )
    final_sites = await asyncio.to_thread(
        refine_sites_with_way_geometry, enriched_sites, origin, selected_ids
    )

    await emit(
        FinalMessage.model_validate({"sites": final_sites, "refined_ids": selected_ids})
    )
    await emit(StatusMessage(msg="Analysis complete"))
