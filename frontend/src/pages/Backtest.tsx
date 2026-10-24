import { useMemo, useState } from "react";
import LineChart, { Series } from "../components/LineChart";
import { SymbolSelect, useMeta } from "../components/Pickers";
import { Badge, Card, Empty, ErrorBox, Note, Row, Stat } from "../components/ui";
import { post, useApi } from "../lib/api";
import { DASH, fmtDate, fmtNum, fmtPct, fmtPctRaw, fmtPrice, fmtProb, fmtTime, isNum, tone } from "../lib/format";

const TFS = ["15m", "1h", "4h", "12h", "1d"];

export default function Backtest() {
  const meta = useMeta();
  const symbols: string[] = (meta.data?.watchlist ?? []).map((w: any) => w.symbol);
  const strategies = meta.data?.strategies ?? {};
  const costs = meta.data?.costs;
  const [f, setF] = useState<any>({ symbol: "BTC/USDT", timeframe: "4h", strategy: "technical", start: "", end: "", initial_capital: 10000, sizing: "fraction", fraction: 1, risk_per_trade: 0.01, stop_atr: 2, take_profit_atr: "", allow_short: false, fee_rate: "", slippage_bps: "", spread_bps: "" });
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const hist = useApi<any[]>("/backtests");
  const up = (k: string, v: any) => setF((x: any) => ({ ...x, [k]: v }));
  const num = (v: any) => (v === "" || v == null ? null : Number(v));

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const body: any = {
        symbol: f.symbol, timeframe: f.timeframe, strategy: f.strategy, initial_capital: Number(f.initial_capital), sizing: f.sizing,
        fraction: Number(f.fraction), risk_per_trade: Number(f.risk_per_trade), stop_atr: num(f.stop_atr), take_profit_atr: num(f.take_profit_atr), allow_short: f.allow_short,
        start: f.start ? new Date(f.start).getTime() : null, end: f.end ? new Date(f.end).getTime() + 86399000 : null,
      };
      for (const k of ["fee_rate", "slippage_bps", "spread_bps"]) if (f[k] !== "") body[k] = Number(f[k]);
      const r = await post<any>("/backtest", body);
      if (r.status !== "done") setErr(r.result?.error ?? "Backtest failed");
      setRes(r.status === "done" ? r.result : null);
      hist.reload();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const s = res?.summary;
  const series = useMemo<Series[]>(() => {
    if (!res) return [];
    const cap = res.config.initial_capital;
    const pct = (curve: any[]) => curve.map((p: any) => ({ ts: p.ts, value: (p.equity / cap - 1) * 100 }));
    return [
      { name: res.strategy_label, color: "#f0b90b", points: pct(res.equity_curve) },
      { name: "Buy & Hold", color: "#6f7e91", points: pct(res.benchmarks.buy_hold.equity_curve), dashed: true },
      { name: "SMA crossover", color: "#c084fc", points: pct(res.benchmarks.sma_cross.equity_curve), dashed: true },
    ];
  }, [res]);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Backtesting</h1>
        <p className="text-sm text-mute">Signals are decided on a bar's close and executed at the next bar's open, with fees, spread and slippage. Net results only.</p>
        <p className="text-xs text-mute">Backtests run on the engine: the result appears here after its next cycle (usually within 15 minutes). You can leave this page; finished runs are listed under Previous runs.</p>
      </div>
      <Card title="Inputs">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <SymbolSelect value={f.symbol} onChange={(v) => up("symbol", v)} symbols={symbols.length ? symbols : [f.symbol]} />
          <label className="text-xs text-mute">Timeframe<select className="input mt-1" value={f.timeframe} onChange={(e) => up("timeframe", e.target.value)}>{TFS.map((t) => <option key={t}>{t}</option>)}</select></label>
          <label className="text-xs text-mute sm:col-span-2">Strategy<select className="input mt-1" value={f.strategy} onChange={(e) => up("strategy", e.target.value)}>{Object.entries(strategies).map(([k, v]: [string, any]) => <option key={k} value={k}>{v.label}</option>)}</select></label>
          <label className="text-xs text-mute">Start date<input type="date" className="input mt-1" value={f.start} onChange={(e) => up("start", e.target.value)} /></label>
          <label className="text-xs text-mute">End date<input type="date" className="input mt-1" value={f.end} onChange={(e) => up("end", e.target.value)} /></label>
          <label className="text-xs text-mute">Initial capital ($)<input className="input mt-1" inputMode="decimal" value={f.initial_capital} onChange={(e) => up("initial_capital", e.target.value)} /></label>
          <label className="text-xs text-mute">Position sizing<select className="input mt-1" value={f.sizing} onChange={(e) => up("sizing", e.target.value)}><option value="fraction">Fraction of equity</option><option value="risk">Risk per trade (needs stop)</option></select></label>
          {f.sizing === "fraction"
            ? <label className="text-xs text-mute">Equity fraction (0–1)<input className="input mt-1" inputMode="decimal" value={f.fraction} onChange={(e) => up("fraction", e.target.value)} /></label>
            : <label className="text-xs text-mute">Risk per trade (0.01 = 1%)<input className="input mt-1" inputMode="decimal" value={f.risk_per_trade} onChange={(e) => up("risk_per_trade", e.target.value)} /></label>}
          <label className="text-xs text-mute">Stop loss (ATR multiples, blank = none)<input className="input mt-1" inputMode="decimal" value={f.stop_atr} onChange={(e) => up("stop_atr", e.target.value)} /></label>
          <label className="text-xs text-mute">Take profit (ATR multiples, blank = none)<input className="input mt-1" inputMode="decimal" value={f.take_profit_atr} onChange={(e) => up("take_profit_atr", e.target.value)} /></label>
          <label className="text-xs text-mute">Trading fee per side<input className="input mt-1" inputMode="decimal" placeholder={String(costs?.fee_rate ?? "")} value={f.fee_rate} onChange={(e) => up("fee_rate", e.target.value)} /></label>
          <label className="text-xs text-mute">Slippage (bps per side)<input className="input mt-1" inputMode="decimal" placeholder={String(costs?.slippage_bps ?? "")} value={f.slippage_bps} onChange={(e) => up("slippage_bps", e.target.value)} /></label>
          <label className="text-xs text-mute">Spread (bps)<input className="input mt-1" inputMode="decimal" placeholder={String(costs?.spread_bps ?? "")} value={f.spread_bps} onChange={(e) => up("spread_bps", e.target.value)} /></label>
          <label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" checked={f.allow_short} onChange={(e) => up("allow_short", e.target.checked)} />Allow short positions</label>
          <button className="btn btn-primary self-end" disabled={busy} onClick={run}>{busy ? "Queued — waiting for the engine…" : "Run backtest"}</button>
        </div>
        {f.strategy === "ai_ensemble" && <Note>The AI strategy is only evaluated on walk-forward out-of-sample bars: every prediction it trades was made by a model trained strictly on earlier data. The period is clipped to that range.</Note>}
      </Card>
      {err && <ErrorBox error={err} />}

      {res && s && (
        <>
          <Card title={`${res.symbol} ${res.timeframe.toUpperCase()} · ${res.strategy_label}`} right={<Badge tone={res.verdict.startsWith("Beats") ? "bull" : "warn"}>{res.verdict}</Badge>}>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-6">
              <Stat label="Net return" value={fmtPct(s.net_return, 1)} className={tone(s.net_return)} sub={`final $${fmtNum(s.final_equity)}`} />
              <Stat label="Annualized" value={fmtPct(s.annualized_return, 1)} className={tone(s.annualized_return)} />
              <Stat label="Sharpe / Sortino" value={`${fmtNum(s.sharpe)} / ${fmtNum(s.sortino)}`} />
              <Stat label="Max drawdown" value={fmtPct(s.max_drawdown, 1)} className="text-bear" sub={`Calmar ${fmtNum(s.calmar)}`} />
              <Stat label="Win rate" value={fmtProb(s.win_rate, 1)} sub={`${s.trades} trades`} />
              <Stat label="Profit factor" value={fmtNum(s.profit_factor)} />
              <Stat label="Average trade" value={fmtPctRaw(s.avg_trade_pct)} className={tone(s.avg_trade_pct)} />
              <Stat label="Best / worst trade" value={`${fmtPctRaw(s.best_trade_pct, 1)} / ${fmtPctRaw(s.worst_trade_pct, 1)}`} />
              <Stat label="Avg holding" value={isNum(s.avg_holding_bars) ? `${s.avg_holding_bars.toFixed(1)} bars` : DASH} />
              <Stat label="Exposure" value={fmtProb(s.exposure)} sub={`${s.bars} bars`} />
              <Stat label="Period" value={<span className="text-sm">{fmtDate(s.start_ts)} → {fmtDate(s.end_ts)}</span>} />
            </div>
            <div className="mt-4 grid gap-6 lg:grid-cols-[18rem_1fr]">
              <div>
                <div className="label mb-1">From gross to net</div>
                <Row k="Gross return" v={fmtPct(s.gross_return, 2)} className={tone(s.gross_return)} />
                <Row k="Fees" v={`−$${fmtNum(s.fees)} (${fmtPct(s.fees_pct, 2, false)})`} className="text-bear" />
                <Row k="Slippage + spread" v={`−$${fmtNum(s.slippage)} (${fmtPct(s.slippage_pct, 2, false)})`} className="text-bear" />
                <Row k="Net return" v={fmtPct(s.net_return, 2)} className={`font-semibold ${tone(s.net_return)}`} />
                <div className="label mb-1 mt-4">Stability (four consecutive segments)</div>
                {res.segments.map((g: any) => <Row key={g.segment} k={`Segment ${g.segment}`} v={fmtPct(g.net_return, 1)} className={tone(g.net_return)} />)}
              </div>
              <LineChart series={series} percent />
            </div>
            <div className="mt-4 overflow-x-auto">
              <table className="grid-table">
                <thead><tr><th>Compared against (same bars and costs)</th><th className="text-right">Net return</th><th className="text-right">Sharpe</th><th className="text-right">Max drawdown</th><th className="text-right">Trades</th></tr></thead>
                <tbody>
                  <tr className="bg-raised/40 font-medium"><td>{res.strategy_label}</td><td className={`num text-right ${tone(s.net_return)}`}>{fmtPct(s.net_return, 1)}</td><td className="num text-right">{fmtNum(s.sharpe)}</td><td className="num text-right">{fmtPct(s.max_drawdown, 1)}</td><td className="num text-right">{s.trades}</td></tr>
                  {["buy_hold", "sma_cross"].map((k) => { const b = res.benchmarks[k]; return (
                    <tr key={k}><td>{b.label}</td><td className={`num text-right ${tone(b.summary.net_return)}`}>{fmtPct(b.summary.net_return, 1)}</td><td className="num text-right">{fmtNum(b.summary.sharpe)}</td><td className="num text-right">{fmtPct(b.summary.max_drawdown, 1)}</td><td className="num text-right">{b.summary.trades}</td></tr>); })}
                  <tr><td>{res.benchmarks.random.label} — median</td><td className={`num text-right ${tone(res.benchmarks.random.summary.net_return)}`}>{fmtPct(res.benchmarks.random.summary.net_return, 1)}</td>
                    <td colSpan={3} className="num text-right text-mute">5–95% range {fmtPct(res.benchmarks.random.summary.p05, 1)} … {fmtPct(res.benchmarks.random.summary.p95, 1)} · strategy beats {fmtProb(res.benchmarks.random.summary.share_beaten)} of random runs</td></tr>
                </tbody>
              </table>
            </div>
            {res.notes.map((n: string) => <Note key={n}>{n}</Note>)}
          </Card>
          <Card title={`Trades (${res.trades.length} most recent)`}>
            <div className="max-h-96 overflow-auto">
              <table className="grid-table">
                <thead><tr><th>Entry</th><th>Exit</th><th>Side</th><th className="text-right">Entry price</th><th className="text-right">Exit price</th><th className="text-right">Net P&L</th><th className="text-right">Return</th><th className="text-right">Bars</th><th>Exit reason</th></tr></thead>
                <tbody>{[...res.trades].reverse().map((t: any, i: number) => (
                  <tr key={i}><td className="text-mute">{fmtTime(t.entry_ts)}</td><td className="text-mute">{fmtTime(t.exit_ts)}</td><td>{t.side}</td><td className="num text-right">{fmtPrice(t.entry)}</td><td className="num text-right">{fmtPrice(t.exit)}</td>
                    <td className={`num text-right ${tone(t.pnl)}`}>{fmtNum(t.pnl)}</td><td className={`num text-right ${tone(t.return_pct)}`}>{fmtPctRaw(t.return_pct)}</td><td className="num text-right">{t.bars_held}</td><td className="text-mute">{t.reason.replace(/_/g, " ")}</td></tr>
                ))}</tbody>
              </table>
            </div>
            {!res.trades.length && <Empty>The strategy took no trades in this period</Empty>}
          </Card>
        </>
      )}
      <Card title="Previous runs">
        {hist.data?.length ? (
          <div className="overflow-x-auto"><table className="grid-table"><thead><tr><th>When</th><th>Asset</th><th>TF</th><th>Strategy</th><th className="text-right">Net return</th><th>Status</th></tr></thead>
            <tbody>{hist.data.map((h: any) => <tr key={h.id}><td className="text-mute">{fmtTime(h.created_at)}</td><td>{h.symbol}</td><td className="uppercase text-mute">{h.timeframe}</td><td>{strategies[h.strategy]?.label ?? h.strategy}</td><td className={`num text-right ${tone(h.net_return)}`}>{fmtPct(h.net_return, 1)}</td><td className="text-mute">{h.error ?? h.status}</td></tr>)}</tbody></table></div>
        ) : <Empty>No backtests run yet</Empty>}
      </Card>
    </div>
  );
}
