/**
 * A stand-in for mapbox-gl in component tests (jsdom has no WebGL).
 * Records what the app asks the map to do, and lets tests click site dots.
 *
 *   vi.mock("mapbox-gl", () => import("../test/mapboxMock"));
 */
type Handler = (event?: unknown) => void;

export class Map {
  static instances: Map[] = [];
  handlers: Record<string, Handler[]> = {};
  sources: Record<string, { data: unknown; setData: (data: unknown) => void }> = {};
  calls: { method: string; args: unknown[] }[] = [];
  zoom = 7;

  constructor(public options: unknown) {
    Map.instances.push(this);
  }
  static get last(): Map {
    return Map.instances[Map.instances.length - 1];
  }
  static reset(): void {
    Map.instances = [];
    Popup.instances = [];
  }

  on(event: string, layerOrHandler: string | Handler, maybeHandler?: Handler): this {
    const key = typeof layerOrHandler === "string" ? `${event}:${layerOrHandler}` : event;
    const handler = typeof layerOrHandler === "string" ? maybeHandler! : layerOrHandler;
    (this.handlers[key] ??= []).push(handler);
    return this;
  }
  emit(key: string, event?: unknown): void {
    for (const handler of this.handlers[key] ?? []) handler(event);
  }
  /** Simulate the style finishing loading. */
  load(): void {
    this.emit("load");
  }
  /** Simulate a click on a site's dot. */
  clickSite(id: number): void {
    this.emit("click:sites", { features: [{ properties: { id: String(id) } }] });
  }
  /** Features the app last put in a source. */
  features(sourceId: string): { properties: Record<string, unknown> }[] {
    return ((this.sources[sourceId]?.data ?? { features: [] }) as { features: never[] }).features;
  }
  called(method: string): unknown[][] {
    return this.calls.filter((call) => call.method === method).map((call) => call.args);
  }

  private record(method: string, args: unknown[]): this {
    this.calls.push({ method, args });
    return this;
  }
  addControl(...args: unknown[]) {
    return this.record("addControl", args);
  }
  addSource(id: string, source: { data: unknown }) {
    const entry = {
      data: source.data,
      setData(data: unknown) {
        entry.data = data;
      },
    };
    this.sources[id] = entry;
    return this;
  }
  addLayer(...args: unknown[]) {
    return this.record("addLayer", args);
  }
  getSource(id: string) {
    return this.sources[id];
  }
  getCanvas() {
    return { style: {} as Record<string, string> };
  }
  getZoom() {
    return this.zoom;
  }
  fitBounds(...args: unknown[]) {
    return this.record("fitBounds", args);
  }
  flyTo(...args: unknown[]) {
    return this.record("flyTo", args);
  }
  jumpTo(...args: unknown[]) {
    return this.record("jumpTo", args);
  }
  easeTo(...args: unknown[]) {
    return this.record("easeTo", args);
  }
  remove() {
    return this.record("remove", []);
  }
}

export class Popup {
  static instances: Popup[] = [];
  html = "";
  removed = false;
  constructor(public options: unknown) {
    Popup.instances.push(this);
  }
  setLngLat() {
    return this;
  }
  setHTML(html: string) {
    this.html = html;
    return this;
  }
  addTo() {
    return this;
  }
  remove() {
    this.removed = true;
    return this;
  }
}

export class Marker {
  lngLat: unknown = null;
  constructor(public options: unknown) {}
  setLngLat(lngLat: unknown) {
    this.lngLat = lngLat;
    return this;
  }
  addTo() {
    return this;
  }
  remove() {
    this.lngLat = null;
    return this;
  }
}

export class NavigationControl {
  constructor(public options?: unknown) {}
}
export class ScaleControl {
  constructor(public options?: unknown) {}
}

const mapboxgl = { Map, Popup, Marker, NavigationControl, ScaleControl, accessToken: "" };
export default mapboxgl;
