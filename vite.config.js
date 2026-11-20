import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [svelte()],
  build: {
    rollupOptions: {
      // mapbox-gl is ~1.7 MB on its own; keep it in its own long-cached chunk.
      output: { manualChunks: { mapbox: ["mapbox-gl"] } },
    },
    chunkSizeWarningLimit: 1800,
  },
  test: {
    include: ["src/**/*.test.{js,ts}"],
  },
});
