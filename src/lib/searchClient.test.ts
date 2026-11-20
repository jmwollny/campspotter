import { get } from "svelte/store";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { isSite, parseServerMessage, runSearch } from "./searchClient";
import { resetState, searching, sites, status, topPickIds } from "./stores";

const SITE = {
  id: 7,
  type: "way",
  lat: 51.3,
  lon: -1.9,
  terrain_description: "natural:wood",
  area_size_band: "medium",
  nearby_red_flags: [{ type: "BUILDING", distance_to_red_flag_m: 40, tag: "structure" }],
  distance_to_bbox_m: 12.5,
  geometry: [
    { lat: 51.3, lon: -1.9 },
    { lat: 51.31, lon: -1.89 },
  ],
};

describe("parseServerMessage", () => {
  it.each([
    { type: "status", msg: "Retrieving..." },
    { type: "error", msg: "Overpass is down" },
    { type: "batch", sites: [SITE] },
    { type: "final", sites: [SITE], refined_ids: [7] },
    { type: "final", sites: [], refined_ids: [] },
  ])("accepts a valid $type message", (message) => {
    expect(parseServerMessage(JSON.stringify(message))).toEqual(message);
  });

  it.each([
    ["not JSON", "{oops"],
    ["a JSON array", "[1, 2]"],
    ["an unknown type", '{"type": "progress", "msg": "50%"}'],
    ["a status without msg", '{"type": "status"}'],
    ["a batch without sites", '{"type": "batch"}'],
    ["a final with string ids", JSON.stringify({ type: "final", sites: [SITE], refined_ids: ["7"] })],
    ["a final without refined_ids", JSON.stringify({ type: "final", sites: [SITE] })],
  ])("rejects %s", (_label, raw) => {
    expect(parseServerMessage(raw)).toBeNull();
  });
});

describe("isSite", () => {
  it("accepts a minimal site", () => {
    const minimal: Record<string, unknown> = { ...SITE, nearby_red_flags: [] };
    delete minimal.distance_to_bbox_m;
    delete minimal.geometry;
    expect(isSite(minimal)).toBe(true);
  });

  it.each([
    ["a missing id", { ...SITE, id: undefined }],
    ["a fractional id", { ...SITE, id: 7.5 }],
    ["an unknown OSM type", { ...SITE, type: "area" }],
    ["a string latitude", { ...SITE, lat: "51.3" }],
    ["an unknown size band", { ...SITE, area_size_band: "huge" }],
    ["a malformed red flag", { ...SITE, nearby_red_flags: [{ type: "BUILDING" }] }],
    ["a non-numeric score", { ...SITE, suitability_score: "85" }],
    ["a malformed outline point", { ...SITE, geometry: [{ lat: 1 }] }],
    ["a null optional field", { ...SITE, distance_to_water_m: null }],
  ])("rejects %s", (_label, value) => {
    expect(isSite(value)).toBe(false);
  });
});

/** A WebSocket stand-in the test drives by hand. */
class FakeSocket {
  static last: FakeSocket;
  sent: string[] = [];
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(public url: string) {
    FakeSocket.last = this;
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    this.onclose?.();
  }
  // Test helpers
  open() {
    this.onopen?.();
  }
  receive(message: unknown) {
    this.onmessage?.({ data: typeof message === "string" ? message : JSON.stringify(message) });
  }
  fail() {
    this.onerror?.();
    this.close();
  }
}

const REQUEST = { lat: 51.3, lon: -1.9, radius: 800 };

function start(onResults = vi.fn()) {
  const handle = runSearch(REQUEST, {
    apiUrl: "ws://test",
    onResults,
    WebSocketImpl: FakeSocket as unknown as typeof WebSocket,
  });
  return { handle, socket: FakeSocket.last, onResults };
}

