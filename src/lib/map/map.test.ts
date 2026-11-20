import type { LineString } from "geojson";
import { describe, expect, it } from "vitest";

import type { Site } from "../types";
import { resultsBounds, siteBounds } from "./camera";
import { buildLayerData, type MapState } from "./layerData";
import { popupHtml } from "./popup";
import { SOURCE_IDS } from "./style";

const site = (id: number, extra: Partial<Site> = {}): Site => ({
  id,
  type: "way",
  lat: 51 + id / 1000,
  lon: -1,
  terrain_description: "natural:wood",
  area_size_band: "small",
  nearby_red_flags: [],
  nearest_bbox_point: { lat: 51 + id / 1000, lon: -1 },
  bounds: { minlat: 51, minlon: -1.01, maxlat: 51.01, maxlon: -0.99 },
  ...extra,
});

const state = (extra: Partial<MapState> = {}): MapState => ({
  track: null,
  origin: { lat: 51, lon: -1 },
  radiusM: 500,
  sites: [site(1), site(2), site(3)],
  topPicks: new Set([2]),
  selectedId: null,
  ...extra,
});

describe("buildLayerData", () => {
  it("fills every source the map declares", () => {
    expect(Object.keys(buildLayerData(state())).sort()).toEqual([...SOURCE_IDS].sort());
  });

  it("numbers the sites and marks top picks and the selection", () => {
    const props = buildLayerData(state({ selectedId: 3 })).sites.features.map((f) => f.properties);
    expect(props).toEqual([
      { id: "1", rank: 1, topPick: false, selected: false },
      { id: "2", rank: 2, topPick: true, selected: false },
      { id: "3", rank: 3, topPick: false, selected: true },
    ]);
  });

  it("draws lines only to the top picks and the selected site", () => {
    const lines = buildLayerData(state({ selectedId: 3 }))["site-lines"].features;
    expect(lines.map((f) => f.properties)).toEqual([
      { id: "2", rank: 2, topPick: true, selected: false },
      { id: "3", rank: 3, topPick: false, selected: true },
    ]);
    // Each line ends at its site's dot.
    expect(lines.map((f) => (f.geometry as LineString).coordinates[1])).toEqual([
      [-1, 51.002],
      [-1, 51.003],
    ]);
  });

  it("outlines the selected site", () => {
    expect(buildLayerData(state())["selected-shape"].features).toHaveLength(0);
    expect(buildLayerData(state({ selectedId: 1 }))["selected-shape"].features).toHaveLength(1);
  });

  it("draws the search circle only with a search point", () => {
    expect(buildLayerData(state())["search-radius"].features).toHaveLength(1);
    expect(buildLayerData(state({ origin: null }))["search-radius"].features).toHaveLength(0);
    expect(buildLayerData(state({ origin: null }))["site-lines"].features).toHaveLength(0);
  });

  it("is empty with nothing loaded", () => {
    const data = buildLayerData(state({ origin: null, sites: [], topPicks: new Set() }));
    for (const id of SOURCE_IDS) expect(data[id].features).toEqual([]);
  });
});

describe("popupHtml", () => {
  it("shows the site's details and links to OpenStreetMap", () => {
    const html = popupHtml(
      site(42, {
        terrain_description: "natural:wood, name:The Moors",
        suitability_score: 76.4,
        suitability_reason: "Quiet and large",
        distance_to_bbox_m: 527,
      }),
      1,
    );
    expect(html).toContain("<strong>1. The Moors</strong>");
    expect(html).toContain("76%");
    expect(html).toContain("“Quiet and large”");
    expect(html).toContain('href="https://www.openstreetmap.org/way/42"');
  });

  it("escapes names and reasons from OSM and the LLM", () => {
    const html = popupHtml(
      site(1, {
        terrain_description: 'natural:wood, name:<img src=x onerror="alert(1)">',
        suitability_reason: "<script>bad()</script>",
      }),
      1,
    );
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;img");
  });

  it("hides the heuristic placeholder reason", () => {
    expect(popupHtml(site(1, { suitability_reason: "heuristic fallback" }), 1)).not.toContain("heuristic");
  });
});

describe("camera", () => {
  it("frames the search point and the top picks", () => {
    const sites = [site(1, { lat: 51.5, lon: -1.5 }), site(2, { lat: 51.2, lon: -0.8 })];
    expect(resultsBounds({ lat: 51, lon: -1 }, sites, new Set([2]))).toEqual([
      [-1, 51],
      [-0.8, 51.2],
    ]);
    // No top picks yet: frame every site.
    expect(resultsBounds({ lat: 51, lon: -1 }, sites, new Set())).toEqual([
      [-1.5, 51],
      [-0.8, 51.5],
    ]);
    expect(resultsBounds({ lat: 51, lon: -1 }, [], new Set())).toBeNull();
  });

  it("frames a site's outline, or its bounding box", () => {
    expect(siteBounds(site(1))).toEqual([
      [-1.01, 51],
      [-0.99, 51.01],
    ]);
    const outlined = site(1, {
      geometry: [
        { lat: 51.1, lon: -1.2 },
        { lat: 51.3, lon: -1.1 },
      ],
    });
    expect(siteBounds(outlined)).toEqual([
      [-1.2, 51.1],
      [-1.1, 51.3],
    ]);
    expect(siteBounds(site(1, { bounds: undefined }))).toBeNull();
  });
});
