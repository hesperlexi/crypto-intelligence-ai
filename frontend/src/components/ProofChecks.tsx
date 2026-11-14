// v2.24 proof checks (admin): do the filters save money, and is the AI still as good live as in training?
// Data: views/guardian.checks (backend services/proof_checks.py), refreshed hourly. Nothing here changes a call.
import { Badge, Tile, type Tone } from "./kit";
import { ago, base, isNum } from "../lib/format";

const r2 = (v: unknown) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(2)}R` : "—");
const rTone = (v: unknown) => (isNum(v) ? (v > 0.0001 ? "text-bull" : v < -0.0001 ? "text-bear" : "") : "text-mute");
const pct = (v: unknown, d = 0) => (isNum(v) ? `${(v * 100).toFixed(d)}%` : "—");
const sk = (v: unknown) => (isNum(v) ? `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%` : "—");
const FLAG_WORD: Record<string, string> = {
  "AGAINST BIGGER TREND": "Bigger trend", "NO PROVEN EDGE": "No proven edge", FILTERED: "Trade filter",
  "TARGET TOO SMALL FOR COSTS": "Target too small", "STOP TOO WIDE": "Stop too wide", "VOLUME WALL AHEAD": "Volume wall",
  "STOP TOO TIGHT FOR FEES": "Stop too tight", "TOO MANY SAME-SIDE CALLS": "Same-side cap", "TIMEFRAME PAUSED": "Timeframe paused",
  "GRADE A ONLY": "Grade A only", "CALL STILL RUNNING": "Call running", "NEWS RISK": "News guard",
};
const STATE: Record<string, [string, Tone]> = {
  ok: ["On track", "bull"], drift: ["Drifting", "bear"], "no skill": ["No skill", "warn"], overconfident: ["Overconfident", "warn"],
  "too few": ["Too few", "mute"],
};

/** Calibration warnings (Health uses this for its tile). */
export function checkWarnings(c: any): string[] {
  return c?.calibration?.warnings ?? [];
}

export function FilterBoard({ c }: { c?: any }) {
  const r = c?.rejected;
  if (!r) return null;
  return (
    <section aria-label="Filter check" className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="label">Filter check</h2>
        <span className="text-xs text-mute">Blocked calls · net R after fees · {c.at ? `updated ${ago(c.at)}` : ""}</span>
      </div>
      {!r.n ? (
        <p className="text-sm text-mute">No blocked calls yet.</p>
      ) : (
        <>
          <div className="metric-strip">
            <Tile variant="strip" label="Blocked" value={String(r.n)} sub={`${r.closed} finished · ${r.open} running`} />
            <Tile variant="strip" label="Would have" value={`${r.would_have_won ?? 0} won · ${r.would_have_lost ?? 0} lost`} />
            <Tile variant="strip" label="Their total" value={r2(r.total_r)} valueClass={rTone(r.total_r)}
              sub={r.verdict ? `filters ${r.verdict}` : `judge after ${r.min_judge}+ finished`} />
          </div>
          <div className="overflow-x-auto rounded-xl border border-glass/[0.08]">
            <table className="w-full text-sm">
              <thead className="text-xs text-mute">
                <tr className="text-left"><th className="px-3 py-2 font-normal">Filter</th><th className="px-2 py-2 text-right font-normal">Blocked</th>
                  <th className="px-2 py-2 text-right font-normal">Won / lost</th><th className="px-2 py-2 text-right font-normal">Avg</th>
                  <th className="px-2 py-2 text-right font-normal">Total</th><th className="px-3 py-2 text-right font-normal">Verdict</th></tr>
              </thead>
              <tbody className="divide-y divide-glass/[0.06]">
                {(r.by_flag ?? []).map((f: any) => (
                  <tr key={f.flag}>
                    <td className="px-3 py-2">{FLAG_WORD[f.flag] ?? f.flag}</td>
                    <td className="num px-2 py-2 text-right">{f.n}{f.open ? <span className="text-mute"> ({f.open} open)</span> : null}</td>
                    <td className="num px-2 py-2 text-right">{f.closed ? `${f.would_have_won} / ${f.would_have_lost}` : "—"}</td>
                    <td className={`num px-2 py-2 text-right ${rTone(f.avg_r)}`}>{r2(f.avg_r)}</td>
                    <td className={`num px-2 py-2 text-right ${rTone(f.total_r)}`}>{f.closed ? r2(f.total_r) : "—"}</td>
                    <td className="px-3 py-2 text-right">
                      {f.verdict ? <Badge tone={f.verdict === "saving money" ? "bull" : "bear"}>{f.verdict === "saving money" ? "Saving" : "Costing"}</Badge>
                        : <span className="text-xs text-mute">{f.closed}/{r.min_judge}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-mute">Negative total = the blocked calls would have lost: the filter saved that much.</p>
          {(r.items ?? []).length > 0 && (
            <details className="text-sm">
              <summary className="tap-h cursor-pointer text-accent">Latest blocked calls</summary>
              <ul className="mt-2 divide-y divide-glass/[0.06] rounded-xl border border-glass/[0.08]">
                {r.items.slice(0, 15).map((x: any) => (
                  <li key={x.id} className="flex flex-wrap items-baseline justify-between gap-2 px-3 py-2">
                    <span><span className="font-semibold">{base(x.symbol)}</span> <span className="num text-mute">{String(x.timeframe).toUpperCase()}</span>{" "}
                      <span className={x.side === "LONG" ? "text-bull" : "text-bear"}>{x.side}</span>{" "}
                      <span className="text-xs text-mute">{FLAG_WORD[x.flag] ?? x.flag} · {ago(x.created_at)}</span></span>
                    <span className={`num ${rTone(x.net_r)}`}>{x.status === "OPEN" ? <span className="text-mute">running</span>
                      : isNum(x.net_r) ? r2(x.net_r) : <span className="text-mute">{x.status === "NOT_FILLED" ? "no fill" : x.status}</span>}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </section>
  );
}

export function ModelCheck({ c }: { c?: any }) {
  const cal = c?.calibration;
  if (!cal) return null;
  const tfs: any[] = cal.timeframes ?? [];
  const tp1: any[] = c?.tp1?.timeframes ?? [];
  return (
    <section aria-label="AI check" className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="label">AI check</h2>
        <span className="text-xs text-mute">Live next-candle forecasts · skill vs base rates</span>
      </div>
      {(cal.warnings ?? []).map((w: string) => (
        <p key={w} className="rounded-lg border border-bear/30 bg-bear/10 px-3 py-2 text-sm text-bear">{w}</p>
      ))}
      {!tfs.length ? <p className="text-sm text-mute">No scored forecasts yet.</p> : (
        <div className="overflow-x-auto rounded-xl border border-glass/[0.08]">
          <table className="w-full text-sm">
            <thead className="text-xs text-mute">
              <tr className="text-left"><th className="px-3 py-2 font-normal">TF</th><th className="px-2 py-2 text-right font-normal">Skill 7d</th>
                <th className="px-2 py-2 text-right font-normal">Skill before</th><th className="hidden px-2 py-2 text-right font-normal sm:table-cell">Hit 7d</th>
                <th className="px-2 py-2 text-right font-normal">Too high by</th><th className="px-3 py-2 text-right font-normal">State</th></tr>
            </thead>
            <tbody className="divide-y divide-glass/[0.06]">
              {tfs.map((t) => {
                const [word, tone] = STATE[t.state] ?? [t.state, "mute" as Tone];
                return (
                  <tr key={t.timeframe}>
                    <td className="num px-3 py-2">{String(t.timeframe).toUpperCase()}</td>
                    <td className={`num px-2 py-2 text-right ${rTone(t.last7?.skill)}`}>{sk(t.last7?.skill)}<span className="hidden text-xs text-mute sm:inline"> · {t.last7?.n ?? 0}</span></td>
                    <td className={`num px-2 py-2 text-right ${rTone(t.prior30?.skill)}`}>{sk(t.prior30?.skill)}</td>
                    <td className="num hidden px-2 py-2 text-right sm:table-cell">{pct(t.last7?.hit_rate)}</td>
                    <td className="num px-2 py-2 text-right">{isNum(t.overconfidence) ? `${t.overconfidence > 0 ? "+" : ""}${(t.overconfidence * 100).toFixed(1)} pts` : "—"}</td>
                    <td className="px-3 py-2 text-right"><Badge tone={tone}>{word}</Badge></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {tp1.length > 0 && (
        <p className="text-xs text-mute">
          TP1 expected vs reached: {tp1.map((t) => `${String(t.timeframe).toUpperCase()} ${pct(t.expected)} → ${pct(t.actual)} (${t.n})`).join(" · ")}
        </p>
      )}
      <p className="text-xs text-mute">Skill above 0 = better than plain base rates. "Too high by" above 0 = the AI's chances are too high.</p>
    </section>
  );
}
