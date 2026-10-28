// Public track record: every trade signal since launch with its real outcome, the models' results on past data
// they never trained on (a labelled simulation), and the demo bots. Readable without an account.
import { useState } from "react";
import { useApi } from "../lib/api";
import { base, fmtDate, fmtPrice, fmtTime, isNum } from "../lib/format";
import { CoinAvatar } from "./Polish";

const pct = (v: unknown, d = 1) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "—");
const rate = (v: unknown) => (isNum(v) ? `${Math.round(v * 100)}%` : "—");
const tone = (v: unknown) => (isNum(v) ? (v > 0 ? "text-bull" : v < 0 ? "text-bear" : "") : "text-mute");
const STATUS: Record<string, [string, string]> = {
  TP3: ["Target 3", "text-bull"], TP2: ["Target 2", "text-bull"], TP1: ["Target 1", "text-bull"],
  STOPPED: ["Stopped", "text-bear"], EXPIRED: ["Expired", "text-mute"], OPEN: ["Open", "text-accent"],
};

function Curve({ pts }: { pts: { ts: number; cum_return_pct: number }[] }) {
  if (pts.length < 2) return null;
  const w = 600, h = 120, ys = pts.map((p) => p.cum_return_pct), lo = Math.min(0, ...ys), hi = Math.max(0, ...ys);
  const x = (i: number) => (i / (pts.length - 1)) * w, y = (v: number) => h - ((v - lo) / (hi - lo || 1)) * h;
  const d = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.cum_return_pct).toFixed(1)}`).join("");
  const up = ys[ys.length - 1] >= 0;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-28 w-full" preserveAspectRatio="none" role="img" aria-label="Cumulative result of all closed signals">
      <line x1="0" x2={w} y1={y(0)} y2={y(0)} stroke="currentColor" className="text-glass/20" strokeDasharray="4 4" />
      <path d={d} fill="none" stroke={up ? "rgb(var(--bull))" : "rgb(var(--bear))"} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Kpi({ k, v, sub, cls = "" }: { k: string; v: string; sub?: string; cls?: string }) {
  return <div className="panel p-3"><div className="text-[11px] uppercase tracking-wide text-mute">{k}</div><div className={`num mt-1 text-xl font-semibold ${cls}`}>{v}</div>{sub && <div className="mt-0.5 text-[11px] text-mute">{sub}</div>}</div>;
}

export default function TrackRecord({ compact = false }: { compact?: boolean }) {
  const v = useApi<any>("/track-record");
  const [tab, setTab] = useState<"live" | "tested" | "bots">("live");
  const d = v.data;
  if (!d && v.error) return <p className="panel p-4 text-center text-sm text-mute">The track record is being prepared and appears after the next engine run.</p>;
  if (!d) return <div className="skeleton h-40 rounded-xl" />;
  const s = d.live?.summary ?? {};
  const tested: any[] = d.tested ?? [];
  const edge = tested.filter((t) => t.edge);
  const avgTested = edge.length ? edge.reduce((a, t) => a + (t.selective_hit_rate ?? 0), 0) / edge.length : null;
  const sigs: any[] = d.live?.signals ?? [];

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Kpi k="Closed signals" v={String(s.closed ?? 0)} sub={d.record_since ? `${d.testing_since ? "testing period · " : ""}since ${fmtDate(d.record_since)}${d.record_since_tf?.["15m"] ? ` (15M since ${fmtDate(d.record_since_tf["15m"])}, rule updates)` : ""} · ${d.live?.open ?? 0} open` : d.since ? `since ${fmtDate(d.since)} · ${d.live?.open ?? 0} open` : undefined} />
        <Kpi k="Win rate (live)" v={rate(s.win_rate)} sub={s.closed ? `${s.closed} closed signals` : "first results soon"} />
        <Kpi k="Avg result per signal" v={pct(s.avg_return_pct, 2)} cls={tone(s.avg_return_pct)} sub="before fees" />
        <Kpi k="Tested hit rate" v={rate(avgTested)} sub={`${edge.length} coin/timeframes with a proven edge`} />
      </div>
      {(d.live?.curve?.length ?? 0) > 1 && (
        <div className="panel px-3 pt-2">
          <div className="flex items-center justify-between text-xs text-mute"><span>Cumulative result of every closed signal (equal size)</span><span className={`num font-semibold ${tone(s.total_return_pct)}`}>{pct(s.total_return_pct)}</span></div>
          <Curve pts={d.live.curve} />
        </div>
      )}
      {compact ? null : (
        <section className="panel p-0">
          <div className="flex gap-1 overflow-x-auto border-b border-glass/[0.06] px-2 pt-2" role="tablist">
            {([["live", `Live signals (${sigs.length})`], ["tested", "Tested on unseen data"], ["bots", "Demo bots"]] as const).map(([k, l]) => (
              <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
                className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm ${tab === k ? "border-accent font-semibold text-text" : "border-transparent text-mute hover:text-text"}`}>{l}</button>
            ))}
          </div>
          {tab === "live" && (
            <div className="overflow-x-auto">
              {!sigs.length ? <p className="p-4 text-sm text-mute">No trade signals yet. Each one appears here the moment it is published, and its result is filled in as the price moves.</p> : (
                <table className="w-full text-sm sm:min-w-[640px]">
                  <thead><tr className="text-left text-[11px] uppercase tracking-wide text-mute"><th className="px-3 py-2">Signal</th><th>Grade</th><th className="hidden sm:table-cell">Entry</th><th className="hidden sm:table-cell">Stop</th><th className="hidden sm:table-cell">Target 1</th><th>Result</th><th className="pr-3 text-right">Return</th></tr></thead>
                  <tbody className="divide-y divide-glass/[0.06]">
                    {sigs.map((x, i) => {
                      const [lab, cls] = STATUS[x.status] ?? [x.status, ""];
                      return (
                        <tr key={i}>
                          <td className="px-3 py-2"><div className="flex items-center gap-2"><CoinAvatar symbol={x.symbol} size={20} /><span className="font-semibold">{base(x.symbol)}</span><span className={`text-xs font-bold ${x.side === "LONG" ? "text-bull" : "text-bear"}`}>{x.side}</span><span className="text-xs text-mute">{String(x.timeframe).toUpperCase()}</span></div><div className="text-[11px] text-mute">{fmtTime(x.created_at)}</div></td>
                          <td>{x.grade ? <span className={`rounded px-1.5 text-[11px] font-bold ${x.grade === "A" ? "bg-accent/15 text-accent" : "bg-warn/15 text-warn"}`}>{x.grade}</span> : <span className="text-mute">—</span>}</td>
                          <td className="num hidden sm:table-cell">{fmtPrice(x.entry)}</td><td className="num hidden text-bear sm:table-cell">{fmtPrice(x.stop)}</td><td className="num hidden text-bull sm:table-cell">{fmtPrice(x.tp1)}</td>
                          <td className={`text-xs font-semibold ${cls}`}>{lab}</td>
                          <td className={`num pr-3 text-right font-semibold ${tone(x.return_pct)}`}>{x.status === "OPEN" ? "…" : pct(x.return_pct, 2)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          )}
          {tab === "tested" && (
            <div className="overflow-x-auto">
              <p className="px-3 pt-3 text-xs text-mute">{d.method?.tested} A coin/timeframe without a proven edge gets no AI-led signals.</p>
              <table className="mt-2 w-full min-w-[560px] text-sm">
                <thead><tr className="text-left text-[11px] uppercase tracking-wide text-mute"><th className="px-3 py-2">Coin</th><th>Edge</th><th>Hit rate (selective)</th><th>95% range</th><th>Calls / day</th><th className="pr-3 text-right">Tested over</th></tr></thead>
                <tbody className="divide-y divide-glass/[0.06]">
                  {tested.map((t, i) => (
                    <tr key={i} className={t.edge ? "" : "opacity-60"}>
                      <td className="px-3 py-2"><span className="font-semibold">{base(t.symbol)}</span> <span className="text-xs text-mute">{String(t.timeframe).toUpperCase()}</span></td>
                      <td className={`text-xs font-bold ${t.edge ? "text-bull" : "text-mute"}`}>{t.edge ? "PROVEN" : "none"}</td>
                      <td className="num">{rate(t.selective_hit_rate)}</td>
                      <td className="num text-xs text-mute">{t.selective_ci95 ? `${rate(t.selective_ci95[0])}–${rate(t.selective_ci95[1])}` : "—"}</td>
                      <td className="num">{isNum(t.calls_per_day) ? t.calls_per_day.toFixed(1) : "—"}</td>
                      <td className="num pr-3 text-right text-xs text-mute">{isNum(t.tested_days) ? `${Math.round(t.tested_days)} days` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {tab === "bots" && (
            <div className="overflow-x-auto">
              <p className="px-3 pt-3 text-xs text-mute">Bots trade automatically with virtual money, around the clock, on every coin. The two <b className="text-accent">APP SCORECARD</b> bots take exactly the futures calls members see on the Signals page (grades A and B), with stop-loss, three targets and fees, so their result is the app's real performance.</p>
              <table className="w-full min-w-[560px] text-sm">
                <thead><tr className="text-left text-[11px] uppercase tracking-wide text-mute"><th className="px-3 py-2">Bot (virtual money)</th><th>Trades</th><th>Win rate</th><th>Return</th><th>Buy &amp; hold</th><th className="pr-3 text-right">Max drop</th></tr></thead>
                <tbody className="divide-y divide-glass/[0.06]">
                  {(d.bots ?? []).map((b: any, i: number) => (
                    <tr key={i} className={b.scorecard ? "bg-accent/[0.05]" : ""}><td className="px-3 py-2">{b.name}{b.scorecard && <span className="ml-2 rounded bg-accent/15 px-1.5 text-[10px] font-bold text-accent">APP SCORECARD</span>}<div className="text-[11px] text-mute">{b.started_at ? `since ${fmtDate(b.started_at)}` : ""}</div></td>
                      <td className="num">{b.trades ?? 0}</td><td className="num">{rate(b.win_rate)}</td>
                      <td className={`num font-semibold ${tone(b.return_pct)}`}>{pct(b.return_pct)}</td>
                      <td className={`num ${tone(b.benchmark_return_pct)}`}>{pct(b.benchmark_return_pct)}</td>
                      <td className="num pr-3 text-right text-bear">{isNum(b.max_drawdown_pct) ? `${b.max_drawdown_pct.toFixed(1)}%` : "—"}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="border-t border-glass/[0.06] px-3 py-2 text-[11px] text-mute">{d.method?.live} Nothing is removed or edited. Past results do not guarantee future results.</p>
        </section>
      )}
    </div>
  );
}
