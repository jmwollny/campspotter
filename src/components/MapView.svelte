<!--
  The map. Draws the current state from the stores; everything Mapbox-specific lives in
  src/lib/map/controller.ts. Parents call the exported functions to move the camera.
-->
<script lang="ts">
  import { createEventDispatcher, onMount } from "svelte";
  import { get } from "svelte/store";

  import { MapController } from "../lib/map/controller";
  import { origin, route, searchRadiusM, selectedSiteId, sites, topPickSet } from "../lib/stores";
  import type { Site } from "../lib/types";

  /** Mapbox access token (VITE_MAPBOX_TOKEN). */
  export let accessToken: string | undefined;

  const dispatch = createEventDispatcher<{ siteclick: number }>();

  let container: HTMLDivElement;
  let controller: MapController | undefined;
  let error = "";

  $: controller?.render({
    track: $route?.geojson ?? null,
    origin: $origin,
    radiusM: $searchRadiusM,
    sites: $sites,
    topPicks: $topPickSet,
    selectedId: $selectedSiteId,
  });

  onMount(() => {
    if (!accessToken) {
      error = "Missing VITE_MAPBOX_TOKEN. Add it to a .env file in the project root (see README).";
      return;
    }
    try {
      controller = new MapController(container, accessToken, {
        onSiteClick: (id) => dispatch("siteclick", id),
        onError: (message) => (error = message),
      });
    } catch (caught) {
      error = caught instanceof Error ? caught.message : "Failed to initialise the map.";
    }
    return () => controller?.destroy();
  });

  export const fitToRoute = () => controller?.fitToRoute(get(route)?.geojson ?? null);
  export const fitToResults = () => controller?.fitToResults(get(origin), get(sites), get(topPickSet));
  export const showSite = (site: Site, rank: number, options?: { zoom?: boolean }) =>
    controller?.showSite(site, rank, options);
  export const clearPopup = () => controller?.clearPopup();
  export const beginScrub = () => controller?.beginScrub(get(origin));
  export const followSearchPoint = () => controller?.followPoint(get(origin));
  export const endScrub = () => controller?.endScrub(get(origin));
</script>

<div class="map-wrap">
  <div class="map" bind:this={container}></div>
  {#if error}
    <div class="map-overlay error-text" role="alert">{error}</div>
  {:else if !$route}
    <div class="map-overlay">Load a GPX route to get started.</div>
  {/if}
</div>
