<!--
  One candidate site in the results list. The button's accessible name is built from its
  visible text (rank, "Top pick", title, score) so it matches what people see and say; the
  rest of the card is read as its description, so the list carries the same details as
  the map popup.
-->
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
  $: title = terrain.name || terrain.kind;
  $: flags = summariseRedFlags(site.nearby_red_flags);
  $: reason = site.suitability_reason && site.suitability_reason !== "heuristic fallback" ? site.suitability_reason : "";
  $: pending = site.suitability_score == null && scoring;
  $: detailsId = `site-${site.id}-details`;
</script>

<button
  type="button"
  class="site-card"
  class:top-pick={topPick}
  class:selected
  aria-pressed={selected}
  aria-describedby={detailsId}
  on:click={() => dispatch("select", site)}
>
  <span class="rank">{rank}</span>
  <span class="site-body">
    {#if topPick}<span class="badge">Top pick</span>{/if}
    <span class="site-title">{title}</span>
    <!-- aria-hidden keeps the details out of the button's name; aria-describedby still reads them. -->
    <span id={detailsId} class="site-details" aria-hidden="true">
      {#if terrain.name}<span class="site-kind">{terrain.kind}</span>{/if}
      <span class="site-meta">
        {formatDistance(site.distance_to_bbox_m)} from route · {formatArea(site.area_m2)}
        {#if site.distance_to_water_m != null}· water {formatDistance(site.distance_to_water_m)}{/if}
        {#if site.distance_to_major_road_m != null}
          <span class="visually-hidden">· major road {formatDistance(site.distance_to_major_road_m)}</span>
        {/if}
      </span>
      {#if flags}<span class="site-flags">Nearby: {flags}</span>{/if}
      {#if reason}<span class="reason">“{reason}”</span>{/if}
    </span>
  </span>
  <span class="score" class:pending={site.suitability_score == null}>
    {#if pending}
      <span class="spinner small" aria-hidden="true"></span><span class="visually-hidden">scoring</span>
    {:else}
      <span class="visually-hidden">score </span>{formatScore(site.suitability_score)}
    {/if}
  </span>
</button>
