"""Websocket API: validates the browser's request and streams the pipeline's messages back."""

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
from pipeline import run_search

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
        await run_search(request, emit)
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
