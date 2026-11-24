// v2.51 Results redesign (owner, 17 Nov 2026: "I don't like the graph on the results page - redesign the results page").
// No line or bar charts: the record read like a statement - the lead figure with a period switch (all results / last 7
// days), a win-rate ring, how every closed signal ended (one stacked bar + a table of outcomes) and the recent form as
// tiles. Same data as before (views/track_record: summary, last_7d, the rows; after fees), nothing new read.
import { useMemo, useState } from "react";
import { base, fmtDate, isNum } from "../lib/format";
import { Segmented } from "./kit";
import { CoinAvatar } from "./Polish";
import { Ring } from "./Premium";

const pct = (v: unknown, d = 1) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "—");
const tone = (v: unknown) => (isNum(v) ? (v > 0 ? "text-bull" : v < 0 ? "text-bear" : "") : "text-mute");
const DUBAI = 4 * 3_600_000;
const OUTCOMES = [
  ["TP3", "Target 3", "o-tp3"], ["TP2", "Target 2", "o-tp2"], ["TP1", "Target 1", "o-tp1"],
  ["EXPIRED", "Time limit", "o-exp"], ["STOPPED", "Stop-loss", "o-stop"],
] as const;

type Row = any;
type Period = "all" | "today" | "week" | "7d" | "30d";
const PERIOD_LABEL: Record<Period, string> = { all: "All results", today: "Today", week: "This week", "7d": "Last 7 days", "30d": "Last 30 days" };
const PERIOD_SUB: Record<Period, string> = { all: "", today: "closed today", week: "closed this week (from Monday)", "7d": "closed in the last 7 days", "30d": "closed in the last 30 days" };
const PL = ({ long, short }: { long: string; short: string }) => <><span className="hidden sm:inline">{long}</span><span className="sm:hidden">{short}</span></>;
// start of a period in the viewer's own time (today = from midnight, this week = from Monday midnight)
function periodStart(p: Period): number {
  const now = new Date();
  if (p === "7d") return now.getTime() - 7 * 86_400_000;
  if (p === "30d") return now.getTime() - 30 * 86_400_000;
  if (p === "all") return 0;
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (p === "week") d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return d.getTime();
}

