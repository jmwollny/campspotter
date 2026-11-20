/**
 * Shapes of the data exchanged with the server over the websocket.
 *
 * These mirror the Pydantic models in server/models.py; keep the two in sync
 * (server/tests/test_types_sync.py checks the field names). The server leaves
 * out fields that have no value yet, so those are optional here.
 */

export interface LatLon {
  lat: number;
  lon: number;
}

export interface Bounds {
  minlat: number;
  minlon: number;
  maxlat: number;
  maxlon: number;
}

/** Something near a site that makes it less suitable (building, barrier, school...). */
export interface RedFlag {
  type: string;
  distance_to_red_flag_m: number;
  tag: string;
}

export type AreaSizeBand = "small" | "medium" | "large" | "unknown";

/** A candidate camping site; later pipeline stages fill in more fields. */
export interface Site {
  // Discover / summarise
  id: number;
  type: "node" | "way" | "relation";
  lat: number;
  lon: number;
  terrain_description: string;
  area_m2?: number;
  area_size_band: AreaSizeBand;
  distance_to_bbox_m?: number;
  nearby_red_flags: RedFlag[];
  bounds?: Bounds;
  nearest_bbox_point?: LatLon;

  // Enrich
  distance_to_major_road_m?: number;
  distance_to_water_m?: number;

  // Score
  suitability_score?: number;
  suitability_reason?: string;

  // Outline
  geometry?: LatLon[];
}

/** What the browser sends to /ws/analyze. */
export interface SearchRequest {
  lat: number;
  lon: number;
  radius: number;
}

// ---------------------------------------------------------------------------
// Server -> browser messages
// ---------------------------------------------------------------------------

export interface StatusMessage {
  type: "status";
  msg: string;
}

/** Sites so far (after discovery, then again after enrichment). */
export interface BatchMessage {
  type: "batch";
  sites: Site[];
}

/** Scored sites plus the ids of the top picks, best first. */
export interface FinalMessage {
  type: "final";
  sites: Site[];
  refined_ids: number[];
}

export interface ErrorMessage {
  type: "error";
  msg: string;
}

export type ServerMessage = StatusMessage | BatchMessage | FinalMessage | ErrorMessage;
