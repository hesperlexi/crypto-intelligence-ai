import { doc, onSnapshot } from "firebase/firestore";
import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { bsym, futures24h, listedPairs, tickers as restTickers, toTicker } from "./binance";
import { Race, raceSocket } from "./ws";
import { db } from "./firebase";
import { localNotify } from "./push";
import { myUid } from "./session";

export interface Ticker {
  symbol: string;
  last: number | null;
  bid?: number | null;
  ask?: number | null;
  spread_bps?: number | null;
  change_pct?: number | null;
  quote_volume?: number | null;
  ts?: number;
}

interface LiveState {
  /** What members see everywhere: the perpetual-futures price (same as the Trade page and the signals), spot when a coin has no futures. */
  tickers: Record<string, Ticker>;
  /** Spot prices only (spot practice trading). */
  spotTickers: Record<string, Ticker>;
  connected: boolean;
  feed: any;
  alerts: { id: string; message: string; created_at: number }[];
  refreshAt: number;
  symbols: string[];
  dismissAlert: (id: string) => void;
}

/** Latest SPOT prices for non-React code (spot paper trading, position sizing). */
export const latestPrices: Record<string, number> = {};

// Prices arrive up to ~16 times a second (spot + futures streams, 125 ms batches). Putting every batch in the React
// context re-rendered every page that reads it (Signals, Dashboard, cards) as often. So:
//  - the context (useLive) gets a price snapshot at most every SLOW_MS (2 per second),
//  - this small store holds the newest prices at full speed, for the trade terminal (useFastTickers) and for
//    components that follow one coin (useTicker), which re-render only when that coin's price changes.
const SLOW_MS = 500;
type Snap = { tickers: Record<string, Ticker>; spotTickers: Record<string, Ticker> };
const EMPTY: Snap = { tickers: {}, spotTickers: {} };
let fastSnap: Snap = EMPTY;
const fastSubs = new Set<() => void>();
function setFast(next: Snap) {
  if (next.tickers === fastSnap.tickers && next.spotTickers === fastSnap.spotTickers) return;
  fastSnap = next;
  fastSubs.forEach((f) => f());
}
const subscribeFast = (f: () => void) => { fastSubs.add(f); return () => { fastSubs.delete(f); }; };
const getFast = () => fastSnap;

const Ctx = createContext<LiveState>({ tickers: {}, spotTickers: {}, connected: false, feed: null, alerts: [], refreshAt: 0, symbols: [], dismissAlert: () => {} });
// several endpoints: some networks block port 9443 or one of the hosts
// the exchange's own stream first (the data-stream.binance.vision mirror can lag a few seconds)
const WS_HOSTS = ["wss://stream.binance.com:9443", "wss://stream.binance.com:443", "wss://data-stream.binance.vision"];
// Binance USDⓈ-M futures: trades on /market (the address the Trade page uses since the 2026-04-23 split)
const FUT_WS = "wss://fstream.binance.com/market";

