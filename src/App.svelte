<script lang="ts">
  import { onDestroy, tick } from "svelte";
  import { get } from "svelte/store";

  import MapView from "./components/MapView.svelte";
  import { describeTerrain, formatArea, formatDistance, formatScore, summariseRedFlags } from "./lib/geo";
  import { OTHER_SITE_COLOR, TOP_PICK_COLOR } from "./lib/map/style";
  import { runSearch, type SearchHandle } from "./lib/searchClient";
  import {
    loadRoute,
    loadRouteFromUrl,
    moveSearchPoint,
    origin,
    route,
    routeError,
    routeLoading,
    searchDistanceKm,
    searchRadiusM,
    searching,
    selectSite as setSelectedSite,
    selectedSiteId,
    sites,
    status,
    topPickSet,
  } from "./lib/stores";
  import type { Site } from "./lib/types";

  interface SampleRoute {
    file: string;
    label: string;
  }

  const mapboxToken = import.meta.env.VITE_MAPBOX_TOKEN;
  const apiUrl = (import.meta.env.VITE_API_WS_URL || "ws://localhost:8000").replace(/\/+$/, "");
  const SAMPLE_ROUTES: SampleRoute[] = [
    { file: "king-alfreds-way-full-route.gpx", label: "King Alfred's Way" },
    { file: "GBDIVIDE_v400.gpx", label: "GB Divide" },
  ];

  let mapView: MapView;
  let listElement: HTMLOListElement;
  let currentSearch: SearchHandle | undefined;

  onDestroy(() => currentSearch?.cancel());

  // ---------------------------------------------------------------------------
  // Route
  // ---------------------------------------------------------------------------

  async function handleFileUpload(event: Event & { currentTarget: HTMLInputElement }) {
    const file = event.currentTarget.files?.[0];
    if (!file) return;
    if (loadRoute(await file.text(), file.name)) routeLoaded();
  }

  async function loadSampleRoute(sample: SampleRoute) {
    if (await loadRouteFromUrl(`/${sample.file}`, sample.label)) routeLoaded();
  }

  function routeLoaded() {
    mapView.clearPopup();
    mapView.fitToRoute();
  }

  // ---------------------------------------------------------------------------
  // Search point and search
  // ---------------------------------------------------------------------------

  function handleDistanceInput(event: Event & { currentTarget: HTMLInputElement }) {
    moveSearchPoint(Number(event.currentTarget.value));
    mapView.clearPopup();
    mapView.followSearchPoint();
  }

  function startSearch() {
    const searchOrigin = get(origin);
    if (!searchOrigin) return;
    mapView.clearPopup();
    currentSearch = runSearch(
      { lat: searchOrigin.lat, lon: searchOrigin.lon, radius: get(searchRadiusM) },
      { apiUrl, onResults: () => tick().then(mapView.fitToResults) },
    );
  }

  // ---------------------------------------------------------------------------
  // Selecting a site (from the list, or by clicking its dot on the map)
  // ---------------------------------------------------------------------------

  async function selectSite(site: Site, { fromMap = false }: { fromMap?: boolean } = {}) {
    setSelectedSite(site.id);
    const rank = get(sites).indexOf(site) + 1;
    // From the list: zoom the map to the site. From the map: scroll the list to it.
    mapView.showSite(site, rank, { zoom: !fromMap });
    if (fromMap) {
      await tick();
      listElement?.querySelector(`[data-site-id="${CSS.escape(String(site.id))}"]`)?.scrollIntoView({
        block: "nearest",
        behavior: "smooth",
      });
    }
  }

  function handleSiteClick(event: CustomEvent<number>) {
    const site = get(sites).find((candidate) => candidate.id === event.detail);
    if (site) selectSite(site, { fromMap: true });
  }
</script>

<div class="app">
  <header class="app-header">
    <h1>Campspotter</h1>
    <p>Find quiet woodland for a wild camp along your route.</p>
  </header>

  <div class="layout">
    <MapView bind:this={mapView} accessToken={mapboxToken} on:siteclick={handleSiteClick} />

    <aside class="panel">
      <section class="panel-section">
        <h2>1. Route</h2>
        <label class="file-button">
          <input type="file" accept=".gpx,application/gpx+xml" on:change={handleFileUpload} />
          Choose GPX file…
        </label>
        <p class="hint">
          or try
          {#each SAMPLE_ROUTES as sample, i (sample.file)}
            {#if i > 0}&nbsp;or&nbsp;{/if}<button
              type="button"
              class="link-button"
              disabled={$routeLoading}
              on:click={() => loadSampleRoute(sample)}>{sample.label}</button
            >
          {/each}
        </p>
        {#if $routeError}
          <p class="error-text" role="alert">{$routeError}</p>
        {:else if $route}
          <p class="route-name"><strong>{$route.name}</strong> · {$route.lengthKm.toFixed(1)} km</p>
        {/if}
      </section>

      {#if $route}
        <section class="panel-section">
          <h2>2. Search point</h2>
          <label class="slider">
            <span class="slider-label">
              Distance along route
              <output>{$searchDistanceKm.toFixed(1)} / {$route.lengthKm.toFixed(1)} km</output>
            </span>
            <input
              type="range"
              min="0"
              max={$route.lengthKm}
              step="0.1"
              value={$searchDistanceKm}
              disabled={$searching}
              on:pointerdown={() => mapView.beginScrub()}
              on:input={handleDistanceInput}
              on:change={() => mapView.endScrub()}
            />
          </label>
          <label class="slider">
            <span class="slider-label">
              Search radius
              <output>{formatDistance($searchRadiusM)}</output>
            </span>
            <input type="range" min="100" max="2000" step="50" bind:value={$searchRadiusM} disabled={$searching} />
          </label>
          <p class="hint">Larger radii take longer: OpenStreetMap returns a lot more data.</p>

          <button type="button" class="primary-button" on:click={startSearch} disabled={$searching || !$origin}>
            {#if $searching}<span class="spinner" aria-hidden="true"></span>Searching…{:else}Search this area{/if}
          </button>
          <p class="status" class:error-text={$status.isError} role="status" aria-live="polite">
            {$status.message}
          </p>
        </section>
      {/if}

      {#if $sites.length}
        <section class="panel-section results">
          <h2>3. Candidate sites <span class="count">{$sites.length}</span></h2>
          <p class="legend">
            <span><i style="background:{TOP_PICK_COLOR}"></i>Top pick</span>
            <span><i style="background:{OTHER_SITE_COLOR}"></i>Other woodland</span>
          </p>
          <ol class="site-list" bind:this={listElement}>
            {#each $sites as site, i (site.id)}
              {@const terrain = describeTerrain(site.terrain_description)}
              {@const flags = summariseRedFlags(site.nearby_red_flags)}
              {@const topPick = $topPickSet.has(site.id)}
              <li data-site-id={site.id}>
                <button
                  type="button"
                  class="site-card"
                  class:top-pick={topPick}
                  class:selected={site.id === $selectedSiteId}
                  aria-pressed={site.id === $selectedSiteId}
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
                    {#if site.suitability_score == null && $searching}
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
