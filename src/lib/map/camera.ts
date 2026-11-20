// Where the camera should go. Pure (returns bounds), so it is unit tested.
import { siteShapeFeature, trackBounds, type LngLatBounds } from "../geo";
import type { LatLon, Site } from "../types";

function boundsOf(points: [number, number][]): LngLatBounds | null {
  if (points.length === 0) return null;
  let [west, south] = points[0];
  let [east, north] = points[0];
  for (const [lng, lat] of points) {
    west = Math.min(west, lng);
    east = Math.max(east, lng);
    south = Math.min(south, lat);
    north = Math.max(north, lat);
  }
  return [
    [west, south],
    [east, north],
  ];
}

export { trackBounds as routeBounds };

/** The search point plus the top picks (or every site if there are no top picks yet). */
export function resultsBounds(
  origin: LatLon,
  sites: Site[],
  topPicks: ReadonlySet<number>,
): LngLatBounds | null {
  if (sites.length === 0) return null;
  const picks = sites.filter((site) => topPicks.has(site.id));
  const focus = picks.length ? picks : sites;
  return boundsOf([[origin.lon, origin.lat], ...focus.map((site) => [site.lon, site.lat] as [number, number])]);
}

/** A site's outline (or bounding box), or null if it has neither (zoom to its point instead). */
export function siteBounds(site: Site): LngLatBounds | null {
  const shape = siteShapeFeature(site);
  if (!shape) return null;
  const positions = shape.geometry.type === "Polygon" ? shape.geometry.coordinates[0] : shape.geometry.coordinates;
  return boundsOf(positions.map(([lng, lat]) => [lng, lat] as [number, number]));
}