export default function ResultsBoard({ d, sigs, roi, admin, avgTested, proven }: {
  d: any; sigs: Row[]; roi: boolean; admin: boolean; avgTested: number | null; proven: number;
}) {
  const [period, setPeriod] = useState<Period>("all");
  const s = d.live?.summary ?? {};
  const closed = useMemo(() => sigs.filter((x) => OUTCOMES.some(([k]) => k === x.status) && isNum(x.return_pct))
    .sort((a, b) => (b.closed_at ?? 0) - (a.closed_at ?? 0)), [sigs]);
  const inPeriod = period === "all" ? closed : closed.filter((x) => (x.closed_at ?? 0) >= periodStart(period));
  const won = inPeriod.filter((x) => x.return_pct > 0).length, lost = inPeriod.length - won;
  const open = d.live?.open ?? 0;
  // a chosen period: the engine's own last-7-days summary for "7 days", else figures from the closed rows (after fees)
  const w7 = d.last_7d;
  const ps = useMemo(() => {
    if (period === "all") return null;
    if (period === "7d" && w7) return w7;
    const r = inPeriod.map((x) => x.return_pct as number);
    const best = inPeriod.reduce<Row | null>((a, x) => (!a || x.return_pct > a.return_pct ? x : a), null);
    const worst = inPeriod.reduce<Row | null>((a, x) => (!a || x.return_pct < a.return_pct ? x : a), null);
    return { closed: r.length, wins: won, losses: lost, win_rate: r.length ? won / r.length : null,
      total_return_pct: r.length ? r.reduce((a, b) => a + b, 0) : null, avg_return_pct: r.length ? r.reduce((a, b) => a + b, 0) / r.length : null,
      best, worst, sample_note: r.length && r.length < 30 ? `${r.length} closed so far in this period: too few to judge (30 or more needed).` : null };
  }, [period, inPeriod, w7, won, lost]);
  const winRate = ps ? ps.win_rate : s.win_rate;
  const lead = ps ? ps.total_return_pct : roi ? s.total_roi_pct : s.total_return_pct;
  const leadLabel = ps ? `${PERIOD_LABEL[period]}, after fees` : roi ? `Total ROI on margin${s.net ? ", after fees" : ""}` : s.net ? "Total result after fees" : "Total price move";

  const weeks = useMemo(() => {
    const m = new Map<number, number>();
    for (const x of closed) {
      const day = Math.floor((x.closed_at + DUBAI) / 86_400_000);
      const wk = day - ((day + 3) % 7);                              // Monday
      m.set(wk, (m.get(wk) ?? 0) + x.return_pct);
    }
    const all = [...m.entries()].sort((a, b) => a[0] - b[0]);
    const months = new Map<string, number>();
    for (const x of closed) {
      const k = new Date(x.closed_at + DUBAI).toISOString().slice(0, 7);
      months.set(k, (months.get(k) ?? 0) + x.return_pct);
    }
    return {
      best: all.length ? all.reduce((a, b) => (b[1] > a[1] ? b : a)) : null,
      worst: all.length ? all.reduce((a, b) => (b[1] < a[1] ? b : a)) : null,
      months: [...months.entries()].slice(-4),
    };
  }, [closed]);
  const wkLabel = (wk: number) => new Date(wk * 86_400_000).toLocaleDateString(undefined, { day: "numeric", month: "short", timeZone: "UTC" });

  return (
    <div className="space-y-3">
      {/* the statement */}
      <section className="panel panel-hero rb-hero p-0" aria-label="Track record statement">
        <div className="grid gap-5 p-4 sm:p-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] lg:items-center">
          <div className="min-w-0">
            <div className="rb-periods"><Segmented label="Period" value={period} onChange={setPeriod}
              options={[["all", <PL key="a" long={d.record_since ? `Since ${fmtDate(d.record_since)}` : "All results"} short="All" />], ["today", "Today"],
                ["week", <PL key="w" long="This week" short="Week" />], ["7d", <PL key="7" long="Last 7 days" short="7 days" />], ["30d", <PL key="3" long="Last 30 days" short="30 days" />]] as const} /></div>
            <div className="label mt-4">{leadLabel}</div>
            <div className={`num statement-figure mt-1 font-semibold ${tone(lead)}`}>{pct(lead)}</div>
            <p className="mt-1.5 text-sm text-mute">
              {ps
                ? `${ps.closed ?? inPeriod.length} ${PERIOD_SUB[period]} · equal size per signal, no leverage`
                : `${s.closed ?? 0} closed ${s.closed === 1 ? "signal" : "signals"}${d.record_since_tf?.["15m"] ? ` (15M since ${fmtDate(d.record_since_tf["15m"])})` : ""} · ${open} open now${d.testing_since ? " · testing" : ""}`}
            </p>
            <div className="rb-trust mt-4">
              <span>✓ Every trade shown, losses included</span><span>✓ Real entry prices</span><span>✓ After fees and funding</span>
            </div>
          </div>
          <div className="rb-score">
            <Ring value={isNum(winRate) ? winRate : 0} size={132} stroke={11} tone="--bull" label={`Win rate ${isNum(winRate) ? Math.round(winRate * 100) : 0}%`}>
              <div><div className="num text-3xl font-semibold">{isNum(winRate) ? `${Math.round(winRate * 100)}%` : "—"}</div><div className="text-xs text-mute">won</div></div>
            </Ring>
            <ul className="rb-tally">
              <li><span className="rb-dot bg-bull" />Won<b className="num">{ps ? (ps.wins ?? won) : won}</b></li>
              <li><span className="rb-dot bg-bear" />Lost<b className="num">{ps ? (ps.losses ?? lost) : lost}</b></li>
              <li><span className="rb-dot live-dot bg-accent" />Open now<b className="num">{open}</b></li>
            </ul>
          </div>
        </div>
        <dl className="statement-facts grid grid-cols-2 border-t border-glass/[0.07] sm:grid-cols-4">
          {ps ? <>
            <Fact k="Average per signal" v={pct(ps.avg_return_pct, 2)} cls={tone(ps.avg_return_pct)} sub="after fees, no leverage" />
            <Fact k="Best" v={ps.best ? pct(ps.best.return_pct, 2) : "—"} cls={tone(ps.best?.return_pct)} sub={ps.best ? `${base(ps.best.symbol)} ${ps.best.side} ${String(ps.best.timeframe).toUpperCase()}` : ""} />
            <Fact k="Worst" v={ps.worst ? pct(ps.worst.return_pct, 2) : "—"} cls={tone(ps.worst?.return_pct)} sub={ps.worst ? `${base(ps.worst.symbol)} ${ps.worst.side} ${String(ps.worst.timeframe).toUpperCase()}` : ""} />
            <Fact k="Closed" v={String(ps.closed ?? 0)} sub={ps.sample_note ? "small sample" : PERIOD_LABEL[period].toLowerCase()} />
          </> : <>
            {roi ? <Fact k="Average ROI per signal" v={pct(s.avg_roi_pct, 2)} cls={tone(s.avg_roi_pct)} sub={`${pct(s.avg_return_pct, 2)} price ${s.net ? "after fees" : "before fees"}`} />
              : <Fact k={s.net ? "Average per signal" : "Average price move"} v={pct(s.avg_return_pct, 2)} cls={tone(s.avg_return_pct)} sub={s.net ? "after fees" : "before fees"} />}
            <Fact k={s.net ? "Total price result" : "Total price move"} v={pct(s.total_return_pct)} cls={tone(s.total_return_pct)} sub="equal size, no leverage" />
            <Fact k="Best week" v={weeks.best ? pct(weeks.best[1], 2) : "—"} cls={tone(weeks.best?.[1])} sub={weeks.best ? `from ${wkLabel(weeks.best[0])}` : ""} />
            {admin ? <Fact k="Model hit rate (next candle)" v={isNum(avgTested) ? `${Math.round(avgTested * 100)}%` : "—"} sub={`admin only, ${proven} proven`} />
              : <Fact k="Worst week" v={weeks.worst ? pct(weeks.worst[1], 2) : "—"} cls={tone(weeks.worst?.[1])} sub={weeks.worst ? `from ${wkLabel(weeks.worst[0])}` : ""} />}
          </>}
        </dl>
        {ps?.sample_note && <p className="px-4 pb-3 text-xs text-warn sm:px-6">{ps.sample_note}</p>}
      </section>

      <Quality rows={inPeriod} />
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Outcomes rows={inPeriod} />
        <Form rows={inPeriod.slice(0, 20)} months={weeks.months} />
      </div>
    </div>
  );
}

