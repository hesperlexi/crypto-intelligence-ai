import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The backend URL can be changed with VITE_BACKEND (default: the local FastAPI server).
const backend = process.env.VITE_BACKEND || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
    },
  },
});
