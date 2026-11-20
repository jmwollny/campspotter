<!--
  Lays out the page and coordinates the map with the side panel. State lives in
  src/lib/stores.ts; each section of the panel is its own component.
-->
<script lang="ts">
  import { onDestroy, tick } from "svelte";
  import { get } from "svelte/store";

  import MapView from "./components/MapView.svelte";
  import RoutePicker from "./components/RoutePicker.svelte";
  import SearchControls from "./components/SearchControls.svelte";
  import SiteList from "./components/SiteList.svelte";
  import { runSearch, type SearchHandle } from "./lib/searchClient";
  import { origin, searchRadiusM, searching, selectSite, sites } from "./lib/stores";
  import type { Site } from "./lib/types";

  const mapboxToken = import.meta.env.VITE_MAPBOX_TOKEN;
  const apiUrl = (import.meta.env.VITE_API_WS_URL || "ws://localhost:8000").replace(/\/+$/, "");

  let mapView: MapView;
  let siteList: SiteList;
  let currentSearch: SearchHandle | undefined;

  onDestroy(() => currentSearch?.cancel());

  function routeLoaded() {
    mapView.clearPopup();
    mapView.fitToRoute();
  }

  function searchPointMoved() {
    mapView.clearPopup();
    mapView.followSearchPoint();
  }

  function cancelSearch() {
    currentSearch?.cancel();
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === "Escape" && get(searching)) cancelSearch();
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

  /** From the list: select and zoom the map to the site. From the map: select and scroll the list. */
  function showSite(site: Site, from: "list" | "map") {
    selectSite(site.id);
    mapView.showSite(site, get(sites).indexOf(site) + 1, { zoom: from === "list" });
    if (from === "map") siteList.scrollTo(site.id);
  }

  function handleMapClick(event: CustomEvent<number>) {
    const site = get(sites).find((candidate) => candidate.id === event.detail);
    if (site) showSite(site, "map");
  }
</script>

<svelte:window on:keydown={handleKeydown} />

<a class="skip-link" href="#controls">Skip to route and search</a>

<div class="app">
  <header class="app-header">
    <h1>Campspotter</h1>
    <p>Find quiet woodland for a wild camp along your route.</p>
  </header>

  <main class="layout">
    <MapView bind:this={mapView} accessToken={mapboxToken} on:siteclick={handleMapClick} />

    <section id="controls" class="panel" aria-label="Route, search and results" tabindex="-1">
      <RoutePicker on:loaded={routeLoaded} />
      <SearchControls
        on:scrubstart={() => mapView.beginScrub()}
        on:move={searchPointMoved}
        on:scrubend={() => mapView.endScrub()}
        on:search={startSearch}
        on:cancel={cancelSearch}
      />
      <SiteList bind:this={siteList} on:select={(event) => showSite(event.detail, "list")} />
    </section>
  </main>
</div>
