// Pure helpers for turning route/site data into GeoJSON. No Svelte or Mapbox here, so they can be unit tested.
import { along, length, lineString } from "@turf/turf";

/**
 * All track/route coordinates from a GeoJSON FeatureCollection, joined into one [lng, lat] list.
 * Handles LineString (GPX routes, single-segment tracks) and MultiLineString (multi-segment tracks).
 */
export function trackCoordinates(geojson) {
  const coords = [];
  for (const feature of geojson?.features ?? []) {
    const geometry = feature?.geometry;
    if (!geometry) continue;
    const lines =
      geometry.type === "LineString"
        ? [geometry.coordinates]
        : geometry.type === "MultiLineString"
          ? geometry.coordinates
          : [];
    for (const line of lines) {
      for (const coord of line) {
        const lng = Number(coord[0]);
        const lat = Number(coord[1]);
        if (Number.isFinite(lng) && Number.isFinite(lat)) coords.push([lng, lat]);
      }
    }
  }
  return coords;
}

/** The whole route as a single turf LineString, or null if it has fewer than two points. */
export function trackLine(geojson) {
  const coords = trackCoordinates(geojson);
  return coords.length >= 2 ? lineString(coords) : null;
}

export const lineLengthKm = (line) => (line ? length(line, { units: "kilometers" }) : 0);

export const trackLengthKm = (geojson) => lineLengthKm(trackLine(geojson));

/** [lng, lat] at `targetKm` along a turf LineString (clamped to the ends), or null. */
export function pointAlongLine(line, targetKm) {
  if (!line) return null;
  const km = Math.max(0, Number(targetKm) || 0);
  return along(line, km, { units: "kilometers" }).geometry.coordinates;
}

/** [lng, lat] at `targetKm` along the route, or null for an empty route. */
export const findCoordsAtDistance = (geojson, targetKm) => pointAlongLine(trackLine(geojson), targetKm);

/** [[west, south], [east, north]] of the route, or null. */
export function trackBounds(geojson) {
  const coords = trackCoordinates(geojson);
  if (coords.length === 0) return null;
  let [west, south] = coords[0];
  let [east, north] = coords[0];
  for (const [lng, lat] of coords) {
    west = Math.min(west, lng);
    east = Math.max(east, lng);
    south = Math.min(south, lat);
    north = Math.max(north, lat);
  }
  return [[west, south], [east, north]];
}

export const featureCollection = (features) => ({ type: "FeatureCollection", features });

export const siteToFeature = (site, index, { topPick = false, selected = false } = {}) => ({
  type: "Feature",
  properties: { id: String(site.id ?? ""), rank: index + 1, topPick, selected },
  geometry: { type: "Point", coordinates: [site.lon, site.lat] },
});

export function lineToNearestPointFeature(origin, site, index) {
  if (!origin || !site.nearest_bbox_point) return null;
  return {
    type: "Feature",
    properties: { id: String(site.id ?? ""), rank: index + 1 },
    geometry: {
      type: "LineString",
      coordinates: [
        [origin.lon, origin.lat],
        [site.nearest_bbox_point.lon, site.nearest_bbox_point.lat],
      ],
    },
  };
}

/** The site's real outline when the server fetched one, otherwise its bounding box. */
export function siteShapeFeature(site) {
  const properties = { id: String(site.id ?? "") };
  if (Array.isArray(site.geometry) && site.geometry.length >= 2) {
    const coordinates = site.geometry.map((point) => [point.lon, point.lat]);
    const first = coordinates[0];
    const last = coordinates[coordinates.length - 1];
    const isClosed = first[0] === last[0] && first[1] === last[1];
    return {
      type: "Feature",
      properties,
      geometry:
        isClosed && coordinates.length >= 4
          ? { type: "Polygon", coordinates: [coordinates] }
          : { type: "LineString", coordinates },
    };
  }
  const b = site.bounds;
  if (!b) return null;
  return {
    type: "Feature",
    properties,
    geometry: {
      type: "Polygon",
      coordinates: [[
        [b.minlon, b.minlat],
        [b.maxlon, b.minlat],
        [b.maxlon, b.maxlat],
        [b.minlon, b.maxlat],
        [b.minlon, b.minlat],
      ]],
    },
  };
}

