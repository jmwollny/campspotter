<!-- Step 1: choose a GPX file or a bundled sample route. -->
<script lang="ts">
  import { createEventDispatcher } from "svelte";

  import { loadRoute, loadRouteFromUrl, route, routeError, routeLoading } from "../lib/stores";

  interface SampleRoute {
    file: string;
    label: string;
  }

  export let samples: SampleRoute[] = [
    { file: "king-alfreds-way-full-route.gpx", label: "King Alfred's Way" },
    { file: "GBDIVIDE_v400.gpx", label: "GB Divide" },
  ];

  /** `loaded`: a new route is in the `route` store. */
  const dispatch = createEventDispatcher<{ loaded: void }>();

  async function handleFile(event: Event & { currentTarget: HTMLInputElement }) {
    const file = event.currentTarget.files?.[0];
    if (file && loadRoute(await file.text(), file.name)) dispatch("loaded");
  }

  async function loadSample(sample: SampleRoute) {
    if (await loadRouteFromUrl(`/${sample.file}`, sample.label)) dispatch("loaded");
  }
</script>

<section class="panel-section">
  <h2>1. Route</h2>
  <label class="file-button">
    <input type="file" accept=".gpx,application/gpx+xml" on:change={handleFile} />
    Choose GPX file…
  </label>
  <p class="hint">
    or try
    {#each samples as sample, i (sample.file)}
      {#if i > 0}&nbsp;or&nbsp;{/if}<button
        type="button"
        class="link-button"
        disabled={$routeLoading}
        on:click={() => loadSample(sample)}>{sample.label}</button
      >
    {/each}
  </p>
  {#if $routeError}
    <p class="error-text" role="alert">{$routeError}</p>
  {:else if $route}
    <p class="route-name"><strong>{$route.name}</strong> · {$route.lengthKm.toFixed(1)} km</p>
  {/if}
</section>
