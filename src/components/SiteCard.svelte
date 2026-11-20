<!-- One candidate site in the results list. -->
<script lang="ts">
  import { createEventDispatcher } from "svelte";

  import { describeTerrain, formatArea, formatDistance, formatScore, summariseRedFlags } from "../lib/geo";
  import type { Site } from "../lib/types";

  export let site: Site;
  export let rank: number;
  export let topPick = false;
  export let selected = false;
  /** Show a spinner instead of the score while the search is still scoring. */
  export let scoring = false;

  const dispatch = createEventDispatcher<{ select: Site }>();

  $: terrain = describeTerrain(site.terrain_description);
  $: flags = summariseRedFlags(site.nearby_red_flags);
  $: reason = site.suitability_reason && site.suitability_reason !== "heuristic fallback" ? site.suitability_reason : "";
</script>

<button
  type="button"
  class="site-card"
  class:top-pick={topPick}
  class:selected
  aria-pressed={selected}
  on:click={() => dispatch("select", site)}
>
  <span class="rank" aria-label="Rank {rank}">{rank}</span>
  <span class="site-body">
    {#if topPick}<span class="badge">Top pick</span>{/if}
    <span class="site-title">{terrain.name || terrain.kind}</span>
    {#if terrain.name}<span class="site-kind">{terrain.kind}</span>{/if}
    <span class="site-meta">
      {formatDistance(site.distance_to_bbox_m)} from route · {formatArea(site.area_m2)}
      {#if site.distance_to_water_m != null}· water {formatDistance(site.distance_to_water_m)}{/if}
    </span>
    {#if flags}<span class="site-flags">Nearby: {flags}</span>{/if}
    {#if reason}<span class="reason">“{reason}”</span>{/if}
  </span>
  <span class="score" class:pending={site.suitability_score == null}>
    {#if site.suitability_score == null && scoring}
      <span class="spinner small" aria-label="Scoring"></span>
    {:else}
      {formatScore(site.suitability_score)}
    {/if}
  </span>
</button>