/** Live tickers straight from Binance's public WebSocket, plus alert / refresh notices from Firestore. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [tickers, setTickers] = useState<Record<string, Ticker>>({});
  const [connected, setConnected] = useState(false);
  const [lastMsg, setLastMsg] = useState<number | null>(null);
  const [alerts, setAlerts] = useState<LiveState["alerts"]>([]);
  const [refreshAt, setRefreshAt] = useState(0);
  const pending = useRef<Record<string, Ticker>>({});
  const started = useRef(Date.now());

  useEffect(() => onSnapshot(doc(db, "config", "watchlist"), (s) => {
    const list = ((s.data()?.symbols ?? []) as any[]).map((x) => (typeof x === "string" ? x : x.symbol));
    setSymbols(list.length ? list : []);
  }, () => {}), []);

  // the member's own coins get live prices too
  const [mine, setMine] = useState<string[]>([]);
  useEffect(() => onSnapshot(doc(db, "user_coins", myUid()), (s) => setMine((s.data()?.symbols ?? []) as string[]), () => {}), []);

  useEffect(() => onSnapshot(doc(db, "views", "meta"), (s) => {
    const t = s.data()?.updated_at;
    if (t) setRefreshAt(t);
    if (!symbols.length && s.data()?.json) {
      try { setSymbols((JSON.parse(s.data()!.json).watchlist ?? []).map((w: any) => w.symbol)); } catch { /* ignore */ }
    }
  }, () => {}), []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => onSnapshot(doc(db, "views", `alerts_u_${myUid()}`), (s) => {
    try {
      const evs = (JSON.parse(s.data()?.json ?? "{}").events ?? []) as any[];
      const fresh = evs.filter((e) => e.created_at > started.current);
      if (fresh.length) {
        started.current = Math.max(...fresh.map((e) => e.created_at));
        setAlerts((a) => [...fresh, ...a].slice(0, 5));
        if (document.hidden) for (const e of fresh.slice(0, 3)) localNotify(`Alert · ${e.symbol ?? ""}`, e.message);
      }
    } catch { /* ignore */ }
  }, () => {}), []);

  // Live prices. Primary: Binance WebSocket. A watchdog reconnects a silent socket (phone sleep, Wi-Fi
  // change, network switch), and while the socket is down prices keep updating over REST every 5 seconds.
  const [mode, setMode] = useState<"ws" | "rest" | "down">("down");
  const [online, setOnline] = useState(typeof navigator === "undefined" ? true : navigator.onLine);
  const all = [...new Set([...symbols, ...mine])];
  const key = all.join(",");
  useEffect(() => {
    const on = () => setOnline(true), off = () => setOnline(false);
    window.addEventListener("online", on); window.addEventListener("offline", off);
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); };
  }, []);
  useEffect(() => {
    const syms = key ? key.split(",") : [];
    if (!syms.length) return;
    let race: Race | null = null;
    let closed = false, attempt = 0, timer = 0, lastFrame = 0, lastRest = 0, busy = false;
    let cur: "ws" | "rest" | "down" = "down";
    const setM = (m: typeof cur) => { if (m !== cur) { cur = m; setMode(m); setConnected(m === "ws"); } };
    const stats: Record<string, Ticker> = {};      // latest 24h stats per coin; trades move the last price in between
    const take = (t: Ticker) => { stats[t.symbol] = t; pending.current[t.symbol] = t; if (t.last != null) latestPrices[t.symbol] = t.last; };
    const trade = (sym: string, px: number, ts: number) => {
      const base = pending.current[sym] ?? stats[sym];
      if (!base || !(px > 0)) return;
      const open = base.last != null && base.change_pct != null ? base.last / (1 + base.change_pct / 100) : null;   // 24h open
      const t = { ...base, last: px, ts, change_pct: open ? (px / open - 1) * 100 : base.change_pct };
      stats[sym] = t; pending.current[sym] = t; latestPrices[sym] = px;
    };

    // all hosts at once; the first to deliver wins (a slow or blocked host costs nothing)
    const connect = () => {
      window.clearTimeout(timer);
      race?.close();
      // @ticker: 24h change / volume / bid-ask (once a second); @aggTrade: every trade, so prices move in real time
      const streams = syms.flatMap((s) => [`${bsym(s).toLowerCase()}@ticker`, `${bsym(s).toLowerCase()}@aggTrade`]).join("/");
      const bySym: Record<string, string> = Object.fromEntries(syms.map((s) => [bsym(s), s]));
      race = raceSocket(WS_HOSTS.map((h) => `${h}/stream?streams=${streams}`), (m) => {
        lastFrame = Date.now(); attempt = 0; setM("ws");
        const d = m.data;
        const sym = d && bySym[d.s];
        if (!sym) return;
        if (d.e === "aggTrade") trade(sym, +d.p, d.T);
        else take(toTicker(sym, +d.c, +d.b, +d.a, +d.P, +d.q, d.E));
      }, () => {
        if (closed) return;
        if (cur === "ws") setM(Date.now() - lastRest < 15000 ? "rest" : "down");
        attempt++;
        timer = window.setTimeout(connect, Math.min(8000, 500 * 2 ** Math.min(attempt, 4)));
      });
    };

    const rest = async () => {
      if (busy || document.hidden || Date.now() - lastFrame < 4000) return;   // socket is delivering: nothing to do
      busy = true;
      try {
        const t = await restTickers(syms);
        Object.values(t).forEach((x: any) => take(x));
        lastRest = Date.now();
        if (Date.now() - lastFrame >= 4000) setM("rest");
      } catch {
        if (Date.now() - lastFrame >= 4000) setM("down");
      } finally { busy = false; }
    };

    const watchdog = window.setInterval(() => {
      if (document.hidden) return;
      if (lastFrame && Date.now() - lastFrame > 15000) { attempt = 0; connect(); }   // silent socket: race again
      rest();
    }, 2000);
    const wake = () => {
      if (document.hidden) return;
      if (Date.now() - lastFrame > 4000) { attempt = 0; connect(); }
      rest();
    };
    document.addEventListener("visibilitychange", wake);
    window.addEventListener("online", wake);
    window.addEventListener("focus", wake);
    connect();
    window.setTimeout(rest, 2500);   // first prices over REST if no stream has answered within 2.5 s

    const flush = window.setInterval(() => {   // up to ~8 renders per second, however many trades arrive
      const p = pending.current;
      if (Object.keys(p).length) {
        pending.current = {};
        setTickers((t) => ({ ...t, ...p }));
        setLastMsg(Date.now());
      }
    }, 125);
    return () => {
      closed = true;
      window.clearTimeout(timer); window.clearInterval(flush); window.clearInterval(watchdog);
      document.removeEventListener("visibilitychange", wake);
      window.removeEventListener("online", wake); window.removeEventListener("focus", wake);
      race?.close();
    };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  // Futures layer: the signals, bots and the Trade page all use the perpetual's price, which differs slightly from
  // spot, so every page shows that price too. Every trade (aggTrade) moves it; 24h change / volume come from the
  // futures REST ticker every 20 s. Coins without a perpetual, or a network that blocks futures, keep spot.
  const [fut, setFut] = useState<Record<string, Ticker>>({});
  useEffect(() => {
    const all0 = key ? key.split(",") : [];
    if (!all0.length) return;
    let closed = false, race: Race | null = null, timer = 0, attempt = 0, lastFrame = 0, syms: string[] = [];
    const stats: Record<string, Ticker> = {}, opens: Record<string, number> = {}, pend: Record<string, Ticker> = {};
    const put = (sym: string, px: number, ts: number) => {
      const o = opens[sym];
      const t: Ticker = { ...(stats[sym] ?? { symbol: sym }), symbol: sym, last: px, ts, ...(o ? { change_pct: (px / o - 1) * 100 } : {}) };
      stats[sym] = t; pend[sym] = t;
    };
    const loadStats = async () => {
      if (closed || document.hidden || !syms.length) return;
      try {
        const rows = await futures24h();
        for (const s of syms) {
          const r = rows[bsym(s)];
          if (!r || !(r.last > 0)) continue;
          opens[s] = r.open;
          const prev = stats[s];
          stats[s] = { ...(prev ?? { symbol: s }), symbol: s, quote_volume: r.qv };
          put(s, prev?.ts && prev.ts > r.ts && prev.last ? prev.last : r.last, Math.max(prev?.ts ?? 0, r.ts));   // keep a newer trade
        }
      } catch { /* futures unreachable: spot stays */ }
    };
    const connect = () => {
      window.clearTimeout(timer);
      race?.close();
      if (closed || !syms.length) return;
      const bySym: Record<string, string> = Object.fromEntries(syms.map((s) => [bsym(s), s]));
      const streams = syms.map((s) => `${bsym(s).toLowerCase()}@aggTrade`).join("/");
      race = raceSocket([`${FUT_WS}/stream?streams=${streams}`], (m) => {
        lastFrame = Date.now(); attempt = 0;
        const d = m.data, sym = d && bySym[d.s];
        if (sym && d.e === "aggTrade" && opens[sym]) put(sym, +d.p, d.T);   // only once its 24h stats are known
      }, () => {
        if (closed) return;
        attempt++;
        timer = window.setTimeout(connect, Math.min(15000, 1000 * 2 ** Math.min(attempt, 4)));
      });
    };
    listedPairs().then(({ fut: listed }) => {
      if (closed) return;
      syms = all0.filter((s) => listed.has(bsym(s)));
      if (!syms.length) return;
      loadStats().then(connect);
    }).catch(() => {});
    const statsTimer = window.setInterval(loadStats, 20000);
    const watchdog = window.setInterval(() => {
      if (!document.hidden && syms.length && lastFrame && Date.now() - lastFrame > 20000) { attempt = 0; connect(); }
    }, 5000);
    const wake = () => { if (!document.hidden && syms.length && Date.now() - lastFrame > 5000) { attempt = 0; loadStats(); connect(); } };
    document.addEventListener("visibilitychange", wake);
    const flush = window.setInterval(() => {
      const ks = Object.keys(pend);
      if (!ks.length) return;
      const batch: Record<string, Ticker> = {};
      for (const k of ks) { batch[k] = pend[k]; delete pend[k]; }
      setFut((f) => ({ ...f, ...batch }));
    }, 125);
    return () => {
      closed = true;
      window.clearTimeout(timer); window.clearInterval(statsTimer); window.clearInterval(watchdog); window.clearInterval(flush);
      document.removeEventListener("visibilitychange", wake);
      race?.close();
    };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  // a futures price older than 30 s (stream and REST both stuck) gives way to the live spot price
  const merged = useMemo(() => {
    const out: Record<string, Ticker> = { ...tickers };
    const now = Date.now();
    for (const [k, f] of Object.entries(fut)) {
      if (f.last == null || (f.ts && now - f.ts > 30_000 && tickers[k]?.last != null)) continue;
      out[k] = { ...(tickers[k] ?? {}), ...f, bid: null, ask: null, spread_bps: null };
    }
    return out;
  }, [tickers, fut]);

  // full speed for the trade terminal and per-coin subscribers
  useEffect(() => { setFast({ tickers: merged, spotTickers: tickers }); }, [merged, tickers]);
  useEffect(() => () => { setFast(EMPTY); }, []);
  // the context: a snapshot at most every SLOW_MS (the first prices go out at once)
  const latest = useRef({ merged, tickers, lastMsg });
  latest.current = { merged, tickers, lastMsg };
  const [slow, setSlow] = useState({ merged, tickers, lastMsg });
  const hasPrices = Object.keys(merged).length > 0;
  useEffect(() => {
    const push = () => setSlow((s) => {
      const l = latest.current;
      return s.merged === l.merged && s.tickers === l.tickers && s.lastMsg === l.lastMsg ? s : { ...l };
    });
    push();
    const id = window.setInterval(push, SLOW_MS);
    return () => window.clearInterval(id);
  }, [hasPrices]);

  const status = !online ? "OFFLINE" : mode === "ws" ? "LIVE" : mode === "rest" ? "LIVE · 2s" : all.length ? "RECONNECTING" : "IDLE";
  const dismissAlert = useCallback((id: string) => setAlerts((a) => a.filter((x) => x.id !== id)), []);
  const symbolList = useMemo(() => (key ? key.split(",") : []), [key]);
  const value = useMemo<LiveState>(() => ({
    tickers: slow.merged, spotTickers: slow.tickers, connected, alerts, refreshAt, symbols: symbolList, dismissAlert,
    feed: {
      status, last_update_ms: slow.lastMsg,
      transport: mode === "ws" ? "Binance WebSocket (streaming)" : mode === "rest" ? "Binance REST, refreshed every 2 s (stream reconnecting)" : "reconnecting to Binance…",
    },
  }), [slow, connected, alerts, refreshAt, symbolList, dismissAlert, status, mode]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Live state for pages: prices refreshed at most twice a second (see SLOW_MS). */
export const useLive = () => useContext(Ctx);

/** Every price at full speed (~8 updates a second): for the trade terminal, where the price must move in real time. */
export function useFastTickers(): Snap {
  return useSyncExternalStore(subscribeFast, getFast, getFast);
}

/** One coin's live price at full speed; the component re-renders only when that coin's price changes. */
export function useTicker(symbol: string | undefined, market: "futures" | "spot" = "futures"): Ticker | undefined {
  const get = useCallback(() => (symbol ? (market === "spot" ? fastSnap.spotTickers : fastSnap.tickers)[symbol] : undefined), [symbol, market]);
  return useSyncExternalStore(subscribeFast, get, get);
}
