<!-- Step 3: the candidate sites, best first. -->
<script lang="ts">
  import { createEventDispatcher, tick } from "svelte";

  import { OTHER_SITE_COLOR, TOP_PICK_COLOR } from "../lib/map/style";
  import { searching, selectedSiteId, sites, topPickSet } from "../lib/stores";
  import type { Site } from "../lib/types";
  import SiteCard from "./SiteCard.svelte";

  const dispatch = createEventDispatcher<{ select: Site }>();

  let list: HTMLOListElement;

  /** Scroll the list so the given site's card is visible. */
  export async function scrollTo(siteId: number) {
    await tick();
    list?.querySelector(`[data-site-id="${CSS.escape(String(siteId))}"]`)?.scrollIntoView({
      block: "nearest",
      behavior: "smooth",
    });
  }
</script>

{#if $sites.length}
  <section class="panel-section results">
    <h2>3. Candidate sites <span class="count">{$sites.length}</span></h2>
    <p class="legend">
      <span><i style="background:{TOP_PICK_COLOR}"></i>Top pick</span>
      <span><i style="background:{OTHER_SITE_COLOR}"></i>Other woodland</span>
    </p>
    <ol class="site-list" bind:this={list}>
      {#each $sites as site, i (site.id)}
        <li data-site-id={site.id}>
          <SiteCard
            {site}
            rank={i + 1}
            topPick={$topPickSet.has(site.id)}
            selected={site.id === $selectedSiteId}
            scoring={$searching}
            on:select={(event) => dispatch("select", event.detail)}
          />
        </li>
      {/each}
    </ol>
  </section>
{/if}
