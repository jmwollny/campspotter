# Campspotter server

A FastAPI server with one WebSocket endpoint, `ws://localhost:8000/ws/analyze`. The client sends
`{"lat": ..., "lon": ..., "radius": ...}`, and the server streams `status`, `batch`, `final` and `error`
messages back as the search progresses. The pipeline lives in [`scout.py`](scout.py).

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

## Tests

```bash
uv run pytest
```

The tests use a captured Overpass response (`tests/fixtures/`) and a fake LLM, so they need no network
access, no Ollama and no API keys.
