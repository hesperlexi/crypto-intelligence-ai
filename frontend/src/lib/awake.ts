import { useSyncExternalStore } from "react";

// v2.52 (audit): live listeners pause while the app has been in the background for HIDDEN_PAUSE_MS - an open tab no
// longer reads Firestore all day. Coming back re-attaches them; the on-device cache shows the last data at once and only
// what changed is downloaded. One shared visibility state for every useApi.
export const HIDDEN_PAUSE_MS = 60_000;
let pageAwake = typeof document === "undefined" || !document.hidden;
const awakeSubs = new Set<() => void>();
if (typeof document !== "undefined") {
  let t = 0;
  document.addEventListener("visibilitychange", () => {
    window.clearTimeout(t);
    if (!document.hidden) { if (!pageAwake) { pageAwake = true; awakeSubs.forEach((f) => f()); } return; }
    t = window.setTimeout(() => { if (document.hidden && pageAwake) { pageAwake = false; awakeSubs.forEach((f) => f()); } }, HIDDEN_PAUSE_MS);
  });
}
export function usePageAwake(): boolean {
  return useSyncExternalStore((f) => { awakeSubs.add(f); return () => { awakeSubs.delete(f); }; }, () => pageAwake, () => true);
}

