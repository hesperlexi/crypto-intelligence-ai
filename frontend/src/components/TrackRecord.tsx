// Public track record: every trade signal since launch with its real outcome, the models' results on past data
// they never trained on (a labelled simulation), and the demo bots. Readable without an account.
import { AdjustHistory, UpdatedBadge } from "./SignalAdjust";
import { useState } from "react";
import { useApi } from "../lib/api";
import { base, fmtDate, fmtPrice, fmtTime, isNum } from "../lib/format";
import { CoinAvatar } from "./Polish";
import { Info } from "./ui";
import { Explain, useIsPro } from "../lib/mode";
import { managedLabel, fillLabel, Pill, RoiFigure } from "./SignalExtras";
import { isOpen, LiveResult, LiveRoi, RecordSheet, statusOf } from "./RecordDetails";

const pct = (v: unknown, d = 1) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "—");
const rate = (v: unknown) => (isNum(v) ? `${Math.round(v * 100)}%` : "—");
const tone = (v: unknown) => (isNum(v) ? (v > 0 ? "text-bull" : v < 0 ? "text-bear" : "") : "text-mute");
// a row opens its details sheet; clicks on the row's own buttons / links (seal pill) stay with them
const fromControl = (e: React.SyntheticEvent) => (e.target as HTMLElement).closest("button, a") !== null;

