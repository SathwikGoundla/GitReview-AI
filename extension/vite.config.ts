/**
 * GitReview AI — Vite build config for Chrome Extension (Manifest V3)
 *
 * Multi-entry build:
 *   background  → dist/background.js   (service worker — no DOM)
 *   content     → dist/content.js      (runs on github.com PR pages)
 *   popup       → dist/popup.html      (toolbar popup — React app)
 *
 * The manifest.json is copied from public/ to dist/ verbatim by Vite's
 * publicDir option. Icons are also placed in public/ and copied the same way.
 *
 * Why separate entries?
 *   Chrome MV3 requires each context to be a separate JS file:
 *   - Service workers cannot access DOM APIs.
 *   - Content scripts run in the page's renderer process, isolated from
 *     the service worker's context.
 *   - Popup is a standard HTML page with a full React render.
 */

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

export default defineConfig({
  plugins: [react()],

  // Copy public/ (manifest.json + icons) to dist/ as-is
  publicDir: "public",

  build: {
    outDir: "dist",
    emptyOutDir: true,

    // Multi-entry rollup config
    rollupOptions: {
      input: {
        background: resolve(__dirname, "src/background/service-worker.ts"),
        content: resolve(__dirname, "src/content/github-pr.ts"),
        popup: resolve(__dirname, "popup.html"),
      },
      output: {
        // Flat output: background.js, content.js, popup.js in dist/
        entryFileNames: "[name].js",
        chunkFileNames: "chunks/[name]-[hash].js",
        assetFileNames: "[name][extname]",
      },
    },
  },

  // Vitest config (test runner)
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["src/test-setup.ts"],
  },
});
