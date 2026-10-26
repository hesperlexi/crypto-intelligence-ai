import { useMemo, useState } from "react";
import LineChart, { Series } from "../components/LineChart";
import { Badge, Card, Empty, ErrorBox, Loading, Note, Row, Stat } from "../components/ui";
import { put, useApi } from "../lib/api";
import { DASH, fmtNum, fmtPctRaw, fmtPrice, fmtProb, fmtTime, isNum, tone } from "../lib/format";
import { useLive } from "../lib/live";
import { useIsAdmin } from "../lib/session";

const TFS = ["1h", "4h", "12h", "1d"];

const SCORECARD = ["futures-signal-ab-1h", "futures-signal-ab-4h"];

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
      setMsg(`${done} Changes take effect on the next engine cycle (within about 10 minutes).`);
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
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold tracking-tight">Demo trading bots</h1>
          <Badge tone="warn">Demo only — virtual money</Badge>
        </div>
        {admin && <div className="flex flex-wrap gap-2">
          <button className="btn" onClick={() => add("decision")}>+ Signal bot</button>
          <button className="btn" onClick={() => add("prediction")}>+ Prediction tracker</button>
          <button className="btn" onClick={() => add("decision", "futures")}>+ Futures signal bot</button>
          <button className="btn" onClick={() => add("prediction", "futures")}>+ Futures tracker</button>
        </div>}
      </div>
      <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Market">
        {(["all", "spot", "futures"] as const).map((m) => (
          <button key={m} className={`btn px-3 py-1 text-xs ${market === m ? "btn-on" : ""}`} aria-pressed={market === m} onClick={() => setMarket(m)}>
            {m === "all" ? "All bots" : m === "spot" ? "Spot" : "Futures"}
          </button>
        ))}
      </div>
      <Card title="How the bots work">
        <div className="grid gap-4 text-sm md:grid-cols-2">
          <p><span className="font-medium text-text">Signal bots</span> <span className="text-mute">trade only the engine's final decisions (BUY, BUY ON PULLBACK, SELL) using the trade plan's entry, stop and three targets. A third of the position closes at each target; the stop moves to break-even after TP1 and trails to TP1 after TP2. Grade A+B bots also take the moderate (grade B) calls, so you can compare. They show what following the signals would have earned.</span></p>
          {admin && <p><span className="font-medium text-text">Prediction trackers</span> <span className="text-mute">take every model call (UP → long, DOWN → short) and hold it for exactly one bar, with no other filter. They show how often the raw predictions are right and what they pay. Only you see them.</span></p>}
          <p className="md:col-span-2"><span className="font-medium text-text">Futures bots</span> <span className="text-mute">trade the same calls as USDT perpetual futures with isolated margin: only the margin (position ÷ leverage) is set aside, futures fees (0.05%) apply, funding is paid or received every 8 hours, and a position is liquidated — losing its margin — if price reaches the liquidation price. With “safe leverage” on, a signal bot lowers its leverage so liquidation always sits well beyond the stop. Position size still comes from the stop, so leverage changes the margin used, not the risk per trade.</span></p>
        </div>
        <Note>The engine runs about every 5–10 minutes. Entries fill at the price available when it runs, plus spread, slippage and fees. Stops and targets are checked against every 15-minute candle, and when one candle touches both, the stop counts first. Only trades taken after a bot started are counted.</Note>
      </Card>
      {msg && <p className="text-sm text-accent">{msg}</p>}
      {b.error && <ErrorBox error={b.error} retry={b.reload} />}
      {!b.data && b.loading && <Loading what="Loading bots" />}
      {shown.map((bot: any) => (
        <BotCard key={bot.config.id} bot={bot} cfg={cfgList.find((c) => c.id === bot.config.id) ?? bot.config}
          admin={admin} editing={editing === bot.config.id} onEdit={() => setEditing(editing === bot.config.id ? null : bot.config.id)}
          onSave={(patch: any) => update(bot.config.id, patch, "Saved.")} onToggle={() => update(bot.config.id, { enabled: !bot.config.enabled }, bot.config.enabled ? "Paused." : "Resumed.")}
          onReset={() => reset(bot.config.id)} onDelete={() => remove(bot.config.id)} />
      ))}
      {cfgList.filter((c) => !(b.data?.bots ?? []).some((x: any) => x.config.id === c.id)).map((c) => (
        <Card key={c.id} title={c.name}><Empty>Waiting for the next engine cycle to start this bot.</Empty></Card>
      ))}
      {b.data && !b.data.bots?.length && !cfgList.length && <Empty>No bots yet. The engine creates the default spot and futures bots on its next run.</Empty>}
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
    { name: "Bot equity", color: "#f0b90b", points: bot.equity_curve.map((p: any) => ({ ts: p.ts, value: p.equity })) },
    { name: "Buy & hold (same coins)", color: "#6f7e91", dashed: true, points: bot.equity_curve.filter((p: any) => isNum(p.benchmark)).map((p: any) => ({ ts: p.ts, value: p.benchmark })) },
  ], [bot.equity_curve]);
  const live = bot.positions.map((p: any) => {
    const px = tickers[p.symbol]?.last ?? null;
    const u = px != null ? p.side * p.qty_open * (px - p.entry) : null;
    const lev = p.lev ?? 1;
    return { ...p, px, u, lev, upct: px != null ? p.side * (px / p.entry - 1) * 100 * lev : null };
  });
  return (
    <Card title={<span className="flex items-center gap-2"><span className="text-text">{bot.config.name}</span><Badge tone={isPred ? "accent" : "mute"}>{isPred ? "prediction tracker" : "signal bot"}</Badge><Badge tone="mute">{bot.config.timeframe}</Badge>{fut ? <Badge tone="warn">futures {bot.config.leverage}x{bot.config.safe_leverage && !isPred ? " max" : ""}</Badge> : <Badge tone="mute">spot</Badge>}{!bot.config.enabled && <Badge tone="warn">paused</Badge>}</span>}
      right={!admin ? undefined : <div className="flex gap-1">
        <button className="btn px-2 py-0.5 text-xs" onClick={onToggle}>{bot.config.enabled ? "Pause" : "Resume"}</button>
        <button className="btn px-2 py-0.5 text-xs" onClick={onEdit}>{editing ? "Close" : "Settings"}</button>
        <button className="btn px-2 py-0.5 text-xs" onClick={onReset}>Reset</button>
        <button className="btn px-2 py-0.5 text-xs hover:text-bear" onClick={onDelete}>Delete</button>
      </div>}>
      {editing && <Editor cfg={cfg} onSave={onSave} />}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 xl:grid-cols-8">
        <Stat label="Equity" value={`$${fmtNum(st.equity)}`} sub={`started $${fmtNum(bot.config.starting_balance, 0)} · ${fmtTime(st.started_at)}`} />
        <Stat label="Return" value={fmtPctRaw(s.return_pct)} className={tone(s.return_pct)} sub={`buy & hold ${fmtPctRaw(s.benchmark_return_pct)}`} />
        <Stat label="Closed trades" value={s.trades} sub={`${s.open_positions} open`} />
        <Stat label={isPred ? "Prediction accuracy" : "Direction right"} value={fmtProb(s.direction_accuracy, 1)} sub={s.direction_ci95 ? `95% CI ${fmtProb(s.direction_ci95[0])}–${fmtProb(s.direction_ci95[1])}` : DASH} />
        <Stat label="Win rate (after costs)" value={fmtProb(s.win_rate, 1)} />
        <Stat label="Profit factor" value={fmtNum(s.profit_factor)} sub={isNum(s.avg_r) ? `avg ${s.avg_r.toFixed(2)} R` : undefined} />
        <Stat label="Max drawdown" value={fmtPctRaw(s.max_drawdown_pct, 1)} className="text-bear" />
        <Stat label="Fees paid" value={`$${fmtNum(s.fees_paid)}`} />
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
      {s.note && <Note>{s.note}</Note>}
      {bot.equity_curve.length > 1 && <div className="mt-4"><LineChart series={series} height={220} /></div>}

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <div>
          <div className="label mb-1">Open positions{bot.pending.length ? ` · ${bot.pending.length} pending limit order(s)` : ""}</div>
          {live.length || bot.pending.length ? (
            <div className="overflow-x-auto"><table className="grid-table">
              <thead><tr><th>Coin</th><th>Side</th><th className="text-right">Entry</th><th className="text-right">Now</th><th className="text-right">P&L{fut ? " (on margin)" : ""}</th>{fut && <th className="text-right">Liquidation</th>}<th className="text-right">{isPred ? "Closes" : "Stop / TP hit"}</th></tr></thead>
              <tbody>
                {live.map((p: any) => (
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
          ) : <Empty>{isPred ? "No open predictions right now." : "No open positions. Signal bots only trade when every check passes, so long quiet stretches are normal."}</Empty>}
        </div>
        <div>
          <div className="label mb-1">Accuracy by {s.confidence_key === "p_max" ? "model probability" : "signal confidence"}</div>
          {s.by_confidence?.length ? (
            <div className="overflow-x-auto"><table className="grid-table">
              <thead><tr><th>Bucket</th><th className="text-right">Trades</th><th className="text-right">Predicted</th><th className="text-right">Direction right</th><th className="text-right">Avg return</th></tr></thead>
              <tbody>{s.by_confidence.map((r: any) => (
                <tr key={r.lo}><td className="num">{fmtProb(r.lo)}–{fmtProb(r.hi)}</td><td className="num text-right">{r.n}</td><td className="num text-right">{fmtProb(r.mean, 1)}</td>
                  <td className="num text-right">{fmtProb(r.hit_rate, 1)}</td><td className={`num text-right ${tone(r.avg_return_pct)}`}>{fmtPctRaw(r.avg_return_pct)}</td></tr>
              ))}</tbody>
            </table></div>
          ) : <Empty>Appears after the first closed trades.</Empty>}
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
          {s.trades > 0 && s.trades < 30 && <Note>Fewer than 30 closed trades: these percentages can still move a lot. Read the confidence interval, not just the headline.</Note>}
        </div>
      </div>

      <div className="mt-4">
        <div className="label mb-1">Closed trades ({bot.trades.length} most recent)</div>
        {bot.trades.length ? (
          <div className="max-h-80 overflow-auto"><table className="grid-table">
            <thead><tr><th>Closed</th><th>Coin</th><th>Side</th><th>{isPred ? "Predicted" : "Decision"}</th><th className="text-right">{isPred ? "Probability" : "Confidence"}</th><th className="text-right">Entry</th><th className="text-right">Exit</th><th className="text-right">Return</th>{fut && <th className="text-right">Lev · on margin</th>}<th className="text-right">P&L</th><th>Exit</th><th>Right?</th></tr></thead>
            <tbody>{bot.trades.map((t: any) => (
              <tr key={t.id}>
                <td className="text-mute">{fmtTime(t.closed_at)}</td><td className="font-medium">{t.symbol}</td>
                <td className={t.side > 0 ? "text-bull" : "text-bear"}>{t.side > 0 ? "LONG" : "SHORT"}</td>
                <td>{isPred ? t.info.predicted : t.info.decision}</td>
                <td className="num text-right">{fmtProb(isPred ? t.info.p_max : t.info.confidence)}</td>
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
