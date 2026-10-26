import { useEffect, useState } from "react";
import { BUILD_ID } from "./version";

/**
 * Auto-update: every deploy writes /version.json with a new build id. The app checks it every minute,
 * when it comes back to the foreground and when the network returns. When a newer build is live:
 *  - app in the background  -> reloads straight away (nothing to interrupt)
 *  - app on screen          -> an "Update now" button; nothing reloads while you are looking at it
 */
export type UpdateState = { phase: "idle" | "updating" | "ready"; build?: string };

let state: UpdateState = { phase: "idle" };
const subs = new Set<(s: UpdateState) => void>();
const emit = (s: UpdateState) => { state = s; subs.forEach((f) => f(s)); };
let reg: ServiceWorkerRegistration | undefined;
let started = false;
const GUARD = "cia-reloaded-for";

function editing(): boolean {
  const el = document.activeElement as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
}

export async function reloadNow(build?: string) {
  try { sessionStorage.setItem(GUARD, JSON.stringify({ b: build, t: Date.now() })); } catch { /* ignore */ }
  try {   // bring in the new service worker first, so the reload is served entirely by the new version
    const r = reg ?? (await navigator.serviceWorker?.getRegistration());
    await r?.update();
    r?.waiting?.postMessage("SKIP_WAITING");
  } catch { /* ignore */ }
  location.reload();
}

export async function checkForUpdate(manual = false): Promise<boolean> {
  try {
    const r = await fetch(`/version.json?t=${Date.now()}`, { cache: "no-store" });
    if (!r.ok) return false;
    const v = await r.json();
    if (!v.build || v.build === BUILD_ID) return false;
    reg?.update().catch(() => {});
    if (!manual) {
      // a CDN edge can briefly serve the old page after a deploy: never reload twice in a row for one build
      try {
        const g = JSON.parse(sessionStorage.getItem(GUARD) ?? "null");
        if (g?.b === v.build && Date.now() - g.t < 120_000) return true;
      } catch { /* ignore */ }
    }
    // never reload under someone's eyes (it reset charts and zoom mid-trade): on screen it offers "Update now",
    // and the update applies by itself the next time the app goes to the background
    if (manual || document.hidden) reloadNow(v.build);
    else emit({ phase: "ready", build: v.build });
    return true;
  } catch {
    return false;
  }
}

export function startUpdater() {
  if (started || !import.meta.env.PROD) return;
  started = true;
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js", { updateViaCache: "none" }).then((r) => { reg = r; }).catch(() => {});
  }
  setTimeout(() => checkForUpdate(), 5_000);
  setInterval(() => { if (!document.hidden) checkForUpdate(); }, 60_000);
  document.addEventListener("visibilitychange", () => checkForUpdate());
  window.addEventListener("online", () => checkForUpdate());
}

export function useUpdate(): UpdateState {
  const [s, setS] = useState(state);
  useEffect(() => { subs.add(setS); return () => { subs.delete(setS); }; }, []);
  return s;
}
