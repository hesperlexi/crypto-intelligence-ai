// Exchange-style paper trading (Binance / MEXC layout): pair bar, live candle chart with your levels,
// order book, order form (limit / market, leverage, size %, TP/SL) and positions / orders / history / assets.
// Virtual money only: nothing is ever sent to an exchange.
import { createContext, memo, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import CandleChart, { Candle, PriceLine } from "./CandleChart";
import TVChart from "./TVChart";
import AutoTrade from "./AutoTrade";
import { useSymbols } from "./Pickers";
import { CoinAvatar } from "./Polish";
import { verdictOf } from "./TradeCall";
import { useApi } from "../lib/api";
import { futuresTicker, listedPairs } from "../lib/binance";
import { StreamState, useDepth, useMarketStream } from "../lib/stream";
import { ProOnly, useIsPro } from "../lib/mode";
import { base, fmtNum, fmtPctRaw, fmtPrice, fmtTime, isNum, tone } from "../lib/format";
import { useLive } from "../lib/live";
import { useFocusTrap } from "./Shell";
import * as SP from "../lib/paper";
import * as PF from "../lib/paperFutures";

type Mkt = "spot" | "futures";
const CHART_TFS = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;
const LEVS = [1, 2, 3, 5, 10, 20, 50];

/** The live stream of the coin on screen (futures price on the Futures tab), shared by every panel. */
const StreamCtx = createContext<StreamState | null>(null);
// Gold: Binance lists Tether Gold (XAUT) only as a USDⓈ-M perpetual, so it is offered on the Futures tab
// (live chart, order book and demo trading; no AI signals, the engine reads spot data).
export const GOLD = "XAUT/USDT";
const isGold = (s: string) => s === GOLD;

function useGoldListed(): boolean {
  const [ok, setOk] = useState(false);
  useEffect(() => { let live = true; listedPairs().then((l) => { if (live) setOk(l.fut.has("XAUTUSDT")); }).catch(() => {}); return () => { live = false; }; }, []);
  return ok;
}

/** 24h stats: the live spot feed for the app's coins, Binance futures for gold (refreshed every 15 s). */
/** Spot screens use spot prices; futures screens the perpetual's own price. */
function useMktTickers(market: Mkt) {
  const { tickers, spotTickers } = useLive();
  return market === "spot" ? spotTickers : tickers;
}

function useTicker(symbol: string, market: Mkt) {
  const tickers = useMktTickers(market);
  const [t, setT] = useState<any>(null);
  const gold = isGold(symbol);
  useEffect(() => {
    if (!gold) return;
    let live = true;
    const load = () => futuresTicker(symbol).then((x) => { if (live) setT(x); }).catch(() => {});
    setT(null); load();
    const id = window.setInterval(load, 15000);
    return () => { live = false; window.clearInterval(id); };
  }, [symbol, gold]);
  return gold ? t : tickers[symbol];
}

function useLastPrice(symbol: string): number | null {
  const st = useContext(StreamCtx);
  const tickers = useMktTickers(st?.source === "spot" ? "spot" : "futures");
  return st?.last ?? tickers[symbol]?.last ?? null;
}

function useAccount(m: Mkt) {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setD(null);
    return (m === "futures" ? PF.subscribe : SP.subscribe)((x: any) => { setD(x); setErr(null); }, (e: Error) => setErr(e.message));
  }, [m]);
  return { d, err };
}

