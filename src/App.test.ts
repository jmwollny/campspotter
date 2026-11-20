// @vitest-environment jsdom
/**
 * UI tests: render the whole app and use it the way a person would (roles, labels and
 * visible text). mapbox-gl and the websocket are replaced with fakes.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import kingAlfredsWayGpx from "../public/king-alfreds-way-full-route.gpx?raw";
import App from "./App.svelte";
import { resetState } from "./lib/stores";
import type { Site } from "./lib/types";
import { Map as FakeMap, Popup as FakePopup } from "./test/mapboxMock";

vi.mock("mapbox-gl", () => import("./test/mapboxMock"));

const site = (id: number, extra: Partial<Site> = {}): Site => ({
  id,
  type: "way",
  lat: 51.06 + id / 1000,
  lon: -1.32,
  terrain_description: "natural:wood",
  area_size_band: "medium",
  nearby_red_flags: [],
  distance_to_bbox_m: 100 * id,
  ...extra,
});

/** A websocket the test plays the server's part in. */
class FakeSocket {
  static last: FakeSocket;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(public url: string) {
    FakeSocket.last = this;
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.onclose?.();
  }
  open() {
    this.onopen?.();
  }
  receive(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}

/** Render the app, let the (fake) map finish loading, and return a user to drive it. */
async function renderApp() {
  const user = userEvent.setup();
  render(App);
  FakeMap.last.load();
  return { user, map: FakeMap.last };
}

async function loadSampleRoute(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "King Alfred's Way" }));
  await screen.findByText("King Alfred's Way", { selector: ".route-name strong" });
}

// jsdom's File/Blob lack .text(), which every browser has.
if (!Blob.prototype.text) {
  Blob.prototype.text = function (this: Blob) {
    return new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(this);
    });
  };
}

beforeEach(() => {
  resetState();
  FakeMap.reset();
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url.endsWith("king-alfreds-way-full-route.gpx")
        ? new Response(kingAlfredsWayGpx)
        : new Response("", { status: 404 }),
    ),
  );
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => vi.unstubAllGlobals());

