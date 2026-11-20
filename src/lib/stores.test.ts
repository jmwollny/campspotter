// @vitest-environment jsdom
import { get } from "svelte/store";
import { beforeEach, describe, expect, it, vi } from "vitest";

import kingAlfredsWayGpx from "../../public/king-alfreds-way-full-route.gpx?raw";
import {
  applyServerMessage,
  beginSearch,
  endSearch,
  loadRoute,
  loadRouteFromUrl,
  moveSearchPoint,
  origin,
  parseRoute,
  resetState,
  route,
  routeError,
  routeLoading,
  searchDistanceKm,
  searching,
  selectSite,
  selectedSite,
  sites,
  status,
  topPickIds,
  topPickSet,
} from "./stores";
import type { Site } from "./types";

const site = (id: number, extra: Partial<Site> = {}): Site => ({
  id,
  type: "way",
  lat: 51,
  lon: -1,
  terrain_description: "natural:wood",
  area_size_band: "small",
  nearby_red_flags: [],
  ...extra,
});

const TWO_POINT_GPX = `<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="51.0" lon="-1.0"/><trkpt lat="51.1" lon="-1.0"/>
  </trkseg></trk>
</gpx>`;

beforeEach(() => resetState());

describe("loading a route", () => {
  it("loads a GPX route and puts the search point at its start", () => {
    expect(loadRoute(TWO_POINT_GPX, "Test route")).toBe(true);
    const loaded = get(route);
    expect(loaded?.name).toBe("Test route");
    expect(loaded?.lengthKm).toBe(11.1); // rounded down to 0.1 km
    expect(get(origin)).toEqual({ lat: 51, lon: -1 });
    expect(get(routeError)).toBe("");
  });

  it("parses the bundled King Alfred's Way sample", () => {
    const parsed = parseRoute(kingAlfredsWayGpx, "KAW");
    expect("route" in parsed && parsed.route.lengthKm).toBeGreaterThan(330);
  });

  it("clears old results and status when a new route loads", () => {
    sites.set([site(1)]);
    topPickIds.set([1]);
    status.set({ message: "Analysis complete", isError: false });
    searchDistanceKm.set(5);
    loadRoute(TWO_POINT_GPX, "Test route");
    expect(get(sites)).toEqual([]);
    expect(get(topPickIds)).toEqual([]);
    expect(get(status).message).toBe("");
    expect(get(searchDistanceKm)).toBe(0);
  });

  it.each([
    ["not xml at all <", "Couldn't read bad.gpx: it isn't valid GPX/XML."],
    [
      '<gpx xmlns="http://www.topografix.com/GPX/1/1"><wpt lat="51" lon="-1"/></gpx>',
      "bad.gpx doesn't contain a track or route to follow.",
    ],
  ])("explains why a file can't be used and keeps the previous route", (text, error) => {
    loadRoute(TWO_POINT_GPX, "Previous");
    expect(loadRoute(text, "bad.gpx")).toBe(false);
    expect(get(routeError)).toBe(error);
    expect(get(route)?.name).toBe("Previous");
  });

  it("fetches a sample route and reports fetch failures", async () => {
    const ok = vi.fn(async () => new Response(TWO_POINT_GPX));
    const loading = loadRouteFromUrl("/sample.gpx", "Sample", ok);
    expect(get(routeLoading)).toBe(true);
    expect(await loading).toBe(true);
    expect(get(routeLoading)).toBe(false);
    expect(ok).toHaveBeenCalledWith("/sample.gpx");

    const missing = vi.fn(async () => new Response("", { status: 404 }));
    expect(await loadRouteFromUrl("/nope.gpx", "Nope", missing)).toBe(false);
    expect(get(routeError)).toBe("Couldn't load the Nope sample (HTTP 404).");
    expect(get(routeLoading)).toBe(false);
  });
});

describe("the search point", () => {
  it("follows the distance along the route", () => {
    loadRoute(TWO_POINT_GPX, "Test route");
    moveSearchPoint(11.1);
    expect(get(origin)?.lat).toBeCloseTo(51.1, 3);
    expect(get(searchDistanceKm)).toBe(11.1);
  });

  it("clears results when it moves", () => {
    loadRoute(TWO_POINT_GPX, "Test route");
    sites.set([site(1)]);
    status.set({ message: "Analysis complete", isError: false });
    moveSearchPoint(2);
    expect(get(sites)).toEqual([]);
    expect(get(status).message).toBe("");
  });

  it("is null without a route", () => {
    expect(get(origin)).toBeNull();
  });
});

describe("server messages", () => {
  it("handles a whole search", () => {
    beginSearch();
    expect(get(searching)).toBe(true);
    expect(get(status).message).toMatch(/Connecting/);

    expect(applyServerMessage({ type: "status", msg: "Retrieving..." })).toEqual({
      done: false,
      showResults: false,
    });
    expect(get(status)).toEqual({ message: "Retrieving...", isError: false });

    // First batch: show it on the map; later batches just update.
    expect(applyServerMessage({ type: "batch", sites: [site(1), site(2)] }).showResults).toBe(true);
    expect(applyServerMessage({ type: "batch", sites: [site(1), site(2)] }).showResults).toBe(false);

    const final = applyServerMessage({
      type: "final",
      sites: [site(1, { suitability_score: 90 }), site(2, { suitability_score: 40 })],
      refined_ids: [2],
    });
    expect(final).toEqual({ done: true, showResults: true });
    expect(get(sites).map((s) => s.id)).toEqual([2, 1]); // top pick first
    expect(get(topPickSet)).toEqual(new Set([2]));

    endSearch();
    expect(get(searching)).toBe(false);
  });

  it("shows errors as errors and ends the search", () => {
    beginSearch();
    expect(applyServerMessage({ type: "error", msg: "Overpass is down" }).done).toBe(true);
    expect(get(status)).toEqual({ message: "Overpass is down", isError: true });
  });

  it("starting a search clears the previous results", () => {
    sites.set([site(1)]);
    topPickIds.set([1]);
    selectSite(1);
    beginSearch();
    expect(get(sites)).toEqual([]);
    expect(get(topPickIds)).toEqual([]);
    expect(get(selectedSite)).toBeNull();
  });
});

describe("selection", () => {
  it("tracks the selected site", () => {
    sites.set([site(1), site(2)]);
    selectSite(2);
    expect(get(selectedSite)?.id).toBe(2);
    selectSite(null);
    expect(get(selectedSite)).toBeNull();
  });
});
