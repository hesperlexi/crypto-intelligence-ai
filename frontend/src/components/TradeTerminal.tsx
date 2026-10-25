// Exchange-style paper trading (Binance / MEXC layout): pair bar, live candle chart with your levels,
// order book, order form (limit / market, leverage, size %, TP/SL) and positions / orders / history / assets.
// Virtual money only: nothing is ever sent to an exchange.
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import CandleChart, { Candle, PriceLine } from "./CandleChart";
import { useSymbols } from "./Pickers";
import { CoinAvatar } from "./Polish";
import { verdictOf } from "./TradeCall";
import { useApi } from "../lib/api";
import { klines, orderbook } from "../lib/binance";
import { base, fmtNum, fmtPctRaw, fmtPrice, fmtTime, isNum, tone } from "../lib/format";
import { useLive } from "../lib/live";
import * as SP from "../lib/paper";
import * as PF from "../lib/paperFutures";

type Mkt = "spot" | "futures";
const CHART_TFS = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;
const LEVS = [1, 2, 3, 5, 10, 20, 50];

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
  const act = async (fn: () => Promise<any>, ok: string) => {
    try { await fn(); setMsg({ ok: true, text: ok }); } catch (e: any) { setMsg({ ok: false, text: e.message }); }
  };
  const positions: any[] = d?.positions ?? [];
  const orders: any[] = d?.orders ?? [];

  return (
    <div className="space-y-3">
      <PairBar symbol={symbol} symbols={symbols} market={market} onSymbol={(s) => setQ({ symbol: s })} onMarket={(m) => setQ({ market: m, symbol })} />
      <SignalStrip symbol={symbol} market={market} />
      {msg && <div role="status" className={`rounded-lg border px-3 py-2 text-sm ${msg.ok ? "border-bull/40 bg-bull/10 text-bull" : "border-bear/40 bg-bear/10 text-bear"}`}>{msg.text}</div>}
      {err && <div className="rounded-lg border border-bear/40 bg-bear/10 px-3 py-2 text-sm text-bear">{err}</div>}

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_220px_320px]">
        <ChartPanel symbol={symbol} market={market} positions={positions} orders={orders} />
        <OrderBook symbol={symbol} />
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
            tab === "positions" ? (market === "futures" ? <FutPositions rows={positions} act={act} hedges={d.hedges} /> : <SpotHoldings rows={positions} act={act} />) :
            tab === "orders" ? <Orders rows={orders} market={market} act={act} /> :
            tab === "history" ? <History rows={d.trades ?? []} market={market} /> :
            <Assets d={d} market={market} act={act} />}
        </div>
      </section>
      <p className="text-xs text-mute">Practice account with virtual USDT. Market orders fill at the live price plus a small spread and slippage; limit orders fill when the price reaches them (checked on every 15-minute candle, also while the app is closed). Fees: spot 0.1%, futures 0.05% market / 0.02% limit.</p>
    </div>
  );
}

