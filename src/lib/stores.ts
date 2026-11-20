/**
 * App state, as Svelte stores, plus the actions that change it.
 *
 * Nothing here touches the map or the DOM (except DOMParser for GPX), so it can be
 * unit tested; components subscribe to the stores and call the actions.
 */
import { gpx as gpxToGeoJSON } from "@tmcw/togeojson";
import type { Feature, FeatureCollection, LineString } from "geojson";
import { derived, get, writable } from "svelte/store";

import { lineLengthKm, pointAlongLine, sortFinalSites, trackLine } from "./geo";
import type { LatLon, ServerMessage, Site } from "./types";

export interface Route {
  name: string;
  geojson: FeatureCollection;
  /** The whole route as one line; used for both its length and the search point. */
  line: Feature<LineString>;
  /** Rounded down to 0.1 km so the slider's maximum is always on the route. */
  lengthKm: number;
}

export interface Status {
  message: string;
  isError: boolean;
}

const NO_STATUS: Status = { message: "", isError: false };
export const DEFAULT_RADIUS_M = 500;

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

// Route
export const route = writable<Route | null>(null);
export const routeError = writable("");
export const routeLoading = writable(false);

// Search point
export const searchDistanceKm = writable(0);
export const searchRadiusM = writable(DEFAULT_RADIUS_M);
/** The point `searchDistanceKm` along the route, or null without a route. */
export const origin = derived([route, searchDistanceKm], ([$route, $km]): LatLon | null => {
  const coords = pointAlongLine($route?.line ?? null, $km);
  return coords ? { lat: coords[1], lon: coords[0] } : null;
});

// Search and results
export const searching = writable(false);
export const status = writable<Status>(NO_STATUS);
export const sites = writable<Site[]>([]);
/** The server's top picks, best first. */
export const topPickIds = writable<number[]>([]);
export const topPickSet = derived(topPickIds, ($ids) => new Set($ids));
export const selectedSiteId = writable<number | null>(null);
export const selectedSite = derived(
  [sites, selectedSiteId],
  ([$sites, $id]) => $sites.find((site) => site.id === $id) ?? null,
);

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

const messageOf = (error: unknown): string => (error instanceof Error ? error.message : String(error));

export function setStatus(message: string, isError = false): void {
  status.set({ message, isError });
}

export function clearResults(): void {
  sites.set([]);
  topPickIds.set([]);
  selectedSiteId.set(null);
}

/** Parse GPX text into a Route, or explain why it can't be used. */
export function parseRoute(text: string, name: string): { route: Route } | { error: string } {
  let geojson: FeatureCollection;
  try {
    const xml = new DOMParser().parseFromString(text, "application/xml");
    if (xml.querySelector("parsererror")) throw new Error("it isn't valid GPX/XML");
    geojson = gpxToGeoJSON(xml);
  } catch (error) {
    return { error: `Couldn't read ${name}: ${messageOf(error)}.` };
  }
  const line = trackLine(geojson);
  if (!line) return { error: `${name} doesn't contain a track or route to follow.` };
  return { route: { name, geojson, line, lengthKm: Math.floor(lineLengthKm(line) * 10) / 10 } };
}

/** Load GPX text as the current route. Returns true if it was usable. */
export function loadRoute(text: string, name: string): boolean {
  const parsed = parseRoute(text, name);
  if ("error" in parsed) {
    routeError.set(parsed.error);
    return false;
  }
  routeError.set("");
  route.set(parsed.route);
  searchDistanceKm.set(0);
  clearResults();
  setStatus("");
  return true;
}

/** Fetch a GPX file (e.g. a bundled sample) and load it. Returns true if it was usable. */
export async function loadRouteFromUrl(
  url: string,
  name: string,
  fetchImpl: typeof fetch = fetch,
): Promise<boolean> {
  routeLoading.set(true);
  try {
    const response = await fetchImpl(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return loadRoute(await response.text(), name);
  } catch (error) {
    routeError.set(`Couldn't load the ${name} sample (${messageOf(error)}).`);
    return false;
  } finally {
    routeLoading.set(false);
  }
}

/** Move the search point; old results no longer apply, so they are cleared. */
export function moveSearchPoint(km: number): void {
  searchDistanceKm.set(km);
  if (get(sites).length || get(status).message) {
    clearResults();
    setStatus("");
  }
}

export function beginSearch(): void {
  clearResults();
  searching.set(true);
  setStatus("Connecting to the Campspotter server…");
}

export function endSearch(): void {
  searching.set(false);
}

export interface MessageOutcome {
  /** The search has its final answer (results or an error). */
  done: boolean;
  /** New results arrived that the map should zoom to. */
  showResults: boolean;
}

/** Apply one message from the server to the state. */
export function applyServerMessage(message: ServerMessage): MessageOutcome {
  switch (message.type) {
    case "status":
      setStatus(message.msg);
      return { done: false, showResults: false };
    case "batch": {
      const firstBatch = get(sites).length === 0;
      sites.set(message.sites);
      return { done: false, showResults: firstBatch };
    }
    case "final":
      topPickIds.set(message.refined_ids);
      sites.set(sortFinalSites(message.sites, message.refined_ids));
      return { done: true, showResults: true };
    case "error":
      setStatus(message.msg, true);
      return { done: true, showResults: false };
  }
}

export function selectSite(id: number | null): void {
  selectedSiteId.set(id);
}

/** Put every store back to its initial value (used by tests). */
export function resetState(): void {
  route.set(null);
  routeError.set("");
  routeLoading.set(false);
  searchDistanceKm.set(0);
  searchRadiusM.set(DEFAULT_RADIUS_M);
  searching.set(false);
  status.set(NO_STATUS);
  clearResults();
}
