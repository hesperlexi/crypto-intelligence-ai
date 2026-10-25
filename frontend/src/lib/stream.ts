// Real-time market stream for the coin open in the trading screen, like the exchange's own chart:
// every trade (aggTrade) moves the price and the forming candle, the kline stream keeps the candle's
// open / high / low / volume exact, and a new candle starts the moment its period begins.
// Futures read Binance USDⓈ-M Futures (its own price, which differs slightly from spot); if the futures
// endpoints cannot be reached, it falls back to spot and says so.
import { useEffect, useRef, useState } from "react";
import { Candle } from "./ta";
import { bsym, fklines, klines } from "./binance";
import { latestPrices } from "./live";

export type Mkt = "spot" | "futures";
const SPOT_WS = ["wss://data-stream.binance.vision", "wss://stream.binance.com:9443"];
const FUT_WS = ["wss://fstream.binance.com"];
const TF_MS: Record<string, number> = { "1m": 6e4, "5m": 3e5, "15m": 9e5, "1h": 36e5, "4h": 144e5, "1d": 864e5 };

/** Last traded futures price per symbol (filled by the stream, read by paper futures for fills). */
export const futuresLast: Record<string, { px: number; ts: number }> = {};

export interface StreamState {
  candles: Candle[];          // history, loaded once per symbol / timeframe / market
  live: Candle | null;        // the forming candle, updated on every trade
  last: number | null;        // last traded price
  source: Mkt;                // which market the numbers come from
  status: "loading" | "live" | "polling" | "error";
  error: string | null;
}

export function useMarketStream(symbol: string, market: Mkt, tf: string): StreamState {
  const [st, setSt] = useState<StreamState>({ candles: [], live: null, last: null, source: market, status: "loading", error: null });
  const liveRef = useRef<Candle | null>(null);

  useEffect(() => {
    let closed = false, ws: WebSocket | null = null, attempt = 0, retry = 0, poll = 0, lastFrame = 0, dirty = false;
    let src: Mkt = market;
    const step = TF_MS[tf] ?? 9e5;
    const s = bsym(symbol).toLowerCase();
    liveRef.current = null;
    setSt({ candles: [], live: null, last: null, source: market, status: "loading", error: null });

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
      const hosts = src === "futures" ? FUT_WS : SPOT_WS;
      const sock = new WebSocket(`${hosts[attempt % hosts.length]}/stream?streams=${s}@aggTrade/${s}@kline_${tf}`);
      ws = sock;
      sock.onmessage = (ev) => {
        lastFrame = Date.now(); attempt = 0;
        try {
          const m = JSON.parse(ev.data);
          if (m.data?.e === "aggTrade") tick(+m.data.p, m.data.T);
          else if (m.data?.e === "kline") kline(m.data.k);
        } catch { /* ignore */ }
      };
      sock.onclose = () => {
        if (closed || ws !== sock) return;
        attempt++;
        retry = window.setTimeout(connect, Math.min(10000, 1000 * 2 ** Math.min(attempt, 3)));
      };
      sock.onerror = () => { try { sock.close(); } catch { /* ignore */ } };
    };

    // while the socket is silent (phone woke up, network switch) the forming candle is polled over REST
    const restPoll = async () => {
      if (closed || document.hidden || Date.now() - lastFrame < 6000) return;
      try {
        const rows = src === "futures" ? await fklines(symbol, tf, 2) : await klines(symbol, tf, 2);
        const c = rows[rows.length - 1];
        if (c) { kline({ t: c[0], o: c[1], h: c[2], l: c[3], c: c[4], v: c[5] }); if (liveRef.current) liveRef.current[4] = c[4]; dirty = true; }
        setSt((x) => (x.status === "polling" ? x : { ...x, status: "polling" }));
      } catch { /* keep trying */ }
      if (ws && ws.readyState === WebSocket.OPEN && Date.now() - lastFrame > 20000) { try { ws.close(); } catch { /* reconnects */ } }
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
      setSt({ candles: rows.slice(0, -1), live: liveRef.current, last: liveRef.current[4], source: src, status: "live", error: null });
      connect();
      poll = window.setInterval(restPoll, 3000);
    })();

    // at most ~6 renders a second, however fast trades arrive
    const flush = window.setInterval(() => {
      if (!dirty || !liveRef.current) return;
      dirty = false;
      const c = [...liveRef.current] as Candle;
      // history keeps its identity (the chart is never rebuilt); the chart appends closed candles itself
      setSt((x) => ({ ...x, live: c, last: c[4], status: Date.now() - lastFrame < 6000 ? "live" : x.status }));
    }, 160);
    const wake = () => { if (!document.hidden && (!ws || ws.readyState > WebSocket.OPEN)) { attempt = 0; connect(); } };
    document.addEventListener("visibilitychange", wake);

    return () => {
      closed = true;
      window.clearTimeout(retry); window.clearInterval(poll); window.clearInterval(flush);
      document.removeEventListener("visibilitychange", wake);
      try { ws?.close(); } catch { /* ignore */ }
    };
  }, [symbol, market, tf]);

  return st;
}
