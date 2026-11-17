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

export default function ResultsBoard({ d, sigs, roi, admin, avgTested, proven }: {
  d: any; sigs: Row[]; roi: boolean; admin: boolean; avgTested: number | null; proven: number;
}) {
  const [period, setPeriod] = useState<"all" | "7d">("all");
  const s = d.live?.summary ?? {};
  const w7 = d.last_7d;
  const closed = useMemo(() => sigs.filter((x) => OUTCOMES.some(([k]) => k === x.status) && isNum(x.return_pct))
    .sort((a, b) => (b.closed_at ?? 0) - (a.closed_at ?? 0)), [sigs]);
  const inPeriod = period === "7d" ? closed.filter((x) => (x.closed_at ?? 0) >= Date.now() - 7 * 86_400_000) : closed;
  const won = inPeriod.filter((x) => x.return_pct > 0).length, lost = inPeriod.length - won;
  const open = d.live?.open ?? 0;
  const winRate = period === "7d" ? (w7?.win_rate ?? (inPeriod.length ? won / inPeriod.length : null)) : s.win_rate;
  const lead = period === "7d" ? w7?.total_return_pct : roi ? s.total_roi_pct : s.total_return_pct;
  const leadLabel = period === "7d" ? "Last 7 days, after fees" : roi ? `Total ROI on margin${s.net ? ", after fees" : ""}` : s.net ? "Total result after fees" : "Total price move";

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
            <Segmented label="Period" value={period} onChange={setPeriod}
              options={[["all", d.record_since ? `Since ${fmtDate(d.record_since)}` : "All results"], ["7d", "Last 7 days"]] as const} />
            <div className="label mt-4">{leadLabel}</div>
            <div className={`num statement-figure mt-1 font-semibold ${tone(lead)}`}>{pct(lead)}</div>
            <p className="mt-1.5 text-sm text-mute">
              {period === "7d"
                ? `${w7?.closed ?? inPeriod.length} closed in the last 7 days · equal size per signal, no leverage`
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
              <li><span className="rb-dot bg-bull" />Won<b className="num">{period === "7d" ? (w7?.wins ?? won) : won}</b></li>
              <li><span className="rb-dot bg-bear" />Lost<b className="num">{period === "7d" ? (w7?.losses ?? lost) : lost}</b></li>
              <li><span className="rb-dot live-dot bg-accent" />Open now<b className="num">{open}</b></li>
            </ul>
          </div>
        </div>
        <dl className="statement-facts grid grid-cols-2 border-t border-glass/[0.07] sm:grid-cols-4">
          {period === "7d" ? <>
            <Fact k="Average per signal" v={pct(w7?.avg_return_pct, 2)} cls={tone(w7?.avg_return_pct)} sub="after fees, no leverage" />
            <Fact k="Best" v={w7?.best ? pct(w7.best.return_pct, 2) : "—"} cls={tone(w7?.best?.return_pct)} sub={w7?.best ? `${base(w7.best.symbol)} ${w7.best.side} ${String(w7.best.timeframe).toUpperCase()}` : ""} />
            <Fact k="Worst" v={w7?.worst ? pct(w7.worst.return_pct, 2) : "—"} cls={tone(w7?.worst?.return_pct)} sub={w7?.worst ? `${base(w7.worst.symbol)} ${w7.worst.side} ${String(w7.worst.timeframe).toUpperCase()}` : ""} />
            <Fact k="Closed" v={String(w7?.closed ?? 0)} sub={w7?.sample_note ? "small sample" : "last 7 days"} />
          </> : <>
            {roi ? <Fact k="Average ROI per signal" v={pct(s.avg_roi_pct, 2)} cls={tone(s.avg_roi_pct)} sub={`${pct(s.avg_return_pct, 2)} price ${s.net ? "after fees" : "before fees"}`} />
              : <Fact k={s.net ? "Average per signal" : "Average price move"} v={pct(s.avg_return_pct, 2)} cls={tone(s.avg_return_pct)} sub={s.net ? "after fees" : "before fees"} />}
            <Fact k={s.net ? "Total price result" : "Total price move"} v={pct(s.total_return_pct)} cls={tone(s.total_return_pct)} sub="equal size, no leverage" />
            <Fact k="Best week" v={weeks.best ? pct(weeks.best[1], 2) : "—"} cls={tone(weeks.best?.[1])} sub={weeks.best ? `from ${wkLabel(weeks.best[0])}` : ""} />
            {admin ? <Fact k="Model hit rate (next candle)" v={isNum(avgTested) ? `${Math.round(avgTested * 100)}%` : "—"} sub={`admin only, ${proven} proven`} />
              : <Fact k="Worst week" v={weeks.worst ? pct(weeks.worst[1], 2) : "—"} cls={tone(weeks.worst?.[1])} sub={weeks.worst ? `from ${wkLabel(weeks.worst[0])}` : ""} />}
          </>}
        </dl>
        {period === "7d" && w7?.sample_note && <p className="px-4 pb-3 text-xs text-warn sm:px-6">{w7.sample_note}</p>}
      </section>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Outcomes rows={inPeriod} />
        <Form rows={inPeriod.slice(0, 20)} months={weeks.months} />
      </div>
    </div>
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
  const parts = OUTCOMES.map(([k, label, cls]) => {
    const xs = rows.filter((x) => x.status === k);
    return { k, label, cls, n: xs.length, avg: xs.length ? xs.reduce((a, x) => a + x.return_pct, 0) / xs.length : null };
  });
  return (
    <section className="panel p-4 sm:p-5" aria-label="How the signals ended">
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
  return (
    <section className="panel p-4 sm:p-5" aria-label="Recent form">
      <div className="flex items-baseline justify-between gap-2"><h2 className="label">Recent form</h2><span className="text-xs text-mute">latest {rows.length} closed, newest first</span></div>
      {rows.length ? (
        <div className="rb-form mt-4">
          {rows.map((x) => (
            <div key={`${x.symbol}${x.timeframe}${x.created_at}`} className={`rb-tile ${x.return_pct > 0 ? "is-up" : "is-down"}`}
              title={`${x.symbol} ${x.side} ${String(x.timeframe).toUpperCase()} · ${pct(x.return_pct, 2)} · closed ${fmtDate(x.closed_at)}`}>
              <div className="flex items-center gap-1.5"><CoinAvatar symbol={x.symbol} size={16} /><b className="truncate text-xs">{base(x.symbol)}</b></div>
              <div className={`num text-sm font-semibold ${tone(x.return_pct)}`}>{pct(x.return_pct, 2)}</div>
              <div className="text-[11px] text-mute">{x.side === "LONG" ? "Long" : "Short"} · {String(x.timeframe).toUpperCase()}</div>
            </div>
          ))}
        </div>
      ) : <p className="mt-3 text-sm text-mute">No signal closed in this period yet.</p>}
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