/** V3.0 results quality (owner brief: expectancy, profit factor, average win / loss, drawdown, sample size - not win
 *  rate alone) and the same figures per timeframe. All from the closed rows shown, after fees, equal size, no leverage. */
function Quality({ rows }: { rows: Row[] }) {
  const q = useMemo(() => {
    const ordered = [...rows].sort((a, b) => (a.closed_at ?? 0) - (b.closed_at ?? 0));
    const r = ordered.map((x) => x.return_pct as number);
    const wins = r.filter((x) => x > 0), losses = r.filter((x) => x <= 0);
    const gw = wins.reduce((a, b) => a + b, 0), gl = -losses.reduce((a, b) => a + b, 0);
    let peak = 0, cum = 0, dd = 0;
    for (const x of r) { cum += x; peak = Math.max(peak, cum); dd = Math.max(dd, peak - cum); }
    const byTf = new Map<string, number[]>();
    for (const x of ordered) { const k = String(x.timeframe ?? "").toUpperCase(); byTf.set(k, [...(byTf.get(k) ?? []), x.return_pct as number]); }
    return { n: r.length, avg: r.length ? r.reduce((a, b) => a + b, 0) / r.length : null, pf: gl > 0 ? gw / gl : null,
      avgWin: wins.length ? gw / wins.length : null, avgLoss: losses.length ? -gl / losses.length : null, dd,
      tfs: [...byTf.entries()].sort((a, b) => ["15M", "1H", "4H", "12H", "1D", "3D"].indexOf(a[0]) - ["15M", "1H", "4H", "12H", "1D", "3D"].indexOf(b[0])) };
  }, [rows]);
  return (
    <section className="panel p-0" aria-label="Quality of the results">
      <header className="card-head flex items-center justify-between border-b px-4 py-2.5"><h2 className="label">Quality of the results</h2>
        <span className="hidden text-xs text-mute sm:inline">after fees · equal size · no leverage</span></header>
      <dl className="statement-facts grid grid-cols-2 sm:grid-cols-5 [&>*:last-child]:col-span-2 sm:[&>*:last-child]:col-span-1">
        <Fact k="Expectancy" v={pct(q.avg, 2)} cls={tone(q.avg)} sub="average per signal" />
        <Fact k="Profit factor" v={isNum(q.pf) ? q.pf.toFixed(2) : "—"} cls={isNum(q.pf) ? (q.pf >= 1 ? "text-bull" : "text-bear") : ""} sub="wins ÷ losses" />
        <Fact k="Average win" v={pct(q.avgWin, 2)} cls="text-bull" />
        <Fact k="Average loss" v={pct(q.avgLoss, 2)} cls="text-bear" />
        <Fact k="Largest drop" v={q.n ? pct(-q.dd, 2) : "—"} cls={q.dd > 0 ? "text-bear" : ""} sub="peak to low, summed" />
      </dl>
      {q.n > 0 && q.n < 30 && <p className="px-4 pb-1 pt-2 text-xs text-warn sm:px-5">{q.n} closed signals so far: too few to judge reliably (30 or more needed).</p>}
      {q.tfs.length > 0 && (
        <div className="overflow-x-auto px-4 pb-4 pt-2 sm:px-5">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-mute"><th className="py-2 font-normal">Timeframe</th><th className="py-2 font-normal">Closed</th>
              <th className="py-2 font-normal">Won</th><th className="py-2 font-normal">Average</th><th className="py-2 text-right font-normal">Total</th></tr></thead>
            <tbody>
              {q.tfs.map(([tf, r]) => {
                const tot = r.reduce((a, b) => a + b, 0);
                return (
                  <tr key={tf} className="border-t" style={{ borderColor: "var(--hair)" }}>
                    <td className="py-2 font-medium">{tf}</td><td className="num py-2">{r.length}</td>
                    <td className="num py-2">{Math.round((r.filter((x) => x > 0).length / r.length) * 100)}%</td>
                    <td className={`num py-2 ${tone(tot / r.length)}`}>{pct(tot / r.length, 2)}</td>
                    <td className={`num py-2 text-right ${tone(tot)}`}>{pct(tot)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Fact({ k, v, sub, cls = "" }: { k: string; v: string; sub?: string; cls?: string }) {
  return (
    <div className="min-w-0 px-4 py-3 sm:px-6">
      <dt className="text-xs text-mute">{k}</dt>
      <dd className={`num mt-0.5 text-lg font-semibold tracking-tight ${cls}`}>{v}</dd>
      {sub && <dd className="truncate text-xs text-mute">{sub}</dd>}
    </div>
  );
}

/** How the closed signals ended: one stacked bar, then each outcome with its count, share and average result. */
function Outcomes({ rows }: { rows: Row[] }) {
  const n = rows.length;
  // owner 24 Nov: no grey area - a call closed at its time limit is shown as the win or loss it was (by its result),
  // never as a separate "Time limit" line. Every closed call is still counted.
  const buckets: [string, string, string, (x: Row) => boolean][] = [
    ...OUTCOMES.filter(([k]) => k !== "EXPIRED" && k !== "STOPPED").map(([k, l, c]) => [k, l, c, (x: Row) => x.status === k] as [string, string, string, (x: Row) => boolean]),
    ["WIN_MKT", "Win, closed at market", "o-tp1", (x: Row) => x.status === "EXPIRED" && x.return_pct > 0],
    ["LOSS_MKT", "Loss, closed at market", "o-stop", (x: Row) => x.status === "EXPIRED" && x.return_pct <= 0],
    ["STOPPED", "Stop-loss", "o-stop", (x: Row) => x.status === "STOPPED"],
  ];
  const parts = buckets.map(([k, label, cls, f]) => {
    const xs = rows.filter(f);
    return { k, label, cls, n: xs.length, avg: xs.length ? xs.reduce((a, x) => a + x.return_pct, 0) / xs.length : null };
  }).filter((p) => p.n || !["WIN_MKT", "LOSS_MKT"].includes(p.k));
  return (
    <section className="panel flex flex-col p-4 sm:p-5" aria-label="How the signals ended">
      <div className="flex items-baseline justify-between gap-2"><h2 className="label">How the signals ended</h2><span className="text-xs text-mute">{n} closed · after fees</span></div>
      {n ? <>
        <div className="rb-stack mt-4" role="img" aria-label={parts.filter((p) => p.n).map((p) => `${p.label} ${p.n}`).join(", ")}>
          {parts.filter((p) => p.n).map((p) => (
            <span key={p.k} className={p.cls} style={{ flexGrow: p.n }} title={`${p.label}: ${p.n}`}>{p.n / n >= 0.12 ? `${Math.round((p.n / n) * 100)}%` : ""}</span>
          ))}
        </div>
        <table className="rb-table mt-4 w-full text-sm">
          <thead><tr><th className="text-left">Ended at</th><th>Signals</th><th>Share</th><th>Average</th></tr></thead>
          <tbody>
            {parts.map((p) => (
              <tr key={p.k} className={p.n ? "" : "opacity-45"}>
                <td><span className={`rb-key ${p.cls}`} />{p.label}</td>
                <td className="num">{p.n}</td>
                <td className="num">{n ? `${Math.round((p.n / n) * 100)}%` : "—"}</td>
                <td className={`num font-semibold ${tone(p.avg)}`}>{pct(p.avg, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </> : <p className="mt-3 text-sm text-mute">No signal closed in this period yet.</p>}
    </section>
  );
}

/** The latest closed signals as tiles, newest first, and the last months' totals. */
function Form({ rows, months }: { rows: Row[]; months: [string, number][] }) {
  // v2.56: the form in three numbers under the tiles - average win, average loss, longest winning run (same rows)
  const wins = rows.filter((x) => x.return_pct > 0), losses = rows.filter((x) => x.return_pct <= 0);
  const avgW = wins.length ? wins.reduce((a, x) => a + x.return_pct, 0) / wins.length : null;
  const avgL = losses.length ? losses.reduce((a, x) => a + x.return_pct, 0) / losses.length : null;
  let run = 0, best = 0;
  for (const x of [...rows].reverse()) { run = x.return_pct > 0 ? run + 1 : 0; best = Math.max(best, run); }
  return (
    <section className="panel flex flex-col p-4 sm:p-5" aria-label="Recent form">
      <div className="flex items-baseline justify-between gap-2"><h2 className="label">Recent form</h2><span className="text-xs text-mute">latest {rows.length} closed, newest first</span></div>
      {rows.length ? (
        <div className="rb-form mt-4">
          {rows.map((x) => (
            <div key={`${x.symbol}${x.timeframe}${x.created_at}`} className={`rb-tile ${x.return_pct > 0 ? "is-up" : "is-down"}`}
              title={`${x.symbol} ${x.side} ${String(x.timeframe).toUpperCase()} · ${pct(x.return_pct, 2)} · closed ${fmtDate(x.closed_at)}`}>
              <div className="flex items-center gap-1.5"><CoinAvatar symbol={x.symbol} size={16} /><b className="truncate text-xs">{base(x.symbol)}</b></div>
              <div className={`num text-sm font-semibold ${tone(x.return_pct)}`}>{pct(x.return_pct, 2)}</div>
              <div className="text-xs text-mute">{x.side === "LONG" ? "Long" : "Short"} · {String(x.timeframe).toUpperCase()}</div>
            </div>
          ))}
        </div>
      ) : <p className="mt-3 text-sm text-mute">No signal closed in this period yet.</p>}
      {rows.length > 0 && (
        <dl className="rb-formstats mt-4">
          <div><dt>Average win</dt><dd className="num text-bull">{pct(avgW, 2)}</dd></div>
          <div><dt>Average loss</dt><dd className={`num ${avgL != null ? "text-bear" : "text-mute"}`}>{pct(avgL, 2)}</dd></div>
          <div><dt>Longest winning run</dt><dd className="num">{best}</dd></div>
        </dl>
      )}
      {months.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2 border-t border-glass/[0.07] pt-3">
          {months.map(([m, v]) => (
            <div key={m} className="rb-month">
              <span className="text-xs text-mute">{new Date(`${m}-01T00:00:00Z`).toLocaleDateString(undefined, { month: "long", year: "numeric", timeZone: "UTC" })}</span>
              <b className={`num ${tone(v)}`}>{pct(v, 2)}</b>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
