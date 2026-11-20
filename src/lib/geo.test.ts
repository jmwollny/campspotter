// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { gpx } from "@tmcw/togeojson";
import type { Feature, FeatureCollection, LineString, Position } from "geojson";
import kingAlfredsWayGpx from "../../public/king-alfreds-way-full-route.gpx?raw";
import {
  circlePolygonFeature,
  describeTerrain,
  escapeHtml,
  findCoordsAtDistance,
  formatArea,
  formatDistance,
  formatScore,
  lineLengthKm,
  lineToNearestPointFeature,
  siteShapeFeature,
  siteToFeature,
  sortFinalSites,
  summariseRedFlags,
  trackBounds,
  trackCoordinates,
  trackLengthKm,
  trackLine,
} from "./geo";

const parseGpx = (text: string) => gpx(new DOMParser().parseFromString(text, "application/xml"));
const line = (coordinates: Position[]): Feature<LineString> => ({
  type: "Feature",
  properties: {},
  geometry: { type: "LineString", coordinates },
});
const collection = (...features: Feature[]): FeatureCollection => ({ type: "FeatureCollection", features });

/** The value, failing the test if it is null/undefined. */
function must<T>(value: T | null | undefined): T {
  expect(value).not.toBeNull();
  expect(value).toBeDefined();
  return value as T;
}

describe("route geometry", () => {
  const straight = collection(line([[0, 51], [0, 52]])); // ~111 km due north

  it("measures and walks along a route", () => {
    expect(trackLengthKm(straight)).toBeCloseTo(111.2, 0);
    const [lng, lat] = must(findCoordsAtDistance(straight, 55.6));
    expect(lng).toBeCloseTo(0, 6);
    expect(lat).toBeCloseTo(51.5, 2);
  });

  it("clamps distances to the ends of the route", () => {
    expect(findCoordsAtDistance(straight, -5)).toEqual([0, 51]);
    expect(must(findCoordsAtDistance(straight, 999))[1]).toBeCloseTo(52, 6);
  });

  it("joins LineStrings and MultiLineStrings and ignores waypoints", () => {
    const geojson = collection(
      line([[0, 0], [1, 0]]),
      {
        type: "Feature",
        properties: {},
        geometry: { type: "MultiLineString", coordinates: [[[1, 0], [2, 0]], [[2, 0], [3, 0]]] },
      },
      { type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [9, 9] } },
      // Invalid per the GeoJSON types, but GPX converters can produce it.
      { type: "Feature", properties: {}, geometry: null } as unknown as Feature,
    );
    expect(trackCoordinates(geojson)).toHaveLength(6);
    expect(trackBounds(geojson)).toEqual([[0, 0], [3, 0]]);
  });

  it("returns null/0 for routes without a line", () => {
    const waypointsOnly = collection({
      type: "Feature",
      properties: {},
      geometry: { type: "Point", coordinates: [0, 0] },
    });
    expect(trackLine(waypointsOnly)).toBeNull();
    expect(trackLengthKm(waypointsOnly)).toBe(0);
    expect(findCoordsAtDistance(waypointsOnly, 1)).toBeNull();
    expect(trackBounds(collection())).toBeNull();
  });

  it("puts the end of the slider exactly at the end of the route", () => {
    const route = must(trackLine(collection(line([[0, 51], [0.5, 51.2], [1, 51]]))));
    const end = must(route.geometry.coordinates.at(-1));
    const [lng, lat] = must(findCoordsAtDistance(collection(route), lineLengthKm(route)));
    expect(lng).toBeCloseTo(end[0], 6);
    expect(lat).toBeCloseTo(end[1], 6);
  });
});

// GBDIVIDE_v400.gpx (3.4 MB) takes minutes to parse under jsdom, so it is checked in the browser instead.
describe("bundled sample route", () => {
  it("King Alfred's Way parses to a followable route", () => {
    const [minKm, maxKm] = [330, 380]; // published as ~350 km
    const geojson = parseGpx(kingAlfredsWayGpx);
    const km = trackLengthKm(geojson);
    expect(km).toBeGreaterThan(minKm);
    expect(km).toBeLessThan(maxKm);
    // Every point along the route must lie on the route (the baseline app once drew the marker off-route).
    const coords = trackCoordinates(geojson);
    const [lng, lat] = must(findCoordsAtDistance(geojson, km / 4));
    const nearest = Math.min(...coords.map(([x, y]) => Math.hypot(x - lng, y - lat)));
    expect(nearest).toBeLessThan(0.02);
  });
});