/** Geodesic circle polygon (for the search radius), or null without a usable origin/radius. */
export function circlePolygonFeature(origin, radiusMeters, steps = 64) {
  if (!origin || origin.lat == null || origin.lon == null || !(radiusMeters > 0)) return null;
  const earthRadiusM = 6371000;
  const latRad = (origin.lat * Math.PI) / 180;
  const lonRad = (origin.lon * Math.PI) / 180;
  const angularDistance = radiusMeters / earthRadiusM;
  const sinLat = Math.sin(latRad);
  const cosLat = Math.cos(latRad);
  const sinAng = Math.sin(angularDistance);
  const cosAng = Math.cos(angularDistance);
  const ring = [];

  for (let i = 0; i <= steps; i += 1) {
    const bearing = (2 * Math.PI * i) / steps;
    const pointLat = Math.asin(sinLat * cosAng + cosLat * sinAng * Math.cos(bearing));
    const pointLon =
      lonRad + Math.atan2(Math.sin(bearing) * sinAng * cosLat, cosAng - sinLat * Math.sin(pointLat));
    ring.push([(pointLon * 180) / Math.PI, (pointLat * 180) / Math.PI]);
  }
  ring[ring.length - 1] = ring[0]; // close exactly, avoiding floating point drift

  return {
    type: "Feature",
    properties: { radius_m: radiusMeters },
    geometry: { type: "Polygon", coordinates: [ring] },
  };
}

/** Final ordering: the server's top picks first (in the server's order), then by score, high to low. */
export function sortFinalSites(sites, refinedIds) {
  const refinedOrder = new Map((refinedIds ?? []).map((id, index) => [String(id), index]));
  const score = (site) => (typeof site.suitability_score === "number" ? site.suitability_score : -1);
  return [...sites].sort((a, b) => {
    const aRank = refinedOrder.get(String(a.id));
    const bRank = refinedOrder.get(String(b.id));
    if (aRank !== undefined && bRank !== undefined) return aRank - bRank;
    if (aRank !== undefined) return -1;
    if (bRank !== undefined) return 1;
    return score(b) - score(a);
  });
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

/** Escape text before putting it into popup HTML (OSM names and LLM reasons are untrusted). */
export function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char],
  );
}

const NBSP = "\u00a0"; // keeps "85 m" together when the line wraps

export function formatDistance(meters) {
  if (typeof meters !== "number" || !Number.isFinite(meters)) return "n/a";
  if (meters < 1000) return `${Math.round(meters)}${NBSP}m`;
  return `${(meters / 1000).toFixed(1)}${NBSP}km`;
}

export function formatArea(squareMeters) {
  if (typeof squareMeters !== "number" || !Number.isFinite(squareMeters)) return "n/a";
  if (squareMeters >= 10000) return `${(squareMeters / 10000).toFixed(1)}${NBSP}ha`;
  return `${Math.round(squareMeters).toLocaleString("en-GB")}${NBSP}m²`;
}

export function formatScore(score) {
  return typeof score === "number" && Number.isFinite(score) ? `${Math.round(score)}%` : "–";
}

/** "natural:wood, name:Foxley Copse" -> { kind: "Wood", name: "Foxley Copse" } */
export function describeTerrain(terrainDescription) {
  const parts = Object.fromEntries(
    String(terrainDescription ?? "")
      .split(",")
      .map((part) => part.trim().split(":"))
      .filter((pair) => pair.length >= 2)
      .map(([key, ...rest]) => [key, rest.join(":")]),
  );
  const rawKind = parts.landuse === "forest" ? "forest" : parts.natural || parts.tourism || parts.landuse || "";
  const kind = rawKind ? rawKind.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()) : "Unknown terrain";
  return { kind, name: parts.name ?? "" };
}

const RED_FLAG_LABELS = {
  RESIDENTIAL: "residential area",
  PARKING: "car park",
  SEWAGE_WORKS: "sewage works",
  WORKS: "works",
  GOLF_COURSE: "golf course",
  POLICE: "police station",
};

/** Short summary of red flags, e.g. "3 buildings, 1 barrier". */
export function summariseRedFlags(flags) {
  const counts = new Map();
  for (const flag of flags ?? []) {
    const rawType = String(flag?.type ?? "OTHER").toUpperCase();
    const type = RED_FLAG_LABELS[rawType] ?? rawType.toLowerCase().replace(/_/g, " ");
    counts.set(type, (counts.get(type) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([type, count]) => `${count} ${type}${count === 1 || type.endsWith("s") ? "" : "s"}`)
    .join(", ");
}