describe("accessibility", () => {
  it("has a main landmark, a labelled map and panel, and a skip link to the controls", async () => {
    await renderApp();
    expect(screen.getByRole("main")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Route map" })).toBeTruthy();
    const panel = screen.getByRole("region", { name: "Route, search and results" });
    const skip = screen.getByRole("link", { name: "Skip to route and search" });
    expect(skip.getAttribute("href")).toBe(`#${panel.id}`);
  });
});

describe("getting started", () => {
  it("asks for a route and hides the search until there is one", async () => {
    await renderApp();
    expect(screen.getByText("Load a GPX route to get started.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /search this area/i })).toBeNull();
    expect(screen.queryByRole("slider")).toBeNull();
  });

  it("loads a bundled sample route and fits the map to it", async () => {
    const { user, map } = await renderApp();
    await loadSampleRoute(user);

    expect(screen.getByText(/350\.9 km/, { selector: ".route-name" })).toBeTruthy();
    expect(screen.queryByText("Load a GPX route to get started.")).toBeNull();
    expect(screen.getByRole("slider", { name: /distance along route/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /search this area/i })).toHaveProperty("disabled", false);
    expect(map.called("fitBounds")).toHaveLength(1);
    expect(map.features("gpx-track").length).toBeGreaterThan(0);
  });

  it("loads a GPX file chosen by the user", async () => {
    const { user } = await renderApp();
    const file = new File([kingAlfredsWayGpx], "my-ride.gpx", { type: "application/gpx+xml" });
    await user.upload(screen.getByLabelText(/choose gpx file/i), file);
    expect(await screen.findByText("my-ride.gpx", { selector: ".route-name strong" })).toBeTruthy();
  });

  it("explains why a file can't be used", async () => {
    const { user } = await renderApp();
    const file = new File(["this is not GPX <"], "bad.gpx");
    await user.upload(screen.getByLabelText(/choose gpx file/i), file);
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Couldn't read bad.gpx: it isn't valid GPX/XML.",
    );
  });
});

describe("choosing the search point", () => {
  it("moves the point along the route and keeps the map on it", async () => {
    const { user, map } = await renderApp();
    await loadSampleRoute(user);
    const slider = screen.getByRole("slider", { name: /distance along route/i });

    await fireEvent.input(slider, { target: { value: "86.6" } });

    expect(screen.getByText("86.6 / 350.9 km")).toBeTruthy();
    expect(map.called("jumpTo")).toHaveLength(1);
  });

  it("changes the search radius", async () => {
    const { user, map } = await renderApp();
    await loadSampleRoute(user);
    await fireEvent.input(screen.getByRole("slider", { name: /search radius/i }), {
      target: { value: "1500" },
    });
    expect(screen.getByRole("slider", { name: /search radius/i }).getAttribute("aria-valuetext")).toBe(
      "1.5\u00a0km",
    );
    expect(map.features("search-radius")[0].properties.radius_m).toBe(1500);
  });
});

describe("searching", () => {
  it("shows progress, then the ranked sites with the top picks first", async () => {
    const { user, map } = await renderApp();
    await loadSampleRoute(user);
    await user.click(screen.getByRole("button", { name: /search this area/i }));

    const searchingButton = screen.getByRole("button", { name: /searching/i });
    expect(searchingButton).toHaveProperty("disabled", true);
    expect(screen.getByRole("status").textContent).toMatch(/connecting/i);

    const socket = FakeSocket.last;
    expect(socket.url).toBe("ws://test-server/ws/analyze");
    socket.open();
    expect(JSON.parse(socket.sent[0])).toMatchObject({ radius: 500 });

    socket.receive({ type: "status", msg: "Retrieving data from OpenStreetMap..." });
    socket.receive({ type: "batch", sites: [site(1), site(2), site(3)] });
    expect(await screen.findByText("3", { selector: ".count" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /scoring$/ })).toHaveLength(3); // still scoring

    socket.receive({
      type: "final",
      sites: [
        site(1, { suitability_score: 61 }),
        site(2, { suitability_score: 40 }),
        site(3, { suitability_score: 85.4, suitability_reason: "Big and quiet" }),
      ],
      refined_ids: [3],
    });
    socket.receive({ type: "status", msg: "Analysis complete (heuristic scores: no LLM is configured)" });
    socket.close();

    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain("Analysis complete (heuristic scores"),
    );
    const cards = within(screen.getByRole("list")).getAllByRole("button");
    const names = cards.map((card) => card.textContent?.replace(/\s+/g, " ").trim());
    expect(names.map((name) => name?.match(/^(\d+) (Top pick )?Wood/)?.[0])).toEqual([
      "1 Top pick Wood",
      "2 Wood",
      "3 Wood",
    ]);
    expect(screen.getByRole("button", { name: /^1\s*Top pick\s*Wood\s*score 85%$/ })).toBeTruthy();
    expect(cards[0].textContent).toContain("Top pick");
    expect(cards[0].textContent).toContain("85%");
    expect(cards[0].textContent).toContain("“Big and quiet”");
    expect(cards[1].textContent).not.toContain("Top pick");
    expect(screen.getByRole("button", { name: /search this area/i })).toHaveProperty("disabled", false);
    expect(map.features("sites").map((f) => f.properties.topPick)).toEqual([true, false, false]);
  });

  it("shows server errors as errors", async () => {
    const { user } = await renderApp();
    await loadSampleRoute(user);
    await user.click(screen.getByRole("button", { name: /search this area/i }));
    FakeSocket.last.receive({ type: "error", msg: "No woods or forests found within 500 m." });
    FakeSocket.last.close();

    const status = await screen.findByText("No woods or forests found within 500 m.");
    expect(status.getAttribute("role")).toBe("status");
    expect(status.classList.contains("error-text")).toBe(true);
  });

  it("tells the user when the server can't be reached", async () => {
    const { user } = await renderApp();
    await loadSampleRoute(user);
    await user.click(screen.getByRole("button", { name: /search this area/i }));
    FakeSocket.last.onerror?.();
    FakeSocket.last.close();
    expect((await screen.findByRole("status")).textContent).toContain(
      "Can't reach the Campspotter server at ws://test-server",
    );
  });
});

describe("selecting a site", () => {
  async function withResults() {
    const app = await renderApp();
    await loadSampleRoute(app.user);
    await app.user.click(screen.getByRole("button", { name: /search this area/i }));
    FakeSocket.last.receive({
      type: "final",
      sites: [
        site(1, { terrain_description: "natural:wood, name:The Moors" }),
        site(2),
      ],
      refined_ids: [1],
    });
    FakeSocket.last.close();
    await screen.findByText("The Moors");
    return app;
  }

  it("from the list: highlights the card, opens its popup and zooms the map", async () => {
    const { user, map } = await withResults();
    const card = screen.getByRole("button", { name: /the moors/i });
    const zoomsBefore = map.called("fitBounds").length + map.called("easeTo").length;

    await user.click(card);

    expect(card.getAttribute("aria-pressed")).toBe("true");
    expect(FakePopup.instances.at(-1)?.html).toContain("1. The Moors");
    // Keyboard focus stays on the card instead of jumping into the map popup.
    expect(FakePopup.instances.at(-1)?.options).toMatchObject({ focusAfterOpen: false });
    // The popup's OpenStreetMap link is also in the list, for people not using the map.
    expect(screen.getByRole("link", { name: /view on openstreetmap/i }).getAttribute("href")).toBe(
      "https://www.openstreetmap.org/way/1",
    );
    expect(map.called("fitBounds").length + map.called("easeTo").length).toBe(zoomsBefore + 1);
    expect(map.features("selected-shape")).toHaveLength(0); // no bounds or outline for this site
  });

  it("from the map: highlights the card and scrolls the list to it", async () => {
    const { map } = await withResults();
    map.clickSite(2);

    await waitFor(() =>
      expect(screen.getAllByRole("button", { pressed: true })).toHaveLength(1),
    );
    const pressed = screen.getByRole("button", { pressed: true });
    expect(pressed.querySelector(".rank")?.textContent).toBe("2");
    await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalled());
    expect(FakePopup.instances.at(-1)?.html).toContain("2. Wood");
  });

  it("skips map animations when the user prefers reduced motion", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce") }));
    const { user, map } = await withResults();
    await user.click(screen.getByRole("button", { name: /the moors/i }));
    const lastZoom = map.called("easeTo").at(-1) ?? map.called("fitBounds").at(-1);
    expect(JSON.stringify(lastZoom)).toContain('"duration":0');
  });

  it("moving the search point clears the results and the popup", async () => {
    const { user } = await withResults();
    await user.click(screen.getByRole("button", { name: /the moors/i }));
    await fireEvent.input(screen.getByRole("slider", { name: /distance along route/i }), {
      target: { value: "5" },
    });
    expect(screen.queryByText("The Moors")).toBeNull();
    expect(FakePopup.instances.at(-1)?.removed).toBe(true);
  });
});
