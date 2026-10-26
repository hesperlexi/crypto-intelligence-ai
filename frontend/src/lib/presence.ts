// Activity for the owner's Users page: when each person last used the app, roughly where (country), and on what.
// The country comes from the device's time zone (falling back to the language region), so no location
// permission and no outside service is needed. It is approximate (a VPN does not change it; travel does).
import { doc, setDoc } from "firebase/firestore";
import { db } from "./firebase";
import { myUid } from "./session";
import { inAndroidApp } from "./push";
import TZ from "./tzCountry.json";

const EVERY = 4 * 60_000;           // at most one write every 4 minutes while the app is on screen
let lastWrite = 0;
let started = false;

export function country(): string | null {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const c = (TZ as Record<string, string>)[tz];
    if (c) return c;
  } catch { /* fall through */ }
  const lang = (navigator.languages?.[0] || navigator.language || "").split("-");
  const r = lang.find((x, i) => i > 0 && /^[A-Z]{2}$/.test(x));
  return r ?? null;
}

export function device(): string {
  const ua = navigator.userAgent;
  const standalone = window.matchMedia?.("(display-mode: standalone)").matches || (navigator as any).standalone === true;
  if (inAndroidApp()) return "Android app";
  if (/iphone|ipad|ipod/i.test(ua)) return standalone ? "iPhone app" : "iPhone browser";
  if (/android/i.test(ua)) return standalone ? "Android app (Chrome)" : "Android browser";
  return standalone ? "Desktop app" : "Desktop browser";
}

async function beat(force = false) {
  const uid = myUid();
  if (!uid || document.hidden) return;
  if (!force && Date.now() - lastWrite < EVERY) return;
  lastWrite = Date.now();
  try {
    await setDoc(doc(db, "presence", uid), {
      last_seen: Date.now(), country: country(),
      tz: Intl.DateTimeFormat().resolvedOptions().timeZone || null, device: device(),
    }, { merge: true });
  } catch { lastWrite = 0; }
}

/** Starts the heartbeat once per page (called from the signed-in shell). */
export function startPresence() {
  if (started) return;
  started = true;
  beat(true);
  window.setInterval(() => beat(), 60_000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) beat(); });
}

/** Online = seen in the last 5 minutes (the app writes every 4 minutes while on screen). */
export const ONLINE_MS = 5 * 60_000;

export function flagUrl(cc?: string | null) { return cc ? `https://flagcdn.com/w40/${cc.toLowerCase()}.png` : null; }
export function countryName(cc?: string | null): string {
  if (!cc) return "unknown";
  try { return new Intl.DisplayNames(["en"], { type: "region" }).of(cc) ?? cc; } catch { return cc; }
}
