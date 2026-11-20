/**
 * Talks to the Campspotter server: opens the websocket, sends the search, checks the
 * shape of every message that comes back and applies it to the stores.
 */
import { get } from "svelte/store";

import { applyServerMessage, beginSearch, endSearch, searching, setStatus } from "./stores";
import type { Bounds, LatLon, RedFlag, SearchRequest, ServerMessage, Site } from "./types";

// ---------------------------------------------------------------------------
// Runtime checks of server messages (types.ts only describes them at compile time)
// ---------------------------------------------------------------------------

type Json = Record<string, unknown>;

const isObject = (value: unknown): value is Json =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const isString = (value: unknown): value is string => typeof value === "string";
const isOptional = (value: unknown, check: (v: unknown) => boolean) => value === undefined || check(value);
const isArrayOf = <T>(value: unknown, check: (v: unknown) => v is T): value is T[] =>
  Array.isArray(value) && value.every(check);

const isLatLon = (value: unknown): value is LatLon =>
  isObject(value) && isNumber(value.lat) && isNumber(value.lon);

const isBounds = (value: unknown): value is Bounds =>
  isObject(value) &&
  isNumber(value.minlat) &&
  isNumber(value.minlon) &&
  isNumber(value.maxlat) &&
  isNumber(value.maxlon);

const isRedFlag = (value: unknown): value is RedFlag =>
  isObject(value) && isString(value.type) && isNumber(value.distance_to_red_flag_m) && isString(value.tag);

const SITE_TYPES = new Set(["node", "way", "relation"]);
const AREA_BANDS = new Set(["small", "medium", "large", "unknown"]);

export const isSite = (value: unknown): value is Site =>
  isObject(value) &&
  Number.isInteger(value.id) &&
  SITE_TYPES.has(value.type as string) &&
  isNumber(value.lat) &&
  isNumber(value.lon) &&
  isString(value.terrain_description) &&
  AREA_BANDS.has(value.area_size_band as string) &&
  isArrayOf(value.nearby_red_flags, isRedFlag) &&
  isOptional(value.area_m2, isNumber) &&
  isOptional(value.distance_to_bbox_m, isNumber) &&
  isOptional(value.bounds, isBounds) &&
  isOptional(value.nearest_bbox_point, isLatLon) &&
  isOptional(value.distance_to_major_road_m, isNumber) &&
  isOptional(value.distance_to_water_m, isNumber) &&
  isOptional(value.suitability_score, isNumber) &&
  isOptional(value.suitability_reason, isString) &&
  isOptional(value.geometry, (geometry) => isArrayOf(geometry, isLatLon));

/** The message, if `raw` is a valid server message; otherwise null. */
export function parseServerMessage(raw: string): ServerMessage | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isObject(data)) return null;
  switch (data.type) {
    case "status":
    case "error":
      return isString(data.msg) ? (data as unknown as ServerMessage) : null;
    case "batch":
      return isArrayOf(data.sites, isSite) ? (data as unknown as ServerMessage) : null;
    case "final":
      return isArrayOf(data.sites, isSite) &&
        isArrayOf(data.refined_ids, (id): id is number => Number.isInteger(id))
        ? (data as unknown as ServerMessage)
        : null;
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Running a search
// ---------------------------------------------------------------------------

export interface SearchOptions {
  /** e.g. "ws://localhost:8000" */
  apiUrl: string;
  /** Called when new results should be shown on the map. */
  onResults?: () => void;
  /** Injected in tests. */
  WebSocketImpl?: typeof WebSocket;
}

export interface SearchHandle {
  /** Stop the search: closes the socket (the server then stops too) and keeps any sites found so far. */
  cancel(): void;
}

const NOOP_HANDLE: SearchHandle = { cancel() {} };

/** Start a search; progress and results go into the stores. */
export function runSearch(
  request: SearchRequest,
  { apiUrl, onResults, WebSocketImpl = WebSocket }: SearchOptions,
): SearchHandle {
  if (get(searching)) return NOOP_HANDLE;
  beginSearch();
  // `finished`: the search has its answer (results or an error) - later status messages,
  // like the final "Analysis complete (...)", are still shown.
  // `stopped`: we gave up on this socket (cancelled, or an unreadable message) - ignore the rest.
  let finished = false;
  let stopped = false;

  let socket: WebSocket;
  try {
    socket = new WebSocketImpl(`${apiUrl}/ws/analyze`);
  } catch (error) {
    endSearch();
    setStatus(`Invalid server address ${apiUrl}: ${error instanceof Error ? error.message : error}`, true);
    return NOOP_HANDLE;
  }

  socket.onopen = () => socket.send(JSON.stringify(request));

  socket.onmessage = (event: MessageEvent) => {
    if (stopped) return;
    const message = typeof event.data === "string" ? parseServerMessage(event.data) : null;
    if (!message) {
      console.warn("Unexpected message from the server:", event.data);
      setStatus("The server sent a message the app doesn't understand. Is the server up to date?", true);
      finished = stopped = true;
      socket.close();
      return;
    }
    const outcome = applyServerMessage(message);
    if (outcome.done) finished = true;
    if (outcome.showResults) onResults?.();
  };

  socket.onerror = () => {
    if (!finished) {
      setStatus(
        `Can't reach the Campspotter server at ${apiUrl}. Is it running? (cd server && uv run python server.py)`,
        true,
      );
    }
    finished = true;
  };

  socket.onclose = () => {
    endSearch();
    if (!finished) setStatus("The server closed the connection before the search finished.", true);
    finished = true;
  };

  return {
    cancel() {
      if (stopped) return;
      const wasFinished = finished;
      finished = stopped = true;
      socket.close();
      if (wasFinished) return;
      setStatus("Search cancelled.");
    },
  };
}
