import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  // Tauri expects a fixed port; strictPort means fail fast if 1420 is taken
  server: {
    port: 1420,
    strictPort: true,
  },
  // Tauri uses Chromium, no need to polyfill
  envPrefix: ["VITE_", "TAURI_"],
  build: {
    // Tauri supports ES2021+
    target: ["es2021", "chrome100", "safari13"],
    // don't minify source maps in debug
    minify: !process.env.TAURI_DEBUG ? "esbuild" : false,
    sourcemap: !!process.env.TAURI_DEBUG,
  },
});
