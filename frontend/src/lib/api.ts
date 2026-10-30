/**
 * Data layer for the Firebase deployment.
 *
 * The pages still call useApi("/path") / post("/path"), exactly as with the local API server, and this module
 * maps each path to its source:
 *   - engine results  -> Firestore documents views/<name> (JSON written by the scheduled engine)
 *   - your settings   -> Firestore config/*, alerts/*, paper/*  (written here, read by the engine next cycle)
 *   - live market data-> Binance public REST / WebSocket, straight from the browser
 *   - heavy work      -> Firestore jobs/* queue (backtests, replays, retraining), run by the next engine cycle
 */
import { addDoc, collection, deleteDoc, doc, getDoc, getDocs, onSnapshot, query, setDoc, updateDoc, where } from "firebase/firestore";
import { useCallback, useEffect, useRef, useState } from "react";
import * as binance from "./binance";
import { auth, db } from "./firebase";
import * as paper from "./paper";
import * as paperFutures from "./paperFutures";
import { positionSize } from "./risk";
import { getSession, isAdmin, myUid } from "./session";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type Sub = (cb: (v: any) => void, err: (e: Error) => void) => () => void;
const NOT_READY = "The engine has not published this yet. It runs every 5 minutes; the first run also trains the models.";

const toSymbol = (s: string) => {
  const u = decodeURIComponent(s).toUpperCase().replace(/[-_]/g, "/");
  return u.includes("/") ? u : u.endsWith("USDT") && u.length > 4 ? `${u.slice(0, -4)}/USDT` : `${u}/USDT`;
};
const slugOf = (s: string) => toSymbol(s).replace("/", "");

function view(name: string, map: (v: any) => any = (v) => v): Sub {
  return (cb, err) => onSnapshot(doc(db, "views", name), (s) => {
    const d = s.data();
    if (!d?.json) return err(new ApiError(404, NOT_READY));
    try { cb(map(JSON.parse(d.json))); } catch (e) { err(e as Error); }
  }, (e) => err(new ApiError(403, permissionHint(e))));
}

function permissionHint(e: Error): string {
  return /permission/i.test(e.message) ? (isAdmin() ? "Access denied by the database rules (redeploy the website so the latest rules apply)." : "This needs the app owner's permission (members cannot change it).") : e.message;
}

function rawDoc(path: string[]): Sub {
  return (cb, err) => onSnapshot(doc(db, path[0], ...path.slice(1)), (s) => cb(s.data() ?? null), (e) => err(new Error(permissionHint(e))));
}

/** Combine several subscriptions; emits once every part has produced a value. */
function combine(parts: Record<string, Sub>, map: (v: Record<string, any>) => any): Sub {
  return (cb, err) => {
    const vals: Record<string, any> = {};
    const seen = new Set<string>();
    const unsubs = Object.entries(parts).map(([k, sub]) => sub((v) => {
      vals[k] = v;
      seen.add(k);
      if (seen.size === Object.keys(parts).length) { try { cb(map(vals)); } catch (e) { err(e as Error); } }
    }, (e) => {
      if (e instanceof ApiError && e.status === 404) { vals[k] = null; seen.add(k); if (seen.size === Object.keys(parts).length) cb(map(vals)); }
      else err(e);
    }));
    return () => unsubs.forEach((u) => u());
  };
}

function poll(fn: () => Promise<any>, ms: number): Sub {
  return (cb, err) => {
    let alive = true;
    let last = 0;
    const run = () => { last = Date.now(); fn().then((v) => alive && cb(v)).catch((e) => alive && err(e)); };
    // pause while the app is in the background; refresh at once when it comes back or the network returns
    const tickRun = () => { if (!document.hidden) run(); };
    const wake = () => { if (!document.hidden && Date.now() - last > Math.min(ms, 5000)) run(); };
    run();
    const t = ms ? window.setInterval(tickRun, ms) : 0;
    if (ms) { document.addEventListener("visibilitychange", wake); window.addEventListener("online", wake); }
    return () => {
      alive = false;
      if (t) window.clearInterval(t);
      if (ms) { document.removeEventListener("visibilitychange", wake); window.removeEventListener("online", wake); }
    };
  };
}

