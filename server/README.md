# Campspotter server

A FastAPI server with one WebSocket endpoint, `ws://localhost:8000/ws/analyze`. The client sends
`{"lat": ..., "lon": ..., "radius": ...}`, and the server streams `status`, `batch`, `final` and `error`
messages back as the search progresses.

## Code layout

The search runs in five stages, each in its own module with its own tests in `tests/`:

| Module | Stage / role |
| --- | --- |
| [`pipeline.py`](pipeline.py) | Runs the stages in order and emits progress messages |
| [`discover.py`](discover.py) | 1. Fetch woods and red flags around the point from OpenStreetMap |
| [`summarise.py`](summarise.py) | 2. Build candidate sites: size, distance from the route, nearby red flags |
| [`enrich.py`](enrich.py) | 3. Distance from the nearest candidates to major roads and water |
| [`select_sites.py`](select_sites.py) | 4. Score candidates with the LLM (or a heuristic) and pick the best three |
| [`outline.py`](outline.py) | 5. Fetch full outlines for the chosen sites |
| [`overpass.py`](overpass.py) | Overpass API client (mirrors, retries, backoff) |
| [`geo.py`](geo.py) | Distance, area and bounding-box maths |
| [`models.py`](models.py) | Pydantic models for the request, sites and websocket messages |
| [`config.py`](config.py) | Settings from environment variables / `.env` |
| [`server.py`](server.py) | FastAPI websocket endpoint |

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then, from this folder:

```bash
uv sync                      # create .venv and install dependencies
cp .env.example .env         # optional: LLM and Overpass settings
uv run python server.py
```

If all is well, you will see:

```
INFO:     Started server process [84816]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

The server listens on `127.0.0.1` by default. Set `HOST=0.0.0.0` to reach it from other devices.

## Configuration

All settings are optional and documented in [`.env.example`](.env.example). The main ones:

| Setting | Default | What it does |
| --- | --- | --- |
| `LOCAL_LLM_ENABLED` | `true` | Use local Ollama. If `false`, use Gemini when `GEMINI_API_KEY` is set. |
| `OLLAMA_MODEL` | `gemma4:e2b` | Ollama model, e.g. `safe-gemma` (see `safe-gemma`). |
| `LLM_CANDIDATE_POOL_SIZE` | `10` | How many of the nearest sites get road/water checks and LLM scoring. |
| `MIN_DISTANCE_TO_HAZARD` | `150` | Red flags within this many metres of a site are reported. |
| `OVERPASS_URLS` | overpass-api.de mirrors | Comma-separated Overpass mirrors to try in order. |
| `LOG_LEVEL` | `INFO` | `DEBUG` also logs Overpass queries to `overpass_query_log.txt`. |

If the LLM is unreachable, or returns something unusable, sites are scored with a simple heuristic
instead, so a search always completes.

The public Overpass servers are often busy ("502 at capacity"). The server retries with exponential
backoff, but a search can still take a minute or two at busy times.

## Tests and checks

```bash
uv run pytest            # tests
uv run ruff check .      # lint
uv run ruff format .     # format
uv run mypy              # type check
```

The tests use a captured Overpass response (`tests/fixtures/`) and a fake LLM, so they need no network
access, no Ollama and no API keys.
