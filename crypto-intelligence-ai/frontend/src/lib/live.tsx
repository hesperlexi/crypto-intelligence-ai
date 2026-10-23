import { doc, onSnapshot } from "firebase/firestore";
import { createContext, ReactNode, useContext, useEffect, useRef, useState } from "react";
import { bsym, toTicker } from "./binance";
import { db } from "./firebase";

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
const WS_HOSTS = ["wss://stream.binance.com:9443", "wss://data-stream.binance.vision"];

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

  useEffect(() => onSnapshot(doc(db, "views", "meta"), (s) => {
    const t = s.data()?.updated_at;
    if (t) setRefreshAt(t);
    if (!symbols.length && s.data()?.json) {
      try { setSymbols((JSON.parse(s.data()!.json).watchlist ?? []).map((w: any) => w.symbol)); } catch { /* ignore */ }
    }
  }, () => {}), []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => onSnapshot(doc(db, "views", "alerts"), (s) => {
    try {
      const evs = (JSON.parse(s.data()?.json ?? "{}").events ?? []) as any[];
      const fresh = evs.filter((e) => e.created_at > started.current);
      if (fresh.length) {
        started.current = Math.max(...fresh.map((e) => e.created_at));
        setAlerts((a) => [...fresh, ...a].slice(0, 5));
      }
    } catch { /* ignore */ }
  }, () => {}), []);

  const key = symbols.join(",");
  useEffect(() => {
    if (!symbols.length) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let attempt = 0;
    let timer = 0;
    const connect = () => {
      const host = WS_HOSTS[attempt % WS_HOSTS.length];
      const streams = symbols.map((s) => `${bsym(s).toLowerCase()}@ticker`).join("/");
      ws = new WebSocket(`${host}/stream?streams=${streams}`);
      ws.onopen = () => { setConnected(true); attempt = 0; };
      ws.onmessage = (ev) => {
        try {
          const d = JSON.parse(ev.data).data;
          const sym = symbols.find((s) => bsym(s) === d.s);
          if (!sym) return;
          const t = toTicker(sym, +d.c, +d.b, +d.a, +d.P, +d.q, d.E);
          pending.current[sym] = t;
          latestPrices[sym] = t.last;
        } catch { /* ignore malformed frames */ }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) { attempt++; timer = window.setTimeout(connect, Math.min(15000, 1000 * 2 ** Math.min(attempt, 4))); }
      };
      ws.onerror = () => ws?.close();
    };
    connect();
    const flush = window.setInterval(() => {   // at most 4 renders per second
      const p = pending.current;
      if (Object.keys(p).length) {
        pending.current = {};
        setTickers((t) => ({ ...t, ...p }));
        setLastMsg(Date.now());
      }
    }, 250);
    return () => { closed = true; window.clearTimeout(timer); window.clearInterval(flush); ws?.close(); };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const feed = { status: connected ? "LIVE" : symbols.length ? "CONNECTING" : "IDLE", transport: "Binance WebSocket", last_update_ms: lastMsg };
  const dismissAlert = (id: string) => setAlerts((a) => a.filter((x) => x.id !== id));
  return <Ctx.Provider value={{ tickers, connected, feed, alerts, refreshAt, symbols, dismissAlert }}>{children}</Ctx.Provider>;
}

export const useLive = () => useContext(Ctx);

export function useTicker(symbol: string | undefined): Ticker | undefined {
  const { tickers } = useLive();
  return symbol ? tickers[symbol] : undefined;
}
