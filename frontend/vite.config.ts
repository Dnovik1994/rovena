import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    include: [
      "react",
      "react-dom",
      "react-router-dom",
      "@tanstack/react-query",
      "react-hook-form",
      "zod",
      "zustand",
      "axios",
    ],
  },
  build: {
    chunkSizeWarningLimit: 1000,
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      "/api/v1": {
        target: "http://localhost:8020",
        changeOrigin: true,
      },
      "/ws": {
        target: "http://localhost:8020",
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
