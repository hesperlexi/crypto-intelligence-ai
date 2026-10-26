// Real-time market stream for the coin open in the trading screen, like the exchange's own chart:
// every trade (aggTrade) moves the price and the forming candle, the kline stream keeps the candle's
// open / high / low / volume exact, and a new candle starts the moment its period begins.
// Futures read Binance USDⓈ-M Futures (its own price, which differs slightly from spot); if the futures
// endpoints cannot be reached, it falls back to spot and says so.
import { useEffect, useRef, useState } from "react";
import { Candle } from "./ta";
import { bsym, fklines, klines } from "./binance";
import { latestPrices } from "./live";
import { clockOffset, Race, raceSocket } from "./ws";

export type Mkt = "spot" | "futures";
const SPOT_WS = ["wss://stream.binance.com:9443", "wss://stream.binance.com:443", "wss://data-stream.binance.vision"];
const FUT_WS = ["wss://fstream.binance.com"];
const TF_MS: Record<string, number> = { "1m": 6e4, "5m": 3e5, "15m": 9e5, "30m": 18e5, "1h": 36e5, "4h": 144e5, "12h": 432e5, "1d": 864e5, "3d": 2592e5, "1w": 6048e5 };

/** Last traded futures price per symbol (filled by the stream, read by paper futures for fills). */
export const futuresLast: Record<string, { px: number; ts: number }> = {};

export interface StreamState {
  candles: Candle[];          // history, loaded once per symbol / timeframe / market
  live: Candle | null;        // the forming candle, updated on every trade
  last: number | null;        // last traded price
  source: Mkt;                // which market the numbers come from
  status: "loading" | "live" | "polling" | "error";
  error: string | null;
  delay: number | null;       // how old the latest price is when it arrives (ms, on Binance's clock)
}

export function useMarketStream(symbol: string, market: Mkt, tf: string): StreamState {
  const [st, setSt] = useState<StreamState>({ candles: [], live: null, last: null, source: market, status: "loading", error: null, delay: null });
  const liveRef = useRef<Candle | null>(null);

  useEffect(() => {
    let closed = false, race: Race | null = null, attempt = 0, retry = 0, poll = 0, lastFrame = 0, dirty = false;
    let offset = 0, delay: number | null = null;
    let src: Mkt = market;
    const step = TF_MS[tf] ?? 9e5;
    const s = bsym(symbol).toLowerCase();
    liveRef.current = null;
    setSt({ candles: [], live: null, last: null, source: market, status: "loading", error: null, delay: null });

    const tick = (px: number, ts: number) => {
      let c = liveRef.current;
      if (!c) return;
      if (ts >= c[0] + step) {                       // the period rolled over: open a new candle
        const open = c[0] + Math.floor((ts - c[0]) / step) * step;
        c = [open, px, px, px, px, 0];
      } else c = [c[0], c[1], Math.max(c[2], px), Math.min(c[3], px), px, c[5]];
      liveRef.current = c; dirty = true;
      if (src === "futures") futuresLast[symbol] = { px, ts: Date.now() };
      else latestPrices[symbol] = px;
    };
    const kline = (k: any) => {
      const c: Candle = [k.t, +k.o, +k.h, +k.l, +k.c, +k.v];
      const cur = liveRef.current;
      if (cur && c[0] < cur[0]) return;               // a late frame for a candle already closed
      liveRef.current = cur && cur[0] === c[0] ? [c[0], c[1], Math.max(c[2], cur[2]), Math.min(c[3], cur[3]), cur[4], c[5]] : c;
      dirty = true;
    };

    const connect = () => {
      if (closed) return;
      race?.close();
      const hosts = src === "futures" ? FUT_WS : SPOT_WS;
      const path = `/stream?streams=${s}@aggTrade/${s}@kline_${tf}`;
      race = raceSocket(hosts.map((h) => h + path), (m) => {
        lastFrame = Date.now(); attempt = 0;
        const d = m.data;
        if (d?.e === "aggTrade") {
          tick(+d.p, d.T);
          const age = Date.now() + offset - Number(d.E ?? d.T);
          if (Number.isFinite(age)) delay = delay == null ? age : delay * 0.8 + age * 0.2;
        } else if (d?.e === "kline") kline(d.k);
      }, () => {
        if (closed) return;
        attempt++;
        retry = window.setTimeout(connect, Math.min(8000, 500 * 2 ** Math.min(attempt, 4)));
      });
    };

    // while the socket is silent (phone woke up, network switch) the forming candle is polled over REST
    const restPoll = async () => {
      if (closed || document.hidden || Date.now() - lastFrame < 2500) return;
      try {
        const rows = src === "futures" ? await fklines(symbol, tf, 2) : await klines(symbol, tf, 2);
        const c = rows[rows.length - 1];
        if (c) { kline({ t: c[0], o: c[1], h: c[2], l: c[3], c: c[4], v: c[5] }); if (liveRef.current) liveRef.current[4] = c[4]; dirty = true; }
        setSt((x) => (x.status === "polling" ? x : { ...x, status: "polling" }));
      } catch { /* keep trying */ }
      if (race && Date.now() - lastFrame > 15000) { attempt = 0; connect(); }      // silent socket: race again
    };

    (async () => {
      let rows: Candle[] = [];
      try {
        if (market === "futures") {
          try { rows = await fklines(symbol, tf, 400); } catch { src = "spot"; rows = await klines(symbol, tf, 400); }
        } else rows = await klines(symbol, tf, 400);
      } catch (e: any) {
        if (!closed) setSt((x) => ({ ...x, status: "error", error: e?.message ?? "market data unavailable" }));
        return;
      }
      if (closed || !rows.length) return;
      liveRef.current = [...rows[rows.length - 1]] as Candle;
      setSt({ candles: rows.slice(0, -1), live: liveRef.current, last: liveRef.current[4], source: src, status: "live", error: null, delay: null });
      clockOffset(src === "futures").then((o) => { offset = o; });
      connect();
      poll = window.setInterval(restPoll, 1000);          // only used while no stream data is arriving
    })();

    // at most 5 renders a second, however fast trades arrive
    const flush = window.setInterval(() => {
      if (!dirty || !liveRef.current) return;
      dirty = false;
      const c = [...liveRef.current] as Candle;
      // history keeps its identity (the chart is never rebuilt); the chart appends closed candles itself
      setSt((x) => ({ ...x, live: c, last: c[4], delay, status: Date.now() - lastFrame < 2500 ? "live" : x.status }));
    }, 200);
    const wake = () => { if (!document.hidden && Date.now() - lastFrame > 3000) { attempt = 0; connect(); } };
    document.addEventListener("visibilitychange", wake);

    return () => {
      closed = true;
      window.clearTimeout(retry); window.clearInterval(poll); window.clearInterval(flush);
      document.removeEventListener("visibilitychange", wake);
      race?.close();
    };
  }, [symbol, market, tf]);

  return st;
}


