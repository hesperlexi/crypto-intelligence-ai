import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";
import { defineConfig, Plugin } from "vite";

// The backend URL can be changed with VITE_BACKEND (default: the local FastAPI server).
const backend = process.env.VITE_BACKEND || "http://localhost:8000";

// Version shown in the app. Every build gets its own id; the running app compares it with /version.json
// and reloads itself when a newer deploy is live.
// The release version is set here (also in package.json and the Android app). Updates are detected by the
// build id, so every deploy still reaches phones without changing the version.
const APP_VERSION = "2.0.0";
const stamp = new Date().toISOString().replace(/\D/g, "").slice(0, 12);
const BUILD_ID = `${(process.env.GITHUB_SHA || "local").slice(0, 7)}-${stamp}`;
const V = encodeURIComponent(BUILD_ID);

function versionFiles(): Plugin {
  return {
    name: "version-files",
    apply: "build",
    generateBundle() {
      this.emitFile({ type: "asset", fileName: "version.json", source: JSON.stringify({ version: APP_VERSION, build: BUILD_ID }) });
    },
    // icons, favicon and manifest get ?v=<build> so phones and browsers fetch the new files after every deploy
    // (this is also what makes an installed Android app pick up a changed icon)
    transformIndexHtml(html) {
      return html.replace(/(href="\/(?:manifest\.webmanifest|favicon\.png|icons\/[^"?]+))"/g, `$1?v=${V}"`);
    },
    writeBundle(opts) {
      const dir = opts.dir || "dist";
      const sw = path.join(dir, "sw.js");
      if (fs.existsSync(sw)) fs.writeFileSync(sw, fs.readFileSync(sw, "utf8").split("__BUILD_ID__").join(BUILD_ID));
      const mf = path.join(dir, "manifest.webmanifest");
      if (fs.existsSync(mf)) {
        const m = JSON.parse(fs.readFileSync(mf, "utf8"));
        const bump = (src: string) => `${src.split("?")[0]}?v=${V}`;
        m.icons = (m.icons || []).map((i: any) => ({ ...i, src: bump(i.src) }));
        m.shortcuts = (m.shortcuts || []).map((sc: any) => ({ ...sc, icons: (sc.icons || []).map((i: any) => ({ ...i, src: bump(i.src) })) }));
        fs.writeFileSync(mf, JSON.stringify(m, null, 2));
      }
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
