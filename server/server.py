"""Websocket API: validates the browser's request and streams the pipeline's messages back."""

import asyncio
import contextlib
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from config import configure_logging, get_settings
from models import (
    ErrorMessage,
    SearchRequest,
    ServerMessage,
    describe_validation_error,
)
from pipeline import Emit, run_search

configure_logging()
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


async def send(websocket: WebSocket, message: ServerMessage) -> None:
    # exclude_none: fields a stage hasn't filled in yet are left out rather than sent as null.
    await websocket.send_json(message.model_dump(mode="json", exclude_none=True))


async def wait_for_disconnect(websocket: WebSocket) -> None:
    """Return when the browser closes the socket (e.g. the user cancelled the search)."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return


async def run_until_disconnected(
    websocket: WebSocket, request: SearchRequest, emit: Emit
) -> None:
    """
    Run the search, but stop as soon as the browser disconnects. Without this the
    pipeline would carry on querying OpenStreetMap and the LLM for nobody. A stage
    already running in a worker thread can't be interrupted; it finishes in the
    background, but no later stage starts.
    """
    search = asyncio.create_task(run_search(request, emit))
    disconnected = asyncio.create_task(wait_for_disconnect(websocket))
    done, _ = await asyncio.wait(
        {search, disconnected}, return_when=asyncio.FIRST_COMPLETED
    )
    if disconnected in done and not search.done():
        search.cancel()
        logger.info("Client disconnected; search cancelled.")
        with contextlib.suppress(asyncio.CancelledError):
            await search
        return
    disconnected.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await disconnected
    await search  # re-raises the search's exception, if any


@app.websocket("/ws/analyze")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()

    async def emit(message: ServerMessage) -> None:
        await send(websocket, message)

    try:
        try:
            request = parse_search_request(await websocket.receive_text())
        except ValidationError as exc:
            await emit(
                ErrorMessage(
                    msg=f"Invalid search request: {describe_validation_error(exc)}"
                )
            )
            return
        await run_until_disconnected(websocket, request, emit)
    except WebSocketDisconnect:
        logger.info("Client disconnected before the search finished.")
    except Exception as exc:
        logger.exception("Search failed")
        try:
            await emit(ErrorMessage(msg=str(exc)))
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
