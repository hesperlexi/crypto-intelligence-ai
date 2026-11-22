// v2.67 edge views (owner, 22 Nov 2026: "reduce the load on Firebase, connect Cloudflare free").
// Member views (same list as backend/app/sinks.py EDGE_RE and chat-worker EDGE_RE) are read from the Cloudflare Worker
// instead of Firestore: one small request every POLL_MS while the app is on screen, for all views on the page together,
// answered from Cloudflare's copy - so they cost no Firestore reads at all. On ANY problem (not signed in, not a member
// for the Worker, network, Worker down, view not there yet) that view simply falls back to the Firestore listener as
// before. Kill switch: localStorage cia-edge-off = 1, or build env VITE_EDGE_VIEWS=0.
import { appCheckToken, auth } from "./firebase";
import { BUILD_ID } from "./version";

const CHAT_URL = (import.meta.env.VITE_CHAT_URL as string | undefined)?.replace(/\/$/, "") ?? "";   // same Worker as the chat
const PREVIEW = BUILD_ID === "preview";

type Sub = (cb: (v: any) => void, err: (e: Error) => void) => () => void;
type Listener = { cb: (v: any) => void; err: (e: Error) => void; map: (v: any) => any; fsUnsub?: () => void; fs?: Sub };
type Entry = { name: string; etag: string; data?: any; mode: "edge" | "fs"; listeners: Set<Listener> };

export const EDGE_RE = /^(health|meta|track_record|market_context|context|radar|news|coin_reports|leaderboard|bots|signals|cross_asset_1d|models_status|weekly_report|performance|wins_today|replay_ranges|(dashboard|futures)_(15m|1h|4h|12h|1d|3d)|(analysis|perf|models)_[A-Z0-9]{2,24}_(15m|1h|4h|12h|1d|3d|1w))$/;
const POLL_MS = 30_000;
const RETRY_MS = 5 * 60_000;

function killed(): boolean {
  try { return localStorage.getItem("cia-edge-off") === "1"; } catch { return false; }
}
const ENABLED = !!CHAT_URL && !PREVIEW && import.meta.env.VITE_EDGE_VIEWS !== "0";

const entries = new Map<string, Entry>();
let offUntil = 0;
let timer = 0;
let soon = 0;
let busy = false;

export const edgeEligible = (name: string) => ENABLED && EDGE_RE.test(name);
export function edgeStats() {
  return { on: ENABLED && !killed() && Date.now() >= offUntil, views: [...entries.values()].map((e) => ({ name: e.name, mode: e.mode, listeners: e.listeners.size })) };
}

function emit(l: Listener, data: any) {
  try { l.cb(l.map(data)); } catch (e) { l.err(e as Error); }
}

function toFirestore(e: Entry) {
  e.mode = "fs";
  for (const l of e.listeners) if (!l.fsUnsub && l.fs) l.fsUnsub = l.fs(l.cb, l.err);
}

function allToFirestore() {
  offUntil = Date.now() + RETRY_MS;
  for (const e of entries.values()) if (e.mode === "edge") toFirestore(e);
}

async function poll() {
  if (busy || document.hidden) return;
  const live = [...entries.values()].filter((e) => e.mode === "edge" && e.listeners.size);
  if (!live.length) return;
  busy = true;
  try {
    const user = auth.currentUser;
    if (!user) { allToFirestore(); return; }
    const [token, ac] = await Promise.all([user.getIdToken(), appCheckToken()]);
    const q = `n=${encodeURIComponent(live.map((e) => e.name).join(","))}&e=${encodeURIComponent(live.map((e) => e.etag).join(","))}`;
    const r = await fetch(`${CHAT_URL}/v?${q}`, { headers: { Authorization: `Bearer ${token}`, ...(ac ? { "X-Firebase-AppCheck": ac } : {}) }, cache: "no-store" });
    if (!r.ok) { allToFirestore(); return; }
    const body = await r.json();
    for (const e of live) {
      const v = body?.views?.[e.name];
      if (!v || v.none) { toFirestore(e); continue; }
      if (v.same) continue;
      e.etag = String(v.etag ?? "");
      e.data = v.data;
      for (const l of e.listeners) emit(l, v.data);
    }
  } catch {
    allToFirestore();
  } finally {
    busy = false;
  }
}

function schedule() {
  if (!timer) {
    timer = window.setInterval(() => { void poll(); }, POLL_MS);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) void poll(); });
  }
  if (!soon) soon = window.setTimeout(() => { soon = 0; void poll(); }, 60);   // batch views opened together
}

/** A view read from the edge, falling back to `fs` (the Firestore listener) for this view on any problem. */
export function edgeView(name: string, map: (v: any) => any, fs: Sub): Sub {
  return (cb, err) => {
    if (killed() || Date.now() < offUntil) return fs(cb, err);
    let e = entries.get(name);
    if (!e) { e = { name, etag: "", mode: "edge", listeners: new Set() }; entries.set(name, e); }
    if (e.mode === "fs") {
      if (Date.now() < offUntil) return fs(cb, err);
      e.mode = "edge";                                     // retry the edge after a pause
    }
    const l: Listener = { cb, err, map, fs };
    e.listeners.add(l);
    if (e.data !== undefined) emit(l, e.data);
    schedule();
    return () => {
      e!.listeners.delete(l);
      l.fsUnsub?.();
    };
  };
}
