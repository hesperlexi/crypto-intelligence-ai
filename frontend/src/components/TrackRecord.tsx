// Public track record: every trade signal since launch with its real outcome, the models' results on past data
import { PnlGradients } from "./PnlGradients";
import ResultsBoard from "./ResultsBoard";
// they never trained on (a labelled simulation), and the demo bots. Readable without an account.
import { Segmented, TabStrip } from "./kit";
import { AdjustHistory, UpdatedBadge } from "./SignalAdjust";
import { useState } from "react";
import { useApi } from "../lib/api";
import { base, fmtDate, fmtPrice, fmtTime, isNum } from "../lib/format";
import { CoinAvatar } from "./Polish";
import { Info } from "./ui";
import { Explain, useIsPro } from "../lib/mode";
import { useIsAdmin } from "../lib/session";
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
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-28 w-full" preserveAspectRatio="none" role="img" aria-label={label}>
      <defs><PnlGradients id={id} y0={y(0)} top={0} bottom={h} /></defs>
      <line x1="0" x2={w} y1={y(0)} y2={y(0)} stroke="currentColor" className="text-glass/30" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
      <path d={`${d}L${w},${y(0).toFixed(1)}L0,${y(0).toFixed(1)}Z`} fill={`url(#${id}-f)`} />
      <path d={d} fill="none" stroke={`url(#${id}-s)`} strokeWidth="2.6" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}

/** v2.16 "Last 7 days": calls of the record that closed in the last 7 days, after fees (same numbers as the weekly
 *  Telegram card; views/track_record.last_7d). A sample-size note under 30 trades. */
function Last7({ r }: { r: any }) {
  const one = (x: any) => (x ? <><span className="font-semibold">{base(x.symbol)}</span> <span className="text-mute">{x.side} {String(x.timeframe).toUpperCase()}</span> <span className={`num font-semibold ${tone(x.return_pct)}`}>{pct(x.return_pct, 2)}</span></> : "—");
  return (
    <section className="panel p-4" aria-label="Last 7 days">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="label">Last 7 days</h2>
        <span className="text-xs text-mute">After fees, wins and losses<Info label="How the 7-day figures are counted">{r.basis}</Info></span>
      </div>
      {r.closed ? (
        <>
          <dl className="statement-facts mt-3 grid grid-cols-2 rounded-xl border border-glass/[0.07] sm:grid-cols-4">
            <Fact k="Closed" v={String(r.closed)} sub={`${r.wins} won, ${r.losses} lost`} />
            <Fact k="Win rate" v={rate(r.win_rate)} sub="after fees" />
            <Fact k="Average per signal" v={pct(r.avg_return_pct, 2)} cls={tone(r.avg_return_pct)} sub="after fees, no leverage" />
            <Fact k="Total" v={pct(r.total_return_pct)} cls={tone(r.total_return_pct)} sub="equal size per signal" />
          </dl>
          <div className="mt-3 grid gap-1.5 text-sm sm:grid-cols-2">
            <div className="flex flex-wrap items-baseline gap-x-1.5"><span className="w-12 text-xs text-mute">Best</span>{one(r.best)}</div>
            <div className="flex flex-wrap items-baseline gap-x-1.5"><span className="w-12 text-xs text-mute">Worst</span>{one(r.worst)}</div>
          </div>
        </>
      ) : null}
      {r.sample_note && <p className={`mt-2 text-xs ${r.closed ? "text-warn" : "text-mute"}`}>{r.sample_note}</p>}
    </section>
  );
}

function Fact({ k, v, sub, cls = "" }: { k: string; v: string; sub?: string; cls?: string }) {
  return (
    <div className="min-w-0 px-4 py-3 sm:px-5">
      <dt className="text-xs text-mute">{k}</dt>
      <dd className={`num mt-0.5 text-lg font-semibold tracking-tight ${cls}`}>{v}</dd>
      {sub && <dd className="text-xs text-mute">{sub}</dd>}
    </div>
  );
}

