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