/* ---------------------------------------------------------------- pair bar */
function PairBar({ symbol, symbols, market, onSymbol, onMarket }: { symbol: string; symbols: string[]; market: Mkt; onSymbol: (s: string) => void; onMarket: (m: Mkt) => void }) {
  const { tickers } = useLive();
  const t = tickers[symbol];
  const [open, setOpen] = useState(false);
  return (
    <div className="panel flex flex-wrap items-center gap-x-6 gap-y-2 px-3 py-2.5 sm:px-4">
      <div className="relative">
        <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex items-center gap-2.5 rounded-lg px-1 py-1 hover:bg-glass/[0.05]">
          <CoinAvatar symbol={symbol} size={30} />
          <span className="text-left"><span className="font-display block text-lg font-bold leading-none">{base(symbol)}<span className="text-mute">/USDT</span></span>
            <span className="text-[11px] text-mute">{market === "futures" ? "Perpetual · USDT-M" : "Spot"}</span></span>
          <span className="text-mute" aria-hidden="true">▾</span>
        </button>
        {open && (
          <div className="panel absolute left-0 top-full z-40 mt-1 max-h-80 w-64 overflow-y-auto p-1">
            {symbols.map((s) => {
              const x = tickers[s];
              return (
                <button key={s} onClick={() => { onSymbol(s); setOpen(false); }} className={`flex w-full items-center justify-between gap-2 rounded-lg px-2 py-2 text-sm hover:bg-glass/[0.06] ${s === symbol ? "bg-accent/10" : ""}`}>
                  <span className="flex items-center gap-2"><CoinAvatar symbol={s} size={20} />{base(s)}<span className="text-mute">/USDT</span></span>
                  <span className="num text-right text-xs"><span className="block">{fmtPrice(x?.last)}</span><span className={tone(x?.change_pct)}>{fmtPctRaw(x?.change_pct)}</span></span>
                </button>
              );
            })}
          </div>
        )}
      </div>
      <div><div className={`num text-xl font-semibold ${tone(t?.change_pct)}`}>{fmtPrice(t?.last)}</div><div className="text-[11px] text-mute">last price</div></div>
      <div><div className={`num text-sm ${tone(t?.change_pct)}`}>{fmtPctRaw(t?.change_pct)}</div><div className="text-[11px] text-mute">24h change</div></div>
      <div className="hidden sm:block"><div className="num text-sm">{t?.quote_volume != null ? `${fmtNum(t.quote_volume / 1e6, 1)}M` : "—"}</div><div className="text-[11px] text-mute">24h volume (USDT)</div></div>
      <div className="hidden md:block"><div className="num text-sm">{fmtPrice(t?.bid)} / {fmtPrice(t?.ask)}</div><div className="text-[11px] text-mute">bid / ask</div></div>
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
  if (!r) return null;
  const vd = verdictOf(r, market);
  const p = r.plan;
  const usable = vd.tone !== "wait" && p && (market === "futures" || p.side === "LONG");
  const use = () => {
    const q = new URLSearchParams(params);
    q.set("side", market === "spot" ? "LONG" : p.side); if (market === "futures") q.set("lev", String(p.suggested_leverage));
    q.set("sl", String(p.stop)); q.set("tp", String(p.targets?.[1]?.price ?? p.targets?.[0]?.price)); q.set("limit", String(p.entry));
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
function ChartPanel({ symbol, market, positions, orders }: { symbol: string; market: Mkt; positions: any[]; orders: any[] }) {
  const [tf, setTf] = useState<string>("15m");
  const [candles, setCandles] = useState<Candle[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const { tickers } = useLive();
  useEffect(() => {
    let alive = true;
    const load = () => klines(symbol, tf, 300).then((c: any) => { if (alive) { setCandles(c as Candle[]); setErr(null); } }).catch((e: any) => alive && setErr(e.message));
    setCandles([]); load();
    const id = window.setInterval(load, tf === "1m" ? 15_000 : 45_000);
    return () => { alive = false; window.clearInterval(id); };
  }, [symbol, tf]);
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
        <span className="hidden text-[11px] text-mute sm:inline">your entry, SL, TP, liquidation and limit orders are drawn on the chart</span>
      </div>
      {err ? <p className="p-4 text-sm text-bear">Chart unavailable: {err}</p>
        : candles.length ? <CandleChart candles={candles} lines={lines} livePrice={tickers[symbol]?.last ?? null} height={380} />
        : <div className="skeleton m-3 h-[340px] rounded-lg" />}
    </section>
  );
}

/* ---------------------------------------------------------------- order book */
function OrderBook({ symbol }: { symbol: string }) {
  const [ob, setOb] = useState<any>(null);
  const { tickers } = useLive();
  useEffect(() => {
    let alive = true;
    const load = () => { if (!document.hidden) orderbook(symbol).then((x: any) => alive && setOb(x)).catch(() => {}); };
    setOb(null); load();
    const id = window.setInterval(load, 4000);
    return () => { alive = false; window.clearInterval(id); };
  }, [symbol]);
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
      <div className="grid grid-cols-2 border-b border-glass/[0.06] px-2 py-2 text-[10px] uppercase tracking-wide text-mute"><span>Price</span><span className="text-right">Amount</span></div>
      {!ob ? <div className="skeleton m-2 h-80 rounded" /> : (
        <>
          {asks.map((x) => row(x, "a"))}
          <div className={`num border-y border-glass/[0.06] px-2 py-1.5 text-base font-semibold ${tone(tickers[symbol]?.change_pct)}`}>{fmtPrice(tickers[symbol]?.last)}</div>
          {bids.map((x) => row(x, "b"))}
        </>
      )}
    </section>
  );
}

/* ---------------------------------------------------------------- order form */
function OrderForm({ symbol, market, d, act }: { symbol: string; market: Mkt; d: any; act: (fn: () => Promise<any>, ok: string) => Promise<void> }) {
  const [params] = useSearchParams();
  const { tickers } = useLive();
  const px = tickers[symbol]?.last ?? null;
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
function FutPositions({ rows, act, hedges }: { rows: any[]; act: (fn: () => Promise<any>, ok: string) => Promise<void>; hedges?: any[] }) {
  const [edit, setEdit] = useState<string | null>(null);
  const [sl, setSl] = useState(""); const [tp, setTp] = useState("");
  if (!rows.length) return <p className="py-6 text-center text-sm text-mute">No open positions. Use the order form, or tap “Use this plan” on the AI call.</p>;
  return (
    <div className="space-y-2">
      {hedges?.map((h: any) => <div key={h.symbol} className="rounded-lg border border-accent/30 bg-accent/[0.06] px-3 py-2 text-xs">{h.symbol} hedged · combined P&L <span className={tone(h.pnl)}>${fmtNum(h.pnl)}</span> · net {h.net >= 0 ? "long" : "short"} ${fmtNum(Math.abs(h.net), 0)}</div>)}
      {rows.map((p) => (
        <div key={p.key} className="rounded-xl border border-glass/[0.08] p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className={`h-8 w-1 rounded-full ${p.side > 0 ? "bg-bull" : "bg-bear"}`} />
              <span className="font-semibold">{p.symbol}</span>
              <span className={`rounded px-1.5 py-0.5 text-[11px] font-bold ${p.side > 0 ? "bg-bull/15 text-bull" : "bg-bear/15 text-bear"}`}>{p.side > 0 ? "Long" : "Short"} {fmtNum(p.leverage, 1)}x</span>
            </div>
            <div className="text-right"><div className={`num font-semibold ${tone(p.upnl)}`}>{p.upnl != null ? `${p.upnl >= 0 ? "+" : ""}${fmtNum(p.upnl)} USDT` : "—"}</div><div className={`num text-xs ${tone(p.upnl)}`}>{fmtPctRaw(p.roe_pct, 1)} ROE</div></div>
          </div>
          <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
            {([["Size", `${fmtNum(p.notional, 0)} USDT`], ["Entry", fmtPrice(p.entry)], ["Mark", fmtPrice(p.mark)], ["Liq. price", fmtPrice(p.liq)], ["Margin", `${fmtNum(p.margin)} USDT`],
              ["TP", p.take ? fmtPrice(p.take) : "—"], ["SL", p.stop ? fmtPrice(p.stop) : "—"], ["Funding", `${fmtNum(-(p.funding ?? 0), 3)} USDT`]] as const).map(([k, v]) => (
              <div key={k} className="flex justify-between gap-2"><dt className="text-mute">{k}</dt><dd className={`num text-right ${k === "Liq. price" ? "text-warn" : k === "TP" ? "text-bull" : k === "SL" ? "text-bear" : ""}`}>{v}</dd></div>
            ))}
          </dl>
          {edit === p.key && (
            <div className="mt-2 grid grid-cols-[1fr_1fr_auto] gap-2">
              <input className="input num h-9" placeholder="Take-profit" inputMode="decimal" value={tp} onChange={(e) => setTp(e.target.value)} aria-label="Take-profit" />
              <input className="input num h-9" placeholder="Stop-loss" inputMode="decimal" value={sl} onChange={(e) => setSl(e.target.value)} aria-label="Stop-loss" />
              <button className="btn btn-primary h-9 px-3 text-xs" onClick={() => act(async () => { await PF.setOrders(p.key, Number(sl) || null, Number(tp) || null); setEdit(null); }, "TP / SL updated.")}>Save</button>
            </div>
          )}
          <div className="mt-2 flex flex-wrap justify-end gap-2">
            <button className="btn px-3 py-1 text-xs" onClick={() => { setEdit(edit === p.key ? null : p.key); setSl(p.stop ? String(p.stop) : ""); setTp(p.take ? String(p.take) : ""); }}>TP / SL</button>
            <button className="btn px-3 py-1 text-xs" onClick={() => act(() => PF.close(p.key, 0.5), `Closed half of ${p.symbol}.`)}>Close 50%</button>
            <button className="btn border-bear/40 px-3 py-1 text-xs text-bear" onClick={() => act(() => PF.close(p.key, 1), `Closed ${p.symbol} at market.`)}>Close all</button>
          </div>
        </div>
      ))}
    </div>
  );
}

function SpotHoldings({ rows, act }: { rows: any[]; act: (fn: () => Promise<any>, ok: string) => Promise<void> }) {
  if (!rows.length) return <p className="py-6 text-center text-sm text-mute">No coins held yet. Buy from the order form.</p>;
  return (
    <div className="space-y-2">
      {rows.map((p) => {
        const pct = p.mark && p.avg_price ? (p.mark / p.avg_price - 1) * 100 : null;
        return (
          <div key={p.symbol} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-glass/[0.08] p-3">
            <div className="flex items-center gap-2.5"><CoinAvatar symbol={p.symbol} size={28} /><div><div className="font-semibold">{base(p.symbol)}</div><div className="num text-xs text-mute">{fmtNum(p.qty, 6)} · avg {fmtPrice(p.avg_price)}</div></div></div>
            <div className="text-right"><div className="num">{fmtNum(p.market_value)} USDT</div><div className={`num text-xs ${tone(p.unrealized_pnl)}`}>{p.unrealized_pnl != null ? `${p.unrealized_pnl >= 0 ? "+" : ""}${fmtNum(p.unrealized_pnl)} (${fmtPctRaw(pct, 1)})` : "—"}</div></div>
            <button className="btn px-3 py-1 text-xs" onClick={() => act(() => SP.order(p.symbol, "SELL", p.qty, null), `Sold all ${base(p.symbol)}.`)}>Sell all</button>
          </div>
        );
      })}
    </div>
  );
}

function Orders({ rows, market, act }: { rows: any[]; market: Mkt; act: (fn: () => Promise<any>, ok: string) => Promise<void> }) {
  if (!rows.length) return <p className="py-6 text-center text-sm text-mute">No open orders. Choose “Limit” in the order form to buy or sell at your price.</p>;
  return (
    <div className="overflow-x-auto"><table className="grid-table">
      <thead><tr><th>Time</th><th>Pair</th><th>Type</th><th>Side</th><th className="text-right">Price</th><th className="text-right">{market === "futures" ? "Margin" : "Amount"}</th><th className="text-right">Action</th></tr></thead>
      <tbody>{rows.map((o) => {
        const buy = o.side === "BUY" || o.side > 0;
        return (
          <tr key={o.id}><td className="text-mute">{fmtTime(o.created_at)}</td><td className="font-medium">{o.symbol}</td><td>Limit{market === "futures" ? ` · ${o.leverage}x` : ""}</td>
            <td className={buy ? "text-bull" : "text-bear"}>{market === "futures" ? (buy ? "Long" : "Short") : buy ? "Buy" : "Sell"}</td>
            <td className="num text-right">{fmtPrice(o.price)}</td><td className="num text-right">{market === "futures" ? `${fmtNum(o.margin)} USDT` : fmtNum(o.qty, 6)}</td>
            <td className="text-right"><button className="btn px-2 py-0.5 text-xs" onClick={() => act(() => (market === "futures" ? PF.cancelOrder(o.id) : SP.cancelOrder(o.id)), "Order cancelled; the funds are back.")}>Cancel</button></td></tr>
        );
      })}</tbody>
    </table></div>
  );
}

function History({ rows, market }: { rows: any[]; market: Mkt }) {
  if (!rows.length) return <p className="py-6 text-center text-sm text-mute">No trades yet.</p>;
  return (
    <div className="max-h-96 overflow-auto"><table className="grid-table">
      <thead><tr><th>Time</th><th>Pair</th><th>Action</th><th className="text-right">Price</th><th className="text-right">Qty</th><th className="text-right">Fee</th><th className="text-right">Realized P&L</th></tr></thead>
      <tbody>{rows.slice(0, 100).map((t) => {
        const label = market === "futures" ? `${t.type === "OPEN" ? "Open" : "Close"} ${t.side > 0 ? "long" : "short"}${t.reason && t.reason !== "manual" ? ` · ${t.reason}` : ""}${t.order_type === "LIMIT" ? " · limit" : ""}` : `${t.side === "BUY" ? "Buy" : "Sell"}${t.order_type === "LIMIT" ? " · limit" : ""}`;
        const pnl = t.realized_pnl;
        return (
          <tr key={t.id}><td className="text-mute">{fmtTime(t.created_at)}</td><td className="font-medium">{t.symbol}</td><td className={(market === "futures" ? t.side > 0 : t.side === "BUY") ? "text-bull" : "text-bear"}>{label}</td>
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