export default function TradeTerminal() {
  const [params, setParams] = useSearchParams();
  const market: Mkt = params.get("market") === "spot" ? "spot" : "futures";
  const symbols = useSymbols();
  const symbol = params.get("symbol") ?? symbols[0] ?? "BTC/USDT";
  const setQ = (patch: Record<string, string>) => { const p = new URLSearchParams(params); Object.entries(patch).forEach(([k, v]) => p.set(k, v)); ["side", "lev", "sl", "tp", "limit"].forEach((k) => { if (!(k in patch)) p.delete(k); }); setParams(p, { replace: true }); };
  const { d, err } = useAccount(market);
  const [tab, setTab] = useState<"positions" | "orders" | "history" | "assets">("positions");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  // stable across price ticks, so memoized rows do not re-render just because the parent did
  const act = useCallback(async (fn: () => Promise<any>, ok: string) => {
    try { await fn(); setMsg({ ok: true, text: ok }); } catch (e: any) { setMsg({ ok: false, text: e.message }); }
  }, []);
  const [detail, setDetail] = useState<string | null>(null);     // key (futures) or symbol (spot) of the position in the details panel
  useEffect(() => setDetail(null), [market]);
  const chartRef = useRef<HTMLDivElement>(null);       // the pair bar right above the chart
  const paramsRef = useRef(params); paramsRef.current = params;
  /** Pair name clicked in a list: show that coin on the chart (same timeframe), and bring the chart into view. */
  const showPair = useCallback((s: string) => {
    const p = new URLSearchParams(paramsRef.current); p.set("symbol", s); ["side", "lev", "sl", "tp", "limit"].forEach((k) => p.delete(k));
    setParams(p, { replace: true });
    const el = chartRef.current;
    if (el) {
      const r = el.getBoundingClientRect();
      if (r.top < 64 || r.top > window.innerHeight * 0.4) el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [setParams]);
  const positions: any[] = d?.positions ?? [];
  const orders: any[] = d?.orders ?? [];
  const [tf, setTf] = useState<string>("15m");
  const pro = useIsPro();
  const stream = useMarketStream(symbol, market, tf);

  return (
    <StreamCtx.Provider value={stream}>
    <div className="space-y-3">
      <div ref={chartRef} className="scroll-mt-20 md:scroll-mt-32"><PairBar symbol={symbol} symbols={symbols} market={market} onSymbol={(s) => setQ({ symbol: s })}
        onMarket={(m) => setQ({ market: m, symbol: m === "spot" && isGold(symbol) ? (symbols[0] ?? "BTC/USDT") : symbol })} /></div>
      <SignalStrip symbol={symbol} market={market} />
      {market === "futures" && <AutoTrade />}
      {msg && <div role="status" className={`rounded-lg border px-3 py-2 text-sm ${msg.ok ? "border-bull/40 bg-bull/10 text-bull" : "border-bear/40 bg-bear/10 text-bear"}`}>{msg.text}</div>}
      {err && <div className="rounded-lg border border-bear/40 bg-bear/10 px-3 py-2 text-sm text-bear">{err}</div>}

      <div className={`grid gap-3 ${pro ? "lg:grid-cols-[minmax(0,1fr)_220px_320px]" : "lg:grid-cols-[minmax(0,1fr)_320px]"}`}>
        <ChartPanel symbol={symbol} market={market} positions={positions} orders={orders} tf={tf} setTf={setTf} />
        <ProOnly><OrderBook symbol={symbol} market={market} /></ProOnly>
        <OrderForm symbol={symbol} market={market} d={d} act={act} />
      </div>

      <section className="panel p-0">
        <div className="flex gap-1 overflow-x-auto border-b border-glass/[0.06] px-2 pt-2" role="tablist">
          {([["positions", `${market === "futures" ? "Positions" : "Holdings"} (${positions.length})`], ["orders", `Open orders (${orders.length})`], ["history", "Order history"], ["assets", "Assets"]] as const).map(([k, l]) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
              className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm ${tab === k ? "border-accent font-semibold text-text" : "border-transparent text-mute hover:text-text"}`}>{l}</button>
          ))}
        </div>
        <div className="p-3">
          {!d ? <div className="skeleton h-16 rounded-lg" /> :
            tab === "positions" ? (market === "futures" ? <FutPositions rows={positions} act={act} hedges={d.hedges} onOpen={setDetail} onPair={showPair} /> : <SpotHoldings rows={positions} act={act} onOpen={setDetail} onPair={showPair} />) :
            tab === "orders" ? <Orders rows={orders} market={market} act={act} onPair={showPair} /> :
            tab === "history" ? <History rows={d.trades ?? []} market={market} onPair={showPair} /> :
            <Assets d={d} market={market} act={act} />}
        </div>
      </section>
      {d && detail && <PositionDrawer market={market} d={d} id={detail} act={act} onPair={showPair} onClose={() => setDetail(null)} />}
      <p className="text-xs text-mute">Practice account with virtual USDT. Market orders fill at the live price plus a small spread and slippage; limit orders fill when the price reaches them (checked on every 15-minute candle, also while the app is closed). Fees: spot 0.1%, futures 0.05% market / 0.02% limit.</p>
    </div>
    </StreamCtx.Provider>
  );
}

/* ---------------------------------------------------------------- pair bar */
function PairBar({ symbol, symbols, market, onSymbol, onMarket }: { symbol: string; symbols: string[]; market: Mkt; onSymbol: (s: string) => void; onMarket: (m: Mkt) => void }) {
  const tickers = useMktTickers(market);
  const t = useTicker(symbol, market);
  const last = useLastPrice(symbol);
  const st = useContext(StreamCtx);
  const [open, setOpen] = useState(false);
  const goldOk = useGoldListed();
  const list = market === "futures" && goldOk && !symbols.includes(GOLD) ? [...symbols, GOLD] : symbols;
  return (
    <div className="panel flex flex-wrap items-center gap-x-6 gap-y-2 px-3 py-2.5 sm:px-4">
      <div className="relative">
        <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex items-center gap-2.5 rounded-lg px-1 py-1 hover:bg-glass/[0.05]">
          <CoinAvatar symbol={symbol} size={30} />
          <span className="text-left"><span className="font-display block text-lg font-bold leading-none">{base(symbol)}<span className="text-mute">/USDT</span></span>
            <span className="text-[11px] text-mute">{isGold(symbol) ? "Gold · Perpetual · USDT-M" : market === "futures" ? "Perpetual · USDT-M" : "Spot"}</span></span>
          <span className="text-mute" aria-hidden="true">▾</span>
        </button>
        {open && (
          <div className="panel absolute left-0 top-full z-40 mt-1 max-h-80 w-64 overflow-y-auto p-1">
            {list.map((s) => {
              const x = tickers[s];
              return (
                <button key={s} onClick={() => { onSymbol(s); setOpen(false); }} className={`flex w-full items-center justify-between gap-2 rounded-lg px-2 py-2 text-sm hover:bg-glass/[0.06] ${s === symbol ? "bg-accent/10" : ""}`}>
                  <span className="flex items-center gap-2"><CoinAvatar symbol={s} size={20} />{base(s)}<span className="text-mute">/USDT</span>{isGold(s) && <span className="rounded bg-accent/15 px-1 text-[11px] font-bold text-accent">GOLD</span>}</span>
                  <span className="num text-right text-xs"><span className="block">{fmtPrice(x?.last)}</span><span className={tone(x?.change_pct)}>{fmtPctRaw(x?.change_pct)}</span></span>
                </button>
              );
            })}
          </div>
        )}
      </div>
      <div><div className={`num text-xl font-semibold ${tone(t?.change_pct)}`}>{fmtPrice(last)}</div>
        <div className="flex items-center gap-1 text-[11px] text-mute">
          <span className={`h-1.5 w-1.5 rounded-full ${st?.status === "live" ? "bg-bull" : st?.status === "polling" ? "bg-warn" : "bg-glass/30"}`} aria-hidden="true" />
          {st?.status === "live" ? "live" : st?.status === "polling" ? "reconnecting" : "last price"}{market === "futures" ? (st?.source === "spot" ? " · spot price (futures unreachable)" : " · futures price") : " · spot price"}
          {st?.status === "live" && st.delay != null && <span className={st.delay < 1500 ? "text-bull" : st.delay < 4000 ? "text-warn" : "text-bear"} title="How old the latest price is when it reaches this device (on Binance's clock)"> · {(Math.max(0, st.delay) / 1000).toFixed(1)} s</span>}
        </div></div>
      <div><div className={`num text-sm ${tone(t?.change_pct)}`}>{fmtPctRaw(t?.change_pct)}</div><div className="text-[11px] text-mute">24h change</div></div>
      <div className="hidden sm:block"><div className="num text-sm">{t?.quote_volume != null ? `${fmtNum(t.quote_volume / 1e6, 1)}M` : "—"}</div><div className="text-[11px] text-mute">24h volume (USDT)</div></div>
      {market === "spot" && <div className="hidden md:block"><div className="num text-sm">{fmtPrice(t?.bid)} / {fmtPrice(t?.ask)}</div><div className="text-[11px] text-mute">bid / ask</div></div>}
      <div className="ml-auto inline-flex rounded-xl border border-glass/10 bg-ink/40 p-1" role="group" aria-label="Market">
        {(["futures", "spot"] as const).map((k) => (
          <button key={k} aria-pressed={market === k} onClick={() => onMarket(k)}
            className={`rounded-lg px-3 py-1.5 text-sm font-semibold ${market === k ? "bg-accent text-ink" : "text-mute hover:text-text"}`}>{k === "futures" ? "Futures" : "Spot"}</button>
        ))}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- the app's call for this coin */
function SignalStrip({ symbol, market }: { symbol: string; market: Mkt }) {
  const v = useApi<any>("/futures?timeframe=4h");
  const [params, setParams] = useSearchParams();
  const r = (v.data?.rows ?? []).find((x: any) => x.symbol === symbol);
  if (isGold(symbol)) return <div className="rounded-xl border border-glass/10 bg-glass/[0.03] px-3 py-2 text-xs text-mute">Gold (XAUT) is for live charts and demo trading. The AI does not make signals for it.</div>;
  if (!r) return null;
  const vd = verdictOf(r, market);
  const p = r.plan;
  const usable = vd.tone !== "wait" && p && (market === "futures" || p.side === "LONG");
  const use = () => {
    const q = new URLSearchParams(params);
    q.set("side", market === "spot" ? "LONG" : p.side); if (market === "futures") q.set("lev", String(p.suggested_leverage));
    q.set("sl", String(p.stop)); q.set("tp", String((p.targets?.[1] ?? p.targets?.[0])?.price)); q.set("limit", String(p.entry));
    setParams(q, { replace: true });
  };
  const cls = vd.tone === "bull" ? "border-bull/40 bg-bull/[0.07]" : vd.tone === "bear" ? "border-bear/40 bg-bear/[0.07]" : "border-glass/10 bg-glass/[0.03]";
  return (
    <div className={`flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border px-3 py-2 text-sm ${cls}`}>
      <span className="text-xs uppercase tracking-wide text-mute">AI call · 4H</span>
      <span className={`font-bold ${vd.tone === "bull" ? "text-bull" : vd.tone === "bear" ? "text-bear" : "text-mute"}`}>{vd.label}</span>
      {usable ? (
        <span className="num text-xs text-mute">entry <span className="text-accent">{fmtPrice(p.entry)}</span> · stop <span className="text-bear">{fmtPrice(p.stop)}</span> · TP1 <span className="text-bull">{fmtPrice(p.targets?.[0]?.price)}</span>{market === "futures" ? ` · ${p.suggested_leverage}x` : ""}</span>
      ) : <span className="text-xs text-mute">no setup right now · models lean {r.lean ?? "neither way"}</span>}
      {usable && <button className="btn ml-auto px-3 py-1 text-xs" onClick={use}>Use this plan</button>}
    </div>
  );
}

/* ---------------------------------------------------------------- chart */
function ChartPanel({ symbol, market, positions, orders, tf, setTf }: { symbol: string; market: Mkt; positions: any[]; orders: any[]; tf: string; setTf: (t: string) => void }) {
  const st = useContext(StreamCtx);
  const candles = st?.candles ?? [];
  const [pro, setPro] = useState(false);
  const lines: PriceLine[] = useMemo(() => {
    const out: PriceLine[] = [];
    for (const p of positions.filter((x) => x.symbol === symbol)) {
      if (market === "futures") {
        const s = p.side > 0 ? "Long" : "Short";
        out.push({ price: p.entry, title: `${s} entry`, color: "#f0b90b" });
        if (p.stop) out.push({ price: p.stop, title: "SL", color: "#f6465d", dashed: true });
        if (p.take) out.push({ price: p.take, title: "TP", color: "#0ecb81", dashed: true });
        out.push({ price: p.liq, title: "Liq.", color: "#f97316", dashed: true });
      } else out.push({ price: p.avg_price, title: "Avg buy", color: "#f0b90b" });
    }
    for (const o of orders.filter((x) => x.symbol === symbol)) {
      const buy = o.side === "BUY" || o.side > 0;
      out.push({ price: o.price, title: `Limit ${market === "futures" ? (buy ? "long" : "short") : buy ? "buy" : "sell"}`, color: buy ? "#0ecb81" : "#f6465d", dashed: true });
    }
    return out;
  }, [positions, orders, symbol, market]);
  return (
    <section className="panel min-h-[360px] p-0">
      <div className="flex items-center justify-between gap-2 border-b border-glass/[0.06] px-2 py-1.5">
        <div className="flex gap-0.5" role="group" aria-label="Chart timeframe">
          {CHART_TFS.map((t) => <button key={t} aria-pressed={tf === t} onClick={() => setTf(t)} className={`rounded-md px-2.5 py-1 text-xs ${tf === t ? "bg-accent/15 font-semibold text-accent" : "text-mute hover:text-text"}`}>{t}</button>)}
        </div>
        <span className="flex items-center gap-2">
          <span className="hidden text-[11px] text-mute xl:inline">{pro ? "TradingView tools; your levels are on the AI chart" : "your entry, SL, TP, liquidation and limit orders are drawn on the chart"}</span>
          <span className="inline-flex rounded-lg border border-glass/10 p-0.5">
            <button className={`rounded-md px-2 py-0.5 text-xs ${!pro ? "bg-accent font-semibold text-ink" : "text-mute"}`} aria-pressed={!pro} onClick={() => setPro(false)}>AI</button>
            <button className={`rounded-md px-2 py-0.5 text-xs ${pro ? "bg-accent font-semibold text-ink" : "text-mute"}`} aria-pressed={pro} onClick={() => setPro(true)}>Pro</button>
          </span>
        </span>
      </div>
      {pro ? <div className="p-1"><TVChart symbol={symbol} market={market} tf={tf} height={380} /></div>
        : st?.error ? <p className="p-4 text-sm text-bear">Chart unavailable: {st.error}</p>
        : candles.length ? <CandleChart candles={candles} lines={lines} liveCandle={st?.live ?? null} height={380} viewKey={`trade|${symbol}|${market}|${tf}`} />
        : <div className="skeleton m-3 h-[340px] rounded-lg" />}
    </section>
  );
}

/* ---------------------------------------------------------------- order book */
function OrderBook({ symbol, market }: { symbol: string; market: Mkt }) {
  const ob = useDepth(symbol, market);
  const tickers = useMktTickers(market);
  const last = useLastPrice(symbol);
  const asks: [number, number][] = (ob?.asks ?? []).slice(0, 9).reverse();
  const bids: [number, number][] = (ob?.bids ?? []).slice(0, 9);
  const max = Math.max(1, ...[...asks, ...bids].map((x) => x[0] * x[1]));
  const row = (x: [number, number], side: "a" | "b") => (
    <div key={`${side}${x[0]}`} className="relative grid grid-cols-2 px-2 py-[3px] text-[11px]">
      <div className={`absolute inset-y-0 right-0 ${side === "a" ? "bg-bear/10" : "bg-bull/10"}`} style={{ width: `${(x[0] * x[1] / max) * 100}%` }} />
      <span className={`num relative ${side === "a" ? "text-bear" : "text-bull"}`}>{fmtPrice(x[0])}</span>
      <span className="num relative text-right text-text/80">{fmtNum(x[1], x[1] < 10 ? 4 : 1)}</span>
    </div>
  );
  return (
    <section className="panel hidden p-0 lg:block">
      <div className="grid grid-cols-2 border-b border-glass/[0.06] px-2 py-2 text-[11px] uppercase tracking-wide text-mute"><span>Price</span><span className="text-right">Amount</span></div>
      {!ob ? <div className="skeleton m-2 h-80 rounded" /> : (
        <>
          {asks.map((x) => row(x, "a"))}
          <div className={`num border-y border-glass/[0.06] px-2 py-1.5 text-base font-semibold ${tone(tickers[symbol]?.change_pct)}`}>{fmtPrice(last)}</div>
          {bids.map((x) => row(x, "b"))}
        </>
      )}
    </section>
  );
}

/* ---------------------------------------------------------------- order form */
function OrderForm({ symbol, market, d, act }: { symbol: string; market: Mkt; d: any; act: (fn: () => Promise<any>, ok: string) => Promise<void> }) {
  const [params] = useSearchParams();
  const px = useLastPrice(symbol);
  const [type, setType] = useState<"limit" | "market">("market");
  const [limit, setLimit] = useState("");
  const [lev, setLev] = useState(5);
  const [amount, setAmount] = useState("");
  const [tpsl, setTpsl] = useState(false);
  const [sl, setSl] = useState(""); const [tp, setTp] = useState("");
  const [spotSide, setSpotSide] = useState<"BUY" | "SELL">("BUY");
  const [busy, setBusy] = useState(false);
  // a plan handed over from Signals / Futures / "Use this plan"
  useEffect(() => {
    const l = params.get("lev"), s = params.get("sl"), t = params.get("tp"), lim = params.get("limit");
    if (l) setLev(Math.max(1, Math.min(50, Number(l))));
    if (s || t) { setTpsl(true); setSl(s ?? ""); setTp(t ?? ""); }
    if (lim) { setType("limit"); setLimit(lim); }
    if (params.get("side") === "LONG") setSpotSide("BUY");
  }, [params.toString()]); // eslint-disable-line react-hooks/exhaustive-deps

  const avail = market === "futures" ? d?.wallet ?? 0 : spotSide === "BUY" ? d?.cash ?? 0 : (d?.positions ?? []).find((p: any) => p.symbol === symbol)?.qty ?? 0;
  const price = type === "limit" ? Number(limit) || px : px;
  const amt = Number(amount) || 0;
  const setPct = (f: number) => setAmount(market === "spot" && spotSide === "SELL" ? String(+(avail * f).toPrecision(6)) : String(Math.floor(avail * f * (market === "futures" ? 0.995 : 0.99) * 100) / 100));
  const pctNow = avail > 0 ? Math.min(100, Math.round((amt / avail) * 100)) : 0;

  const go = async (side: 1 | -1) => {
    setBusy(true);
    const stop = tpsl && Number(sl) ? Number(sl) : null, take = tpsl && Number(tp) ? Number(tp) : null;
    if (market === "futures") {
      const o = { symbol, side, margin: amt, leverage: lev, stop, take };
      const what = `${side > 0 ? "LONG" : "SHORT"} ${base(symbol)} ${lev}x, margin $${fmtNum(amt)}`;
      await (type === "market" ? act(() => PF.open(o), `Opened ${what}.`) : act(() => PF.placeLimit({ ...o, price: Number(limit) }), `Limit order placed: ${what} at ${fmtPrice(Number(limit))}.`));
    } else {
      const s = side > 0 ? "BUY" : "SELL";
      if (type === "market") await act(() => s === "BUY" ? SP.order(symbol, s, null, amt) : SP.order(symbol, s, amt, null), `${s === "BUY" ? "Bought" : "Sold"} ${base(symbol)} at the market price.`);
      else await act(() => SP.placeLimit(symbol, s, Number(limit), s === "BUY" ? amt / Number(limit) : amt), `Limit ${s.toLowerCase()} placed at ${fmtPrice(Number(limit))}.`);
    }
    setBusy(false);
  };

  const notional = market === "futures" ? amt * lev : spotSide === "BUY" ? amt : amt * (price ?? 0);
  const estLiq = (side: number) => (price && market === "futures" ? PF.liqPrice(price, side, lev) : null);

  return (
    <section className="panel p-3">
      {market === "futures" && (
        <div className="mb-3 flex items-center gap-2">
          <span className="rounded-md border border-glass/10 px-2 py-1 text-xs">Isolated</span>
          <ModeToggle d={d} act={act} />
          <label className="ml-auto flex items-center gap-1 text-xs text-mute">Leverage
            <select className="input h-8 w-[72px] py-0 text-sm font-semibold text-accent" value={lev} onChange={(e) => setLev(Number(e.target.value))} aria-label="Leverage">
              {[...new Set([...LEVS, lev])].sort((a, b) => a - b).map((l) => <option key={l} value={l}>{l}x</option>)}
            </select>
          </label>
        </div>
      )}
      {market === "spot" && (
        <div className="mb-3 grid grid-cols-2 gap-1 rounded-xl bg-ink/40 p-1">
          {(["BUY", "SELL"] as const).map((s) => <button key={s} aria-pressed={spotSide === s} onClick={() => { setSpotSide(s); setAmount(""); }} className={`rounded-lg py-1.5 text-sm font-semibold ${spotSide === s ? (s === "BUY" ? "bg-bull text-ink" : "bg-bear text-white") : "text-mute"}`}>{s === "BUY" ? "Buy" : "Sell"}</button>)}
        </div>
      )}
      <div className="mb-3 flex gap-4 border-b border-glass/[0.06] text-sm" role="tablist">
        {(["limit", "market"] as const).map((k) => <button key={k} role="tab" aria-selected={type === k} onClick={() => { setType(k); if (k === "limit" && !limit && px) setLimit(String(px)); }} className={`-mb-px border-b-2 pb-2 capitalize ${type === k ? "border-accent font-semibold" : "border-transparent text-mute"}`}>{k}</button>)}
      </div>
      <div className="space-y-2.5">
        <div className="flex justify-between text-xs text-mute"><span>Available</span><span className="num text-text">{market === "spot" && spotSide === "SELL" ? `${fmtNum(avail, 6)} ${base(symbol)}` : `${fmtNum(avail)} USDT`}</span></div>
        {type === "limit" ? (
          <label className="flex items-center rounded-lg border border-glass/10 bg-ink/40 px-3"><span className="w-16 text-xs text-mute">Price</span>
            <input className="num min-w-0 flex-1 bg-transparent py-2 text-right outline-none" inputMode="decimal" value={limit} onChange={(e) => setLimit(e.target.value)} aria-label="Limit price" />
            <button className="ml-2 text-xs text-accent" onClick={() => px && setLimit(String(px))}>Last</button><span className="ml-2 text-xs text-mute">USDT</span></label>
        ) : <div className="flex items-center rounded-lg border border-glass/10 bg-ink/20 px-3 py-2 text-sm text-mute"><span className="w-16 text-xs">Price</span><span className="flex-1 text-right">Market price</span></div>}
        <label className="flex items-center rounded-lg border border-glass/10 bg-ink/40 px-3"><span className="w-16 text-xs text-mute">{market === "futures" ? "Margin" : spotSide === "BUY" ? "Total" : "Amount"}</span>
          <input className="num min-w-0 flex-1 bg-transparent py-2 text-right outline-none" inputMode="decimal" placeholder="0" value={amount} onChange={(e) => setAmount(e.target.value)} aria-label="Order size" />
          <span className="ml-2 text-xs text-mute">{market === "spot" && spotSide === "SELL" ? base(symbol) : "USDT"}</span></label>
        <div>
          <input type="range" min={0} max={100} step={1} value={pctNow} onChange={(e) => setPct(Number(e.target.value) / 100)} className="w-full accent-[rgb(var(--accent))]" aria-label="Size as % of available" />
          <div className="mt-1 grid grid-cols-4 gap-1">{[0.25, 0.5, 0.75, 1].map((f) => <button key={f} onClick={() => setPct(f)} className="rounded-md border border-glass/10 py-1 text-[11px] text-mute hover:border-accent/50 hover:text-text">{f * 100}%</button>)}</div>
        </div>
        {market === "futures" && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={tpsl} onChange={(e) => setTpsl(e.target.checked)} />TP / SL</label>}
        {market === "futures" && tpsl && (
          <div className="grid grid-cols-2 gap-2">
            <label className="text-[11px] text-mute">Take-profit<input className="input num mt-0.5 h-9" inputMode="decimal" value={tp} onChange={(e) => setTp(e.target.value)} placeholder="price" /></label>
            <label className="text-[11px] text-mute">Stop-loss<input className="input num mt-0.5 h-9" inputMode="decimal" value={sl} onChange={(e) => setSl(e.target.value)} placeholder="price" /></label>
          </div>
        )}
        <div className="space-y-1 rounded-lg bg-ink/30 px-3 py-2 text-xs">
          <div className="flex justify-between"><span className="text-mute">{market === "futures" ? "Position size" : "Order value"}</span><span className="num">{fmtNum(notional)} USDT</span></div>
          {market === "futures" && <div className="flex justify-between"><span className="text-mute">Est. liq. long / short</span><span className="num"><span className="text-bull">{fmtPrice(estLiq(1))}</span> / <span className="text-bear">{fmtPrice(estLiq(-1))}</span></span></div>}
          <div className="flex justify-between"><span className="text-mute">Est. fee</span><span className="num">{fmtNum(notional * (market === "futures" ? (type === "limit" ? 0.0002 : 0.0005) : 0.001), 3)} USDT</span></div>
        </div>
        {market === "futures" ? (
          <div className="grid grid-cols-2 gap-2">
            <button disabled={busy || !amt} onClick={() => go(1)} className="rounded-xl bg-bull py-3 text-sm font-bold text-ink transition hover:brightness-110 disabled:opacity-50">Buy / Long</button>
            <button disabled={busy || !amt} onClick={() => go(-1)} className="rounded-xl bg-bear py-3 text-sm font-bold text-white transition hover:brightness-110 disabled:opacity-50">Sell / Short</button>
          </div>
        ) : (
          <button disabled={busy || !amt} onClick={() => go(spotSide === "BUY" ? 1 : -1)} className={`w-full rounded-xl py-3 text-sm font-bold transition hover:brightness-110 disabled:opacity-50 ${spotSide === "BUY" ? "bg-bull text-ink" : "bg-bear text-white"}`}>{spotSide === "BUY" ? "Buy" : "Sell"} {base(symbol)}</button>
        )}
      </div>
    </section>
  );
}

function ModeToggle({ d, act }: { d: any; act: (fn: () => Promise<any>, ok: string) => Promise<void> }) {
  const mode = d?.mode ?? "oneway";
  return (
    <button className="rounded-md border border-glass/10 px-2 py-1 text-xs hover:border-accent/50" title="One-way: one direction per coin. Hedge: hold a long and a short on the same coin."
      onClick={() => act(() => PF.setMode(mode === "hedge" ? "oneway" : "hedge"), mode === "hedge" ? "One-way mode on." : "Hedge mode on: you can hold a long and a short on the same coin.")}>
      {mode === "hedge" ? "Hedge" : "One-way"}
    </button>
  );
}

/* ---------------------------------------------------------------- bottom tabs */
type Act = (fn: () => Promise<any>, ok: string) => Promise<void>;
const sideName = (side: number) => (side > 0 ? "Long" : "Short");
const signed = (v: number | null | undefined, digits = 2) => (isNum(v) ? `${v >= 0 ? "+" : ""}${fmtNum(v, digits)}` : "—");

/** Pair name in a list: switches the chart to that coin (does not open the row's details). */
function PairButton({ symbol, onPair, className = "" }: { symbol: string; onPair: (s: string) => void; className?: string }) {
  return (
    <button type="button" className={`rounded-sm font-semibold underline-offset-2 hover:text-accent hover:underline focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent/60 ${className}`}
      title={`Show ${symbol} on the chart`} onClick={(e) => { e.stopPropagation(); onPair(symbol); }}>{symbol}</button>
  );
}

/** Props of a clickable card row: opens the details panel by mouse, Enter or Space. */
const openable = (open: () => void, label: string) => ({
  role: "button", tabIndex: 0, "aria-label": label, onClick: open,
  onKeyDown: (e: React.KeyboardEvent) => { if ((e.key === "Enter" || e.key === " ") && e.target === e.currentTarget) { e.preventDefault(); open(); } },
});

function FutPositions({ rows, act, hedges, onOpen, onPair }: { rows: any[]; act: Act; hedges?: any[]; onOpen: (key: string) => void; onPair: (s: string) => void }) {
  const [edit, setEdit] = useState<string | null>(null);
  if (!rows.length) return <p className="py-6 text-center text-sm text-mute">No open positions. Use the order form, or tap “Use this plan” on the AI call.</p>;
  return (
    <div className="space-y-2">
      {hedges?.map((h: any) => <div key={h.symbol} className="rounded-lg border border-accent/30 bg-accent/[0.06] px-3 py-2 text-xs">{h.symbol} hedged · combined P&L <span className={tone(h.pnl)}>${fmtNum(h.pnl)}</span> · net {h.net >= 0 ? "long" : "short"} ${fmtNum(Math.abs(h.net), 0)}</div>)}
      {rows.map((p) => <FutPositionRow key={p.key} p={p} act={act} editing={edit === p.key} setEdit={setEdit} onOpen={onOpen} onPair={onPair} />)}
      <p className="text-[11px] text-mute">Tap a position for all its details. Tap the pair name to show it on the chart.</p>
    </div>
  );
}

/** What a position row shows, rounded as displayed: the row re-renders only when one of these changes. */
const futSig = (p: any) => [p.key, p.symbol, p.side, fmtNum(p.leverage, 1), fmtNum(p.upnl), fmtPctRaw(p.roe_pct, 1), fmtNum(p.notional, 0), fmtPrice(p.entry),
  fmtPrice(p.mark), fmtPrice(p.liq), fmtNum(p.margin), p.take, p.stop, fmtNum(p.funding ?? 0, 3), p.auto ? 1 : 0].join("|");

const FutPositionRow = memo(function FutPositionRow({ p, act, editing, setEdit, onOpen, onPair }: { p: any; act: Act; editing: boolean; setEdit: (k: string | null) => void; onOpen: (key: string) => void; onPair: (s: string) => void }) {
  const [sl, setSl] = useState(""); const [tp, setTp] = useState("");
  return (
    <div className="cursor-pointer rounded-xl border border-glass/[0.08] p-3 transition-colors hover:border-accent/30 focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent/60" {...openable(() => onOpen(p.key), `${p.symbol} ${sideName(p.side)} position: show details`)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={`h-8 w-1 rounded-full ${p.side > 0 ? "bg-bull" : "bg-bear"}`} />
          <PairButton symbol={p.symbol} onPair={onPair} />
          <span className={`rounded px-1.5 py-0.5 text-[11px] font-bold ${p.side > 0 ? "bg-bull/15 text-bull" : "bg-bear/15 text-bear"}`}>{sideName(p.side)} {fmtNum(p.leverage, 1)}x</span>
          {p.auto && <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[11px] font-bold text-accent" title="Opened automatically from an app signal">AUTO</span>}
        </div>
        <div className="text-right"><div className={`num font-semibold ${tone(p.upnl)}`}>{p.upnl != null ? `${signed(p.upnl)} USDT` : "—"}</div><div className={`num text-xs ${tone(p.upnl)}`}>{fmtPctRaw(p.roe_pct, 1)} ROE</div></div>
      </div>
      <dl className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-4 xl:grid-cols-8">
        {([["Size", `${fmtNum(p.notional, 0)} USDT`], ["Entry", fmtPrice(p.entry)], ["Mark", fmtPrice(p.mark)], ["Liq. price", fmtPrice(p.liq)], ["Margin", `${fmtNum(p.margin)} USDT`],
          ["TP", p.take ? fmtPrice(p.take) : "—"], ["SL", p.stop ? fmtPrice(p.stop) : "—"], ["Funding", `${fmtNum(-(p.funding ?? 0), 3)} USDT`]] as const).map(([k, v]) => (
          <div key={k} className="min-w-0"><dt className="text-[11px] text-mute">{k}</dt><dd className={`num mt-0.5 truncate text-[13px] font-medium ${k === "Liq. price" ? "text-warn" : k === "TP" ? "text-bull" : k === "SL" ? "text-bear" : ""}`}>{v}</dd></div>
        ))}
      </dl>
      {editing && (
        <div className="mt-2 grid grid-cols-[1fr_1fr_auto] gap-2" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
          <input className="input num h-9" placeholder="Take-profit" inputMode="decimal" value={tp} onChange={(e) => setTp(e.target.value)} aria-label="Take-profit" />
          <input className="input num h-9" placeholder="Stop-loss" inputMode="decimal" value={sl} onChange={(e) => setSl(e.target.value)} aria-label="Stop-loss" />
          <button className="btn btn-primary h-9 px-3 text-xs" onClick={() => act(async () => { await PF.setOrders(p.key, Number(sl) || null, Number(tp) || null); setEdit(null); }, "TP / SL updated.")}>Save</button>
        </div>
      )}
      <div className="mt-2 flex flex-wrap justify-end gap-2" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
        <button className="btn px-3 py-1 text-xs" onClick={() => { setEdit(editing ? null : p.key); setSl(p.stop ? String(p.stop) : ""); setTp(p.take ? String(p.take) : ""); }}>TP / SL</button>
        <button className="btn px-3 py-1 text-xs" onClick={() => act(() => PF.close(p.key, 0.5), `Closed half of ${p.symbol}.`)}>Close 50%</button>
        <button className="btn border-bear/40 px-3 py-1 text-xs text-bear" onClick={() => act(() => PF.close(p.key, 1), `Closed ${p.symbol} at market.`)}>Close all</button>
      </div>
    </div>
  );
}, (a, b) => a.editing === b.editing && a.act === b.act && a.onOpen === b.onOpen && a.onPair === b.onPair && futSig(a.p) === futSig(b.p));

function SpotHoldings({ rows, act, onOpen, onPair }: { rows: any[]; act: Act; onOpen: (symbol: string) => void; onPair: (s: string) => void }) {
  if (!rows.length) return <p className="py-6 text-center text-sm text-mute">No coins held yet. Buy from the order form.</p>;
  return (
    <div className="space-y-2">
      {rows.map((p) => <SpotHoldingRow key={p.symbol} p={p} act={act} onOpen={onOpen} onPair={onPair} />)}
      <p className="text-[11px] text-mute">Tap a coin for its details. Tap the pair name to show it on the chart.</p>
    </div>
  );
}

const spotSig = (p: any) => [p.symbol, fmtNum(p.qty, 6), fmtPrice(p.avg_price), fmtNum(p.market_value), fmtNum(p.unrealized_pnl), fmtPrice(p.mark)].join("|");
const SpotHoldingRow = memo(function SpotHoldingRow({ p, act, onOpen, onPair }: { p: any; act: Act; onOpen: (symbol: string) => void; onPair: (s: string) => void }) {
  const pct = p.mark && p.avg_price ? (p.mark / p.avg_price - 1) * 100 : null;
  return (
    <div className="flex cursor-pointer flex-wrap items-center justify-between gap-3 rounded-xl border border-glass/[0.08] p-3 transition-colors hover:border-accent/30 focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent/60" {...openable(() => onOpen(p.symbol), `${p.symbol} holding: show details`)}>
      <div className="flex items-center gap-2.5"><CoinAvatar symbol={p.symbol} size={28} /><div><PairButton symbol={p.symbol} onPair={onPair} /><div className="num text-xs text-mute">{fmtNum(p.qty, 6)} · avg {fmtPrice(p.avg_price)}</div></div></div>
      <div className="text-right"><div className="num">{fmtNum(p.market_value)} USDT</div><div className={`num text-xs ${tone(p.unrealized_pnl)}`}>{p.unrealized_pnl != null ? `${signed(p.unrealized_pnl)} (${fmtPctRaw(pct, 1)})` : "—"}</div></div>
      <button className="btn px-3 py-1 text-xs" onClick={(e) => { e.stopPropagation(); act(() => SP.order(p.symbol, "SELL", p.qty, null), `Sold all ${base(p.symbol)}.`); }}>Sell all</button>
    </div>
  );
}, (a, b) => a.act === b.act && a.onOpen === b.onOpen && a.onPair === b.onPair && spotSig(a.p) === spotSig(b.p));

function Orders({ rows, market, act, onPair }: { rows: any[]; market: Mkt; act: Act; onPair: (s: string) => void }) {
  if (!rows.length) return <p className="py-6 text-center text-sm text-mute">No open orders. Choose “Limit” in the order form to buy or sell at your price.</p>;
  return (
    <div className="overflow-x-auto"><table className="grid-table">
      <thead><tr><th>Time</th><th>Pair</th><th>Type</th><th>Side</th><th className="text-right">Price</th><th className="text-right">{market === "futures" ? "Margin" : "Amount"}</th><th className="text-right">Action</th></tr></thead>
      <tbody>{rows.map((o) => {
        const buy = o.side === "BUY" || o.side > 0;
        return (
          <tr key={o.id}><td className="text-mute">{fmtTime(o.created_at)}</td><td className="font-medium"><PairButton symbol={o.symbol} onPair={onPair} className="font-medium" />{o.auto && <span className="ml-1 rounded bg-accent/15 px-1 text-[11px] font-bold text-accent">AUTO</span>}</td><td>Limit{market === "futures" ? ` · ${o.leverage}x` : ""}</td>
            <td className={buy ? "text-bull" : "text-bear"}>{market === "futures" ? (buy ? "Long" : "Short") : buy ? "Buy" : "Sell"}</td>
            <td className="num text-right">{fmtPrice(o.price)}</td><td className="num text-right">{market === "futures" ? `${fmtNum(o.margin)} USDT` : fmtNum(o.qty, 6)}</td>
            <td className="text-right"><button className="btn px-2 py-0.5 text-xs" onClick={() => act(() => (market === "futures" ? PF.cancelOrder(o.id) : SP.cancelOrder(o.id)), "Order cancelled; the funds are back.")}>Cancel</button></td></tr>
        );
      })}</tbody>
    </table></div>
  );
}

function History({ rows, market, onPair }: { rows: any[]; market: Mkt; onPair: (s: string) => void }) {
  if (!rows.length) return <p className="py-6 text-center text-sm text-mute">No trades yet.</p>;
  return (
    <div className="max-h-96 overflow-auto"><table className="grid-table">
      <thead><tr><th>Time</th><th>Pair</th><th>Action</th><th className="text-right">Price</th><th className="text-right">Qty</th><th className="text-right">Fee</th><th className="text-right">Realized P&L</th></tr></thead>
      <tbody>{rows.slice(0, 100).map((t) => {
        const label = market === "futures" ? `${t.type === "OPEN" ? "Open" : "Close"} ${t.side > 0 ? "long" : "short"}${t.reason && t.reason !== "manual" ? ` · ${t.reason}` : ""}${t.order_type === "LIMIT" ? " · limit" : ""}` : `${t.side === "BUY" ? "Buy" : "Sell"}${t.order_type === "LIMIT" ? " · limit" : ""}`;
        const pnl = t.realized_pnl;
        return (
          <tr key={t.id}><td className="text-mute">{fmtTime(t.created_at)}</td><td><PairButton symbol={t.symbol} onPair={onPair} className="font-medium" /></td><td className={(market === "futures" ? t.side > 0 : t.side === "BUY") ? "text-bull" : "text-bear"}>{label}</td>
            <td className="num text-right">{fmtPrice(t.price)}</td><td className="num text-right">{fmtNum(t.qty, 6)}</td><td className="num text-right text-mute">{fmtNum(t.fee, 3)}</td>
            <td className={`num text-right ${tone(pnl)}`}>{isNum(pnl) && (market === "spot" ? t.side === "SELL" : t.type === "CLOSE") ? `${pnl >= 0 ? "+" : ""}${fmtNum(pnl)}` : "—"}</td></tr>
        );
      })}</tbody>
    </table></div>
  );
}

function Assets({ d, market, act }: { d: any; market: Mkt; act: (fn: () => Promise<any>, ok: string) => Promise<void> }) {
  const [bal, setBal] = useState("10000");
  const nav = useNavigate();
  const items: [string, string, string?][] = market === "futures" ? [
    ["Equity", `${fmtNum(d.equity)} USDT`, tone(d.return_pct)], ["Return", fmtPctRaw(d.return_pct), tone(d.return_pct)], ["Available", `${fmtNum(d.wallet)} USDT`],
    ["In orders", `${fmtNum(d.reserved ?? 0)} USDT`], ["Margin in use", `${fmtNum(d.margin_used)} USDT`], ["Unrealized P&L", `${fmtNum(d.unrealized_pnl)} USDT`, tone(d.unrealized_pnl)],
    ["Realized P&L", `${fmtNum(d.realized_pnl)} USDT`, tone(d.realized_pnl)], ["Fees / funding", `${fmtNum(d.fees)} / ${fmtNum(d.funding)}`], ["Win rate", d.win_rate != null ? `${Math.round(d.win_rate * 100)}% of ${d.closed}` : "—"], ["Liquidations", String(d.liquidations ?? 0)],
  ] : [
    ["Equity", `${fmtNum(d.equity)} USDT`, tone(d.return_pct)], ["Return", fmtPctRaw(d.return_pct), tone(d.return_pct)], ["Cash", `${fmtNum(d.cash)} USDT`],
    ["In orders", `${fmtNum(d.reserved ?? 0)} USDT`], ["Coins value", `${fmtNum(d.market_value)} USDT`], ["Unrealized P&L", `${fmtNum(d.unrealized_pnl)} USDT`, tone(d.unrealized_pnl)],
    ["Realized P&L", `${fmtNum(d.realized_pnl)} USDT`, tone(d.realized_pnl)], ["Fees", `${fmtNum(d.fees)} USDT`], ["Trades", String(d.trade_count ?? 0)],
    ["vs buy & hold BTC", d.benchmark?.excess_pct != null ? fmtPctRaw(d.benchmark.excess_pct) : "—", tone(d.benchmark?.excess_pct)],
  ];
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {items.map(([k, v, c]) => <div key={k} className="rounded-xl border border-glass/[0.08] bg-ink/30 px-3 py-2"><dt className="text-[11px] uppercase tracking-wide text-mute">{k}</dt><dd className={`num mt-0.5 font-semibold ${c ?? ""}`}>{v}</dd></div>)}
      </dl>
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-mute">Starting balance (USDT)<input className="input num mt-1 w-40" inputMode="decimal" value={bal} onChange={(e) => setBal(e.target.value)} /></label>
        <button className="btn" onClick={() => { if (window.confirm("Start a fresh practice account? Current positions and orders are cleared.")) act(() => (market === "futures" ? PF.reset(Number(bal)) : SP.reset(Number(bal))), "New practice account started."); }}>Reset account</button>
        <button className="btn ml-auto" onClick={() => nav("/bots")}>Compare with the demo bots →</button>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- position details (side panel on a computer, bottom sheet on a phone) */
function duration(ms: number): string {
  const m = Math.max(0, Math.floor(ms / 60_000));
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h} h ${m % 60} min`;
  return `${Math.floor(h / 24)} d ${h % 24} h`;
}

function PositionDrawer({ market, d, id, act, onPair, onClose }: { market: Mkt; d: any; id: string; act: Act; onPair: (s: string) => void; onClose: () => void }) {
  const ref = useFocusTrap(true, onClose);
  const p = market === "futures" ? (d.positions ?? []).find((x: any) => x.key === id) : (d.positions ?? []).find((x: any) => x.symbol === id);
  const [edit, setEdit] = useState(false);
  const [sl, setSl] = useState(""); const [tp, setTp] = useState("");
  const [, tick] = useState(0);
  useEffect(() => { const t = window.setInterval(() => tick((n) => n + 1), 30_000); return () => window.clearInterval(t); }, []);   // open-for counter
  const title = p ? `${p.symbol} ${market === "futures" ? sideName(p.side) : "holding"}` : "Position closed";
  const rows: [string, React.ReactNode, string?][] = [];
  if (p && market === "futures") {
    const sig = p.signal;
    rows.push(
      ["Pair", <PairButton symbol={p.symbol} onPair={(s) => { onPair(s); onClose(); }} />],
      ["Side", sideName(p.side), p.side > 0 ? "text-bull" : "text-bear"],
      ["Leverage", `${fmtNum(p.leverage, 1)}x`],
      ["Margin mode", `Isolated · ${d.mode === "hedge" ? "Hedge" : "One-way"} mode`],
      ["Size", <>{fmtNum(p.qty, 6)} {base(p.symbol)}<span className="block text-[11px] text-mute">{fmtNum(p.notional, 2)} USDT notional</span></>],
      ["Entry price", fmtPrice(p.entry)],
      ["Mark price", <>{fmtPrice(p.mark)}<span className="block text-[11px] text-mute">live futures price</span></>],
      ["Unrealised P&L", <>{p.upnl != null ? `${signed(p.upnl)} USDT` : "—"}<span className="block text-[11px]">{fmtPctRaw(p.roe_pct, 2)} ROI on margin</span></>, tone(p.upnl)],
      ["Margin", `${fmtNum(p.margin)} USDT`],
      ["Liquidation price", fmtPrice(p.liq), "text-warn"],
      ["Take-profit", p.take ? fmtPrice(p.take) : "not set", p.take ? "text-bull" : "text-mute"],
      ["Stop-loss", p.stop ? fmtPrice(p.stop) : "not set", p.stop ? "text-bear" : "text-mute"],
      ["Fees paid", `${fmtNum(p.fees ?? 0, 3)} USDT`],
      ["Funding", `${fmtNum(-(p.funding ?? 0), 3)} USDT`, tone(-(p.funding ?? 0))],
      ["Opened", <>{fmtTime(p.opened_at)}<span className="block text-[11px] text-mute">open for {duration(Date.now() - p.opened_at)}</span></>],
      ["Origin", p.auto
        ? <>Auto-trade{sig ? <> from the <b>{sig.timeframe?.toUpperCase()}</b> {sig.side === "SHORT" ? "short" : "long"} signal{sig.grade ? ` (grade ${sig.grade})` : ""}{sig.at ? `, ${fmtTime(sig.at)}` : ""}</> : " from an app signal"}
            <span className="mt-0.5 flex flex-wrap justify-end gap-x-3 text-[11px]">
              <Link className="text-accent hover:underline" to={`/signals?market=futures&symbol=${encodeURIComponent(p.symbol)}${sig?.timeframe ? `&timeframe=${sig.timeframe}` : ""}`}>Open signal</Link>
              <Link className="text-accent hover:underline" to={`/results?tab=log&coin=${encodeURIComponent(base(p.symbol))}${sig?.timeframe ? `&tf=${sig.timeframe}` : ""}`}>Signal log</Link>
            </span></>
        : "Manual (your order)"],
    );
  } else if (p) {
    const pct = p.mark && p.avg_price ? (p.mark / p.avg_price - 1) * 100 : null;
    rows.push(
      ["Pair", <PairButton symbol={p.symbol} onPair={(s) => { onPair(s); onClose(); }} />],
      ["Market", "Spot · no leverage"],
      ["Quantity", `${fmtNum(p.qty, 6)} ${base(p.symbol)}`],
      ["Average buy price", fmtPrice(p.avg_price)],
      ["Live price", fmtPrice(p.mark)],
      ["Value", `${fmtNum(p.market_value)} USDT`],
      ["Unrealised P&L", <>{p.unrealized_pnl != null ? `${signed(p.unrealized_pnl)} USDT` : "—"}<span className="block text-[11px]">{fmtPctRaw(pct, 2)}</span></>, tone(p.unrealized_pnl)],
      ["Cost", `${fmtNum(p.qty * p.avg_price)} USDT`],
      ...(p.fees != null ? [["Buy fees paid", `${fmtNum(p.fees, 3)} USDT`] as [string, string]] : []),
      ...(p.opened_at ? [["First bought", <>{fmtTime(p.opened_at)}<span className="block text-[11px] text-mute">held for {duration(Date.now() - p.opened_at)}</span></>] as [string, React.ReactNode]] : []),
      ["Origin", "Manual (your order)"],
    );
  }
  // portal: the page wrapper animates with a transform, which would trap a fixed overlay under the header / bottom bar
  return createPortal(
    <div className="fixed inset-0 z-[60]" onClick={onClose}>
      <div className="absolute inset-0 bg-ink/60 backdrop-blur-sm" />
      <div ref={ref} role="dialog" aria-modal="true" aria-label={`${title}: details`} onClick={(e) => e.stopPropagation()}
        className="absolute inset-x-0 bottom-0 max-h-[88dvh] sm:inset-x-auto sm:bottom-0 sm:right-0 sm:top-0 sm:max-h-none sm:w-[420px]">
        <div className="panel animate-in flex h-full max-h-[88dvh] flex-col rounded-b-none p-0 sm:max-h-none sm:rounded-none sm:rounded-l-2xl">
          <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-glass/20 sm:hidden" aria-hidden="true" />
          <div className="flex items-center justify-between gap-2 border-b border-glass/[0.06] px-4 py-3">
            <div className="flex min-w-0 items-center gap-2.5">
              {p && <CoinAvatar symbol={p.symbol} size={28} />}
              <div className="min-w-0"><h2 className="truncate font-display text-base font-bold">{title}</h2>
                <p className="text-[11px] text-mute">{market === "futures" ? "Perpetual · USDT-M · practice account" : "Spot · practice account"}</p></div>
            </div>
            <button className="btn h-9 w-9 shrink-0 p-0" aria-label="Close details" onClick={onClose}>✕</button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-2 pb-[calc(1rem+env(safe-area-inset-bottom))]">
            {!p ? <p className="py-8 text-center text-sm text-mute">This position is no longer open. Its result is in Order history.</p> : (
              <>
                <dl className="divide-y divide-glass/[0.06] text-sm">
                  {rows.map(([k, v, c]) => (
                    <div key={k} className="flex items-start justify-between gap-4 py-2">
                      <dt className="shrink-0 text-mute">{k}</dt><dd className={`num min-w-0 text-right font-medium ${c ?? ""}`}>{v}</dd>
                    </div>
                  ))}
                </dl>
                {market === "futures" && edit && (
                  <div className="mt-3 grid grid-cols-[1fr_1fr_auto] gap-2">
                    <input className="input num h-9" placeholder="Take-profit" inputMode="decimal" value={tp} onChange={(e) => setTp(e.target.value)} aria-label="Take-profit" />
                    <input className="input num h-9" placeholder="Stop-loss" inputMode="decimal" value={sl} onChange={(e) => setSl(e.target.value)} aria-label="Stop-loss" />
                    <button className="btn btn-primary h-9 px-3 text-xs" onClick={() => act(async () => { await PF.setOrders(p.key, Number(sl) || null, Number(tp) || null); setEdit(false); }, "TP / SL updated.")}>Save</button>
                  </div>
                )}
                <div className="mt-3 flex flex-wrap justify-end gap-2">
                  {market === "futures" ? (<>
                    <button className="btn px-3 py-1.5 text-xs" onClick={() => { setEdit((v) => !v); setSl(p.stop ? String(p.stop) : ""); setTp(p.take ? String(p.take) : ""); }}>Edit TP / SL</button>
                    <button className="btn px-3 py-1.5 text-xs" onClick={() => act(() => PF.close(p.key, 0.5), `Closed half of ${p.symbol}.`)}>Close 50%</button>
                    <button className="btn border-bear/40 px-3 py-1.5 text-xs text-bear" onClick={() => act(() => PF.close(p.key, 1), `Closed ${p.symbol} at market.`)}>Close all</button>
                  </>) : (
                    <button className="btn px-3 py-1.5 text-xs" onClick={() => act(() => SP.order(p.symbol, "SELL", p.qty, null), `Sold all ${base(p.symbol)}.`)}>Sell all</button>
                  )}
                </div>
                <p className="mt-3 text-[11px] text-mute">{market === "futures" ? "Virtual money only. P&L follows the live price; fees and funding are already taken from the margin and wallet." : "Virtual money only. P&L follows the live spot price; the selling fee is paid when you sell."}</p>
              </>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
