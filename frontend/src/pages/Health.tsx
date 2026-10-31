import { Badge, Card, Empty, ErrorBox, Loading, Note, Row, Stat } from "../components/ui";
import { useApi } from "../lib/api";
import { ago, DASH, fmtNum, fmtTime, isNum } from "../lib/format";
import { useLive } from "../lib/live";

const toneOf = (s: string) => (["LIVE", "OK", "active", "done"].includes(s) ? "bull" : ["DOWN", "failed"].includes(s) ? "bear" : ["POLLING", "running", "queued"].includes(s) ? "accent" : "warn") as "bull" | "bear" | "accent" | "warn";

const FREE_LIMIT = 20_000;      // Firebase free (Spark) plan: document writes per day (day = midnight US Pacific)
const DEFAULT_BUDGET = 15_000;  // backend sinks.FIRESTORE_DAILY_BUDGET default: the engine goes lean above it
const arr = (x: any): any[] => (Array.isArray(x) ? x : []);

/** Firestore writes today against the engine's budget and the free plan's hard limit. */
function WritesCard({ e }: { e: any }) {
  const n = isNum(e?.firestore_writes_today) ? e.firestore_writes_today : null;
  const budget = isNum(e?.firestore_write_budget) ? e.firestore_write_budget : DEFAULT_BUDGET;
  const limit = isNum(e?.firestore_free_limit) ? e.firestore_free_limit : FREE_LIMIT;
  const engineBudget = isNum(e?.firestore_engine_budget) ? e.firestore_engine_budget : budget;
  const reserve = isNum(e?.firestore_member_reserve) ? e.firestore_member_reserve : null;
  const pct = n != null ? Math.min(100, (n / limit) * 100) : 0;
  const tone = n == null ? "" : n >= limit * 0.95 ? "text-bear" : n >= engineBudget || e?.firestore_lean ? "text-warn" : "text-bull";
  return (
    <Card title="Database writes today (Firebase free plan)" right={e?.firestore_lean ? <Badge tone="warn">lean mode</Badge> : n != null ? <Badge tone="bull">normal</Badge> : undefined}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <Stat label="Engine writes today" value={<span className={tone}>{n != null ? fmtNum(n, 0) : DASH}</span>}
          sub={`budget ${fmtNum(budget, 0)} · free limit ${fmtNum(limit, 0)} a day (resets at midnight US Pacific)`} />
        <div className="text-right text-xs text-mute">
          {reserve != null && <div>kept for members: <span className="num text-text">{fmtNum(reserve, 0)}</span>{isNum(e?.firestore_members_active) ? ` (${e.firestore_members_active} active in 24 h)` : ""}</div>}
          <div>engine goes lean at <span className="num text-text">{fmtNum(engineBudget, 0)}</span></div>
        </div>
      </div>
      <div className="relative mt-3 h-2.5 overflow-hidden rounded-full bg-glass/[0.08]" role="img" aria-label={n != null ? `${fmtNum(n, 0)} of ${fmtNum(limit, 0)} writes used` : "no data"}>
        <div className={`h-full rounded-full ${n != null && n >= engineBudget ? "bg-warn" : "bg-accent"}`} style={{ width: `${pct}%` }} />
        <div className="absolute inset-y-0 w-px bg-text/60" style={{ left: `${Math.min(100, (engineBudget / limit) * 100)}%` }} title="lean from here" />
      </div>
      <Note>Counts only the engine's own writes; members' writes (presence, practice trades, alerts) also use the {fmtNum(limit, 0)} limit, so the engine keeps room for them. Above its budget it publishes only the essentials, every 30 min.</Note>
    </Card>
  );
}

