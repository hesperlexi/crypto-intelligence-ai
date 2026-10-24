import { Fragment, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { TfTabs, useSymbols } from "../components/Pickers";
import { Badge, Card, Empty, ErrorBox, Loading, Note, ProbBar, Stat } from "../components/ui";
import { useApi } from "../lib/api";
import { DASH, ago, base, fmtCompact, fmtPctRaw, fmtPrice, fmtProb, isNum, slug, tone } from "../lib/format";
import { useLive } from "../lib/live";
import { liqPrice } from "../lib/paperFutures";

const TFS = ["1h", "4h", "12h", "1d"] as const;

function actionTone(a?: string) {
  if (!a) return "mute" as const;
  if (a.startsWith("LONG")) return "bull" as const;
  if (a === "SHORT") return "bear" as const;
  return "warn" as const;
}

export default function Futures() {
  const [tf, setTf] = useState<string>("4h");
  const [filter, setFilter] = useState<"all" | "trade" | "long" | "short">("all");
  const v = useApi<any>(`/futures?timeframe=${tf}`);
  const symbols = useSymbols();
  const mkt = useApi<any>(symbols.length ? `/futures/market?symbols=${symbols.join(",")}` : null, 60_000);
  const rows: any[] = useMemo(() => {
    let r: any[] = v.data?.rows ?? [];
    if (filter === "trade") r = r.filter((x) => x.side !== 0);
    if (filter === "long") r = r.filter((x) => x.side > 0 || (x.side === 0 && x.lean === "LONG"));
    if (filter === "short") r = r.filter((x) => x.side < 0 || (x.side === 0 && x.lean === "SHORT"));
    return r;
  }, [v.data, filter]);
  const all: any[] = v.data?.rows ?? [];
  const nLong = all.filter((r) => r.side > 0).length, nShort = all.filter((r) => r.side < 0).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight">Futures</h1>
            <Badge tone="warn">Predictions + demo only</Badge>
          </div>
          <p className="text-sm text-mute">Long / short calls for USDT perpetuals on the {tf.toUpperCase()} timeframe, with leverage, liquidation and funding.</p>
        </div>
        <TfTabs value={tf} onChange={setTf} options={TFS} />
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
        <Card title="Calls now"><div className="flex gap-6"><Stat label="Long" value={nLong} className="text-bull" /><Stat label="Short" value={nShort} className="text-bear" /><Stat label="Wait" value={all.length - nLong - nShort} /></div></Card>
        <Card title="Live futures data" className="col-span-2 order-last md:order-none">
          {mkt.data?.available ? <p className="text-sm">Funding, open interest and long/short ratios come live from Binance USDⓈ-M futures in your browser · updated {ago(mkt.data.fetched_at)}.</p>
            : <p className="text-sm text-warn">{mkt.loading ? "Loading Binance futures data…" : `Binance futures data not reachable from this device (${mkt.data?.reason ?? mkt.error ?? "unknown"}). Calls still work; funding uses the standard 0.01% per 8h.`}</p>}
          <Note>{v.data?.funding_source ? `Engine funding: ${v.data.funding_source}.` : ""}</Note>
        </Card>
        <Card title="Practise"><div className="flex flex-col gap-2 [&>a]:py-1.5 [&>a]:text-sm"><Link className="btn btn-primary" to="/paper?market=futures">Paper trading</Link><Link className="btn" to="/bots">Demo bots</Link></div></Card>
      </div>

      <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Filter">
        {([["all", "All coins"], ["trade", "Trade calls only"], ["long", "Long side"], ["short", "Short side"]] as const).map(([k, l]) => (
          <button key={k} className={`btn px-3 py-1 text-xs ${filter === k ? "btn-on" : ""}`} aria-pressed={filter === k} onClick={() => setFilter(k)}>{l}</button>
        ))}
      </div>

      {v.error && <ErrorBox error={v.error} retry={v.reload} />}
      {!v.data && v.loading && <Loading what="Loading futures predictions" />}
      {v.data === null && !v.loading && <Empty>Futures predictions appear after the next engine run (within about 15 minutes).</Empty>}
      <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
        {rows.map((r) => <FuturesCard key={r.symbol} r={r} m={mkt.data?.rows?.[r.symbol]} />)}
      </div>
      {v.data && !rows.length && <Empty>No coin matches this filter right now.</Empty>}

      <LeverageCalculator />
      <Note>Forecasts are probabilities, not certainties. Leverage multiplies both gains and losses; a liquidated position loses its whole margin. Suggested leverage keeps the liquidation price at least 1.5× the stop distance away and is capped at 10x. Everything here is analysis and virtual trading only — no real orders are placed.</Note>
    </div>
  );
}

