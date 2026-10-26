import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { TfTabs, useSymbols } from "../components/Pickers";
import { Badge, Card, Empty, ErrorBox, Loading, Note, Stat } from "../components/ui";
import { useApi } from "../lib/api";
import { ago, fmtCompact, fmtPrice } from "../lib/format";
import TradeCall from "../components/TradeCall";
import { liqPrice } from "../lib/paperFutures";

const TFS = ["15m", "1h", "4h", "12h", "1d", "3d"] as const;

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
      {v.data === null && !v.loading && <Empty>Futures predictions appear after the next engine run (within about 10 minutes).</Empty>}
      <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
        {rows.map((r) => <TradeCall key={r.symbol} r={r} market="futures" m={mkt.data?.rows?.[r.symbol]} compact />)}
      </div>
      {v.data && !rows.length && <Empty>No coin matches this filter right now.</Empty>}

      <LeverageCalculator />
      <Note>Forecasts are probabilities, not certainties. Leverage multiplies both gains and losses; a liquidated position loses its whole margin. Suggested leverage keeps the liquidation price at least 1.5× the stop distance away and is capped at 10x. Everything here is analysis and virtual trading only — no real orders are placed.</Note>
    </div>
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
