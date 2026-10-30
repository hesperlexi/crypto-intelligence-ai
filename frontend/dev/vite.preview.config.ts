// DEV PREVIEW ONLY: `npx vite --config dev/vite.preview.config.ts` (from frontend/), then open
// http://localhost:5174/?preview=admin | member | pending | signedout
// Firebase is swapped for in-memory mocks with sample data (dev/seed.ts) and Binance for sample prices, so pages
// behind Google sign-in can be looked at and screenshotted. The production build (vite.config.ts, index.html)
// never references this folder.
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";
import { defineConfig, Plugin } from "vite";

const here = path.dirname(new URL(import.meta.url).pathname);
const root = path.resolve(here, "..");
const m = (f: string) => path.join(here, "mocks", f);

function spa(): Plugin {
  return {
    name: "preview-spa",
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const url = req.url ?? "/";
        if (req.method !== "GET" || !(req.headers.accept ?? "").includes("text/html") || /\.[a-z0-9]+(\?|$)/i.test(url.split("?")[0])) return next();
        const html = await server.transformIndexHtml(url, fs.readFileSync(path.join(here, "preview.html"), "utf8"));
        res.setHeader("Content-Type", "text/html");
        res.end(html);
      });
    },
  };
}

export default defineConfig({
  root,
  plugins: [react(), spa()],
  define: { __APP_VERSION__: JSON.stringify("2.0.0"), __BUILD_ID__: JSON.stringify("preview") },
  resolve: {
    alias: [
      { find: /^firebase\/firestore$/, replacement: m("firestore.ts") },
      { find: /^firebase\/auth$/, replacement: m("auth.ts") },
      { find: /^firebase\/(app|analytics|app-check|messaging)$/, replacement: m("app.ts") },
    ],
  },
  server: { port: 5174, strictPort: true },
});
