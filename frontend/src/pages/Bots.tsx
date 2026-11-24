import { Component, type ReactNode, useMemo, useState } from "react";
import { botFacts, PositionGrid } from "../components/PositionInfo";
import LineChart, { Series } from "../components/LineChart";
import LazyMount from "../components/LazyMount";
import { Card, Empty, ErrorBox, Info, Loading, Note, Row, Stat } from "../components/ui";
import { Badge, Tile } from "../components/kit";
import { FleetPulse } from "../components/Xeno";
import { put, useApi } from "../lib/api";
import { DASH, fmtNum, fmtPctRaw, fmtPrice, fmtProb, fmtTime, isNum, tone } from "../lib/format";
import { useLive } from "../lib/live";
import { useIsAdmin } from "../lib/session";

const TFS = ["15m", "1h", "4h", "12h", "1d", "3d"];

const SCORECARD = ["15m", "1h", "4h", "12h", "1d", "3d"].map((tf) => `futures-signal-ab-${tf}`);   // every public timeframe (v2.49)

export default function Bots() {
  const admin = useIsAdmin();
  const b = useApi<any>("/bots");
  const [editing, setEditing] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [market, setMarket] = useState<"all" | "spot" | "futures">("all");
  const cfgList: any[] = b.data?.config ?? [];
  // members see the bots that trade the signals; the raw prediction trackers are diagnostics for the owner
  const shown = (b.data?.bots ?? []).filter((x: any) => (market === "all" || (x.config.market ?? "spot") === market) && (admin || x.config.mode !== "prediction"))
    .sort((x: any, y: any) => Number(!SCORECARD.includes(x.config.id)) - Number(!SCORECARD.includes(y.config.id)));

  const save = async (list: any[], done: string) => {
    try {
      await put("/bots", { bots: list });
      setMsg(`${done} Applies within about 5 minutes.`);
      setEditing(null);
    } catch (e: any) {
      setMsg(e.message);
    }
  };
  const update = (id: string, patch: any, done: string) => save(cfgList.map((c) => (c.id === id ? { ...c, ...patch } : c)), done);
  const reset = (id: string) => {
    if (window.confirm("Reset this bot? Its trades and equity history are cleared and it starts again with its starting balance.")) {
      update(id, { reset_token: String(Date.now()) }, "Reset requested.");
    }
  };
  const remove = (id: string) => {
    if (window.confirm("Delete this bot and its history?")) save(cfgList.filter((c) => c.id !== id), "Bot deleted.");
  };
  const add = (mode: string, mkt = "spot") => {
    const tpl = (b.data?.defaults ?? []).find((d: any) => d.mode === mode && (d.market ?? "spot") === mkt) ?? {};
    const id = `${mkt === "futures" ? "fut-" : ""}${mode}-${Math.random().toString(36).slice(2, 7)}`;
    save([...cfgList, { ...tpl, id, name: `${tpl.name ?? "Bot"} (copy)`, reset_token: "1" }], "Bot added.");
  };

  return (
    <div className="fx-lite space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 className="section-title flex items-center gap-2">Demo trading bots <Info label="Bot rules">
        <span className="block space-y-2">
          <span className="block"><span className="font-medium text-text">Signal bots</span> <span className="text-mute">trade only the engine's final decisions (BUY, BUY ON PULLBACK, SELL) using the trade plan's entry, stop and three targets. Half the position closes at TP1 (1:1), a quarter at TP2 (up to 1:2) and a quarter at TP3 (up to 1:3); the stop moves to break-even after TP1 and trails to TP1 after TP2. Grade A+B bots also take the moderate (grade B) calls, so you can compare. They show what following the signals would have earned.</span></span>
          {admin && <span className="block"><span className="font-medium text-text">Prediction trackers</span> <span className="text-mute">take every model call (UP → long, DOWN → short) and hold it for exactly one bar, with no other filter. They show how often the raw predictions are right and what they pay. Only you see them.</span></span>}
          <span className="block"><span className="font-medium text-text">Futures bots</span> <span className="text-mute">trade the same calls as USDT perpetual futures with isolated margin: only the margin (position ÷ leverage) is set aside, futures fees (0.05%) apply, funding is paid or received every 8 hours, and a position is liquidated — losing its margin — if price reaches the liquidation price. With “safe leverage” on, a signal bot lowers its leverage so liquidation always sits well beyond the stop. Position size still comes from the stop, so leverage changes the margin used, not the risk per trade.</span></span>
        </span>
        <span className="mt-2 block">The engine runs every 5 minutes. Entries fill at the price available when it runs, plus spread, slippage and fees. Stops and targets are checked against every 15-minute candle, and when one candle touches both, the stop counts first. Only trades taken after a bot started are counted.</span>
        </Info></h2>
        </div>
        {admin && <div className="flex flex-wrap gap-2">
          <button className="btn btn-sm" onClick={() => add("decision")}>Add signal bot</button>
          <button className="btn btn-sm" onClick={() => add("prediction")}>Add prediction tracker</button>
          <button className="btn btn-sm" onClick={() => add("decision", "futures")}>Add futures signal bot</button>
          <button className="btn btn-sm" onClick={() => add("prediction", "futures")}>Add futures tracker</button>
        </div>}
      </div>
      <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Market">
        {(["all", "spot", "futures"] as const).map((m) => (
          <button key={m} className={`btn px-3 py-1 text-xs ${market === m ? "btn-on" : ""}`} aria-pressed={market === m} onClick={() => setMarket(m)}>
            {m === "all" ? "All bots" : m === "spot" ? "Spot" : "Futures"}
          </button>
        ))}
      </div>
      {shown.length > 0 && <SafePart><FleetHero bots={shown} /></SafePart>}
      {msg && <p className="text-sm text-accent">{msg}</p>}
      {b.error && <ErrorBox error={b.error} retry={b.reload} />}
      {!b.data && b.loading && <Loading what="Loading bots" />}
      {shown.map((bot: any) => (
        <SafePart key={bot.config.id}><BotCard bot={bot} cfg={cfgList.find((c) => c.id === bot.config.id) ?? bot.config}
          admin={admin} editing={editing === bot.config.id} onEdit={() => setEditing(editing === bot.config.id ? null : bot.config.id)}
          onSave={(patch: any) => update(bot.config.id, patch, "Saved.")} onToggle={() => update(bot.config.id, { enabled: !bot.config.enabled }, bot.config.enabled ? "Paused." : "Resumed.")}
          onReset={() => reset(bot.config.id)} onDelete={() => remove(bot.config.id)} /></SafePart>
      ))}
      {cfgList.filter((c) => !(b.data?.bots ?? []).some((x: any) => x.config.id === c.id)).map((c) => (
        <Card key={c.id} title={c.name}><Empty>Starting soon.</Empty></Card>
      ))}
      {b.data && !b.data.bots?.length && !cfgList.length && <Empty>No bots yet.</Empty>}
    </div>
  );
}

