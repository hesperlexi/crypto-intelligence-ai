// DEV PREVIEW ONLY. Sample market data instead of Binance (the sandbox and screenshots run offline), then the real app.
import { PRICES } from "./seed";

const realFetch = window.fetch.bind(window);
const json = (o: any) => new Response(JSON.stringify(o), { status: 200, headers: { "Content-Type": "application/json" } });
const bs = (s: string) => s.replace("/", "");
const bySym = Object.fromEntries(Object.entries(PRICES).map(([s, x]) => [bs(s), { s, ...x }]));
window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input instanceof Request ? input.url : input);
  if (!/binance|flagcdn/.test(url)) return realFetch(input, init);
  const u = new URL(url);
  const p = u.pathname;
  const t24 = (k: string) => { const x = bySym[k]; return { symbol: k, lastPrice: String(x.p), bidPrice: String(x.p * 0.9999), askPrice: String(x.p * 1.0001), priceChangePercent: String(x.c), quoteVolume: "250000000", openPrice: String(x.p / (1 + x.c / 100)), closeTime: Date.now() }; };
  if (p.endsWith("/ticker/24hr")) {
    const want = u.searchParams.get("symbols") ? JSON.parse(u.searchParams.get("symbols")!) as string[] : u.searchParams.get("symbol") ? [u.searchParams.get("symbol")!] : Object.keys(bySym);
    const rows = want.filter((k) => bySym[k]).map(t24);
    return json(u.searchParams.get("symbol") ? rows[0] : rows);
  }
  // candles: a deterministic random walk that ends at the sample price (Home chart / sparklines / volatility)
  if (p.endsWith("/klines")) {
    const k = u.searchParams.get("symbol") ?? "BTCUSDT", x = bySym[k];
    if (!x) return json([]);
    const step: Record<string, number> = { "1m": 6e4, "15m": 9e5, "1h": 36e5, "4h": 144e5, "12h": 432e5, "1d": 864e5, "3d": 2592e5, "1w": 6048e5 };
    const ms = step[u.searchParams.get("interval") ?? "1h"] ?? 36e5, n = Math.min(1000, Number(u.searchParams.get("limit") ?? 200));
    const vol = Math.min(0.06, 0.0045 * Math.sqrt(ms / 36e5));
    let seed = [...k].reduce((a, c) => a + c.charCodeAt(0), 0) + Math.round(ms / 6e4);
    const rnd = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };
    const rets = Array.from({ length: n }, (_, i) => (rnd() - 0.48) * vol * 2 * (1 + 0.6 * Math.sin(i / 17)));
    let c = x.p; const closes: number[] = [];
    for (let i = n - 1; i >= 0; i--) { closes[i] = c; c = c / (1 + rets[i]); }
    const t0 = Math.floor(Date.now() / ms) * ms - (n - 1) * ms;
    return json(closes.map((cl, i) => { const o = i ? closes[i - 1] : cl / (1 + rets[0]); const hi = Math.max(o, cl) * (1 + rnd() * vol * 0.6), lo = Math.min(o, cl) * (1 - rnd() * vol * 0.6);
      return [t0 + i * ms, String(o), String(hi), String(lo), String(cl), String(1000 + rnd() * 4000), t0 + (i + 1) * ms - 1]; }));
  }
  if (p.endsWith("/ticker/price")) return json(Object.keys(bySym).map((k) => ({ symbol: k, price: String(bySym[k].p) })));
  if (p.endsWith("/premiumIndex")) return json(Object.keys(bySym).map((k) => ({ symbol: k, lastFundingRate: "0.0001", nextFundingTime: Date.now() + 3e6, markPrice: String(bySym[k].p), indexPrice: String(bySym[k].p) })));
  return json([]);
};
// no live sockets in the preview: every attempt closes, the app falls back to the sample prices above
class OfflineSocket extends EventTarget {
  static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
  readyState = 3; url: string; onclose: any = null; onerror: any = null; onmessage: any = null; onopen: any = null;
  constructor(url: string) { super(); this.url = url; setTimeout(() => this.onclose?.({}), 50); }
  send() {} close() {}
}
(window as any).WebSocket = OfflineSocket;

void import("../src/main");
