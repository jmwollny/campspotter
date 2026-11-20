// What each map source should contain for a given app state. Pure, so it is unit tested.
import type { FeatureCollection } from "geojson";

import {
  circlePolygonFeature,
  featureCollection,
  lineToSiteFeature,
  siteShapeFeature,
  siteToFeature,
} from "../geo";
import type { LatLon, Site } from "../types";
import type { SourceId } from "./style";

export interface MapState {
  track: FeatureCollection | null;
  origin: LatLon | null;
  radiusM: number;
  sites: Site[];
  topPicks: ReadonlySet<number>;
  selectedId: number | null;
}

const isPresent = <T>(value: T | null | undefined): value is T => value != null;

export function buildLayerData(state: MapState): Record<SourceId, FeatureCollection> {
  const { track, origin, radiusM, sites, topPicks, selectedId } = state;
  const isTop = (site: Site) => topPicks.has(site.id);
  const selected = sites.find((site) => site.id === selectedId);
  const selectedShape = selected ? siteShapeFeature(selected) : null;
  const circle = circlePolygonFeature(origin, radiusM);

  return {
    "gpx-track": track ?? featureCollection([]),
    sites: featureCollection(
      sites.map((site, index) =>
        siteToFeature(site, index, { topPick: isTop(site), selected: site.id === selectedId }),
      ),
    ),
    // Lines from the search point to the top picks (and the selected site) only, to avoid
    // a cluttered fan of lines to every candidate.
    "site-lines": featureCollection(
      sites
        .map((site, index) =>
          isTop(site) || site.id === selectedId
            ? lineToSiteFeature(origin, site, index, {
                topPick: isTop(site),
                selected: site.id === selectedId,
              })
            : null,
        )
        .filter(isPresent),
    ),
    "site-shapes": featureCollection(sites.map(siteShapeFeature).filter(isPresent)),
    "selected-shape": featureCollection(selectedShape ? [selectedShape] : []),
    "search-radius": featureCollection(circle ? [circle] : []),
  };
}