export default function Health() {
  const h = useApi<any>("/system/health", 10000);
  const { connected, feed } = useLive();
  const raw = h.data;
  // the engine publishes {error} instead of the view when it could not build it (e.g. too large for one document)
  const viewError: string | null = raw && typeof raw === "object" && raw.error && !raw.status ? String(raw.error) : null;
  const d = raw && !viewError ? { ...raw, engine: raw.engine ?? {}, market_data: raw.market_data ?? {}, exchange: raw.exchange ?? {},
    database: raw.database ?? {}, config: raw.config ?? {}, series: arr(raw.series), models: arr(raw.models),
    model_libraries: arr(raw.model_libraries), recent_errors: arr(raw.recent_errors), safety: arr(raw.safety) } : null;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="page-title">System health</h1>
        {d?.status && <Badge tone={toneOf(d.status)}>● {d.status}</Badge>}
      </div>
      {h.error && <ErrorBox error={h.error} retry={h.reload} />}
      {viewError && <ErrorBox error={`The engine could not publish the health report: ${viewError}`} retry={h.reload} />}
      {!d && h.loading && <Loading />}
      {d && (
        <>
          <WritesCard e={d.engine} />
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <Card title="Prediction engine">
              <Stat label="Last cycle" value={d.engine?.last_tick_finished ? ago(d.engine.last_tick_finished) : "not run yet"}
                sub={`runs every ${d.engine?.schedule_minutes ?? 5} min · ${d.engine?.ticks ?? 0} cycles so far`}
                className={d.engine?.last_tick_finished && Date.now() - d.engine.last_tick_finished > 45 * 60_000 ? "text-warn" : ""} />
              <div className="mt-3">
                <Row k="Cycle duration" v={isNum(d.engine?.last_tick_seconds) ? `${d.engine.last_tick_seconds}s` : DASH} />
                <Row k="Failed steps" v={arr(d.engine.failed_steps).length ? arr(d.engine.failed_steps).join(", ") : "none"} className={arr(d.engine.failed_steps).length ? "text-warn" : ""} />
                <Row k="Market data host" v={d.engine?.data_host?.replace("https://", "") ?? DASH} />
                <Row k="Last training run" v={d.engine?.last_train?.finished_at ? ago(d.engine.last_train.finished_at) : "not yet"} />
              </div>
              {d.engine?.last_tick_finished && Date.now() - d.engine.last_tick_finished > 45 * 60_000 && <Note>The engine is late. GitHub sometimes delays scheduled runs; if it stays late for hours, check the Actions tab of the repository.</Note>}
            </Card>
            <Card title="Live prices (this browser)">
              <Stat label="Binance WebSocket" value={<Badge tone={connected ? "bull" : "bear"}>{connected ? "● LIVE" : "Disconnected"}</Badge>} sub="reconnects automatically" />
              <div className="mt-3"><Row k="Last tick" v={ago(feed?.last_update_ms)} /></div>
            </Card>
            <Card title="Market data at last cycle">
              <Stat label="Candle data quality" value={isNum(d.market_data.quality_pct) ? `${fmtNum(d.market_data.quality_pct, 2)}%` : DASH} />
              <div className="mt-3">
                <Row k="Stale series" v={d.market_data.stale_series ?? DASH} className={d.market_data.stale_series ? "text-warn" : ""} />
                <Row k="API errors in cycle" v={d.exchange.errors ?? DASH} className={d.exchange.errors ? "text-warn" : ""} />
                <Row k="Clock difference" v={isNum(d.exchange.clock_skew_ms) ? `${d.exchange.clock_skew_ms} ms` : DASH} />
              </div>
              {d.exchange.last_error && <Note>Last error: {d.exchange.last_error}</Note>}
            </Card>
            <Card title="Configuration">
              <Row k="Mode" v="Analysis + demo only" />
              <Row k="Database (engine state)" v={d.database.engine ? `${d.database.engine} · ${d.database.ok ? "OK" : "DOWN"}` : DASH} />
              <Row k="Retrain interval" v={isNum(d.config.retrain_interval_h) ? `${d.config.retrain_interval_h}h` : DASH} />
              <Row k="Deep models" v={d.config.deep_models ? "enabled" : "disabled"} />
            </Card>
          </div>
          <Card title="Safety switch" right={<Badge tone={d.safety?.length ? "warn" : "bull"}>{d.safety?.length ? `${d.safety.length} paused` : "all active"}</Badge>}>
            {d.safety?.length ? (
              <ul className="space-y-1.5 text-sm">
                {d.safety.map((x: any) => (
                  <li key={x.symbol + x.timeframe} className="flex flex-wrap justify-between gap-2 rounded-lg bg-glass/[0.04] px-2.5 py-1.5">
                    <span className="font-medium">{x.symbol} <span className="uppercase text-mute">{x.timeframe}</span></span>
                    <span className="text-xs text-mute">paused {ago(x.paused_at)}{x.trigger ? ` · last ${x.trigger.n} signals avg ${Number(x.trigger.avg_return_pct).toFixed(2)}%, ${Math.round(x.trigger.tp1_rate * 100)}% hit TP1` : ""}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="text-sm text-mute">No coin or timeframe is paused.</p>}
            <Note>A coin/timeframe pauses when its last 25 live signals lost on average and fewer than 40% reached TP1. It resumes by itself once 8 hidden practice trades recover.</Note>
          </Card>
          <Card title="Candle series">
            <div className="max-h-96 overflow-auto"><table className="grid-table">
              <thead><tr><th>Asset</th><th>TF</th><th>Status</th><th className="text-right">Candles</th><th className="text-right">Missing</th><th className="text-right">Duplicates</th><th className="text-right">Malformed</th><th className="text-right">Quality</th><th>Last candle closed</th></tr></thead>
              <tbody>{d.series.map((s: any) => (
                <tr key={s.symbol + s.timeframe}><td className="font-medium">{s.symbol}</td><td className="uppercase text-mute">{s.timeframe}</td><td><Badge tone={toneOf(s.status)}>{s.status}</Badge></td>
                  <td className="num text-right">{s.candles}</td><td className={`num text-right ${s.missing ? "text-warn" : ""}`}>{s.missing}</td><td className="num text-right">{s.duplicates}</td><td className={`num text-right ${s.malformed ? "text-warn" : ""}`}>{s.malformed}</td>
                  <td className="num text-right">{isNum(s.quality_pct) ? `${fmtNum(s.quality_pct, 2)}%` : DASH}</td><td className="text-mute">{isNum(s.age_s) ? ago(Date.now() - s.age_s * 1000) : DASH}</td></tr>
              ))}</tbody>
            </table></div>
            {!d.series.length && <Empty>No series yet</Empty>}
          </Card>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card title="Models">
              <div className="max-h-96 overflow-auto"><table className="grid-table">
                <thead><tr><th>Asset</th><th>TF</th><th>State</th><th>Edge</th><th className="text-right">Age</th><th>Detail</th></tr></thead>
                <tbody>{d.models.map((m: any) => (
                  <tr key={m.symbol + m.timeframe}><td className="font-medium">{m.symbol}</td><td className="uppercase text-mute">{m.timeframe}</td>
                    <td><Badge tone={toneOf(m.state)}>{m.state}{m.state === "running" && isNum(m.progress) ? ` ${(m.progress * 100).toFixed(0)}%` : ""}</Badge></td>
                    <td className="text-xs text-mute">{m.edge_confirmed == null ? DASH : m.edge_confirmed ? "confirmed" : "none"}</td><td className="num text-right text-mute">{isNum(m.age_h) ? `${m.age_h}h` : DASH}</td>
                    <td className="max-w-[16rem] truncate text-xs text-mute" title={m.message ?? ""}>{m.message ?? m.version ?? ""}</td></tr>
                ))}</tbody>
              </table></div>
            </Card>
            <Card title="Model libraries & recent errors">
              {d.model_libraries.map((l: any) => <Row key={l.name} k={l.label} v={l.available ? "available" : l.reason} className={l.available ? "text-bull" : "text-mute"} />)}
              <div className="label mb-1 mt-4">Recent errors</div>
              {d.recent_errors.length ? d.recent_errors.slice(0, 8).map((e: any, i: number) => <p key={i} className="border-b border-line/50 py-1 text-xs last:border-0"><span className="text-mute">{fmtTime(e.ts)} · {e.where}: </span><span className="text-warn">{e.error}</span></p>) : <p className="text-sm text-mute">None</p>}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