/** The signed-in user's own alert rules. An admin's older rules (made before member accounts) are adopted once. */
function myAlertRules(): Sub {
  return (cb, err) => {
    const uid = myUid();
    if (isAdmin()) {
      getDocs(collection(db, "alerts")).then((q) => q.docs.filter((d) => !d.data().owner_uid)
        .forEach((d) => updateDoc(d.ref, { owner_uid: uid }).catch(() => {}))).catch(() => {});
    }
    return onSnapshot(query(collection(db, "alerts"), where("owner_uid", "==", uid)),
      (q) => cb(q.docs.map((d) => ({ id: d.id, ...d.data() }))), (e) => err(new Error(permissionHint(e))));
  };
}

function collectionSub(name: string): Sub {
  return (cb, err) => onSnapshot(collection(db, name), (q) => cb(q.docs.map((d) => ({ id: d.id, ...d.data() }))), (e) => err(new Error(permissionHint(e))));
}

function resolve(path: string, refreshMs: number): Sub {
  const u = new URL(path, "http://x");
  const p = u.pathname.split("/").filter(Boolean);
  const q = u.searchParams;
  const tf = q.get("timeframe") ?? "4h";
  switch (p[0]) {
    case "meta":
      return combine({ meta: view("meta"), wl: rawDoc(["config", "watchlist"]), mine: rawDoc(["user_coins", myUid()]) }, ({ meta, wl, mine }) => {
        const m = { ...(meta ?? { watchlist: [], strategies: {}, alert_types: {} }) };
        if (wl?.symbols) m.watchlist = wl.symbols.map((x: any) => (typeof x === "string" ? { symbol: x, pinned: 0 } : { symbol: x.symbol, pinned: x.pinned ? 1 : 0 }));
        // the member's own coins come after the shared list, marked as theirs
        const have = new Set((m.watchlist ?? []).map((w: any) => w.symbol));
        m.watchlist = [...(m.watchlist ?? []), ...((mine?.symbols ?? []) as string[]).filter((s) => !have.has(s)).map((s) => ({ symbol: s, pinned: 0, mine: true }))];
        m.my_coins = mine?.symbols ?? [];
        return m;
      });
    case "dashboard": return view(`dashboard_${tf}`);
    case "scanner":
      return combine({ d: view(`dashboard_${tf}`), wl0: rawDoc(["config", "watchlist"]), mine: rawDoc(["user_coins", myUid()]) }, ({ d, wl0, mine }) => {
        const wl = wl0 ? { ...wl0, symbols: [...(wl0.symbols ?? []), ...((mine?.symbols ?? []) as string[]).map((s) => ({ symbol: s, pinned: false }))] } : wl0;
        const rows = [...(d?.rows ?? [])];
        const have = new Set(rows.map((r: any) => r.symbol));
        for (const x of wl?.symbols ?? []) {
          const s = typeof x === "string" ? x : x.symbol;
          if (!have.has(s)) rows.push({ symbol: s, status: "PENDING", reason: "added: data and models arrive with the next engine runs", pinned: !!x.pinned });
        }
        const pins = Object.fromEntries((wl?.symbols ?? []).map((x: any) => [x.symbol ?? x, !!x.pinned]));
        return { timeframe: tf, rows: rows.filter((r: any) => !wl?.symbols || r.symbol in pins).map((r: any) => ({ ...r, pinned: pins[r.symbol] ?? r.pinned })) };
      });
    case "analysis": return view(`analysis_${slugOf(p[1])}_${tf}`);
    case "models": return p[1] === "status" ? view("models_status") : view(`models_${slugOf(p[1])}_${tf}`);
    case "performance": return p[1] ? view(`perf_${slugOf(p[1])}_${tf}`) : view("performance");
    case "system": return view("health");
    case "context": return view("context");
    case "market-context": return view("market_context");
    case "news": return view("news");
    case "track-record": return view("track_record");
    case "radar": return view("radar");
    case "wins-today": return view("wins_today");
    case "weekly-report": return view("weekly_report");
    case "cross-asset": return view("cross_asset_1d");
    case "signals": return view("signals");
    case "backtests": return view("backtests");
    case "bots": return combine({ v: view("bots"), cfg: rawDoc(["config", "bots"]) }, ({ v, cfg }) => ({ ...(v ?? { bots: [] }), config: cfg?.bots ?? v?.defaults ?? [] }));
    case "settings":
      return combine({ v: view("settings"), c: rawDoc(["config", "settings"]) }, ({ v, c }) => ({
        risk_profile: { ...(v?.risk_profile ?? {}), ...(c?.risk_profile ?? {}) },
        signal_weights: { ...(v?.signal_weights ?? {}), ...(c?.signal_weights ?? {}) },
        forecast_refresh_s: 900, refresh_options_s: [900],
      }));
    case "alerts":
      return combine({ rules: myAlertRules(), v: view(`alerts_u_${myUid()}`), read: rawDoc(["user_state", myUid()]) }, ({ rules, v, read }) => {
        const state = v?.state ?? {};
        const before = read?.alerts_read_before ?? 0;
        return {
          alerts: rules.map((a: any) => ({ ...a, ...(state[a.id] ?? {}) })).sort((a: any, b: any) => (b.created_at ?? 0) - (a.created_at ?? 0)),
          events: (v?.events ?? []).map((e: any) => ({ ...e, is_read: e.created_at <= before ? 1 : 0 })),
          types: v?.types ?? {},
        };
      });
    case "paper": return p[1] === "futures" ? paperFutures.subscribe : paper.subscribe;
    case "futures":
      if (p[1] === "market") return poll(() => binance.futuresMarket((q.get("symbols") ?? "").split(",").filter(Boolean)), refreshMs);
      return view(`futures_${tf}`);
    case "replay":
      return view("replay_ranges", (r) => r[`${slugOf(p[1])}_${tf}`] ?? { available: false, reason: `replay is available for 1h, 4h, 12h and 1d` });
    case "market": {
      const s = toSymbol(p[1]);
      if (p[2] === "ohlcv") return poll(() => binance.ohlcv(s, tf, Number(q.get("limit") ?? 500)), refreshMs);
      if (p[2] === "orderbook") return poll(() => binance.orderbook(s), refreshMs);
      if (p[2] === "derivatives") return poll(() => binance.derivatives(s), refreshMs);
      break;
    }
  }
  return (_cb, err) => { err(new ApiError(404, `unknown data path ${path}`)); return () => {}; };
}

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** Live subscription to a data path. Firestore documents push updates; Binance paths poll every refreshMs. */
export function useApi<T = any>(path: string | null, refreshMs = 0): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const [tick, setTick] = useState(0);
  const seq = useRef(0);

  useEffect(() => {
    setData(null);
    if (!path) { setLoading(false); return; }
    const id = ++seq.current;
    setLoading(true);
    const unsub = resolve(path, refreshMs)(
      (v) => { if (id === seq.current) { setData(v); setError(null); setLoading(false); } },
      (e) => { if (id === seq.current) { setError(e.message); setLoading(false); } },
    );
    return unsub;
  }, [path, refreshMs, tick]);

  const reload = useCallback(() => setTick((x) => x + 1), []);
  return { data, error, loading, reload };
}