export function Curve({ pts, roi, id = "tr-fill", label = "Cumulative result of all closed signals" }: { pts: { ts: number; cum_return_pct: number; cum_roi_pct?: number }[]; roi: boolean; id?: string; label?: string }) {
  if (pts.length < 2) return null;
  const val = (p: { cum_return_pct: number; cum_roi_pct?: number }) => (roi && isNum(p.cum_roi_pct) ? p.cum_roi_pct : p.cum_return_pct);
  const w = 600, h = 120, ys = pts.map(val), lo = Math.min(0, ...ys), hi = Math.max(0, ...ys);
  const x = (i: number) => (i / (pts.length - 1)) * w, y = (v: number) => h - ((v - lo) / (hi - lo || 1)) * h;
  const d = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(val(p)).toFixed(1)}`).join("");
  const up = ys[ys.length - 1] >= 0;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-28 w-full" preserveAspectRatio="none" role="img" aria-label={label}>
      <defs><linearGradient id={id} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor={up ? "rgb(var(--bull))" : "rgb(var(--bear))"} stopOpacity="0.22" /><stop offset="1" stopColor={up ? "rgb(var(--bull))" : "rgb(var(--bear))"} stopOpacity="0" /></linearGradient></defs>
      <line x1="0" x2={w} y1={y(0)} y2={y(0)} stroke="currentColor" className="text-glass/20" strokeDasharray="4 4" />
      <path d={`${d}L${w},${y(0).toFixed(1)}L0,${y(0).toFixed(1)}Z`} fill={`url(#${id})`} />
      <path d={d} fill="none" stroke={up ? "rgb(var(--bull))" : "rgb(var(--bear))"} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Kpi({ k, v, sub, cls = "" }: { k: string; v: string; sub?: string; cls?: string }) {
  return <div className="panel p-4"><div className="label">{k}</div><div className={`num mt-1.5 text-2xl font-semibold leading-none ${cls}`}>{v}</div>{sub && <div className="mt-1.5 text-[11px] leading-snug text-mute">{sub}</div>}</div>;
}

export default function TrackRecord({ compact = false }: { compact?: boolean }) {
  const v = useApi<any>("/track-record");
  const [tab, setTab] = useState<"live" | "tested" | "bots">("live");
  const [detail, setDetail] = useState<string | null>(null);   // row key; the row is looked up again when the view refreshes
  const pro = useIsPro();
  const d = v.data;
  if (!d && v.error) return <p className="panel p-4 text-center text-sm text-mute">The track record appears after the next update.</p>;
  if (!d) return <div className="skeleton h-40 rounded-xl" />;
  const s = d.live?.summary ?? {};
  const tested: any[] = d.tested ?? [];
  const edge = tested.filter((t) => t.edge);
  const avgTested = edge.length ? edge.reduce((a, t) => a + (t.selective_hit_rate ?? 0), 0) / edge.length : null;
  // open calls first (newest first), then closed ones (most recently closed first)
  const sigs: any[] = [...(d.live?.signals ?? [])].sort((a, b) => {
    const ao = a.status === "OPEN" ? 0 : 1, bo = b.status === "OPEN" ? 0 : 1;
    if (ao !== bo) return ao - bo;
    return ao === 0 ? (b.created_at ?? 0) - (a.created_at ?? 0) : (b.closed_at ?? b.created_at ?? 0) - (a.closed_at ?? a.created_at ?? 0);
  });
  const keyOf = (x: any) => `${x.symbol}|${x.timeframe}|${x.created_at}`;
  const shown = detail ? sigs.find((x) => keyOf(x) === detail) : null;
  const rowProps = (x: any) => ({
    "data-record-row": "", tabIndex: 0, "aria-haspopup": "dialog" as const,
    "aria-label": `${x.symbol} ${x.side} ${String(x.timeframe).toUpperCase()}: details`,
    onClick: (e: React.MouseEvent) => { if (!fromControl(e)) setDetail(keyOf(x)); },
    onKeyDown: (e: React.KeyboardEvent) => { if ((e.key === "Enter" || e.key === " ") && e.target === e.currentTarget) { e.preventDefault(); setDetail(keyOf(x)); } },
  });

  const fresh = !(s.closed > 0);
  const roi = isNum(s.avg_roi_pct);          // ROI on margin available (v2.6 record); else the price move, labelled   // nothing closed yet (e.g. right after a fresh start of the record)
  return (
    <div className="space-y-3">
      {fresh ? (
        <div className="panel flex flex-col items-center px-5 py-8 text-center">
          <svg aria-hidden="true" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="rgb(var(--accent))" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></svg>
          <h2 className="mt-3 text-lg font-semibold">No trades yet</h2>
          <p className="mt-1 max-w-md text-sm text-mute">
            {d.record_since ? `Since ${fmtDate(d.record_since)}. ` : ""}Every result, win or loss, appears here when a signal closes.
            {sigs.length ? ` ${sigs.filter((x) => x.status === "OPEN").length} open now.` : ""}
          </p>
        </div>
      ) : (
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi k="Closed signals" v={String(s.closed ?? 0)} sub={d.record_since ? `${d.testing_since ? "testing · " : ""}since ${fmtDate(d.record_since)}${d.record_since_tf?.["15m"] ? ` (15M ${fmtDate(d.record_since_tf["15m"])})` : ""} · ${d.live?.open ?? 0} open` : d.since ? `since ${fmtDate(d.since)} · ${d.live?.open ?? 0} open` : undefined} />
        <Kpi k="Win rate (live)" v={rate(s.win_rate)} sub={s.closed ? `${s.closed} closed signals` : "first results soon"} />
        {roi ? <Kpi k="Avg ROI per signal" v={pct(s.avg_roi_pct, 2)} cls={tone(s.avg_roi_pct)} sub={`on margin · price ${pct(s.avg_return_pct, 2)} · before fees`} />
          : <Kpi k="Avg price move per signal" v={pct(s.avg_return_pct, 2)} cls={tone(s.avg_return_pct)} sub="before fees" />}
        {pro ? <Kpi k="Tested hit rate" v={rate(avgTested)} sub={`${edge.length} coin/timeframes with a proven edge`} />
          : roi ? <Kpi k="Total ROI on margin" v={pct(s.total_roi_pct)} cls={tone(s.total_roi_pct)} sub={`all closed signals · price ${pct(s.total_return_pct)}`} />
          : <Kpi k="Total price move" v={pct(s.total_return_pct)} cls={tone(s.total_return_pct)} sub="all closed signals, equal size" />}
      </div>
      )}
      <Explain>ROI on margin = price move × suggested leverage. Leverage magnifies losses.</Explain>
      {(d.live?.curve?.length ?? 0) > 1 && (
        <div className="panel px-4 pt-3">
          <div className="flex items-center justify-between text-xs text-mute"><span>{roi ? "Cumulative ROI on margin" : "Cumulative price move"}</span><span className={`num font-semibold ${tone(roi ? s.total_roi_pct : s.total_return_pct)}`}>{pct(roi ? s.total_roi_pct : s.total_return_pct)}</span></div>
          <Curve pts={d.live.curve} roi={roi} />
        </div>
      )}
      {compact ? null : (
        <section className="panel p-0">
          <div className="flex gap-1 overflow-x-auto border-b border-glass/[0.06] px-2 pt-2" role="tablist">
            {([["live", `Live signals (${sigs.length})`], ...(pro ? [["tested", "Tested on unseen data"]] as const : []), ["bots", "Demo bots"]] as const).map(([k, l]) => (
              <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
                className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm ${tab === k ? "border-accent font-semibold text-text" : "border-transparent text-mute hover:text-text"}`}>{l}</button>
            ))}
          </div>
          {(tab === "live" || (!pro && tab === "tested")) && (
            <div className="overflow-x-auto">
              {!sigs.length ? <p className="p-4 text-sm text-mute">No trade signals yet.</p> : (<>
                {/* phones: one card per signal, the result on margin up front */}
                <ul className="divide-y divide-glass/[0.06] sm:hidden">
                  {sigs.map((x, i) => {
                    const [lab, cls] = statusOf(x);
                    return (
                      <li key={i} {...rowProps(x)} className="cursor-pointer px-4 py-3 outline-none transition-colors hover:bg-glass/[0.03] focus-visible:bg-glass/[0.05] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/60">
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex min-w-0 items-center gap-2.5">
                            <CoinAvatar symbol={x.symbol} size={30} />
                            <div className="min-w-0">
                              <div className="flex items-center gap-1.5"><span className="font-semibold">{base(x.symbol)}</span><span className={`text-[11px] font-bold ${x.side === "LONG" ? "text-bull" : "text-bear"}`}>{x.side}</span><span className="text-[11px] text-mute">{String(x.timeframe).toUpperCase()}</span>{x.grade && <span className={`inline-flex h-4 min-w-4 items-center justify-center rounded border px-1 text-[10px] font-bold ${x.grade === "A" ? "border-accent/50 bg-accent/15 text-accent" : "border-warn/45 bg-warn/10 text-warn"}`}>{x.grade}</span>}</div>
                              <div className={`mt-0.5 whitespace-nowrap text-[11px] font-semibold ${cls}`}>{lab} <span className="num font-normal text-mute">· {fmtDate(x.created_at)}</span></div>
                            </div>
                          </div>
                          {isOpen(x) ? <LiveRoi x={x} size="md" /> : <RoiFigure x={x} size="md" />}
                        </div>
                        <dl className="num mt-2 grid grid-cols-3 gap-2 text-[11px]">
                          <div><dt className="text-mute">Entry</dt><dd className="font-medium">{fmtPrice(x.entry)}</dd></div>
                          <div className="text-center"><dt className="text-mute">Stop</dt><dd className="font-medium text-bear">{fmtPrice(x.stop)}</dd></div>
                          <div className="text-right"><dt className="text-mute">Target 1</dt><dd className="font-medium text-bull">{fmtPrice(x.tp1)}</dd></div>
                        </dl>
                        {isOpen(x) && <div className="mt-1.5"><LiveResult x={x} /></div>}
                        <RecordExtras x={x} />
                      </li>
                    );
                  })}
                </ul>
                <table className="grid-table hidden min-w-[720px] sm:table">
                  <thead><tr><th>Signal</th><th className="text-center">Grade</th><th className="text-right">Entry</th><th className="text-right">Stop</th><th className="text-right">Target 1</th><th>Result</th><th className="text-right">ROI on margin</th></tr></thead>
                  <tbody>
                    {sigs.map((x, i) => {
                      const [lab, cls] = statusOf(x);
                      return (
                        <tr key={i} {...rowProps(x)} className="cursor-pointer outline-none focus-visible:bg-glass/[0.05] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/60">
                          <td><div className="flex items-center gap-2"><CoinAvatar symbol={x.symbol} size={22} /><span className="font-semibold">{base(x.symbol)}</span><span className={`text-xs font-bold ${x.side === "LONG" ? "text-bull" : "text-bear"}`}>{x.side}</span><span className="text-xs text-mute">{String(x.timeframe).toUpperCase()}</span></div><div className="num mt-0.5 pl-[30px] text-[11px] text-mute">{fmtTime(x.created_at)}</div></td>
                          <td className="text-center">{x.grade ? <span className={`inline-flex h-5 min-w-5 items-center justify-center rounded-md border px-1.5 text-[11px] font-bold ${x.grade === "A" ? "border-accent/50 bg-accent/15 text-accent" : "border-warn/45 bg-warn/10 text-warn"}`}>{x.grade}</span> : <span className="text-mute">—</span>}</td>
                          <td className="num text-right">{fmtPrice(x.entry)}</td><td className="num text-right text-bear">{fmtPrice(x.stop)}</td><td className="num text-right text-bull">{fmtPrice(x.tp1)}</td>
                          <td className={`text-xs font-semibold ${cls}`}>{lab}{isOpen(x) && <LiveResult x={x} />}<RecordExtras x={x} /></td>
                          <td className="text-right align-middle">{isOpen(x) ? <LiveRoi x={x} /> : <RoiFigure x={x} size="sm" />}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </>)}
              <p className="px-4 py-2 text-[11px] text-mute">Tap a signal for details. <span className="font-semibold text-accent">Live</span> = not final until closed.</p>
            </div>
          )}
          {shown && <RecordSheet x={shown} onClose={() => setDetail(null)} />}
          {tab === "tested" && pro && (
            <div className="overflow-x-auto">
              <p className="px-4 pt-3 text-xs text-mute">Simulation on unseen data, not live results. {d.method?.tested && <Info>{d.method.tested}</Info>}</p>
              <table className="grid-table mt-2 min-w-[560px]">
                <thead><tr><th>Coin</th><th>Edge</th><th className="text-right">Hit rate (selective)</th><th className="text-right">95% range</th><th className="text-right">Calls / day</th><th className="text-right">Tested over</th></tr></thead>
                <tbody>
                  {tested.map((t, i) => (
                    <tr key={i} className={t.edge ? "" : "opacity-60"}>
                      <td><span className="font-semibold">{base(t.symbol)}</span> <span className="text-xs text-mute">{String(t.timeframe).toUpperCase()}</span></td>
                      <td className={`text-xs font-bold ${t.edge ? "text-bull" : "text-mute"}`}>{t.edge ? "PROVEN" : "none"}</td>
                      <td className="num text-right">{rate(t.selective_hit_rate)}</td>
                      <td className="num text-right text-xs text-mute">{t.selective_ci95 ? `${rate(t.selective_ci95[0])}–${rate(t.selective_ci95[1])}` : "—"}</td>
                      <td className="num text-right">{isNum(t.calls_per_day) ? t.calls_per_day.toFixed(1) : "—"}</td>
                      <td className="num text-right text-xs text-mute">{isNum(t.tested_days) ? `${Math.round(t.tested_days)} days` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {tab === "bots" && (
            <div className="overflow-x-auto">
              <p className="px-4 pt-3 text-xs text-mute">Virtual money. <b className="text-accent">APP SCORECARD</b> bots take exactly the Signals-page calls, fees included.</p>
              <table className="grid-table mt-2 min-w-[600px]">
                <thead><tr><th>Bot (virtual money)</th><th className="text-right">Trades</th><th className="text-right">Win rate</th><th className="text-right">Return</th><th className="text-right">Buy &amp; hold</th><th className="text-right">Max drop</th></tr></thead>
                <tbody>
                  {(d.bots ?? []).map((b: any, i: number) => (
                    <tr key={i} className={b.scorecard ? "bg-accent/[0.05]" : ""}><td>{b.name}{b.scorecard && <span className="ml-2 rounded-md border border-accent/40 bg-accent/15 px-1.5 py-0.5 text-[11px] font-bold leading-none text-accent">APP SCORECARD</span>}<div className="text-[11px] text-mute">{b.started_at ? `since ${fmtDate(b.started_at)}` : ""}</div></td>
                      <td className="num text-right">{b.trades ?? 0}</td><td className="num text-right">{rate(b.win_rate)}</td>
                      <td className={`num text-right font-semibold ${tone(b.return_pct)}`}>{pct(b.return_pct)}</td>
                      <td className={`num text-right ${tone(b.benchmark_return_pct)}`}>{pct(b.benchmark_return_pct)}</td>
                      <td className="num text-right text-bear">{isNum(b.max_drawdown_pct) ? `${b.max_drawdown_pct.toFixed(1)}%` : "—"}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="border-t border-glass/[0.06] px-4 py-2.5 text-[11px] text-mute">Wins and losses alike, never edited. Before fees. Past results do not guarantee future results. {d.method?.live && <Info label="How results are counted">{d.method.live}</Info>}</p>
        </section>
      )}
    </div>
  );
}

/** v1 extras on a record row (fill status, managed exit, peak). Old rows show nothing extra. */
function RecordExtras({ x }: { x: any }) {
  const fill = fillLabel(x.fill_status);
  const managed = x.managed === 1 ? managedLabel(x.exit_reason) : null;
  const adj = x.adjustments?.length ? x.adjustments : null;
  if (!fill && !managed && !isNum(x.peak_pct) && !adj && !x.proof) return null;
  return (
    <div className="font-normal">
    <div className="mt-0.5 flex flex-wrap items-center gap-1">
      <UpdatedBadge adj={adj} />
      {x.exit_reason === "admin_stop" && <Pill tone="warn" title="Closed at the stop-loss the admin moved (public change, shown below)">Admin stop</Pill>}
      {x.exit_reason === "admin_close" && <Pill tone="warn" title="Closed by the admin at the market price (public, shown below); the result is what that price gave">Closed by admin</Pill>}
      {fill && <Pill tone={fill[1]}>{fill[0]}</Pill>}
      {managed && <Pill tone="accent">{managed}</Pill>}
      {isNum(x.peak_pct) && <span className="num text-[11px] text-mute" title="Best open profit reached">peak {pct(x.peak_pct, 1)}</span>}
    </div>
    {adj && <AdjustHistory adj={adj} compact />}
    </div>
  );
}