/** Live order book (top 20 levels, every 100 ms) over the same racing WebSocket, REST every 2 s as a fallback. */
export function useDepth(symbol: string, market: Mkt): { bids: [number, number][]; asks: [number, number][] } | null {
  const [book, setBook] = useState<{ bids: [number, number][]; asks: [number, number][] } | null>(null);
  useEffect(() => {
    let closed = false, race: Race | null = null, retry = 0, last = 0, pending: any = null;
    const s = bsym(symbol).toLowerCase();
    const fut = market === "futures";
    const conv = (rows: any[]) => (rows || []).map((x: any) => [+x[0], +x[1]] as [number, number]);
    setBook(null);
    const connect = () => {
      if (closed) return;
      const hosts = fut ? FUT_WS : SPOT_WS;
      race = raceSocket(hosts.map((h) => `${h}/stream?streams=${s}@depth20@100ms`), (m) => {
        const d = m.data || {};
        pending = { bids: conv(d.bids ?? d.b), asks: conv(d.asks ?? d.a) };
        last = Date.now();
      }, () => { if (!closed) retry = window.setTimeout(connect, 2000); });
    };
    connect();
    const flush = window.setInterval(() => { if (pending) { setBook(pending); pending = null; } }, 250);
    const poll = window.setInterval(async () => {
      if (closed || document.hidden || Date.now() - last < 3000) return;
      try {
        const { orderbook } = await import("./binance");
        const ob: any = await orderbook(symbol, market);
        if (ob?.bids && !closed) setBook({ bids: ob.bids, asks: ob.asks });
      } catch { /* keep trying */ }
    }, 2000);
    return () => { closed = true; race?.close(); window.clearTimeout(retry); window.clearInterval(flush); window.clearInterval(poll); };
  }, [symbol, market]);
  return book;
}
