import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

/**
 * Vite configuration.
 *
 * The dev server proxies the local adapter so the browser sees a single
 * origin. That keeps the API base a relative path in every environment,
 * including the production build served by the adapter itself, and means no
 * external host is ever contacted.
 *
 * The proxy target follows `SATSA_API_PORT` (set by dev.sh to the backend's
 * actual port) and falls back to 8000, so the adapter may live on any free
 * localhost port without editing this file.
 */
const apiPort = process.env.SATSA_API_PORT ?? "8000";
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${apiPort}`,
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: "dist",
    // Every asset is emitted locally. No CDN, no remote font, no runtime
    // fetch of anything outside this bundle.
    assetsDir: "assets",
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
});
