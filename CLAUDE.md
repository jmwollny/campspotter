# Project rules

Campspotter finds wild camping spots along a GPX route. A Python backend pulls candidate sites
and hazards from OpenStreetMap, ranks them, and asks a local LLM (via Ollama) to pick the best
three. A Svelte + Mapbox frontend shows progress over a websocket and displays results on a map.

## Stack
- Frontend: Svelte 4 + TypeScript (strict), Vite, Mapbox GL JS. Match the Svelte version and syntax already in package.json
  (Svelte 4: `export let`, `$:`, stores, `createEventDispatcher` - not Svelte 5 runes).
- Backend: Python 3.12+, managed with `uv`. Websocket server for progress updates.
- LLM: Ollama running locally (default model `gemma4:e2b`). Gemini is an alternative (`LOCAL_LLM_ENABLED=false` +
  `GEMINI_API_KEY`). If no LLM is available or it fails, sites are scored by a built-in heuristic.
- Data: OpenStreetMap (Overpass API).

## Commands
- Backend (run in `server/`): `uv sync`, `uv run python server.py`, `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format .`, `uv run mypy`
- Frontend (run in the project root): `npm install`, `npm run dev`, `npm test`, `npm run check` (svelte-check),
  `npm run lint`, `npm run build`
- LLM: `ollama pull gemma4:e2b`, `ollama serve`
- Before saying a task is done: run the tests, the linter and the type checks for whichever side you changed.

## Where things live
- Backend (`server/`): one module per pipeline stage - `discover.py`, `summarise.py`, `enrich.py`, `select_sites.py`,
  `outline.py` - run in order by `pipeline.py`; `server.py` is only the websocket endpoint. Shared pieces:
  `overpass.py` (OSM client), `llm_client.py` (the only module that talks to an LLM), `prompts.py`, `models.py`
  (Pydantic), `config.py` (settings), `geo.py`. Tests in `server/tests/`, one file per module.
- Frontend (`src/`): `lib/stores.ts` (state + actions), `lib/searchClient.ts` (websocket + message checks),
  `lib/types.ts`, `lib/geo.ts`, `lib/map/` (all Mapbox code; `controller.ts` is the only mapbox-gl user),
  `components/` (UI), `App.svelte` (layout + wiring between the panel and the map).
- `src/lib/types.ts` mirrors `server/models.py`; `server/tests/test_types_sync.py` fails if they drift.
- Prompts are snapshot-tested (`server/tests/test_prompts.py`). After a deliberate prompt change, regenerate with
  `UPDATE_PROMPT_SNAPSHOT=1 uv run pytest tests/test_prompts.py` and say what changed in the commit message.

## Frontend (Svelte)
- Small, single-purpose components. Keep map logic (Mapbox setup, layers, markers) out of UI components.
- Put shared state in stores or a dedicated state module, not passed through many levels of props.
- Type all props and websocket message shapes in one shared `types.ts`.
- Never hard-code the Mapbox token; read it from `import.meta.env`.
- Tests: Vitest + Svelte Testing Library. Test behaviour through the UI (roles, labels), not internals.
- Focus on usability and a11y. Use aria attributes and roles where applicable.

## Backend (Python)
- Type hints on all functions; keep functions small and pure where possible.
- Keep the pipeline stages separate: discover (fetch woods and hazards from OSM) -> summarise (classify, measure
  hazards per site, rank nearest first, then largest) -> enrich (roads/water for the nearest `LLM_CANDIDATE_POOL_SIZE`,
  default 10) -> select (LLM, or heuristic fallback) -> outline (full polygons for the top picks).
  Each stage is its own module/function with its own tests.
- No network calls in unit tests: mock Overpass and the LLM client. Use saved fixture data (sample GPX, sample OSM JSON).
- Use `pathlib`, `logging` (not print), and dataclasses or Pydantic models for structured data.
- Config (model name, Ollama URL, API keys) comes from environment variables or the config file, never hard-coded.

## Local LLM
- All LLM calls go through one client module, so the model or provider can be swapped (Ollama <-> Gemini) in one place.
- Keep prompts in their own files or constants, not inline in business logic. Version them with the code.
- Ask the model for structured output (JSON) and validate it against a schema before using it.
  If parsing fails, retry once with a stricter prompt, then fall back to the heuristic scores (`heuristic_score`).
- Set timeouts on LLM calls and report progress/errors to the UI over the websocket.
- Keep inputs small: send only the top candidates and the fields the model needs. Small local models lose track with long prompts.
- Don't send personal data or secrets to a hosted model.

## Working with me
- Propose a short plan before large changes, then make changes in small steps I can review.
- Ask before adding new dependencies (Python or npm).
- Don't change prompts or model settings without telling me what changed and why.
- If something in these rules is unclear or out of date, say so rather than guessing.
