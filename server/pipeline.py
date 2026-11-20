"""
The search pipeline: runs each stage in order and reports progress.

    discover -> summarise -> enrich -> select -> outline

Progress and results go out through `emit`, one ServerMessage at a time, so the
pipeline doesn't know or care that it is talking to a websocket.
"""

import asyncio
from collections.abc import Awaitable, Callable

from discover import discover_elements
from enrich import enrich_sites
from models import (
    BatchMessage,
    ErrorMessage,
    FinalMessage,
    SearchRequest,
    ServerMessage,
    SiteRecord,
    StatusMessage,
)
from outline import add_outlines
from select_sites import score_and_select_sites
from summarise import summarise_sites

Emit = Callable[[ServerMessage], Awaitable[None]]


async def run_search(request: SearchRequest, emit: Emit) -> None:
    # Every stage makes blocking HTTP calls, so each one runs in a worker thread.
    # Calling them directly would block the event loop, which stops the server
    # answering websocket keep-alive pings and the browser drops the connection.
    origin, radius = request.origin, int(request.radius)

    # --- Stage 1 + 2: discover and summarise ---
    await emit(StatusMessage(msg="Retrieving data from OpenStreetMap..."))
    elements = await asyncio.to_thread(discover_elements, origin, radius)
    if isinstance(elements, str):  # human-readable error from discover
        await emit(ErrorMessage(msg=elements))
        return

    sites = await asyncio.to_thread(summarise_sites, elements, origin)
    if not sites:
        await emit(
            ErrorMessage(
                msg=f"No woods or forests found within {radius} m. "
                "Try a larger radius or another point."
            )
        )
        return
    await emit(BatchMessage.model_validate({"sites": sites}))

    # Short notes about anything that fell back, repeated in the final status so they
    # are still visible when the search finishes (each status replaces the previous one).
    notes: list[str] = []

    # --- Stage 3: enrich (roads/water) ---
    await emit(StatusMessage(msg="Checking context (roads/water)..."))
    if not await asyncio.to_thread(enrich_sites, sites):
        notes.append("roads/water not checked")
        await emit(
            StatusMessage(
                msg="Couldn't check roads and water (OpenStreetMap is busy); "
                "scoring without them..."
            )
        )
    await emit(BatchMessage.model_validate({"sites": sites}))

    # --- Stage 4: select ---
    await emit(StatusMessage(msg="Scoring sites..."))
    selection = await asyncio.to_thread(score_and_select_sites, sites)
    if selection.fallback_reason:
        notes.append(f"heuristic scores: {selection.fallback_reason}")
        await emit(
            StatusMessage(
                msg=f"Scored with the built-in heuristic: {selection.fallback_reason}."
            )
        )

    # --- Stage 5: outline ---
    await emit(StatusMessage(msg="Fetching outlines for the top picks..."))
    final_sites = await asyncio.to_thread(add_outlines, sites, origin, selection.ids)
    if outlines_missing(final_sites, selection.ids):
        notes.append("outlines unavailable, showing boxes")

    await emit(
        FinalMessage.model_validate(
            {"sites": final_sites, "refined_ids": selection.ids}
        )
    )
    summary = f" ({'; '.join(notes)})" if notes else ""
    await emit(StatusMessage(msg=f"Analysis complete{summary}"))


def outlines_missing(sites: list[SiteRecord], selected_ids: list[int]) -> bool:
    """True if top picks that should have an outline (OSM ways) got none at all."""
    selected = set(selected_ids)
    expected = [s for s in sites if s["id"] in selected and s.get("type") == "way"]
    return bool(expected) and not any(s.get("geometry") for s in expected)