describe("runSearch", () => {
  beforeEach(() => resetState());
  afterEach(() => vi.restoreAllMocks());

  it("sends the request and applies the server's messages", () => {
    const { socket, onResults } = start();
    expect(socket.url).toBe("ws://test/ws/analyze");
    expect(get(searching)).toBe(true);

    socket.open();
    expect(JSON.parse(socket.sent[0])).toEqual(REQUEST);

    socket.receive({ type: "status", msg: "Retrieving..." });
    socket.receive({ type: "batch", sites: [SITE] });
    expect(get(sites)).toHaveLength(1);
    expect(onResults).toHaveBeenCalledTimes(1);

    socket.receive({ type: "final", sites: [SITE], refined_ids: [7] });
    socket.receive({ type: "status", msg: "Analysis complete" });
    socket.close();

    expect(get(topPickIds)).toEqual([7]);
    expect(onResults).toHaveBeenCalledTimes(2);
    expect(get(status)).toEqual({ message: "Analysis complete", isError: false });
    expect(get(searching)).toBe(false);
  });

  it("reports a server that can't be reached", () => {
    const { socket } = start();
    socket.fail();
    expect(get(status).isError).toBe(true);
    expect(get(status).message).toContain("Can't reach the Campspotter server at ws://test");
    expect(get(searching)).toBe(false);
  });

  it("reports a connection that closes before the search finishes", () => {
    const { socket } = start();
    socket.open();
    socket.receive({ type: "status", msg: "Retrieving..." });
    socket.close();
    expect(get(status)).toEqual({
      message: "The server closed the connection before the search finished.",
      isError: true,
    });
  });

  it("keeps the server's error message when it closes the socket after an error", () => {
    const { socket } = start();
    socket.receive({ type: "error", msg: "No woods or forests found within 500 m." });
    socket.close();
    expect(get(status)).toEqual({ message: "No woods or forests found within 500 m.", isError: true });
  });

  it("stops on a message it doesn't understand", () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const { socket } = start();
    socket.receive({ type: "batch", sites: [{ id: "not a site" }] });
    expect(socket.closed).toBe(true);
    expect(get(status).isError).toBe(true);
    expect(get(status).message).toContain("doesn't understand");
    expect(get(sites)).toEqual([]);
    expect(get(searching)).toBe(false);
  });

  it("ignores a second search while one is running", () => {
    const { socket } = start();
    const second = runSearch(REQUEST, {
      apiUrl: "ws://test",
      WebSocketImpl: FakeSocket as unknown as typeof WebSocket,
    });
    expect(FakeSocket.last).toBe(socket);
    second.cancel(); // harmless no-op
    expect(get(searching)).toBe(true);
  });

  it("still shows status messages that arrive after the results", () => {
    const { socket } = start();
    socket.receive({ type: "final", sites: [SITE], refined_ids: [7] });
    socket.receive({ type: "status", msg: "Analysis complete (heuristic scores: no LLM is configured)" });
    expect(get(status).message).toBe("Analysis complete (heuristic scores: no LLM is configured)");
  });

  it("ignores messages after it stops on a bad one", () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const { socket } = start();
    socket.receive("garbage");
    socket.receive({ type: "status", msg: "Retrieving..." });
    expect(get(status).message).toContain("doesn't understand");
  });

  it("can be cancelled", () => {
    const { handle, socket } = start();
    socket.open();
    handle.cancel();
    expect(socket.closed).toBe(true);
    expect(get(searching)).toBe(false);
    expect(get(status)).toEqual({ message: "", isError: false });
  });

  it("reports an invalid server address", () => {
    const Throwing = function () {
      throw new SyntaxError("The URL 'nope' is invalid.");
    } as unknown as typeof WebSocket;
    runSearch(REQUEST, { apiUrl: "nope", WebSocketImpl: Throwing });
    expect(get(status).message).toBe("Invalid server address nope: The URL 'nope' is invalid.");
    expect(get(searching)).toBe(false);
  });
});
