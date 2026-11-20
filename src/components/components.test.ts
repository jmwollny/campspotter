// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { resetState, setStatus } from "../lib/stores";
import type { Site } from "../lib/types";
import MapView from "./MapView.svelte";
import SiteCard from "./SiteCard.svelte";
import StatusMessage from "./StatusMessage.svelte";

vi.mock("mapbox-gl", () => import("../test/mapboxMock"));

const SITE: Site = {
  id: 9,
  type: "way",
  lat: 51,
  lon: -1,
  terrain_description: "natural:wood, name:Foxley Copse",
  area_size_band: "large",
  area_m2: 84000,
  nearby_red_flags: [{ type: "BUILDING", distance_to_red_flag_m: 30, tag: "structure" }],
  distance_to_bbox_m: 527,
  distance_to_water_m: 154,
  suitability_score: 76.4,
  suitability_reason: "Large and away from roads",
};

beforeEach(() => resetState());

describe("SiteCard", () => {
  it("shows the site's name, details, score and reason", () => {
    render(SiteCard, { site: { ...SITE, distance_to_major_road_m: 1200 }, rank: 2, topPick: true });
    const card = screen.getByRole("button", { name: /^2\s*Top pick\s*Foxley Copse\s*score 76%$/ });
    expect(card.textContent).toContain("Foxley Copse");
    expect(card.textContent).toContain("Wood");
    expect(card.textContent).toContain("Top pick");
    expect(card.textContent).toContain("527 m from route · 8.4 ha");
    expect(card.textContent).toContain("water 154 m");
    expect(card.textContent).toContain("Nearby: 1 building");
    expect(card.textContent).toContain("76%");
    expect(card.textContent).toContain("“Large and away from roads”");
    expect(card.getAttribute("aria-pressed")).toBe("false");
    // The details are the button's description, including the road distance the popup shows.
    const details = document.getElementById(card.getAttribute("aria-describedby")!);
    expect(details?.textContent).toContain("527\u00a0m from route");
    expect(details?.textContent).toContain("major road 1.2\u00a0km");
    expect(details?.textContent).toContain("Nearby: 1 building");
  });

  it("shows a spinner while scoring, and a dash for a missing score afterwards", () => {
    const unscored = { ...SITE, suitability_score: undefined };
    const { component } = render(SiteCard, { site: unscored, rank: 1, scoring: true });
    expect(screen.getByRole("button", { name: /^1\s*Foxley Copse\s*scoring$/ })).toBeTruthy();
    component.$set({ scoring: false });
    return Promise.resolve().then(() =>
      expect(screen.getByRole("button", { name: /^1\s*Foxley Copse\s*score –$/ })).toBeTruthy(),
    );
  });

  it("hides the heuristic placeholder reason", () => {
    render(SiteCard, { site: { ...SITE, suitability_reason: "heuristic fallback" }, rank: 1 });
    expect(screen.getByRole("button").textContent).not.toContain("heuristic");
  });

  it("reports clicks", async () => {
    const { component } = render(SiteCard, { site: SITE, rank: 1, selected: true });
    const onSelect = vi.fn();
    component.$on("select", onSelect);
    await userEvent.click(screen.getByRole("button", { pressed: true }));
    expect(onSelect.mock.calls[0][0].detail).toEqual(SITE);
  });
});

describe("StatusMessage", () => {
  it("is a polite live region that styles errors", async () => {
    render(StatusMessage);
    const region = screen.getByRole("status");
    expect(region.getAttribute("aria-live")).toBe("polite");
    setStatus("OpenStreetMap is busy", true);
    await Promise.resolve();
    expect(region.textContent?.trim()).toBe("OpenStreetMap is busy");
    expect(region.classList.contains("error-text")).toBe(true);
  });
});

describe("MapView", () => {
  it("explains a missing Mapbox token instead of showing a blank map", () => {
    render(MapView, { accessToken: undefined });
    expect(screen.getByRole("alert").textContent).toContain("Missing VITE_MAPBOX_TOKEN");
  });
});