describe("map features", () => {
  const site = {
    id: 42,
    lat: 51.1,
    lon: -1.2,
    nearest_bbox_point: { lat: 51.101, lon: -1.2 },
    bounds: { minlat: 51.1, minlon: -1.21, maxlat: 51.11, maxlon: -1.19 },
  };

  it("builds point features with rank and flags", () => {
    expect(siteToFeature(site, 0, { topPick: true })).toEqual({
      type: "Feature",
      properties: { id: "42", rank: 1, topPick: true, selected: false },
      geometry: { type: "Point", coordinates: [-1.2, 51.1] },
    });
  });

  it("draws a line from the origin to the nearest point", () => {
    const feature = must(lineToNearestPointFeature({ lat: 51, lon: -1 }, site, 2));
    expect(feature.geometry.coordinates).toEqual([[-1, 51], [-1.2, 51.101]]);
    expect(lineToNearestPointFeature(null, site, 0)).toBeNull();
    expect(lineToNearestPointFeature({ lat: 51, lon: -1 }, { id: 1 }, 0)).toBeNull();
  });

  it("uses the real outline when present, else the bounding box", () => {
    expect(must(siteShapeFeature(site)).geometry.coordinates[0]).toHaveLength(5);
    const closed = [[0, 0], [1, 0], [1, 1], [0, 0]].map(([lon, lat]) => ({ lat, lon }));
    expect(must(siteShapeFeature({ ...site, geometry: closed })).geometry.type).toBe("Polygon");
    const open = closed.slice(0, 3);
    expect(must(siteShapeFeature({ ...site, geometry: open })).geometry.type).toBe("LineString");
    expect(siteShapeFeature({ id: 1 })).toBeNull();
  });

  it("draws a closed circle of the right radius", () => {
    const circle = must(circlePolygonFeature({ lat: 51, lon: -1 }, 1000, 32));
    const ring = circle.geometry.coordinates[0];
    expect(ring).toHaveLength(33);
    expect(ring[0]).toEqual(ring.at(-1));
    expect((ring[0][1] - 51) * 111.195).toBeCloseTo(1, 2); // first point due north, 1 km
    expect(circlePolygonFeature(null, 1000)).toBeNull();
    expect(circlePolygonFeature({ lat: 51, lon: -1 }, 0)).toBeNull();
  });
});

describe("sortFinalSites", () => {
  it("puts top picks first in the server's order, then the rest by score", () => {
    const sites = [
      { id: 1, suitability_score: 90 },
      { id: 2, suitability_score: 40 },
      { id: 3 },
      { id: 4, suitability_score: 70 },
      { id: 5, suitability_score: 60 },
    ];
    expect(sortFinalSites(sites, [5, "2"]).map((s) => s.id)).toEqual([5, 2, 1, 4, 3]);
    expect(sites[0].id).toBe(1); // does not mutate the input
  });
});

describe("formatting", () => {
  it("escapes HTML from OSM names and LLM text", () => {
    expect(escapeHtml(`<img src=x onerror="alert('x')">&`)).toBe(
      "&lt;img src=x onerror=&quot;alert(&#39;x&#39;)&quot;&gt;&amp;",
    );
    expect(escapeHtml(null)).toBe("");
  });

  it("formats distances, areas and scores", () => {
    const nb = (s: string) => s.replace(/ /g, "\u00a0");
    expect(formatDistance(0)).toBe(nb("0 m"));
    expect(formatDistance(527.4)).toBe(nb("527 m"));
    expect(formatDistance(1520)).toBe(nb("1.5 km"));
    expect(formatDistance(null)).toBe("n/a");
    expect(formatDistance(NaN)).toBe("n/a");
    expect(formatArea(4500)).toBe(nb("4,500 m²"));
    expect(formatArea(84000)).toBe(nb("8.4 ha"));
    expect(formatArea(undefined)).toBe("n/a");
    expect(formatScore(76.24)).toBe("76%");
    expect(formatScore(undefined)).toBe("–");
  });

  it("turns OSM tag text into readable names", () => {
    expect(describeTerrain("natural:wood, name:The Moors")).toEqual({ kind: "Wood", name: "The Moors" });
    expect(describeTerrain("landuse:forest")).toEqual({ kind: "Forest", name: "" });
    expect(describeTerrain("natural:tree_group")).toEqual({ kind: "Tree group", name: "" });
    expect(describeTerrain("name:Odd: Name, natural:wood").name).toBe("Odd: Name");
    expect(describeTerrain(undefined)).toEqual({ kind: "Unknown terrain", name: "" });
  });

  it("summarises red flags with readable labels", () => {
    const flags = [{ type: "BUILDING" }, { type: "BUILDING" }, { type: "BARRIER" }, { type: "RESIDENTIAL" }];
    expect(summariseRedFlags(flags)).toBe("2 buildings, 1 barrier, 1 residential area");
    expect(summariseRedFlags([{ type: "SEWAGE_WORKS" }, { type: "SEWAGE_WORKS" }])).toBe("2 sewage works");
    expect(summariseRedFlags([])).toBe("");
  });
});
