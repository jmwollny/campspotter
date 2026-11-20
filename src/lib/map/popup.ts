// The HTML shown in a site's popup. Every value from OSM or the LLM is escaped.
import {
  describeTerrain,
  escapeHtml,
  formatArea,
  formatDistance,
  formatScore,
  summariseRedFlags,
} from "../geo";
import type { Site } from "../types";

export function popupHtml(site: Site, rank: number): string {
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
  const osmUrl = `https://www.openstreetmap.org/${site.type}/${encodeURIComponent(site.id)}`;
  return `
      <div class="popup">
        <strong>${rank}. ${escapeHtml(name || kind)}</strong>
        ${name ? `<div class="popup-kind">${escapeHtml(kind)}</div>` : ""}
        <dl>${rows.map(([label, value]) => `<dt>${label}</dt><dd>${escapeHtml(value)}</dd>`).join("")}</dl>
        ${reason ? `<p class="popup-reason">“${escapeHtml(reason)}”</p>` : ""}
        <a href="${escapeHtml(osmUrl)}" target="_blank" rel="noopener noreferrer">View on OpenStreetMap ↗</a>
      </div>`;
}