function FuturesCard({ r, m }: { r: any; m?: any }) {
  const { tickers } = useLive();
  const nav = useNavigate();
  const px = tickers[r.symbol]?.last ?? r.price;
  if (r.status !== "OK") {
    return <Card title={r.symbol}><Empty>{r.reason ?? r.status ?? "Not available yet"}</Empty></Card>;
  }
  const p = r.plan;
  const funding = m?.funding_rate ?? r.funding_rate;
  const trade = () => {
    const q = new URLSearchParams({ market: "futures", symbol: r.symbol, side: (p?.side ?? (r.lean === "SHORT" ? "SHORT" : "LONG")),
      ...(p?.suggested_leverage ? { lev: String(p.suggested_leverage) } : {}), ...(p?.stop ? { sl: String(p.stop) } : {}),
      ...(p?.targets?.[1]?.price ? { tp: String(p.targets[1].price) } : {}) });
    nav(`/paper?${q}`);
  };
  return (
    <Card>
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <Link to={`/asset/${slug(r.symbol)}`} className="min-w-0 hover:text-accent">
            <div className="text-lg font-semibold leading-tight">{base(r.symbol)}<span className="text-sm font-normal text-mute">/USDT</span></div>
            <div className="num text-sm text-mute">{fmtPrice(px)}</div>
          </Link>
          <Badge tone={actionTone(r.action)}>{r.action === "SHORT" ? "▼ " : r.action?.startsWith("LONG") ? "▲ " : ""}{r.action}</Badge>
        </div>
        <ProbBar up={r.p_up} neutral={r.p_neutral} down={r.p_down} />
        <div className="grid grid-cols-3 gap-3">
          <Stat label="Confidence" value={fmtProb(r.confidence)} />
          <Stat label="Lean" value={r.lean ?? DASH} className={r.lean === "LONG" ? "text-bull" : r.lean === "SHORT" ? "text-bear" : ""} />
          <Stat label="Next bar" value={isNum(r.expected_return) ? fmtPctRaw(r.expected_return * 100) : DASH} className={tone(r.expected_return)} sub={r.edge_confirmed ? "edge ✓" : "no edge yet"} />
        </div>
        {r.side === 0 && r.decision_reason && <p className="text-xs text-mute">No trade: {r.decision_reason}</p>}
        {p ? (
          <div className="tile p-3 text-sm">
            <div className="mb-2 flex items-center justify-between"><span className="label">{p.valid ? "Trade plan" : "Plan (not valid yet)"} · {p.side}</span><span className="num text-xs text-mute">R:R 1:{isNum(p.risk_reward) ? p.risk_reward.toFixed(1) : DASH}</span></div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1">
              <span className="text-mute">Entry</span><span className="num text-right">{fmtPrice(p.entry)}</span>
              <span className="text-mute">Stop <span className="text-xs">({fmtPctRaw(-p.risk_pct, 1, false)})</span></span><span className="num text-right text-bear">{fmtPrice(p.stop)}</span>
              {p.targets.map((t: any) => <Fragment key={t.name}><span className="text-mute">{t.name}{isNum(t.probability) && <span className="text-xs"> · {fmtProb(t.probability)} hit</span>}</span><span className="num text-right text-bull">{fmtPrice(t.price)}</span></Fragment>)}
              <span className="text-mute">Suggested leverage</span><span className="num text-right">{p.suggested_leverage}x</span>
              <span className="text-mute">Liquidation at {p.suggested_leverage}x</span><span className="num text-right text-warn">{fmtPrice(p.liquidation_at_suggested)}</span>
              <span className="text-mute">Margin lost at stop</span><span className="num text-right">{fmtPctRaw(-p.margin_loss_at_stop_pct, 0, false)}</span>
            </div>
            {!p.valid && p.reason && <p className="mt-2 text-xs text-mute">{p.reason}</p>}
          </div>
        ) : null}
        <div className="grid grid-cols-3 items-start gap-3 text-sm">
          <Stat label="Funding 8h" value={isNum(funding) ? fmtPctRaw(funding * 100, 4) : DASH} className={tone(-(funding ?? 0))} sub={m?.listed === false ? "not listed on futures" : isNum(funding) ? (funding > 0 ? "longs pay" : "shorts pay") : undefined} />
          <Stat label="OI 24h" value={isNum(m?.oi_change_24h) ? fmtPctRaw(m.oi_change_24h * 100, 1) : DASH} sub={isNum(m?.open_interest_usd) ? `$${fmtCompact(m.open_interest_usd)}` : undefined} />
          <Stat label="Longs" value={isNum(m?.long_account_pct) ? `${m.long_account_pct.toFixed(0)}%` : DASH} sub={isNum(m?.long_short_ratio) ? `L/S ${m.long_short_ratio.toFixed(2)}` : undefined} />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <button className="btn btn-primary py-2 text-sm" onClick={trade}>Paper trade this</button>
          <Link className="btn py-2 text-sm" to={`/asset/${slug(r.symbol)}`}>Full analysis</Link>
        </div>
      </div>
    </Card>
  );
}

