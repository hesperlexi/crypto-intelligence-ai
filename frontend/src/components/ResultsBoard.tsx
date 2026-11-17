// v2.55 Results redesign (owner, 17 Nov 2026: "redesign the results page completely different").
// A scoreboard instead of a statement: big gold-foil score tiles with a period switch, every timeframe as its own
// scorecard, every closed signal as one tile in a mosaic coloured by how it ended, and a coin ranking. No line or bar
// charts. Same data as before (views/track_record: summary, by_timeframe, the rows; after fees); nothing new is read.
import { useMemo, useState } from "react";
import { base, fmtDate, isNum } from "../lib/format";
import { Segmented } from "./kit";
import { CoinAvatar } from "./Polish";
import { Ring } from "./Premium";

const pct = (v: unknown, d = 1) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "—");
const tone = (v: unknown) => (isNum(v) ? (v > 0 ? "text-bull" : v < 0 ? "text-bear" : "") : "text-mute");
const TFS = ["15m", "1h", "4h", "12h", "1d", "3d"];
const OUT: Record<string, [string, string]> = {
  TP3: ["Target 3", "o-tp3"], TP2: ["Target 2", "o-tp2"], TP1: ["Target 1", "o-tp1"], EXPIRED: ["Time limit", "o-exp"], STOPPED: ["Stop-loss", "o-stop"],
};
const DAY = 86_400_000;
type Row = any;
type Period = "all" | "today" | "week" | "7d" | "30d";
const PERIODS = [["today", "Today"], ["week", "This week"], ["7d", "7 days"], ["30d", "30 days"], ["all", "All time"]] as const;
const PERIOD_TEXT: Record<Period, string> = { all: "all closed signals", today: "closed today", week: "closed this week (from Monday)", "7d": "closed in the last 7 days", "30d": "closed in the last 30 days" };
// start of the period in the viewer's own time zone (today = from midnight, this week = from Monday midnight)
function periodStart(p: Period): number {
  const now = new Date();
  if (p === "7d") return now.getTime() - 7 * DAY;
  if (p === "30d") return now.getTime() - 30 * DAY;
  if (p === "all") return 0;
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (p === "week") d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return d.getTime();
}

function stats(rows: Row[]) {
  const r = rows.map((x) => x.return_pct as number);
  const wins = r.filter((v) => v > 0), losses = r.filter((v) => v <= 0);
  const lossSum = -losses.reduce((a, b) => a + b, 0);
  const roi = rows.every((x) => isNum(x.roi_pct)) ? rows.reduce((a, x) => a + x.roi_pct, 0) : null;
  return {
    n: r.length, won: wins.length, lost: losses.length, win: r.length ? wins.length / r.length : null,
    total: r.reduce((a, b) => a + b, 0), avg: r.length ? r.reduce((a, b) => a + b, 0) / r.length : null,
    avgRoi: roi != null && r.length ? roi / r.length : null,
    pf: lossSum > 0 ? wins.reduce((a, b) => a + b, 0) / lossSum : null, roi,
    best: r.length ? Math.max(...r) : null, worst: r.length ? Math.min(...r) : null,
  };
}