function BotCard({ bot, cfg, admin, editing, onEdit, onSave, onToggle, onReset, onDelete }: any) {
  const { tickers } = useLive();
  const s = bot.stats;
  const st = bot.state;
  const isPred = bot.config.mode === "prediction";
  const fut = bot.config.market === "futures";
  const series = useMemo<Series[]>(() => [
    { name: "Bot equity", color: "--accent", baseline: Number(bot.state?.deposited ?? bot.config.starting_balance) || undefined, points: bot.equity_curve.map((p: any) => ({ ts: p.ts, value: p.equity })) },
    { name: "Buy & hold (same coins)", color: "--mute", dashed: true, points: bot.equity_curve.filter((p: any) => isNum(p.benchmark)).map((p: any) => ({ ts: p.ts, value: p.benchmark })) },
  ], [bot.equity_curve, bot.config.starting_balance, bot.state?.deposited]);
  // v2.76 (owner: the tab was ~7 screens long): a compact summary per bot, the full details open on tap (remembered)
  const openKey = `cia-bot-open-${bot.config.id}`;
  const [open, setOpen] = useState(() => { try { return localStorage.getItem(openKey) === "1"; } catch { return false; } });
  const flip = () => setOpen((v: boolean) => { try { localStorage.setItem(openKey, v ? "0" : "1"); } catch { /* ignore */ } return !v; });
  const live = bot.positions.map((p: any) => {
    const px = tickers[p.symbol]?.last ?? null;
    const u = px != null ? p.side * p.qty_open * (px - p.entry) : null;
    const lev = p.lev ?? 1;
    return { ...p, px, u, lev, upct: px != null ? p.side * (px / p.entry - 1) * 100 * lev : null };
  });
  return (
    <Card className="ai-card" title={<span className="flex flex-wrap items-center gap-2"><span className="v3-dot" style={{ background: `rgb(var(${!bot.config.enabled ? "--mute" : (s.return_pct ?? 0) > 0 ? "--bull" : (s.return_pct ?? 0) < 0 ? "--bear" : "--ai"}))` }} /><span className="whitespace-nowrap text-text">{bot.config.name}</span><Badge tone={isPred ? "accent" : "mute"}>{isPred ? "Prediction tracker" : "Signal bot"}</Badge><Badge tone="mute">{String(bot.config.timeframe).toUpperCase()}</Badge>{fut ? <Badge tone="warn">Futures {bot.config.leverage}x{bot.config.safe_leverage && !isPred ? " max" : ""}</Badge> : <Badge tone="mute">Spot</Badge>}{!bot.config.enabled && <Badge tone="warn">Paused</Badge>}</span>}
      right={!admin ? undefined : <div className="flex gap-1">
        <button className="btn px-2 py-0.5 text-xs" onClick={onToggle}>{bot.config.enabled ? "Pause" : "Resume"}</button>
        <button className="btn px-2 py-0.5 text-xs" onClick={onEdit}>{editing ? "Close" : "Settings"}</button>
        <button className="btn px-2 py-0.5 text-xs" onClick={onReset}>Reset</button>
        <button className="btn px-2 py-0.5 text-xs hover:text-bear" onClick={onDelete}>Delete</button>
      </div>}>
      {editing && <Editor cfg={cfg} onSave={onSave} />}
      <div className="bot-sum">
        <Stat label="Equity" value={`$${fmtNum(st.equity)}`} />
        <Stat label="Return" value={fmtPctRaw(s.return_pct)} className={tone(s.return_pct)} />
        <Stat label="Closed trades" value={s.trades} sub={`${s.open_positions} open`} />
        <Stat label="Win rate" value={fmtProb(s.win_rate, 1)} />
        <div className="max-sm:hidden"><Stat label="Max drawdown" value={fmtPctRaw(s.max_drawdown_pct, 1)} className="text-bear" /></div>
        <button type="button" className="bot-more" onClick={flip} aria-expanded={open}>{open ? "Hide details ▴" : "Details ▾"}</button>
      </div>
      {open && <>
      <div className="mt-4 grid grid-cols-2 gap-4 border-t border-glass/[0.06] pt-4 sm:grid-cols-4">
        <Stat label="Capital" value={`$${fmtNum(bot.state?.deposited ?? bot.config.starting_balance, 0)}`} sub={bot.state?.deposits?.length ? `started $${fmtNum(bot.config.starting_balance, 0)} · ${fmtTime(st.started_at)}` : fmtTime(st.started_at)} />
        <Stat label="Buy & hold" value={fmtPctRaw(s.benchmark_return_pct)} sub="same coins" />
        <Stat label={isPred ? "Prediction accuracy" : "Direction right"} value={fmtProb(s.direction_accuracy, 1)} sub={s.direction_ci95 ? `95% CI ${fmtProb(s.direction_ci95[0])}–${fmtProb(s.direction_ci95[1])}` : DASH} />
        <Stat label="Profit factor" value={fmtNum(s.profit_factor)} sub={isNum(s.avg_r) ? `avg ${s.avg_r.toFixed(2)} R` : `fees $${fmtNum(s.fees_paid)}`} />
        <div className="sm:hidden"><Stat label="Max drawdown" value={fmtPctRaw(s.max_drawdown_pct, 1)} className="text-bear" /></div>
      </div>
      {fut && (
        <div className="mt-3 grid grid-cols-2 gap-4 border-t border-glass/[0.06] pt-3 sm:grid-cols-5">
          <Stat label="Liquidations" value={s.liquidations ?? 0} className={s.liquidations ? "text-bear" : ""} />
          <Stat label="Funding paid" value={`$${fmtNum(s.funding_paid)}`} className={tone(-(s.funding_paid ?? 0))} sub="negative = received" />
          <Stat label="Avg leverage" value={isNum(s.avg_leverage) ? `${s.avg_leverage.toFixed(1)}x` : DASH} />
          <Stat label="Avg return on margin" value={fmtPctRaw(s.avg_roe_pct)} className={tone(s.avg_roe_pct)} />
          <Stat label="Long / short P&L" value={s.trades ? <span><span className={tone(s.long_pnl)}>${fmtNum(s.long_pnl, 0)}</span> / <span className={tone(s.short_pnl)}>${fmtNum(s.short_pnl, 0)}</span></span> : DASH} />
        </div>
      )}
      
      {bot.equity_curve.length > 1 && <div className="mt-4"><LazyMount height={220}><LineChart series={series} height={220} /></LazyMount></div>}

      <div className="mt-4 grid gap-6 2xl:grid-cols-2 2xl:[&_.table-wrap]:mx-0">
        <div className="min-w-0">
          <div className="label mb-1">Open positions{bot.pending.length ? ` · ${bot.pending.length} pending limit order(s)` : ""}</div>
          {!isPred && live.length > 0 && (
            <div className="mb-2 space-y-2">
              {live.map((p: any) => (
                <div key={p.id} className="tile p-3">
                  <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-semibold">{p.symbol}</span>
                    <span className={`text-xs font-bold ${p.side > 0 ? "text-bull" : "text-bear"}`}>{p.side > 0 ? "▲ LONG" : "▼ SHORT"}</span>
                    {fut && <span className="rounded bg-glass/[0.06] px-1.5 text-xs">Isolated {p.lev}x</span>}
                    {p.info?.timeframe && <span className="text-xs uppercase text-mute">{p.info.timeframe}</span>}
                    {p.opened_at ? <span className="ml-auto text-xs text-mute">opened {fmtTime(p.opened_at)}</span> : null}
                  </div>
                  <PositionGrid p={botFacts(p, p.px)} note={fut ? "Realized PNL includes the closed targets, fees and funding so far." : undefined} />
                </div>
              ))}
            </div>
          )}
          {(isPred ? live.length : 0) || bot.pending.length ? (
            <div className="table-wrap"><table className="grid-table">
              <thead><tr><th>Coin</th><th>Side</th><th className="text-right">Entry</th><th className="text-right">Now</th><th className="text-right">P&L{fut ? " (on margin)" : ""}</th>{fut && <th className="text-right">Liquidation</th>}<th className="text-right">{isPred ? "Closes" : "Stop / TP hit"}</th></tr></thead>
              <tbody>
                {(isPred ? live : []).map((p: any) => (
                  <tr key={p.id}><td className="font-medium">{p.symbol}</td><td className={p.side > 0 ? "text-bull" : "text-bear"}>{p.side > 0 ? "▲ LONG" : "▼ SHORT"}{fut ? ` ${p.lev}x` : ""}</td>
                    <td className="num text-right">{fmtPrice(p.entry)}</td><td className="num text-right">{fmtPrice(p.px)}</td>
                    <td className={`num text-right ${tone(p.u)}`}>{p.u != null ? `$${fmtNum(p.u)} (${fmtPctRaw(p.upct)})` : DASH}</td>
                    {fut && <td className="num text-right text-warn">{fmtPrice(p.liq)}</td>}
                    <td className="num text-right text-mute">{isPred ? fmtTime(p.exit_at) : `${fmtPrice(p.stop)} · ${p.tp_hit}/3`}</td></tr>
                ))}
                {bot.pending.map((o: any, i: number) => (
                  <tr key={`p${i}`} className="text-mute"><td>{o.symbol}</td><td>limit {o.side > 0 ? "buy" : "sell"}</td><td className="num text-right">{fmtPrice(o.limit)}</td>
                    <td className="num text-right">{fmtPrice(tickers[o.symbol]?.last)}</td><td className="text-right">waiting</td>{fut && <td />}<td className="num text-right">expires {fmtTime(o.expires_at)}</td></tr>
                ))}
              </tbody>
            </table></div>
          ) : !live.length ? <Empty>{isPred ? "No open predictions right now." : "No open positions. Quiet stretches are normal."}</Empty> : null}
        </div>
        <div className="min-w-0">
          {/* v2.17: the signal-confidence buckets (next-candle hit rate) are admin only */}
          {(s.confidence_key === "p_max" || admin) && <>
          <div className="label mb-1">Accuracy by {s.confidence_key === "p_max" ? "model probability" : "model hit rate (next candle)"}</div>
          {s.by_confidence?.length ? (
            <div className="table-wrap"><table className="grid-table">
              <thead><tr><th>Bucket</th><th className="text-right">Trades</th><th className="text-right">Predicted</th><th className="text-right">Direction right</th><th className="text-right">Avg return</th></tr></thead>
              <tbody>{s.by_confidence.map((r: any) => (
                <tr key={r.lo}><td className="num">{fmtProb(r.lo)}–{fmtProb(r.hi)}</td><td className="num text-right">{r.n}</td><td className="num text-right">{fmtProb(r.mean, 1)}</td>
                  <td className="num text-right">{fmtProb(r.hit_rate, 1)}</td><td className={`num text-right ${tone(r.avg_return_pct)}`}>{fmtPctRaw(r.avg_return_pct)}</td></tr>
              ))}</tbody>
            </table></div>
          ) : <Empty>Appears after the first closed trades.</Empty>}
          </>}
          {s.trades > 0 && (
            <div className="mt-3 grid gap-x-6 sm:grid-cols-2">
              <Row k="Longs / shorts" v={`${s.longs} / ${s.shorts}`} />
              <Row k="Long / short accuracy" v={`${fmtProb(s.long_accuracy)} / ${fmtProb(s.short_accuracy)}`} />
              <Row k="Average trade" v={fmtPctRaw(s.avg_return_pct)} className={tone(s.avg_return_pct)} />
              <Row k="Average hold" v={isNum(s.avg_hold_h) ? `${s.avg_hold_h.toFixed(1)} h` : DASH} />
              <Row k="Best / worst" v={`${fmtPctRaw(s.best_pct, 1)} / ${fmtPctRaw(s.worst_pct, 1)}`} />
              <Row k="Exits" v={Object.entries(s.by_exit ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ")} />
            </div>
          )}
          
        </div>
      </div>

      <div className="mt-4">
        <div className="label mb-1">Closed trades ({bot.trades.length} most recent)</div>
        {bot.trades.length ? (
          <div className="max-h-80 overflow-auto"><table className="grid-table">
            <thead><tr><th>Closed</th><th>Coin</th><th>Side</th><th>{isPred ? "Predicted" : "Decision"}</th><th className="text-right">{isPred ? "Probability" : admin ? "Model hit rate" : "Grade"}</th><th className="text-right">Entry</th><th className="text-right">Exit</th><th className="text-right">Return</th>{fut && <th className="text-right">Lev · on margin</th>}<th className="text-right">P&L</th><th>Exit</th><th>Right?</th></tr></thead>
            <tbody>{bot.trades.map((t: any) => (
              <tr key={t.id}>
                <td className="text-mute">{fmtTime(t.closed_at)}</td><td className="font-medium">{t.symbol}</td>
                <td className={t.side > 0 ? "text-bull" : "text-bear"}>{t.side > 0 ? "LONG" : "SHORT"}</td>
                <td>{isPred ? t.info.predicted : t.info.decision}</td>
                <td className="num text-right">{isPred ? fmtProb(t.info.p_max) : admin ? fmtProb(t.info.confidence) : (t.info.grade ?? DASH)}</td>
                <td className="num text-right">{fmtPrice(t.entry)}</td><td className="num text-right">{fmtPrice(t.exit)}</td>
                <td className={`num text-right ${tone(t.return_pct)}`}>{fmtPctRaw(t.return_pct)}</td>
                {fut && <td className={`num text-right ${tone(t.info.roe_pct)}`}>{t.info.leverage ?? 1}x · {fmtPctRaw(t.info.roe_pct)}</td>}
                <td className={`num text-right ${tone(t.pnl)}`}>{fmtNum(t.pnl)}</td>
                <td className={t.exit_reason === "liquidated" ? "text-bear" : "text-mute"}>{t.exit_reason}</td>
                <td>{t.correct ? <span className="text-bull">✓ yes</span> : <span className="text-bear">✕ no</span>}</td>
              </tr>
            ))}</tbody>
          </table></div>
        ) : <Empty>No closed trades yet.</Empty>}
      </div>
      {s.by_symbol?.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          {s.by_symbol.map((r: any) => <span key={r.symbol} className="rounded border border-line px-2 py-1"><span className="text-text">{r.symbol}</span> <span className="text-mute">{r.n} trades · {fmtProb(r.accuracy)} right ·</span> <span className={tone(r.pnl)}>${fmtNum(r.pnl)}</span></span>)}
        </div>
      )}
      </>}
    </Card>
  );
}

function Editor({ cfg, onSave }: { cfg: any; onSave: (patch: any) => void }) {
  const [f, setF] = useState<any>({ ...cfg, symbols: Array.isArray(cfg.symbols) ? cfg.symbols.join(", ") : cfg.symbols });
  const up = (k: string, v: any) => setF((x: any) => ({ ...x, [k]: v }));
  const isPred = f.mode === "prediction";
  const fut = f.market === "futures";
  const field = (k: string, label: string) => (
    <label key={k} className="text-xs text-mute">{label}<input className="input mt-1" value={f[k] ?? ""} onChange={(e) => up(k, e.target.value)} /></label>
  );
  const submit = () => {
    const symbols = String(f.symbols).trim().toLowerCase() === "all" || !String(f.symbols).trim() ? "all"
      : String(f.symbols).split(",").map((s) => s.trim().toUpperCase()).filter(Boolean).map((s) => (s.includes("/") ? s : `${s.replace(/USDT$/, "")}/USDT`));
    const num = (k: string) => (f[k] === "" || f[k] == null ? undefined : Number(f[k]));
    onSave({ name: f.name, timeframe: f.timeframe, symbols, allow_short: !!f.allow_short, starting_balance: num("starting_balance"),
      market: f.market ?? "spot", ...(fut ? { leverage: num("leverage"), safe_leverage: f.safe_leverage !== false } : {}),
      ...(isPred ? { position_pct: num("position_pct"), min_probability: num("min_probability") }
        : { risk_per_trade_pct: num("risk_per_trade_pct"), max_position_pct: num("max_position_pct"), max_open_positions: num("max_open_positions"), pending_bars: num("pending_bars"), max_hold_bars: num("max_hold_bars") }) });
  };
  return (
    <div className="mb-4 rounded-md border border-line bg-raised/40 p-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {field("name", "Name")}
        <label className="text-xs text-mute">Timeframe<select className="input mt-1" value={f.timeframe} onChange={(e) => up("timeframe", e.target.value)}>{TFS.map((t) => <option key={t}>{t}</option>)}</select></label>
        {field("symbols", "Coins (\"all\" or e.g. BTC, ETH, SOL)")}
        {field("starting_balance", "Starting balance ($)")}
        {isPred ? [field("position_pct", "Position size (% of equity)"), field("min_probability", "Minimum probability (0–1)")]
          : [field("risk_per_trade_pct", "Risk per trade (%)"), field("max_position_pct", "Max position (% of equity)"), field("max_open_positions", "Max open positions"),
            field("pending_bars", "Pullback order valid (bars)"), field("max_hold_bars", "Time exit after (bars)")]}
        <label className="text-xs text-mute">Market<select className="input mt-1" value={f.market ?? "spot"} onChange={(e) => up("market", e.target.value)}><option value="spot">Spot (1x)</option><option value="futures">Futures (perpetual)</option></select></label>
        {fut && field("leverage", isPred ? "Leverage (1–20x)" : "Maximum leverage (1–20x)")}
        {fut && !isPred && <label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" checked={f.safe_leverage !== false} onChange={(e) => up("safe_leverage", e.target.checked)} />Safe leverage (liquidation beyond the stop)</label>}
        <label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" checked={!!f.allow_short} onChange={(e) => up("allow_short", e.target.checked)} />Allow short trades</label>
      </div>
      <div className="mt-3 flex items-center gap-3">
        <button className="btn btn-primary" onClick={submit}>Save settings</button>
        <span className="text-xs text-mute">Changing the market, timeframe or starting balance restarts the bot from scratch.</span>
      </div>
    </div>
  );
}

/** V3.0: the bots at a glance - a league of returns and every bot's return over time. */
/** v2.39: a drawing that fails on some phone never takes the whole Demo bots page down with it. */
class SafePart extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? null : this.props.children; }
}