export default function TrackRecord({ compact = false }: { compact?: boolean }) {
  const v = useApi<any>("/track-record");
  const [tab, setTab] = useState<"live" | "tested" | "bots">("live");
  const [show, setShow] = useState<"all" | "running" | "waiting" | "closed">("all");
  const [detail, setDetail] = useState<string | null>(null);   // row key; the row is looked up again when the view refreshes
  const pro = useIsPro();
  const admin = useIsAdmin();
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
  // v2.22 (owner, 14 Nov 2026): open and closed calls apart - Running / Waiting entry / Closed / All
  const stOf = (x: any) => (x.status === "OPEN" ? (x.fill_status === "PENDING" ? "waiting" : "running") : "closed");
  const cnt = (k: string) => sigs.filter((x) => stOf(x) === k).length;
  const rows = show === "all" ? sigs : sigs.filter((x) => stOf(x) === show);
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
        <div className="panel panel-hero flex flex-col items-center px-5 py-9 text-center">
          <svg aria-hidden="true" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="rgb(var(--accent))" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></svg>
          <h2 className="mt-3 font-display text-xl font-semibold">No closed trades yet</h2>
          <p className="mt-1 max-w-md text-sm text-mute">
            {d.record_since ? `Counting since ${fmtDate(d.record_since)}. ` : ""}Every result, win or loss, appears here when a signal closes.
            {sigs.length ? ` ${sigs.filter((x) => x.status === "OPEN").length} open now.` : ""}
          </p>
        </div>
      ) : !compact ? (
        <ResultsBoard d={d} sigs={sigs} roi={roi} admin={admin} avgTested={avgTested} proven={edge.length} />
      ) : (
        /* the statement: one lead figure, the curve beside it, the supporting facts underneath */
        <section className="panel panel-hero p-0" aria-label="Track record statement">
          <div className="grid gap-4 p-4 sm:p-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)] lg:items-end">
            <div className="min-w-0">
              <div className="label">{roi ? `Total ROI on margin${s.net ? ", after fees" : ""}` : s.net ? "Total result after fees" : "Total price move"}</div>
              <div className={`num statement-figure mt-1 font-semibold ${tone(roi ? s.total_roi_pct : s.total_return_pct)}`}>{pct(roi ? s.total_roi_pct : s.total_return_pct)}</div>
              <p className="mt-1.5 text-sm text-mute">
                {s.closed ?? 0} closed {s.closed === 1 ? "signal" : "signals"}{d.record_since ? ` since ${fmtDate(d.record_since)}` : d.since ? ` since ${fmtDate(d.since)}` : ""}{d.record_since_tf?.["15m"] ? ` (15M since ${fmtDate(d.record_since_tf["15m"])})` : ""}, {d.live?.open ?? 0} open now{d.testing_since ? ", testing" : ""}.
              </p>
            </div>
            {(d.live?.curve?.length ?? 0) > 1 && <div className="min-w-0"><Curve pts={d.live.curve} roi={roi} /></div>}
          </div>
          <dl className="statement-facts grid grid-cols-2 border-t border-glass/[0.07] sm:grid-cols-4">
            <Fact k="Win rate" v={rate(s.win_rate)} sub={s.closed ? `${s.closed} closed` : "first results soon"} />
            {roi ? <Fact k="Average ROI per signal" v={pct(s.avg_roi_pct, 2)} cls={tone(s.avg_roi_pct)} sub={`${pct(s.avg_return_pct, 2)} price ${s.net ? "after fees" : "before fees"}`} />
              : <Fact k={s.net ? "Average per signal" : "Average price move"} v={pct(s.avg_return_pct, 2)} cls={tone(s.avg_return_pct)} sub={s.net ? "after fees" : "before fees"} />}
            <Fact k={s.net ? "Total price result" : "Total price move"} v={pct(s.total_return_pct)} cls={tone(s.total_return_pct)} sub="equal size, no leverage" />
            {/* v2.17: the next-candle hit rate is admin only (it overstates) */}
            {admin ? <Fact k="Model hit rate (next candle)" v={rate(avgTested)} sub={`admin only, ${edge.length} proven`} />
              : <Fact k="Open now" v={String(d.live?.open ?? 0)} sub="live, not final" />}
          </dl>
        </section>
      )}
      {!compact && fresh && d.last_7d && <Last7 r={d.last_7d} />}
      {d.excluded_tests?.map((x: any) => (
        <p key={`${x.timeframe}${x.grade}`} className="px-1 text-xs text-mute">
          {x.timeframe.toUpperCase()} grade {x.grade} was tested {fmtDate(x.from)}–{fmtDate(x.to)} and stopped; its {x.calls} call{x.calls === 1 ? "" : "s"} ({x.wins} won, {x.losses} lost{isNum(x.total_net_pct) ? `, ${x.total_net_pct > 0 ? "+" : ""}${x.total_net_pct.toFixed(1)}% in total after fees` : ""}{x.open ? `, ${x.open} still open` : ""}) are not counted. They stay in the Signal log.
        </p>
      ))}
      {(d.restart?.text || d.withdrawn?.count > 0) && (
        <p className="px-1 text-xs text-mute">
          {d.restart?.text}{d.restart?.text && d.withdrawn?.count > 0 ? " " : ""}
          {d.withdrawn?.count > 0 && <>{d.withdrawn.count} call{d.withdrawn.count === 1 ? " was" : "s were"} withdrawn by the admin within {d.withdrawn.window_min} min of publication and {d.withdrawn.count === 1 ? "is" : "are"} not counted.</>}
        </p>
      )}
      <Explain>{d.results_net ? "Results are after fees (trading costs and funding). ROI on margin = result × suggested leverage (15m: 10–50x chosen by engine). Leverage magnifies losses." : "ROI on margin = price move × suggested leverage. Leverage magnifies losses."}</Explain>
      {compact ? null : (
        <section className="panel p-0">
          <TabStrip label="Track record" value={tab} onChange={setTab} className="px-2 pt-2"
            options={[["live", `Live signals (${sigs.length})`], ...(pro ? [["tested", "Tested on unseen data"]] as const : []), ["bots", "Demo bots"]] as const} />
          {(tab === "live" || (!pro && tab === "tested")) && (
            <div className="overflow-x-auto">
              {sigs.length > 0 && (
                <div className="px-3 pt-3">
                  <Segmented label="Show" value={show} onChange={setShow}
                    options={[["all", `All ${sigs.length}`], ["running", `Running ${cnt("running")}`], ["waiting", `Waiting entry ${cnt("waiting")}`], ["closed", `Closed ${cnt("closed")}`]] as const} />
                </div>
              )}
              {sigs.length > 0 && !rows.length && <p className="p-4 text-sm text-mute">Nothing here right now.</p>}
              {!rows.length ? (sigs.length ? null : <p className="p-4 text-sm text-mute">No trade signals yet.</p>) : (<>
                {/* phones: one card per signal, the result on margin up front */}
                <ul className="divide-y divide-glass/[0.06] sm:hidden">
                  {rows.map((x, i) => {
                    const [lab, cls] = statusOf(x);
                    return (
                      <li key={i} {...rowProps(x)} className="cursor-pointer px-4 py-3 outline-none transition-colors hover:bg-glass/[0.03] focus-visible:bg-glass/[0.05] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/60">
                        {/* below 360 px (Z Fold cover) the result takes its own row under the coin, so neither is squeezed */}
                        <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5 min-[360px]:flex-nowrap">
                          <div className="flex min-w-0 flex-1 items-center gap-2.5">
                            <CoinAvatar symbol={x.symbol} size={30} />
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-x-1.5"><span className="font-semibold">{base(x.symbol)}</span><span className={`text-xs font-bold ${x.side === "LONG" ? "text-bull" : "text-bear"}`}>{x.side}</span><span className="text-xs text-mute">{String(x.timeframe).toUpperCase()}</span>{x.grade && <span className={`inline-flex h-4 min-w-4 items-center justify-center rounded border px-1 text-xs font-bold ${x.grade === "A" ? "border-accent/50 bg-accent/15 text-accent" : "border-warn/45 bg-warn/10 text-warn"}`}>{x.grade}</span>}</div>
                              <div className={`mt-0.5 text-xs font-semibold ${cls}`}>{lab} <span className="num whitespace-nowrap font-normal text-mute">· {fmtDate(x.created_at)}</span></div>
                            </div>
                          </div>
                          <div className="shrink-0 text-right max-[359px]:basis-full min-[360px]:max-w-[45%]">{isOpen(x) ? <LiveRoi x={x} size="md" /> : <RoiFigure x={x} size="md" />}</div>
                        </div>
                        <dl className="num mt-2 grid grid-cols-3 gap-2 text-xs">
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
                    {rows.map((x, i) => {
                      const [lab, cls] = statusOf(x);
                      return (
                        <tr key={i} {...rowProps(x)} className="cursor-pointer outline-none focus-visible:bg-glass/[0.05] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/60">
                          <td><div className="flex items-center gap-2"><CoinAvatar symbol={x.symbol} size={22} /><span className="font-semibold">{base(x.symbol)}</span><span className={`text-xs font-bold ${x.side === "LONG" ? "text-bull" : "text-bear"}`}>{x.side}</span><span className="text-xs text-mute">{String(x.timeframe).toUpperCase()}</span></div><div className="num mt-0.5 pl-[30px] text-xs text-mute">{fmtTime(x.created_at)}</div></td>
                          <td className="text-center">{x.grade ? <span className={`inline-flex h-5 min-w-5 items-center justify-center rounded-md border px-1.5 text-xs font-bold ${x.grade === "A" ? "border-accent/50 bg-accent/15 text-accent" : "border-warn/45 bg-warn/10 text-warn"}`}>{x.grade}</span> : <span className="text-mute">—</span>}</td>
                          <td className="num text-right">{fmtPrice(x.entry)}</td><td className="num text-right text-bear">{fmtPrice(x.stop)}</td><td className="num text-right text-bull">{fmtPrice(x.tp1)}</td>
                          <td className={`text-xs font-semibold ${cls}`}>{lab}{isOpen(x) && <LiveResult x={x} />}<RecordExtras x={x} /></td>
                          <td className="text-right align-middle">{isOpen(x) ? <LiveRoi x={x} /> : <RoiFigure x={x} size="sm" />}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </>)}
              <p className="px-4 py-2 text-xs text-mute">Tap a signal for details. <span className="font-semibold text-accent">Live</span> = not final until closed.</p>
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
                      <td className={`text-xs font-semibold ${t.edge ? "text-bull" : "text-mute"}`}>{t.edge ? "Proven" : "None"}</td>
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
              <p className="px-4 pt-3 text-xs text-mute"><b className="text-accent">Scorecard</b> bots take exactly the Signals-page calls, fees included.</p>
              <table className="grid-table mt-2 min-w-[600px]">
                <thead><tr><th>Bot (virtual money)</th><th className="text-right">Trades</th><th className="text-right">Win rate</th><th className="text-right">Return</th><th className="text-right">Buy &amp; hold</th><th className="text-right">Max drop</th></tr></thead>
                <tbody>
                  {(d.bots ?? []).map((b: any, i: number) => (
                    <tr key={i} className={b.scorecard ? "bg-accent/[0.05]" : ""}><td>{b.name}{b.scorecard && <span className="ml-2 rounded-md border border-accent/40 bg-accent/15 px-1.5 py-0.5 text-xs font-semibold leading-none text-accent">Scorecard</span>}<div className="text-xs text-mute">{b.started_at ? `since ${fmtDate(b.started_at)}` : ""}</div></td>
                      <td className="num text-right">{b.trades ?? 0}</td><td className="num text-right">{rate(b.win_rate)}</td>
                      <td className={`num text-right font-semibold ${tone(b.return_pct)}`}>{pct(b.return_pct)}</td>
                      <td className={`num text-right ${tone(b.benchmark_return_pct)}`}>{pct(b.benchmark_return_pct)}</td>
                      <td className="num text-right text-bear">{isNum(b.max_drawdown_pct) ? `${b.max_drawdown_pct.toFixed(1)}%` : "—"}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="border-t border-glass/[0.06] px-4 py-2.5 text-xs text-mute">Wins and losses alike, never edited. {d.results_net ? "Signals: after fees." : "Before fees."} Past results do not guarantee future results. {d.method?.live && <Info label="How results are counted">{d.method.live}</Info>}</p>
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
      {isNum(x.peak_pct) && <span className="num text-xs text-mute" title="Best open profit reached">peak {pct(x.peak_pct, 1)}</span>}
    </div>
    {adj && <AdjustHistory adj={adj} compact />}
    </div>
  );
}