function first<T>(sub: Sub): Promise<T> {
  return new Promise((res, rej) => {
    let un: () => void = () => {};
    let done = false;
    un = sub((v) => { if (!done) { done = true; res(v); setTimeout(() => un(), 0); } }, (e) => { if (!done) { done = true; rej(e); setTimeout(() => un(), 0); } });
  });
}

// ---- jobs -------------------------------------------------------------------------------------------------
export interface JobHandle<T = any> { id: string; done: Promise<T> }

/** Queue work for the engine. Resolves with the result once a later engine cycle has run it. */
export async function queueJob<T = any>(type: string, params: Record<string, any>): Promise<JobHandle<T>> {
  const ref = await addDoc(collection(db, "jobs"), { type, params, status: "queued", created_at: Date.now(), by: auth.currentUser?.email ?? null });
  const done = new Promise<T>((res, rej) => {
    const un = onSnapshot(ref, (s) => {
      const d = s.data();
      if (d?.status === "done") { un(); try { res(JSON.parse(d.json)); } catch (e) { rej(e); } }
      else if (d?.status === "failed") { un(); rej(new Error(d.error ?? "job failed")); }
    }, (e) => rej(e));
  });
  return { id: ref.id, done };
}

// ---- one-shot reads and mutations (same signatures as the local API client) ----------------------------
async function settingsDoc(): Promise<any> {
  return (await getDoc(doc(db, "config", "settings"))).data() ?? {};
}

