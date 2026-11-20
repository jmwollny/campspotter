/**
 * Owns the Mapbox map: creates it, draws the app state, shows popups and moves the camera.
 * This is the only module that talks to mapbox-gl; components just call these methods.
 */
import mapboxgl from "mapbox-gl";

import type { LatLon, Site } from "../types";
import { resultsBounds, routeBounds, siteBounds } from "./camera";
import { buildLayerData, type MapState } from "./layerData";
import { popupHtml } from "./popup";
import { addSourcesAndLayers, ROUTE_COLOR, SITES_LAYER, SOURCE_IDS } from "./style";

export interface MapCallbacks {
  /** A site's dot was clicked. */
  onSiteClick?: (siteId: number) => void;
  /** Something went wrong that the user should see (e.g. a rejected token). */
  onError?: (message: string) => void;
}

const INITIAL_VIEW = { center: [-1.6, 51.2] as [number, number], zoom: 7 };

/** Animation length, or 0 if the user asked the system to reduce motion. */
function duration(ms: number): number {
  const reduce = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  return reduce ? 0 : ms;
}

export class MapController {
  private readonly map: mapboxgl.Map;
  private readonly marker = new mapboxgl.Marker({ color: ROUTE_COLOR });
  private popup: mapboxgl.Popup | undefined;
  private loaded = false;
  /** State received before the style loaded; drawn as soon as it has. */
  private pendingState: MapState | undefined;
  private pendingRouteFit: MapState["track"] | undefined;
  private zoomBeforeScrub: number | null = null;

  /** Throws if the map can't be created (e.g. no WebGL). */
  constructor(container: HTMLElement, accessToken: string, private readonly callbacks: MapCallbacks = {}) {
    mapboxgl.accessToken = accessToken;
    this.map = new mapboxgl.Map({ container, style: "mapbox://styles/mapbox/outdoors-v12", ...INITIAL_VIEW });
    this.map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-right");
    this.map.addControl(new mapboxgl.ScaleControl({ unit: "metric" }), "bottom-left");
    if (import.meta.env.DEV) (window as unknown as { __map: mapboxgl.Map }).__map = this.map; // for debugging

    this.map.on("load", () => this.onLoad());
    this.map.on("error", (event) => {
      if ((event?.error as { status?: number } | undefined)?.status === 401) {
        this.callbacks.onError?.("Mapbox rejected the access token (VITE_MAPBOX_TOKEN).");
      }
    });
  }

  private onLoad(): void {
    addSourcesAndLayers(this.map);
    this.map.on("click", SITES_LAYER, (event: mapboxgl.MapMouseEvent) => {
      const id = Number(event.features?.[0]?.properties?.id);
      if (Number.isInteger(id)) this.callbacks.onSiteClick?.(id);
    });
    this.map.on("mouseenter", SITES_LAYER, () => (this.map.getCanvas().style.cursor = "pointer"));
    this.map.on("mouseleave", SITES_LAYER, () => (this.map.getCanvas().style.cursor = ""));
    this.loaded = true;

    if (this.pendingState) this.render(this.pendingState);
    if (this.pendingRouteFit !== undefined) this.fitToRoute(this.pendingRouteFit);
    this.pendingState = this.pendingRouteFit = undefined;
  }

  /** Draw the route, search area and sites for this state. */
  render(state: MapState): void {
    if (!this.loaded) {
      this.pendingState = state;
      return;
    }
    const data = buildLayerData(state);
    for (const id of SOURCE_IDS) {
      this.map.getSource<mapboxgl.GeoJSONSource>(id)?.setData(data[id]);
    }
    if (state.origin) this.marker.setLngLat([state.origin.lon, state.origin.lat]).addTo(this.map);
    else this.marker.remove();
  }

  fitToRoute(track: MapState["track"]): void {
    if (!this.loaded) {
      this.pendingRouteFit = track;
      return;
    }
    const bounds = routeBounds(track);
    if (bounds) this.map.fitBounds(bounds, { padding: 50, duration: duration(800) });
  }

  fitToResults(origin: LatLon | null, sites: Site[], topPicks: ReadonlySet<number>): void {
    const bounds = origin ? resultsBounds(origin, sites, topPicks) : null;
    if (bounds) this.map.fitBounds(bounds, { padding: 80, maxZoom: 15, duration: duration(800) });
  }

  /** Open the site's popup; optionally zoom to the site's outline. */
  showSite(site: Site, rank: number, { zoom = true }: { zoom?: boolean } = {}): void {
    this.clearPopup();
    // focusAfterOpen: false keeps keyboard focus on the list card (or map) the user is on;
    // the card already carries the popup's details for screen readers.
    this.popup = new mapboxgl.Popup({ maxWidth: "280px", offset: 10, focusAfterOpen: false })
      .setLngLat([site.lon, site.lat])
      .setHTML(popupHtml(site, rank))
      .addTo(this.map);
    if (!zoom) return;
    const bounds = siteBounds(site);
    if (bounds) this.map.fitBounds(bounds, { padding: 80, maxZoom: 16, duration: duration(700) });
    else this.map.easeTo({ center: [site.lon, site.lat], zoom: 16, duration: duration(700) });
  }

  clearPopup(): void {
    this.popup?.remove();
    this.popup = undefined;
  }

  // Dragging the route slider: zoom in while scrubbing, follow the point, zoom back out after.

  beginScrub(point: LatLon | null): void {
    if (!point) return;
    this.zoomBeforeScrub = this.map.getZoom();
    this.map.flyTo({
      center: [point.lon, point.lat],
      zoom: Math.max(this.zoomBeforeScrub, 12),
      duration: duration(300),
    });
  }

  followPoint(point: LatLon | null): void {
    if (point) this.map.jumpTo({ center: [point.lon, point.lat] });
  }

  endScrub(point: LatLon | null): void {
    // Only zoom back out if the drag started with the pointer (keyboard changes never zoomed in).
    if (point && this.zoomBeforeScrub != null) {
      this.map.flyTo({ center: [point.lon, point.lat], zoom: this.zoomBeforeScrub, duration: duration(800) });
    }
    this.zoomBeforeScrub = null;
  }

  destroy(): void {
    this.map.remove();
  }
}
