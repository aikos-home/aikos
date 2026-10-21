import { defineConfig } from "vite";
import preact from "@preact/preset-vite";

// `npm run dev` serves the PWA on :5173 and forwards the API to the app service on :8780.
export default defineConfig({
  plugins: [preact()],
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
  server: { proxy: { "/api": "http://localhost:8780", "/.well-known": "http://localhost:8780" } },
});