function LeverageCalculator() {
  const [entry, setEntry] = useState("100");
  const [stop, setStop] = useState("97");
  const [lev, setLev] = useState("5");
  const [balance, setBalance] = useState("10000");
  const [risk, setRisk] = useState("1");
  const e = Number(entry), s = Number(stop), L = Math.max(1, Number(lev)), B = Number(balance), R = Number(risk);
  const side = s < e ? 1 : -1;
  const ok = e > 0 && s > 0 && s !== e && L >= 1;
  const liq = ok ? liqPrice(e, side, L) : NaN;
  const dist = ok ? Math.abs(e - s) / e : NaN;
  const qty = ok ? (B * R / 100) / Math.abs(e - s) : NaN;
  const notional = qty * e, margin = notional / L;
  const liqBeyondStop = ok && side * (s - liq) > 0;
  const field = (label: string, val: string, set: (v: string) => void) => (
    <label className="text-xs text-mute">{label}<input className="input mt-1" inputMode="decimal" value={val} onChange={(ev) => set(ev.target.value)} /></label>
  );
  return (
    <Card title="Leverage & liquidation calculator">
      <div className="grid gap-3 sm:grid-cols-5">
        {field("Entry price", entry, setEntry)}{field("Stop price", stop, setStop)}{field("Leverage (x)", lev, setLev)}{field("Account balance ($)", balance, setBalance)}{field("Risk per trade (%)", risk, setRisk)}
      </div>
      {ok && (
        <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-6">
          <Stat label="Direction" value={side > 0 ? "LONG" : "SHORT"} className={side > 0 ? "text-bull" : "text-bear"} />
          <Stat label="Liquidation" value={fmtPrice(liq)} className={liqBeyondStop ? "text-warn" : "text-bear"} sub={liqBeyondStop ? "beyond your stop" : "BEFORE your stop — lower the leverage"} />
          <Stat label="Position size" value={`$${fmtCompact(notional)}`} sub={`${qty.toPrecision(4)} coins`} />
          <Stat label="Margin needed" value={`$${fmtCompact(margin)}`} sub={`${((margin / B) * 100).toFixed(1)}% of balance`} />
          <Stat label="Loss at stop" value={`$${fmtCompact(B * R / 100)}`} sub={`${(dist * L * 100).toFixed(0)}% of margin`} />
          <Stat label="Max safe leverage" value={`${Math.max(1, Math.floor(1 / (1.5 * dist + 0.005)))}x`} sub="liq. ≥ 1.5× stop distance" />
        </div>
      )}
      <Note>The position size comes from the stop and your risk, not from the leverage: leverage only changes how much margin is locked. Maintenance margin 0.5% assumed; the exchange's exact tiers can differ slightly.</Note>
    </Card>
  );
}
