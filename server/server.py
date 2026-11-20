import asyncio
import json
import logging
import math
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketState

from scout import (
    build_site_summaries,
    enrich_sites_with_context_metrics,
    llm_select_geom_candidates,
    llm_wild_camping_criteria,
    refine_sites_with_way_geometry,
    scout_agent_run,
)

logger = logging.getLogger(__name__)

MIN_RADIUS_M = 100
MAX_RADIUS_M = 5000

app = FastAPI(title="Campspotter")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def parse_search_params(raw):
    """Parse {"lat", "lon", "radius"} from the client; radius is clamped to a sane range."""
    params = json.loads(raw)
    if not isinstance(params, dict):
        raise ValueError("expected a JSON object")
    lat = float(params["lat"])
    lon = float(params["lon"])
    radius = float(params.get("radius", 500))
    if not all(math.isfinite(value) for value in (lat, lon, radius)):
        raise ValueError("lat, lon and radius must be finite numbers")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("lat/lon out of range")
    radius = int(min(max(radius, MIN_RADIUS_M), MAX_RADIUS_M))
    return (lat, lon), radius


async def run_search(websocket, origin, radius):
    # Every step below makes blocking HTTP calls, so run each one in a worker thread.
    # Calling them directly blocks the event loop, which stops the server answering
    # websocket keep-alive pings and the browser drops the connection mid-search.

    # --- WAVE 1: INITIAL DISCOVERY ---
    await websocket.send_json(
        {"type": "status", "msg": "Retrieving data from OpenStreetMap..."}
    )
    elements = await asyncio.to_thread(scout_agent_run, origin, radius)
    if isinstance(elements, str):  # human-readable error from scout
        await websocket.send_json({"type": "error", "msg": elements})
        return

    sites = await asyncio.to_thread(build_site_summaries, elements, origin)
    if not sites:
        await websocket.send_json(
            {
                "type": "error",
                "msg": f"No woods or forests found within {radius} m. Try a larger radius or another point.",
            }
        )
        return
    await websocket.send_json({"type": "batch", "sites": sites})

    # --- WAVE 2: ENRICHMENT (Roads/Water) ---
    await websocket.send_json(
        {"type": "status", "msg": "Checking context (roads/water)..."}
    )
    enriched_sites = await asyncio.to_thread(enrich_sites_with_context_metrics, sites)
    await websocket.send_json({"type": "batch", "sites": enriched_sites})

    # --- WAVE 3: LLM REFINEMENT & GEOMETRY ---
    await websocket.send_json(
        {"type": "status", "msg": "Scoring sites and fetching outlines..."}
    )
    criteria = await asyncio.to_thread(llm_wild_camping_criteria)
    selected_ids = await asyncio.to_thread(
        llm_select_geom_candidates, criteria, enriched_sites
    )
    final_sites = await asyncio.to_thread(
        refine_sites_with_way_geometry, enriched_sites, origin, selected_ids
    )

    await websocket.send_json(
        {"type": "final", "sites": final_sites, "refined_ids": selected_ids}
    )
    await websocket.send_json({"type": "status", "msg": "Analysis complete"})


@app.websocket("/ws/analyze")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        try:
            origin, radius = parse_search_params(await websocket.receive_text())
        except (ValueError, KeyError, TypeError) as exc:
            await websocket.send_json(
                {"type": "error", "msg": f"Invalid search request: {exc}"}
            )
            return
        await run_search(websocket, origin, radius)
    except WebSocketDisconnect:
        logger.info("Client disconnected before the search finished.")
    except Exception as exc:
        logger.exception("Search failed")
        try:
            await websocket.send_json({"type": "error", "msg": str(exc)})
        except Exception:
            pass  # client already gone
    finally:
        if (
            websocket.client_state == WebSocketState.CONNECTED
            and websocket.application_state == WebSocketState.CONNECTED
        ):
            try:
                await websocket.close()
            except RuntimeError:
                pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000"))
    )
