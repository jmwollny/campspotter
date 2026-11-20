<!-- Step 2: pick the search point and radius, then search. -->
<!--
  The visible slider readouts are aria-hidden: each slider announces its own value
  (aria-valuetext), and <output> is otherwise a live region that would repeat every move.
-->
<script lang="ts">
  import { createEventDispatcher } from "svelte";

  import { formatDistance } from "../lib/geo";
  import { moveSearchPoint, origin, route, searchDistanceKm, searchRadiusM, searching } from "../lib/stores";
  import StatusMessage from "./StatusMessage.svelte";

  /**
   * scrubstart / scrubend: the distance slider was grabbed / released with the pointer.
   * move: the search point moved (any input, including the keyboard).
   * search: the user asked to search around the current point.
   */
  const dispatch = createEventDispatcher<{ scrubstart: void; move: void; scrubend: void; search: void }>();

  function handleDistanceInput(event: Event & { currentTarget: HTMLInputElement }) {
    moveSearchPoint(Number(event.currentTarget.value));
    dispatch("move");
  }
</script>

{#if $route}
  <section class="panel-section">
    <h2>2. Search point</h2>
    <label class="slider">
      <span class="slider-label">
        <span id="distance-label">Distance along route</span>
        <output for="distance-input" aria-hidden="true">{$searchDistanceKm.toFixed(1)} / {$route.lengthKm.toFixed(1)} km</output>
      </span>
      <input
        id="distance-input"
        type="range"
        aria-labelledby="distance-label"
        aria-valuetext="{$searchDistanceKm.toFixed(1)} of {$route.lengthKm.toFixed(1)} km"
        min="0"
        max={$route.lengthKm}
        step="0.1"
        value={$searchDistanceKm}
        disabled={$searching}
        on:pointerdown={() => dispatch("scrubstart")}
        on:input={handleDistanceInput}
        on:change={() => dispatch("scrubend")}
      />
    </label>
    <label class="slider">
      <span class="slider-label">
        <span id="radius-label">Search radius</span>
        <output for="radius-input" aria-hidden="true">{formatDistance($searchRadiusM)}</output>
      </span>
      <input
        id="radius-input"
        type="range"
        aria-labelledby="radius-label"
        aria-valuetext={formatDistance($searchRadiusM)}
        min="100"
        max="2000"
        step="50"
        bind:value={$searchRadiusM}
        disabled={$searching}
      />
    </label>
    <p class="hint">Larger radii take longer: OpenStreetMap returns a lot more data.</p>

    <button
      type="button"
      class="primary-button"
      on:click={() => dispatch("search")}
      disabled={$searching || !$origin}
    >
      {#if $searching}<span class="spinner" aria-hidden="true"></span>Searching…{:else}Search this area{/if}
    </button>
    <StatusMessage />
  </section>
{/if}