export default function ResultsBoard({ d, sigs, roi, admin, avgTested, proven }: {
  d: any; sigs: Row[]; roi: boolean; admin: boolean; avgTested: number | null; proven: number;
}) {
  const [period, setPeriod] = useState<Period>("all");
  const s = d.live?.summary ?? {};
  const closedAll = useMemo(() => sigs.filter((x) => x.status in OUT && isNum(x.return_pct)).sort((a, b) => (b.closed_at ?? 0) - (a.closed_at ?? 0)), [sigs]);
  const cut = periodStart(period);
  const rows = closedAll.filter((x) => (x.closed_at ?? 0) >= cut);
  const st = stats(rows);
  const open = d.live?.open ?? 0;
  // all-time headline from the engine's full summary (the rows on the page can be the newest part only)
  const all = period === "all";
  const lead = all ? (roi ? s.total_roi_pct : s.total_return_pct) : (roi && isNum(st.roi) ? st.roi : st.total);
  const leadIsRoi = all ? roi : roi && isNum(st.roi);
  const n = all ? (s.closed ?? st.n) : st.n;
  const win = all ? s.win_rate : st.win;
  const pf = all ? s.profit_factor ?? st.pf : st.pf;
  const avg = all ? (roi ? s.avg_roi_pct : s.avg_return_pct) : (leadIsRoi && isNum(st.avgRoi) ? st.avgRoi : st.avg);
  const small = n < 30;

  const byTf = d.live?.by_timeframe ?? {};
  const tfCards = TFS.map((tf) => {
    const sv = all ? byTf[tf] : null;
    const r = rows.filter((x) => x.timeframe === tf);
    const k = stats(r);
    return { tf, n: sv?.closed ?? k.n, win: sv?.win_rate ?? k.win, avg: sv?.avg_return_pct ?? k.avg, total: sv?.total_return_pct ?? k.total,
      open: sigs.filter((x) => x.timeframe === tf && x.status === "OPEN").length };
  });

  const coins = useMemo(() => {
    const m = new Map<string, Row[]>();
    for (const x of rows) m.set(x.symbol, [...(m.get(x.symbol) ?? []), x]);
    return [...m.entries()].map(([sym, xs]) => ({ sym, ...stats(xs) })).sort((a, b) => b.total - a.total);
  }, [rows]);
  const maxAbs = Math.max(0.5, ...coins.map((c) => Math.abs(c.total)));
  const counts = Object.keys(OUT).map((k) => ({ k, n: rows.filter((x) => x.status === k).length }));

  return (
    <div className="space-y-4">
      {/* ---- scoreboard ---- */}
      <section className="panel panel-hero rs-board" aria-label="Scoreboard">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-display text-xl font-semibold">Scoreboard</h2>
            <p className="text-xs text-mute">Every signal counted, losses included · after fees and funding{d.record_since ? ` · since ${fmtDate(d.record_since)}` : ""}</p>
          </div>
          <div className="rs-periods"><Segmented label="Period" value={period} onChange={setPeriod} options={PERIODS} /></div>
        </div>
        <div className="rs-tiles mt-4">
          <div className="rs-tile rs-lead">
            <span className="text-xs text-mute">{leadIsRoi ? "Total ROI on margin" : "Total result"}</span>
            <b className={`num rs-big ${isNum(lead) && lead > 0 ? "foil-text" : tone(lead)}`}>{pct(lead)}</b>
            <span className="text-xs text-mute">{leadIsRoi ? "at each card's suggested leverage" : "price move, equal size, no leverage"}</span>
          </div>
          <div className="rs-tile items-center">
            <Ring value={isNum(win) ? win : 0} size={92} stroke={9} tone="--bull" label={`Win rate ${isNum(win) ? Math.round(win * 100) : 0}%`}>
              <div className="num text-xl font-semibold">{isNum(win) ? `${Math.round(win * 100)}%` : "—"}</div>
            </Ring>
            <span className="text-xs text-mute">won</span>
          </div>
          <div className="rs-tile">
            <span className="text-xs text-mute">Closed</span>
            <b className="num rs-mid">{n}</b>
            <span className="text-xs"><span className="text-bull">{all ? Math.round((s.win_rate ?? 0) * (s.closed ?? 0)) : st.won} won</span> · <span className="text-bear">{all ? (s.closed ?? 0) - Math.round((s.win_rate ?? 0) * (s.closed ?? 0)) : st.lost} lost</span></span>
          </div>
          <div className="rs-tile">
            <span className="text-xs text-mute">Profit factor</span>
            <b className={`num rs-mid ${isNum(pf) ? (pf >= 1 ? "text-bull" : "text-bear") : "text-mute"}`}>{isNum(pf) ? pf.toFixed(2) : "—"}</b>
            <span className="text-xs text-mute">won ÷ lost</span>
          </div>
          <div className="rs-tile">
            <span className="text-xs text-mute">Average per signal</span>
            <b className={`num rs-mid ${tone(avg)}`}>{pct(avg, 2)}</b>
            <span className="text-xs text-mute">{open} open now, not final</span>
          </div>
          {admin && <div className="rs-tile"><span className="text-xs text-mute">Model hit rate</span><b className="num rs-mid">{isNum(avgTested) ? `${Math.round(avgTested * 100)}%` : "—"}</b><span className="text-xs text-mute">admin only · {proven} proven</span></div>}
        </div>
        {small && <p className="mt-3 text-xs text-warn">{n} closed signal{n === 1 ? "" : "s"} so far: too few to judge the method (30 or more needed); results this early swing a lot.</p>}
      </section>

      {/* ---- per timeframe ---- */}
      <section aria-label="By timeframe">
        <div className="mb-2 flex items-baseline justify-between px-1"><h2 className="label">Each timeframe</h2><span className="text-xs text-mute">{PERIOD_TEXT[period]}</span></div>
        <div className="rs-tf">
          {tfCards.map((c) => (
            <div key={c.tf} className={`rs-tfcard ${!c.n ? "is-empty" : isNum(c.avg) && c.avg > 0 ? "is-up" : "is-down"}`}>
              <div className="flex items-center justify-between"><b className="text-base">{c.tf.toUpperCase()}</b>{c.open > 0 && <span className="rs-open">{c.open} open</span>}</div>
              {c.n ? (
                <>
                  <div className={`num mt-1 text-xl font-semibold ${tone(c.total)}`}>{pct(c.total)}</div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-bear/50" title={`${Math.round((c.win ?? 0) * 100)}% won`}><div className="h-full rounded-full bg-bull" style={{ width: `${Math.round((c.win ?? 0) * 100)}%` }} /></div>
                  <div className="mt-1.5 text-xs text-mute">{c.n} closed · {Math.round((c.win ?? 0) * 100)}% won</div><div className={`text-xs ${tone(c.avg)}`}>{pct(c.avg, 2)} per signal</div>
                </>
              ) : <div className="mt-2 text-xs text-mute">No closed signal yet</div>}
            </div>
          ))}
        </div>
      </section>

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        {/* ---- every signal as a tile ---- */}
        <section className="panel p-4 sm:p-5" aria-label="Every closed signal">
          <div className="flex flex-wrap items-baseline justify-between gap-2"><h2 className="label">Every closed signal</h2><span className="text-xs text-mute">newest first · tap a tile</span></div>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-mute">
            {counts.map(({ k, n: c }) => <span key={k} className={c ? "" : "opacity-50"}><span className={`rb-key ${OUT[k][1]}`} />{OUT[k][0]} <b className="text-text">{c}</b></span>)}
          </div>
          {rows.length ? (
            <div className="rs-mosaic mt-3">
              {rows.slice(0, 120).map((x) => (
                <span key={`${x.symbol}${x.timeframe}${x.created_at}`} className={`rs-cell ${OUT[x.status][1]}`} tabIndex={0}
                  title={`${base(x.symbol)} ${x.side} ${String(x.timeframe).toUpperCase()} · ${OUT[x.status][0]} · ${pct(x.return_pct, 2)} · ${fmtDate(x.closed_at)}`}>
                  <span className="rs-cell-c">{base(x.symbol).slice(0, 4)}</span>
                  <span className="rs-cell-v num">{pct(x.return_pct, 1)}</span>
                </span>
              ))}
            </div>
          ) : <p className="mt-3 text-sm text-mute">No signal closed in this period yet.</p>}
        </section>

        {/* ---- coins ---- */}
        <section className="panel p-4 sm:p-5" aria-label="By coin">
          <div className="flex items-baseline justify-between gap-2"><h2 className="label">By coin</h2><span className="text-xs text-mute">total after fees</span></div>
          {coins.length ? (
            <ul className="mt-3 space-y-2">
              {coins.slice(0, 12).map((c) => (
                <li key={c.sym} className="grid grid-cols-[96px_minmax(0,1fr)_64px] items-center gap-2 text-sm">
                  <span className="flex min-w-0 items-center gap-1.5"><CoinAvatar symbol={c.sym} size={18} /><b className="truncate">{base(c.sym)}</b></span>
                  <span className="rs-div" title={`${c.n} closed · ${c.won} won`}>
                    <span className="rs-div-neg">{c.total < 0 && <span style={{ width: `${(Math.abs(c.total) / maxAbs) * 100}%` }} />}</span>
                    <span className="rs-div-pos">{c.total > 0 && <span style={{ width: `${(c.total / maxAbs) * 100}%` }} />}</span>
                  </span>
                  <span className={`num text-right font-semibold ${tone(c.total)}`}>{pct(c.total)}</span>
                </li>
              ))}
            </ul>
          ) : <p className="mt-3 text-sm text-mute">No signal closed in this period yet.</p>}
          {coins.length > 0 && <p className="mt-3 text-xs text-mute">{coins.filter((c) => c.total > 0).length} of {coins.length} coins in profit · best {base(coins[0].sym)} {pct(coins[0].total)}</p>}
        </section>
      </div>
    </div>
  );
}
