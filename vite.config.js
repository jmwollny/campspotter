import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { svelteTesting } from "@testing-library/svelte/vite";

// https://vitejs.dev/config/
export default defineConfig({
  // svelteTesting(): browser build of Svelte + automatic cleanup in component tests (Vitest only).
  plugins: [svelte(), svelteTesting()],
  build: {
    rollupOptions: {
      // mapbox-gl is ~1.7 MB on its own; keep it in its own long-cached chunk.
      output: { manualChunks: { mapbox: ["mapbox-gl"] } },
    },
    chunkSizeWarningLimit: 1800,
  },
  test: {
    include: ["src/**/*.test.{js,ts}"],
    // Tests must not depend on the developer's .env (e.g. a real Mapbox token).
    env: { VITE_MAPBOX_TOKEN: "test-token", VITE_API_WS_URL: "ws://test-server" },
  },
});
