<script>
  import { onMount, tick } from "svelte";
  import mapboxgl from "mapbox-gl";
  import { gpx as gpxToGeoJSON } from "@tmcw/togeojson";
  import {
    circlePolygonFeature,
    describeTerrain,
    escapeHtml,
    featureCollection,
    formatArea,
    formatDistance,
    formatScore,
    lineLengthKm,
    lineToNearestPointFeature,
    pointAlongLine,
    siteShapeFeature,
    siteToFeature,
    sortFinalSites,
    summariseRedFlags,
    trackBounds,
    trackLine,
  } from "./lib/geo.js";

  const mapboxToken = import.meta.env.VITE_MAPBOX_TOKEN;
  const apiUrl = (import.meta.env.VITE_API_WS_URL || "ws://localhost:8000").replace(/\/+$/, "");
  const SAMPLE_ROUTES = [
    { file: "king-alfreds-way-full-route.gpx", label: "King Alfred's Way" },
    { file: "GBDIVIDE_v400.gpx", label: "GB Divide" },
  ];
  const TOP_PICK_COLOR = "#15803d";
  const OTHER_SITE_COLOR = "#64748b";
  const ROUTE_COLOR = "#2563eb";

  // Map
  let mapContainer;
  let map;
  let mapLoaded = false;
  let mapError = "";
  let scoutMarker;
  let popup;

  // Route
  let routeName = "";
  let routeError = "";
  let routeLoading = false;
  let trackData = null;
  let routeLine = null;
  let trackDistanceKm = 0;
  let searchDistance = 0;
  let origin = null; // { lat, lon } of the search point
  let searchRadiusM = 500;
  let zoomBeforeScrub = null;

  // Search
  let searching = false;
  let statusMessage = "";
  let statusIsError = false;
  let sites = [];
  let refinedIds = [];
  let selectedSiteId = null;
  let listElement;

  $: refinedSet = new Set(refinedIds.map(String));
  $: selectedKey = selectedSiteId == null ? null : String(selectedSiteId);
  $: if (mapLoaded) renderLayers(trackData, origin, searchRadiusM, sites, refinedSet, selectedKey);

  const isTopPick = (site) => refinedSet.has(String(site.id));

  function setStatus(message, isError = false) {
    statusMessage = message;
    statusIsError = isError;
  }

  function clearResults() {
    sites = [];
    refinedIds = [];
    selectedSiteId = null;
    popup?.remove();
  }

  // ---------------------------------------------------------------------------
  // Route loading
  // ---------------------------------------------------------------------------

  async function handleFileUpload(event) {
    const file = event.currentTarget.files?.[0];
    if (!file) return;
    loadRoute(await file.text(), file.name);
  }

  async function loadSampleRoute(sample) {
    routeLoading = true;
    try {
      const response = await fetch(`/${sample.file}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      loadRoute(await response.text(), sample.label);
    } catch (error) {
      routeError = `Couldn't load the ${sample.label} sample (${error.message}).`;
    } finally {
      routeLoading = false;
    }
  }

  function loadRoute(text, name) {
    routeError = "";
    let geojson;
    try {
      const xml = new DOMParser().parseFromString(text, "application/xml");
      if (xml.querySelector("parsererror")) throw new Error("it isn't valid GPX/XML");
      geojson = gpxToGeoJSON(xml);
    } catch (error) {
      routeError = `Couldn't read ${name}: ${error.message}.`;
      return;
    }
    const line = trackLine(geojson);
    if (!line) {
      routeError = `${name} doesn't contain a track or route to follow.`;
      return;
    }

    trackData = geojson;
    routeLine = line;
    // Same line (and turf maths) for length and position, so the slider's end is the route's end.
    trackDistanceKm = Math.floor(lineLengthKm(line) * 10) / 10;
    routeName = name;
    searchDistance = 0;
    clearResults();
    setStatus("");
    moveOriginTo(0);
    fitToRoute();
  }

  function moveOriginTo(km) {
    const coords = pointAlongLine(routeLine, km);
    origin = coords ? { lat: coords[1], lon: coords[0] } : null;
  }

  // ---------------------------------------------------------------------------
  // Search point controls
  // ---------------------------------------------------------------------------

  function beginScrub() {
    if (!map || !origin) return;
    zoomBeforeScrub = map.getZoom();
    map.flyTo({ center: [origin.lon, origin.lat], zoom: Math.max(zoomBeforeScrub, 12), duration: 300 });
  }

  function handleDistanceInput() {
    moveOriginTo(searchDistance);
    if (sites.length || statusMessage) {
      clearResults();
      setStatus("");
    }
    if (map && origin) map.jumpTo({ center: [origin.lon, origin.lat] });
  }

  function endScrub() {
    // Only zoom back out if the drag started with the pointer (keyboard changes never zoomed in).
    if (map && origin && zoomBeforeScrub != null) {
      map.flyTo({ center: [origin.lon, origin.lat], zoom: zoomBeforeScrub, duration: 800 });
    }
    zoomBeforeScrub = null;
  }

  // ---------------------------------------------------------------------------
  // Search
  // ---------------------------------------------------------------------------

  function startSearch() {
    if (searching || !origin) return;
    clearResults();
    searching = true;
    setStatus("Connecting to the Campspotter server…");
    let finished = false;

    let socket;
    try {
      socket = new WebSocket(`${apiUrl}/ws/analyze`);
    } catch (error) {
      searching = false;
      setStatus(`Invalid server address ${apiUrl}: ${error.message}`, true);
      return;
    }

    socket.onopen = () => {
      socket.send(JSON.stringify({ lat: origin.lat, lon: origin.lon, radius: searchRadiusM }));
    };

    socket.onmessage = (event) => {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }
      if (data.type === "status") {
        setStatus(data.msg);
      } else if (data.type === "batch") {
        const firstBatch = sites.length === 0;
        sites = data.sites ?? [];
        if (firstBatch) fitToResults();
      } else if (data.type === "final") {
        refinedIds = data.refined_ids ?? [];
        sites = sortFinalSites(data.sites ?? [], refinedIds);
        finished = true;
        tick().then(fitToResults);
      } else if (data.type === "error") {
        setStatus(data.msg, true);
        finished = true;
      }
    };

    socket.onerror = () => {
      if (!finished) {
        setStatus(
          `Can't reach the Campspotter server at ${apiUrl}. Is it running? (cd server && uv run python server.py)`,
          true,
        );
      }
      finished = true;
    };

    socket.onclose = () => {
      searching = false;
      if (!finished) setStatus("The server closed the connection before the search finished.", true);
    };
  }

  // ---------------------------------------------------------------------------
  // Map
  // ---------------------------------------------------------------------------

  function setSourceData(id, data) {
    map?.getSource(id)?.setData(data);
  }

  function renderLayers(track, searchOrigin, radius, siteList, topPicks, selected) {
    setSourceData("gpx-track", track ?? featureCollection([]));

    const isTop = (site) => topPicks.has(String(site.id));
    setSourceData(
      "sites",
      featureCollection(
        siteList.map((site, index) =>
          siteToFeature(site, index, { topPick: isTop(site), selected: String(site.id) === selected }),
        ),
      ),
    );
    // Lines from the route only to the top picks (and the selected site) to avoid a cluttered fan.
    setSourceData(
      "nearest-lines",
      featureCollection(
        siteList
          .map((site, index) =>
            isTop(site) || String(site.id) === selected
              ? lineToNearestPointFeature(searchOrigin, site, index)
              : null,
          )
          .filter(Boolean),
      ),
    );
    setSourceData("site-shapes", featureCollection(siteList.map(siteShapeFeature).filter(Boolean)));
    const selectedSite = siteList.find((site) => String(site.id) === selected);
    const selectedShape = selectedSite ? siteShapeFeature(selectedSite) : null;
    setSourceData("selected-shape", featureCollection(selectedShape ? [selectedShape] : []));
    const circle = circlePolygonFeature(searchOrigin, radius);
    setSourceData("search-radius", featureCollection(circle ? [circle] : []));

    if (scoutMarker) {
      if (searchOrigin) scoutMarker.setLngLat([searchOrigin.lon, searchOrigin.lat]).addTo(map);
      else scoutMarker.remove();
    }
  }

  function fitToRoute() {
    const bounds = trackBounds(trackData);
    if (map && bounds) map.fitBounds(bounds, { padding: 50, duration: 800 });
  }

  function fitToResults() {
    if (!map || !origin || sites.length === 0) return;
    const focus = sites.some(isTopPick) ? sites.filter(isTopPick) : sites;
    const bounds = new mapboxgl.LngLatBounds([origin.lon, origin.lat], [origin.lon, origin.lat]);
    for (const site of focus) bounds.extend([site.lon, site.lat]);
    map.fitBounds(bounds, { padding: 80, maxZoom: 15, duration: 800 });
  }

  function zoomToSite(site) {
    const shape = siteShapeFeature(site);
    const points =
      shape?.geometry.type === "Polygon" ? shape.geometry.coordinates[0] : (shape?.geometry.coordinates ?? []);
    if (points.length) {
      const bounds = new mapboxgl.LngLatBounds(points[0], points[0]);
      for (const point of points) bounds.extend(point);
      map.fitBounds(bounds, { padding: 80, maxZoom: 16, duration: 700 });
    } else {
      map.easeTo({ center: [site.lon, site.lat], zoom: 16, duration: 700 });
    }
  }

  function popupHtml(site, rank) {
    const { kind, name } = describeTerrain(site.terrain_description);
    const reason =
      site.suitability_reason && site.suitability_reason !== "heuristic fallback" ? site.suitability_reason : "";
    const flags = summariseRedFlags(site.nearby_red_flags);
    const rows = [
      ["Score", formatScore(site.suitability_score)],
      ["From route", formatDistance(site.distance_to_bbox_m)],
      ["Area", `${formatArea(site.area_m2)} (${site.area_size_band ?? "unknown"})`],
      ["Water", formatDistance(site.distance_to_water_m)],
      ["Major road", formatDistance(site.distance_to_major_road_m)],
      ["Nearby", flags || "no red flags"],
    ];
    const osmType = ["node", "way", "relation"].includes(site.type) ? site.type : null;
    return `
      <div class="popup">
        <strong>${rank}. ${escapeHtml(name || kind)}</strong>
        ${name ? `<div class="popup-kind">${escapeHtml(kind)}</div>` : ""}
        <dl>${rows.map(([label, value]) => `<dt>${label}</dt><dd>${escapeHtml(value)}</dd>`).join("")}</dl>
        ${reason ? `<p class="popup-reason">“${escapeHtml(reason)}”</p>` : ""}
        ${
          osmType
            ? `<a href="https://www.openstreetmap.org/${osmType}/${encodeURIComponent(site.id)}" target="_blank" rel="noopener noreferrer">View on OpenStreetMap ↗</a>`
            : ""
        }
      </div>`;
  }

  async function selectSite(site, { fromMap = false } = {}) {
    if (!site || !map) return;
    selectedSiteId = site.id;
    const rank = sites.indexOf(site) + 1;
    popup?.remove();
    popup = new mapboxgl.Popup({ maxWidth: "280px", offset: 10 })
      .setLngLat([site.lon, site.lat])
      .setHTML(popupHtml(site, rank))
      .addTo(map);
    if (fromMap) {
      await tick();
      listElement?.querySelector(`[data-site-id="${CSS.escape(String(site.id))}"]`)?.scrollIntoView({
        block: "nearest",
        behavior: "smooth",
      });
    } else {
      zoomToSite(site);
    }
  }

  function addLayers() {
    const empty = featureCollection([]);
    for (const id of ["search-radius", "gpx-track", "site-shapes", "selected-shape", "nearest-lines", "sites"]) {
      map.addSource(id, { type: "geojson", data: empty });
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
      id: "sites",
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

    map.on("click", "sites", (event) => {
      const id = event.features?.[0]?.properties?.id;
      const site = sites.find((candidate) => String(candidate.id) === String(id));
      if (site) selectSite(site, { fromMap: true });
    });
    map.on("mouseenter", "sites", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "sites", () => (map.getCanvas().style.cursor = ""));
  }

  onMount(() => {
    if (!mapboxToken) {
      mapError = "Missing VITE_MAPBOX_TOKEN. Add it to a .env file in the project root (see README).";
      return;
    }

    try {
      mapboxgl.accessToken = mapboxToken;
      map = new mapboxgl.Map({
        container: mapContainer,
        style: "mapbox://styles/mapbox/outdoors-v12",
        center: [-1.6, 51.2],
        zoom: 7,
      });
      map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-right");
      map.addControl(new mapboxgl.ScaleControl({ unit: "metric" }), "bottom-left");
      if (import.meta.env.DEV) /** @type {any} */ (window).__map = map; // handy for debugging and UI scripts

      map.on("load", () => {
        scoutMarker = new mapboxgl.Marker({ color: ROUTE_COLOR });
        addLayers();
        mapLoaded = true;
        if (trackData) fitToRoute(); // route was picked before the map finished loading
      });
      map.on("error", (event) => {
        if (/** @type {any} */ (event?.error)?.status === 401) mapError = "Mapbox rejected the access token (VITE_MAPBOX_TOKEN).";
      });
    } catch (error) {
      mapError = error instanceof Error ? error.message : "Failed to initialise the map.";
    }

    return () => map?.remove();
  });
</script>

<div class="app">
  <header class="app-header">
    <h1>Campspotter</h1>
    <p>Find quiet woodland for a wild camp along your route.</p>
  </header>

  <div class="layout">
    <div class="map-wrap">
      <div class="map" bind:this={mapContainer}></div>
      {#if mapError}
        <div class="map-overlay error-text" role="alert">{mapError}</div>
      {:else if !trackData}
        <div class="map-overlay">Load a GPX route to get started.</div>
      {/if}
    </div>

    <aside class="panel">
      <section class="panel-section">
        <h2>1. Route</h2>
        <label class="file-button">
          <input type="file" accept=".gpx,application/gpx+xml" on:change={handleFileUpload} />
          Choose GPX file…
        </label>
        <p class="hint">
          or try
          {#each SAMPLE_ROUTES as sample, i}
            {#if i > 0}&nbsp;or&nbsp;{/if}<button
              type="button"
              class="link-button"
              disabled={routeLoading}
              on:click={() => loadSampleRoute(sample)}>{sample.label}</button
            >
          {/each}
        </p>
        {#if routeError}
          <p class="error-text" role="alert">{routeError}</p>
        {:else if routeName}
          <p class="route-name"><strong>{routeName}</strong> · {trackDistanceKm.toFixed(1)} km</p>
        {/if}
      </section>

      {#if trackData}
        <section class="panel-section">
          <h2>2. Search point</h2>
          <label class="slider">
            <span class="slider-label">
              Distance along route
              <output>{searchDistance.toFixed(1)} / {trackDistanceKm.toFixed(1)} km</output>
            </span>
            <input
              type="range"
              min="0"
              max={trackDistanceKm}
              step="0.1"
              bind:value={searchDistance}
              disabled={searching}
              on:pointerdown={beginScrub}
              on:input={handleDistanceInput}
              on:change={endScrub}
            />
          </label>
          <label class="slider">
            <span class="slider-label">
              Search radius
              <output>{formatDistance(searchRadiusM)}</output>
            </span>
            <input type="range" min="100" max="2000" step="50" bind:value={searchRadiusM} disabled={searching} />
          </label>
          <p class="hint">Larger radii take longer: OpenStreetMap returns a lot more data.</p>

          <button type="button" class="primary-button" on:click={startSearch} disabled={searching || !origin}>
            {#if searching}<span class="spinner" aria-hidden="true"></span>Searching…{:else}Search this area{/if}
          </button>
          <p class="status" class:error-text={statusIsError} role="status" aria-live="polite">
            {statusMessage}
          </p>
        </section>
      {/if}

      {#if sites.length}
        <section class="panel-section results">
          <h2>3. Candidate sites <span class="count">{sites.length}</span></h2>
          <p class="legend">
            <span><i style="background:{TOP_PICK_COLOR}"></i>Top pick</span>
            <span><i style="background:{OTHER_SITE_COLOR}"></i>Other woodland</span>
          </p>
          <ol class="site-list" bind:this={listElement}>
            {#each sites as site, i (site.id)}
              {@const terrain = describeTerrain(site.terrain_description)}
              {@const flags = summariseRedFlags(site.nearby_red_flags)}
              {@const topPick = isTopPick(site)}
              <li data-site-id={site.id}>
                <button
                  type="button"
                  class="site-card"
                  class:top-pick={topPick}
                  class:selected={String(site.id) === selectedKey}
                  aria-pressed={String(site.id) === selectedKey}
                  on:click={() => selectSite(site)}
                >
                  <span class="rank" aria-label="Rank {i + 1}">{i + 1}</span>
                  <span class="site-body">
                    {#if topPick}<span class="badge">Top pick</span>{/if}
                    <span class="site-title">{terrain.name || terrain.kind}</span>
                    {#if terrain.name}<span class="site-kind">{terrain.kind}</span>{/if}
                    <span class="site-meta">
                      {formatDistance(site.distance_to_bbox_m)} from route · {formatArea(site.area_m2)}
                      {#if site.distance_to_water_m != null}· water {formatDistance(site.distance_to_water_m)}{/if}
                    </span>
                    {#if flags}<span class="site-flags">Nearby: {flags}</span>{/if}
                    {#if site.suitability_reason && site.suitability_reason !== "heuristic fallback"}
                      <span class="reason">“{site.suitability_reason}”</span>
                    {/if}
                  </span>
                  <span class="score" class:pending={site.suitability_score == null}>
                    {#if site.suitability_score == null && searching}
                      <span class="spinner small" aria-label="Scoring"></span>
                    {:else}
                      {formatScore(site.suitability_score)}
                    {/if}
                  </span>
                </button>
              </li>
            {/each}
          </ol>
        </section>
      {/if}
    </aside>
  </div>
</div>
