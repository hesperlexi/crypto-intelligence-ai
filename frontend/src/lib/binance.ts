// Public Binance market data, fetched directly by the browser (no key). Several hosts are tried in turn.
import { Candle, overlays } from "./ta";

const REST = ["https://api.binance.com", "https://data-api.binance.vision", "https://api1.binance.com"];
const FUTURES = "https://fapi.binance.com";
const TF_MS: Record<string, number> = { "1m": 6e4, "5m": 3e5, "15m": 9e5, "30m": 18e5, "1h": 36e5, "4h": 144e5, "12h": 432e5, "1d": 864e5, "3d": 2592e5, "1w": 6048e5 };
let good = 0;

export const bsym = (symbol: string) => symbol.replace("/", "").toUpperCase();

async function get<T = any>(path: string, hosts = REST): Promise<T> {
  let last: unknown = null;
  for (let k = 0; k < hosts.length; k++) {
    const i = (good + k) % hosts.length;
    try {
      const r = await fetch(hosts[i] + path);
      if (r.status === 400) throw new Error((await r.json().catch(() => ({})))?.msg ?? "bad request");
      if (!r.ok) { last = new Error(`HTTP ${r.status}`); continue; }
      if (hosts === REST) good = i;
      return (await r.json()) as T;
    } catch (e) {
      last = e;
      if (e instanceof Error && e.message !== "Failed to fetch" && !e.message.startsWith("HTTP")) throw e;
    }
  }
  throw new Error(`Binance not reachable (${last instanceof Error ? last.message : "network"})`);
}

export async function klines(symbol: string, tf: string, limit = 500): Promise<Candle[]> {
  const rows = await get<any[]>(`/api/v3/klines?symbol=${bsym(symbol)}&interval=${tf}&limit=${Math.min(limit, 1000)}`);
  return rows.map((r) => [r[0], +r[1], +r[2], +r[3], +r[4], +r[5]] as Candle);
}

/** USDⓈ-M futures candles (the perpetual's own price); falls back to spot when futures are unreachable. */
export async function fklines(symbol: string, tf: string, limit = 500): Promise<Candle[]> {
  try {
    const rows = await get<any[]>(`/fapi/v1/klines?symbol=${bsym(symbol)}&interval=${tf}&limit=${Math.min(limit, 1500)}`, [FUTURES]);
    return rows.map((r) => [r[0], +r[1], +r[2], +r[3], +r[4], +r[5]] as Candle);
  } catch (e) {
    if (limit > 2) return klines(symbol, tf, limit);
    throw e;
  }
}

/** Last futures price for every listed perpetual, keyed by app symbol (empty when futures are unreachable). */
export async function futuresPrices(symbols: string[]): Promise<Record<string, number>> {
  if (!symbols.length) return {};
  try {
    const rows = await get<any[]>("/fapi/v1/ticker/price", [FUTURES]);
    const want = Object.fromEntries(symbols.map((s) => [bsym(s), s]));
    const out: Record<string, number> = {};
    for (const r of rows) if (want[r.symbol]) out[want[r.symbol]] = +r.price;
    return out;
  } catch { return {}; }
}

export async function ohlcv(symbol: string, tf: string, limit = 500) {
  const candles = await klines(symbol, tf, limit);
  const step = TF_MS[tf];
  let missing = 0;
  for (let i = 1; i < candles.length; i++) missing += Math.max(0, Math.round((candles[i][0] - candles[i - 1][0]) / step) - 1);
  return { symbol, timeframe: tf, exchange: "Binance", candles, overlays: overlays(candles, step < 864e5), quality: { missing } };
}

export async function tickers(symbols: string[]) {
  if (!symbols.length) return {};
  const rows = await get<any[]>(`/api/v3/ticker/24hr?symbols=${encodeURIComponent(JSON.stringify(symbols.map(bsym)))}`);
  const by = Object.fromEntries(symbols.map((s) => [bsym(s), s]));
  const out: Record<string, any> = {};
  for (const t of rows) {
    const s = by[t.symbol];
    if (s) out[s] = toTicker(s, +t.lastPrice, +t.bidPrice, +t.askPrice, +t.priceChangePercent, +t.quoteVolume, t.closeTime);
  }
  return out;
}

export function toTicker(symbol: string, last: number, bid: number, ask: number, change: number, qv: number, ts: number) {
  const spread = bid && ask ? ask - bid : null;
  return { symbol, last, bid, ask, spread_bps: spread !== null && last ? (spread / last) * 1e4 : null, change_pct: change, quote_volume: qv, ts };
}

export async function search(q: string) {
  const rows = await get<any[]>("/api/v3/ticker/price");
  const Q = q.toUpperCase().replace(/[/-]/g, "");
  return rows.map((r) => r.symbol as string).filter((s) => s.endsWith("USDT") && s.includes(Q))
    .sort((a, b) => Number(!a.startsWith(Q)) - Number(!b.startsWith(Q)) || a.length - b.length)
    .slice(0, 20).map((s) => `${s.slice(0, -4)}/USDT`);
}

