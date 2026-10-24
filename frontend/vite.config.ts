import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";
import { defineConfig, Plugin } from "vite";

// The backend URL can be changed with VITE_BACKEND (default: the local FastAPI server).
const backend = process.env.VITE_BACKEND || "http://localhost:8000";

// Version shown in the app. Every build gets its own id; the running app compares it with /version.json
// and reloads itself when a newer deploy is live.
const APP_VERSION = "1.1";
const stamp = new Date().toISOString().replace(/\D/g, "").slice(0, 12);
const BUILD_ID = `${(process.env.GITHUB_SHA || "local").slice(0, 7)}-${stamp}`;

function versionFiles(): Plugin {
  return {
    name: "version-files",
    apply: "build",
    generateBundle() {
      this.emitFile({ type: "asset", fileName: "version.json", source: JSON.stringify({ version: APP_VERSION, build: BUILD_ID }) });
    },
    writeBundle(opts) {
      const sw = path.join(opts.dir || "dist", "sw.js");
      if (fs.existsSync(sw)) fs.writeFileSync(sw, fs.readFileSync(sw, "utf8").split("__BUILD_ID__").join(BUILD_ID));
    },
  };
}

export default defineConfig({
  plugins: [react(), versionFiles()],
  define: { __APP_VERSION__: JSON.stringify(APP_VERSION), __BUILD_ID__: JSON.stringify(BUILD_ID) },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
    },
  },
});
