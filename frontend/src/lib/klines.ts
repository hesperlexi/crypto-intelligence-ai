// v2.20 Home: cached candles for the BTC cards and chart. One request per symbol / timeframe / size, shared by every
// component that asks (sparklines and the 1H chart use the same 1h candles), refreshed at most every `maxAgeMs` and
// only while the tab is visible. Binance public REST (futures, spot fallback) - no extra sockets, no Firestore reads.
import { useEffect, useState } from "react";
import { fklines } from "./binance";
import type { Candle } from "./ta";
import { visibleInterval } from "./visibleInterval";

type Entry = { at: number; data: Candle[] | null; error: string | null; req: Promise<void> | null; subs: Set<() => void> };
const cache = new Map<string, Entry>();

function entry(key: string): Entry {
  let e = cache.get(key);
  if (!e) { e = { at: 0, data: null, error: null, req: null, subs: new Set() }; cache.set(key, e); }
  return e;
}

function load(key: string, symbol: string, tf: string, limit: number) {
  const e = entry(key);
  if (e.req) return;
  e.req = fklines(symbol, tf, limit)
    .then((d) => { e.data = d; e.error = null; e.at = Date.now(); })
    .catch((err) => { e.error = err instanceof Error ? err.message : String(err); e.at = Date.now(); })
    .finally(() => { e.req = null; e.subs.forEach((f) => f()); });
}

export function useKlines(symbol: string, tf: string, limit: number, maxAgeMs = 300_000): { data: Candle[] | null; error: string | null } {
  const key = `${symbol}|${tf}|${limit}`;
  const [, bump] = useState(0);
  useEffect(() => {
    const e = entry(key);
    const on = () => bump((n) => n + 1);
    e.subs.add(on);
    const check = () => { if (Date.now() - e.at > maxAgeMs) load(key, symbol, tf, limit); };
    check();
    const stop = visibleInterval(check, Math.min(maxAgeMs, 60_000));
    return () => { e.subs.delete(on); stop(); };
  }, [key, symbol, tf, limit, maxAgeMs]);
  const e = cache.get(key);
  return { data: e?.data ?? null, error: e?.data ? null : e?.error ?? null };
}

/** Realised volatility (annualised, %) of the hourly log returns in `closes` (needs ≥ 3 closes). */
export function realisedVol(closes: number[], periodsPerYear = 24 * 365): number | null {
  if (closes.length < 3) return null;
  const r: number[] = [];
  for (let i = 1; i < closes.length; i++) if (closes[i - 1] > 0 && closes[i] > 0) r.push(Math.log(closes[i] / closes[i - 1]));
  if (r.length < 2) return null;
  const m = r.reduce((a, b) => a + b, 0) / r.length;
  const v = r.reduce((a, b) => a + (b - m) ** 2, 0) / (r.length - 1);
  return Math.sqrt(v * periodsPerYear) * 100;
}