async function watchlist(): Promise<{ symbol: string; pinned: boolean }[]> {
  const d = (await getDoc(doc(db, "config", "watchlist"))).data();
  if (d?.symbols) return d.symbols.map((x: any) => (typeof x === "string" ? { symbol: x, pinned: false } : { symbol: x.symbol, pinned: !!x.pinned }));
  const meta = await first<any>(view("meta")).catch(() => ({ watchlist: [] }));
  return (meta.watchlist ?? []).map((w: any) => ({ symbol: w.symbol, pinned: !!w.pinned }));
}

async function saveWatchlist(list: { symbol: string; pinned: boolean }[]) {
  await setDoc(doc(db, "config", "watchlist"), { symbols: list, updated_at: Date.now() });
  return list.map((w) => ({ ...w, pinned: w.pinned ? 1 : 0 }));
}

export async function api<T = any>(path: string, init?: { method?: string; body?: string }): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const body = init?.body ? JSON.parse(init.body) : {};
  const u = new URL(path, "http://x");
  const p = u.pathname.split("/").filter(Boolean);
  const q = u.searchParams;
  try {
    if (method === "GET") {
      if (p[0] === "search") return { query: q.get("q"), results: await binance.search(q.get("q") ?? "") } as T;
      if (p[0] === "replay" && p.length === 2) {
        const job = await queueJob("replay", { symbol: toSymbol(p[1]), timeframe: q.get("timeframe") ?? "4h", as_of: Number(q.get("as_of")), bars_after: Number(q.get("bars_after") ?? 30) });
        return (await job.done) as T;
      }
      return await first<T>(resolve(path, 0));
    }
    const key = p.length === 3 ? `${method} /${p[0]}/:x/${p[2]}`
      : p.length === 2 && ["watchlist", "alerts"].includes(p[0]) && p[1] !== "read" ? `${method} /${p[0]}/:x`
      : `${method} /${p.join("/")}`;
    switch (key) {
      case "POST /watchlist": {
        const s = toSymbol(body.symbol);
        const found = await binance.search(s.split("/")[0]);
        if (!found.includes(s)) throw new ApiError(404, `${s} is not listed on Binance`);
        const list = await watchlist();
        if (!list.some((w) => w.symbol === s)) list.push({ symbol: s, pinned: false });
        return (await saveWatchlist(list)) as T;
      }
      case "DELETE /watchlist/:x": return (await saveWatchlist((await watchlist()).filter((w) => w.symbol !== toSymbol(p[1])))) as T;
      case "PUT /watchlist/:x/pin": return (await saveWatchlist((await watchlist()).map((w) => (w.symbol === toSymbol(p[1]) ? { ...w, pinned: !!body.pinned } : w)))) as T;
      case "POST /alerts":
        if (!body.type || !body.symbol) throw new ApiError(400, "type and symbol are required");
        return { id: (await addDoc(collection(db, "alerts"), { type: body.type, symbol: toSymbol(body.symbol), timeframe: body.timeframe ?? "4h", params: body.params ?? {}, cooldown_s: Number(body.cooldown_s ?? 3600), enabled: true, created_at: Date.now(), owner_uid: myUid(), owner_email: getSession()?.email ?? null })).id } as T;
      case "PUT /alerts/:x": await updateDoc(doc(db, "alerts", p[1]), { enabled: !!body.enabled }); return { id: p[1] } as T;
      case "DELETE /alerts/:x": await deleteDoc(doc(db, "alerts", p[1])); return { deleted: p[1] } as T;
      case "POST /alerts/read": await setDoc(doc(db, "user_state", myUid()), { alerts_read_before: Date.now() }, { merge: true }); return { ok: true } as T;
      case "PUT /settings": {
        const patch: any = {};
        if (body.risk_profile) patch.risk_profile = Object.fromEntries(Object.entries(body.risk_profile).map(([k, v]) => [k, Number(v)]));
        if (body.signal_weights) {
          const w = Object.fromEntries(Object.entries(body.signal_weights).map(([k, v]) => [k, Math.max(0, Number(v))]));
          if (!Object.values(w).some((x) => x > 0)) throw new ApiError(400, "weights must not all be zero");
          patch.signal_weights = w;
        }
        if (Object.keys(patch).length) await setDoc(doc(db, "config", "settings"), { ...patch, updated_at: Date.now() }, { merge: true });
        return (await first<T>(resolve("/settings", 0)));
      }
      case "POST /settings/optimise-weights": return (await (await queueJob("optimise_weights", { symbol: toSymbol(body.symbol), timeframe: body.timeframe ?? "4h" })).done) as T;
      case "POST /backtest": {
        if (!body.symbol) throw new ApiError(400, "symbol is required");
        return (await (await queueJob("backtest", { ...body, symbol: toSymbol(body.symbol) })).done) as T;
      }
      case "POST /models/train": {
        const params = { symbol: body.symbol ? toSymbol(body.symbol) : null, timeframe: body.timeframe ?? null, fast: !!body.fast };
        await queueJob("train", params);
        return { queued: [params.symbol ? `${params.symbol} ${params.timeframe ?? "all timeframes"}` : "all models"] } as T;
      }
      case "POST /risk/position-size": {
        const s = await settingsDoc();
        const v = await first<any>(view("settings")).catch(() => ({}));
        const ex = await paper.openExposure().catch(() => ({ exposure: 0, today: 0 }));
        return positionSize({ ...(v.risk_profile ?? {}), ...(s.risk_profile ?? {}), ...(body.profile ?? {}) }, Number(body.entry), Number(body.stop), body.sigma_bar, body.timeframe ?? "4h", ex.exposure, ex.today) as T;
      }
      case "POST /paper/order": {
        const meta = await first<any>(view("meta")).catch(() => ({}));
        const trade = await paper.order(toSymbol(body.symbol), body.side, body.qty, body.notional, meta.costs);
        return { trade, state: await first(paper.subscribe) } as T;
      }
      case "POST /paper/reset": await paper.reset(Number(body.starting_balance ?? 10000)); return (await first<T>(paper.subscribe));
      case "PUT /bots": await setDoc(doc(db, "config", "bots"), { bots: body.bots, updated_at: Date.now() }, { merge: true }); return { ok: true } as T;
    }
    throw new ApiError(404, `unsupported action ${method} ${path}`);
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError(400, permissionHint(e as Error));
  }
}

export const post = <T = any>(path: string, body?: unknown) => api<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });
export const put = <T = any>(path: string, body?: unknown) => api<T>(path, { method: "PUT", body: JSON.stringify(body ?? {}) });
export const del = <T = any>(path: string) => api<T>(path, { method: "DELETE" });
