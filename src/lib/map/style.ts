// Map colours, sources and layers. The only place the map's look is defined.
import type { Map as MapboxMap } from "mapbox-gl";

import { featureCollection } from "../geo";

export const TOP_PICK_COLOR = "#15803d";
export const OTHER_SITE_COLOR = "#64748b";
export const ROUTE_COLOR = "#2563eb";

/** Every GeoJSON source the map draws; layerData.ts fills each one. */
export const SOURCE_IDS = [
  "search-radius",
  "gpx-track",
  "site-shapes",
  "selected-shape",
  "nearest-lines",
  "sites",
] as const;
export type SourceId = (typeof SOURCE_IDS)[number];

/** The layer whose dots are clickable sites. */
export const SITES_LAYER = "sites";

export function addSourcesAndLayers(map: MapboxMap): void {
  for (const id of SOURCE_IDS) {
    map.addSource(id, { type: "geojson", data: featureCollection([]) });
  }

  map.addLayer({
    id: "search-radius-fill",
    type: "fill",
    source: "search-radius",
    paint: { "fill-color": "#f43f5e", "fill-opacity": 0.08 },
  });
  map.addLayer({
    id: "search-radius-line",
    type: "line",
    source: "search-radius",
    paint: { "line-color": "#f43f5e", "line-width": 1.5, "line-opacity": 0.7, "line-dasharray": [2, 2] },
  });
  map.addLayer({
    id: "gpx-track-layer",
    type: "line",
    source: "gpx-track",
    layout: { "line-join": "round", "line-cap": "round" },
    paint: { "line-color": ROUTE_COLOR, "line-width": 4, "line-opacity": 0.85 },
  });
  map.addLayer({
    id: "site-shapes-line",
    type: "line",
    source: "site-shapes",
    paint: { "line-color": "#0f766e", "line-width": 1, "line-opacity": 0.45 },
  });
  map.addLayer({
    id: "selected-shape-fill",
    type: "fill",
    source: "selected-shape",
    paint: { "fill-color": TOP_PICK_COLOR, "fill-opacity": 0.18 },
  });
  map.addLayer({
    id: "selected-shape-line",
    type: "line",
    source: "selected-shape",
    paint: { "line-color": "#0f172a", "line-width": 2.5 },
  });
  map.addLayer({
    id: "nearest-lines",
    type: "line",
    source: "nearest-lines",
    paint: { "line-color": "#0f172a", "line-width": 1.5, "line-opacity": 0.6, "line-dasharray": [1, 1.5] },
  });
  map.addLayer({
    id: SITES_LAYER,
    type: "circle",
    source: "sites",
    paint: {
      "circle-radius": ["case", ["get", "selected"], 12, ["get", "topPick"], 10, 8],
      "circle-color": ["case", ["get", "topPick"], TOP_PICK_COLOR, OTHER_SITE_COLOR],
      "circle-stroke-width": ["case", ["get", "selected"], 3, 1.5],
      "circle-stroke-color": ["case", ["get", "selected"], "#0f172a", "#ffffff"],
    },
  });
  map.addLayer({
    id: "site-labels",
    type: "symbol",
    source: "sites",
    layout: {
      "text-field": ["to-string", ["get", "rank"]],
      "text-size": 11,
      "text-font": ["DIN Pro Bold", "Arial Unicode MS Bold"],
      "text-allow-overlap": true,
      "text-ignore-placement": true,
    },
    paint: { "text-color": "#ffffff" },
  });
}