/** Port of the engine's order-book analytics (imbalance within 1% of mid, spread, large orders). */
export function bookMetrics(bids: [number, number][], asks: [number, number][], depthPct = 1, wallMult = 5) {
  if (!bids.length || !asks.length) return null;
  const bb = bids[0][0], ba = asks[0][0], mid = (bb + ba) / 2;
  const inB = bids.filter((b) => b[0] >= mid * (1 - depthPct / 100));
  const inA = asks.filter((a) => a[0] <= mid * (1 + depthPct / 100));
  const bv = inB.reduce((s, b) => s + b[0] * b[1], 0), av = inA.reduce((s, a) => s + a[0] * a[1], 0);
  const med = (side: [number, number][]) => { const q = side.map((x) => x[1]).sort((x, y) => x - y); return q[Math.floor(q.length / 2)]; };
  const walls = (side: [number, number][], name: string) => {
    const m = med(side);
    return side.filter((x) => x[1] > wallMult * m).slice(0, 5).map((x) => ({ side: name, price: x[0], size: x[1], distance_pct: (x[0] / mid - 1) * 100 }));
  };
  return { mid, spread: ba - bb, spread_bps: ((ba - bb) / mid) * 1e4, bid_value: bv, ask_value: av,
    imbalance: bv + av > 0 ? (bv - av) / (bv + av) : 0, walls: [...walls(bids, "bid"), ...walls(asks, "ask")] };
}

export async function orderbook(symbol: string, market: "spot" | "futures" = "spot") {
  let ob: any;
  if (market === "futures") {
    try { ob = await get<any>(`/fapi/v1/depth?symbol=${bsym(symbol)}&limit=500`, [FUTURES]); } catch { /* spot below */ }
  }
  ob ??= await get<any>(`/api/v3/depth?symbol=${bsym(symbol)}&limit=500`);
  const bids = ob.bids.map((x: string[]) => [+x[0], +x[1]]) as [number, number][];
  const asks = ob.asks.map((x: string[]) => [+x[0], +x[1]]) as [number, number][];
  const m = bookMetrics(bids, asks);
  return m ? { symbol, available: true, metrics: m, bids: bids.slice(0, 25), asks: asks.slice(0, 25) }
    : { symbol, available: false, reason: "empty order book" };
}

const OI_MEANING: Record<string, [string, string]> = {
  "1,1": ["Price ↑ + OI ↑", "New positions are opening in the direction of the rise: fresh longs are supporting the move. Trend-confirming, but leverage is building."],
  "1,-1": ["Price ↑ + OI ↓", "Positions are closing as price rises: the move is likely driven by short covering rather than new demand, which tends to be less durable."],
  "-1,1": ["Price ↓ + OI ↑", "New positions are opening as price falls: fresh shorts are pressing the move. Trend-confirming to the downside; squeeze risk rises if it stalls."],
  "-1,-1": ["Price ↓ + OI ↓", "Positions are closing as price falls: long liquidation / de-leveraging. Often seen late in a decline rather than at its start."],
};

export async function derivatives(symbol: string) {
  try {
    const s = bsym(symbol);
    const [prem, oi] = await Promise.all([
      get<any>(`/fapi/v1/premiumIndex?symbol=${s}`, [FUTURES]),
      get<any[]>(`/futures/data/openInterestHist?symbol=${s}&period=1h&limit=25`, [FUTURES]),
    ]);
    const out: any = { available: true, venue: "Binance USDⓈ-M futures", funding: { rate: +prem.lastFundingRate, next_ts: prem.nextFundingTime } };
    if (oi.length >= 2) {
      const ch = +oi[oi.length - 1].sumOpenInterest / +oi[0].sumOpenInterest - 1;
      out.open_interest = { latest: +oi[oi.length - 1].sumOpenInterest, change: ch, hours: oi.length - 1 };
      const k = await klines(symbol, "1h", oi.length);
      const pc = k.length ? k[k.length - 1][4] / k[0][1] - 1 : 0;
      if (Math.abs(pc) > 1e-4 && Math.abs(ch) > 1e-4) {
        const [label, meaning] = OI_MEANING[`${Math.sign(pc)},${Math.sign(ch)}`];
        out.oi_price = { label, meaning, price_change: pc, oi_change: ch };
      }
    }
    return out;
  } catch (e) {
    return { available: false, reason: e instanceof Error ? e.message : "futures data not reachable" };
  }
}

/** Live perpetual-futures context for several coins at once: funding, mark price, open-interest change
 *  over 24h and the share of accounts that are long. Fetched by the browser from Binance USDⓈ-M futures. */
export async function futuresMarket(symbols: string[]) {
  const out: Record<string, any> = {};
  if (!symbols.length) return { available: false, rows: out, reason: "no coins" };
  let prem: any[];
  try {
    prem = await get<any[]>("/fapi/v1/premiumIndex", [FUTURES]);
  } catch (e) {
    return { available: false, rows: out, reason: e instanceof Error ? e.message : "Binance futures not reachable" };
  }
  const by = Object.fromEntries(prem.map((p) => [p.symbol, p]));
  await Promise.all(symbols.map(async (s) => {
    const p = by[bsym(s)];
    if (!p) { out[s] = { listed: false }; return; }
    const row: any = { listed: true, funding_rate: +p.lastFundingRate, next_funding: +p.nextFundingTime, mark: +p.markPrice, index: +p.indexPrice };
    row.basis_pct = row.index ? (row.mark / row.index - 1) * 100 : null;
    const [oi, ls] = await Promise.all([
      get<any[]>(`/futures/data/openInterestHist?symbol=${bsym(s)}&period=1h&limit=25`, [FUTURES]).catch(() => []),
      get<any[]>(`/futures/data/globalLongShortAccountRatio?symbol=${bsym(s)}&period=1h&limit=1`, [FUTURES]).catch(() => []),
    ]);
    if (oi.length >= 2) {
      row.open_interest_usd = +oi[oi.length - 1].sumOpenInterestValue;
      row.oi_change_24h = +oi[oi.length - 1].sumOpenInterest / +oi[0].sumOpenInterest - 1;
    }
    if (ls.length) { row.long_account_pct = +ls[0].longAccount * 100; row.long_short_ratio = +ls[0].longShortRatio; }
    out[s] = row;
  }));
  return { available: true, rows: out, fetched_at: Date.now() };
}
