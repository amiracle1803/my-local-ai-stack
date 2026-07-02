import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Forward /api/* directly to FastAPI (which now serves at /api/*)
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // Proxy WebSocket connection to backend
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
});