function FleetHero({ bots }: { bots: any[] }) {
  const league = [...bots].sort((a, z) => Number(z.stats?.return_pct ?? 0) - Number(a.stats?.return_pct ?? 0));
  const maxAbs = Math.max(1, ...bots.map((x) => Math.abs(Number(x.stats?.return_pct ?? 0))));
  const curves = bots.map((x) => {
    const s0 = Number(x.state?.deposited ?? x.config.starting_balance) || (x.equity_curve?.[0]?.equity ?? 1);
    return { name: x.config.name, pts: (x.equity_curve ?? []).filter((p: any) => isNum(p.equity)).map((p: any) => ({ ts: p.ts, v: (p.equity / s0 - 1) * 100 })) };
  });
  const tot = bots.reduce((a, x) => a + Number(x.stats?.trades ?? 0), 0);
  const open = bots.reduce((a, x) => a + Number(x.stats?.open_positions ?? 0), 0);
  const avg = bots.length ? bots.reduce((a, x) => a + Number(x.stats?.return_pct ?? 0), 0) / bots.length : 0;
  const best = [...bots].sort((a, z) => Number(z.stats?.return_pct ?? 0) - Number(a.stats?.return_pct ?? 0))[0];
  return (
    <section className="panel v3-glass grid gap-5 p-4 sm:p-5 lg:grid-cols-[minmax(0,380px)_1fr] lg:items-start" aria-label="Bot league">
      {/* V3.0: the bot league (best return first) replaces the space fleet drawing */}
      <div className="min-w-0">
        <div className="mb-2 text-sm font-semibold">Bot league</div>
        <ul className="space-y-2">
          {league.map((x) => {
            const r = Number(x.stats?.return_pct ?? 0);
            return (
              <li key={x.config.id} className="grid grid-cols-[3.2rem_minmax(0,1fr)_4.2rem] items-center gap-2 text-sm">
                <span className="num text-xs text-mute">{String(x.config.timeframe).toUpperCase()}</span>
                <span className="relative h-2 rounded-full" style={{ background: "rgb(var(--raised))" }}>
                  <i className="absolute inset-y-0 rounded-full" style={{ left: r >= 0 ? "50%" : `${50 - (Math.abs(r) / maxAbs) * 50}%`, width: `${(Math.abs(r) / maxAbs) * 50}%`, background: `rgb(var(${r >= 0 ? "--bull" : "--bear"}))` }} />
                  <i className="absolute inset-y-[-3px] left-1/2 w-px" style={{ background: "var(--hair-strong)" }} />
                </span>
                <span className={`num text-right ${tone(r)}`}>{fmtPctRaw(r)}</span>
              </li>
            );
          })}
        </ul>
        <p className="mt-2 text-xs text-mute">Return since each bot started, after fees. Practice money.</p>
      </div>
      <div className="min-w-0 space-y-3">
        <div className="metric-strip">
          <Tile variant="strip" label="Bots running" value={String(bots.length)} sub={`${bots.filter((x) => x.config.enabled).length} active`} />
          <Tile variant="strip" label="Average return" value={fmtPctRaw(avg)} valueClass={tone(avg)} sub="since each bot started" />
          <Tile variant="strip" label="Trades" value={String(tot)} sub={`${open} open now`} />
          <Tile variant="strip" label="Leading" value={best ? String(best.config.timeframe).toUpperCase() : "—"} valueClass="text-accent" sub={best ? fmtPctRaw(best.stats?.return_pct) : undefined} />
        </div>
        <div>
          <div className="mb-1 flex items-baseline justify-between text-xs text-mute"><span>Return of every bot over time</span><span>after fees</span></div>
          <FleetPulse curves={curves} />
        </div>
      </div>
    </section>
  );
}
