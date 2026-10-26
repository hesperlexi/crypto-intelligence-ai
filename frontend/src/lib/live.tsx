import { doc, onSnapshot } from "firebase/firestore";
import { createContext, ReactNode, useContext, useEffect, useRef, useState } from "react";
import { bsym, tickers as restTickers, toTicker } from "./binance";
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
  tickers: Record<string, Ticker>;
  connected: boolean;
  feed: any;
  alerts: { id: string; message: string; created_at: number }[];
  refreshAt: number;
  symbols: string[];
  dismissAlert: (id: string) => void;
}

/** Latest prices for non-React code (paper trading, position sizing). */
export const latestPrices: Record<string, number> = {};

const Ctx = createContext<LiveState>({ tickers: {}, connected: false, feed: null, alerts: [], refreshAt: 0, symbols: [], dismissAlert: () => {} });
// several endpoints: some networks block port 9443 or one of the hosts
// the exchange's own stream first (the data-stream.binance.vision mirror can lag a few seconds)
const WS_HOSTS = ["wss://stream.binance.com:9443", "wss://stream.binance.com:443", "wss://data-stream.binance.vision"];

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
    const take = (t: Ticker) => { pending.current[t.symbol] = t; if (t.last != null) latestPrices[t.symbol] = t.last; };

    // all hosts at once; the first to deliver wins (a slow or blocked host costs nothing)
    const connect = () => {
      window.clearTimeout(timer);
      race?.close();
      const streams = syms.map((s) => `${bsym(s).toLowerCase()}@ticker`).join("/");
      race = raceSocket(WS_HOSTS.map((h) => `${h}/stream?streams=${streams}`), (m) => {
        lastFrame = Date.now(); attempt = 0; setM("ws");
        const d = m.data;
        const sym = d && syms.find((s) => bsym(s) === d.s);
        if (sym) take(toTicker(sym, +d.c, +d.b, +d.a, +d.P, +d.q, d.E));
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

    const flush = window.setInterval(() => {   // up to ~6 renders per second
      const p = pending.current;
      if (Object.keys(p).length) {
        pending.current = {};
        setTickers((t) => ({ ...t, ...p }));
        setLastMsg(Date.now());
      }
    }, 160);
    return () => {
      closed = true;
      window.clearTimeout(timer); window.clearInterval(flush); window.clearInterval(watchdog);
      document.removeEventListener("visibilitychange", wake);
      window.removeEventListener("online", wake); window.removeEventListener("focus", wake);
      race?.close();
    };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const status = !online ? "OFFLINE" : mode === "ws" ? "LIVE" : mode === "rest" ? "LIVE · 2s" : all.length ? "RECONNECTING" : "IDLE";
  const feed = {
    status, last_update_ms: lastMsg,
    transport: mode === "ws" ? "Binance WebSocket (streaming)" : mode === "rest" ? "Binance REST, refreshed every 2 s (stream reconnecting)" : "reconnecting to Binance…",
  };
  const dismissAlert = (id: string) => setAlerts((a) => a.filter((x) => x.id !== id));
  return <Ctx.Provider value={{ tickers, connected, feed, alerts, refreshAt, symbols: all, dismissAlert }}>{children}</Ctx.Provider>;
}

export const useLive = () => useContext(Ctx);

export function useTicker(symbol: string | undefined): Ticker | undefined {
  const { tickers } = useLive();
  return symbol ? tickers[symbol] : undefined;
}
