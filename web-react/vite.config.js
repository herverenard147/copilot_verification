import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build statique servi par le même FastAPI que l'ancien front (voir
// api.py: StaticFiles). En dev, proxy /api vers le serveur FastAPI local
// pour éviter tout souci de cookies cross-origin (sid, auth_token).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
