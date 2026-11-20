import asyncio
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from config import get_settings
from models import (
    BatchMessage,
    ErrorMessage,
    FinalMessage,
    SearchRequest,
    ServerMessage,
    StatusMessage,
)
from scout import (
    build_site_summaries,
    enrich_sites_with_context_metrics,
    llm_select_geom_candidates,
    llm_wild_camping_criteria,
    refine_sites_with_way_geometry,
    scout_agent_run,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Campspotter")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def parse_search_request(raw: str) -> SearchRequest:
    """Validate the client's {"lat", "lon", "radius"} message (radius is clamped)."""
    return SearchRequest.model_validate_json(raw)


def describe_validation_error(exc: ValidationError) -> str:
    """One short line per problem, e.g. "lat: Input should be less than or equal to 90"."""
    problems = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        problems.append(f"{location}: {error['msg']}" if location else error["msg"])
    return "; ".join(problems)


async def send(websocket: WebSocket, message: ServerMessage) -> None:
    # exclude_none: fields a stage hasn't filled in yet are left out rather than sent as null.
    await websocket.send_json(message.model_dump(mode="json", exclude_none=True))


async def run_search(websocket: WebSocket, request: SearchRequest) -> None:
    # Every step below makes blocking HTTP calls, so run each one in a worker thread.
    # Calling them directly blocks the event loop, which stops the server answering
    # websocket keep-alive pings and the browser drops the connection mid-search.
    origin, radius = request.origin, int(request.radius)

    # --- WAVE 1: INITIAL DISCOVERY ---
    await send(websocket, StatusMessage(msg="Retrieving data from OpenStreetMap..."))
    elements = await asyncio.to_thread(scout_agent_run, origin, radius)
    if isinstance(elements, str):  # human-readable error from scout
        await send(websocket, ErrorMessage(msg=elements))
        return

    sites = await asyncio.to_thread(build_site_summaries, elements, origin)
    if not sites:
        await send(
            websocket,
            ErrorMessage(
                msg=f"No woods or forests found within {radius} m. "
                "Try a larger radius or another point."
            ),
        )
        return
    await send(websocket, BatchMessage.model_validate({"sites": sites}))

    # --- WAVE 2: ENRICHMENT (Roads/Water) ---
    await send(websocket, StatusMessage(msg="Checking context (roads/water)..."))
    enriched_sites = await asyncio.to_thread(enrich_sites_with_context_metrics, sites)
    await send(websocket, BatchMessage.model_validate({"sites": enriched_sites}))

    # --- WAVE 3: LLM REFINEMENT & GEOMETRY ---
    await send(websocket, StatusMessage(msg="Scoring sites and fetching outlines..."))
    criteria = await asyncio.to_thread(llm_wild_camping_criteria)
    selected_ids = await asyncio.to_thread(
        llm_select_geom_candidates, criteria, enriched_sites
    )
    final_sites = await asyncio.to_thread(
        refine_sites_with_way_geometry, enriched_sites, origin, selected_ids
    )

    await send(
        websocket,
        FinalMessage.model_validate(
            {"sites": final_sites, "refined_ids": selected_ids}
        ),
    )
    await send(websocket, StatusMessage(msg="Analysis complete"))


@app.websocket("/ws/analyze")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        try:
            request = parse_search_request(await websocket.receive_text())
        except ValidationError as exc:
            await send(
                websocket,
                ErrorMessage(
                    msg=f"Invalid search request: {describe_validation_error(exc)}"
                ),
            )
            return
        await run_search(websocket, request)
    except WebSocketDisconnect:
        logger.info("Client disconnected before the search finished.")
    except Exception as exc:
        logger.exception("Search failed")
        try:
            await send(websocket, ErrorMessage(msg=str(exc)))
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

    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port)
