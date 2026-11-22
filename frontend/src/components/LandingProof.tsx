// v2.68 landing page (owner, 22 Nov 2026): (1) the real record in one strip from views/public_record (public, same
// numbers as Results; wins and losses), linking to /record; (2) how one signal plays out, start to finish - a fixed
// illustration of the rules, labelled as an example, never a promise.
import { Link } from "react-router-dom";
import { useApi } from "../lib/api";
import { isNum } from "../lib/format";

const pct = (v: number | null | undefined, d = 1) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "—");

function Spark({ pts }: { pts: { cum: number }[] }) {
  if (pts.length < 2) return null;
  const W = 220, H = 56, lo = Math.min(0, ...pts.map((p) => p.cum)), hi = Math.max(0, ...pts.map((p) => p.cum));
  const y = (v: number) => H - 4 - ((v - lo) / (hi - lo || 1)) * (H - 8);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${((i / (pts.length - 1)) * W).toFixed(1)} ${y(p.cum).toFixed(1)}`).join(" ");
  const up = pts[pts.length - 1].cum >= 0;
  return <svg viewBox={`0 0 ${W} ${H}`} className="lp-spark" aria-hidden="true"><path d={d} fill="none" stroke={up ? "rgb(var(--bull))" : "rgb(var(--bear))"} strokeWidth="2.2" strokeLinejoin="round" /></svg>;
}

const STEPS: [string, string, string][] = [
  ["Signal published", "Entry, stop-loss and three targets, with the grade and the reasons.", "accent"],
  ["Target 1 reached", "Half the trade closes in profit; the stop moves to the entry, so the rest can no longer lose.", "bull"],
  ["Target 2 reached", "A quarter more closes; the stop moves up to target 1.", "bull"],
  ["Closed and recorded", "The last quarter ends at target 3, the stop or the time limit. The result after fees goes into the public record.", "ai"],
];

export default function LandingProof() {
  const v = useApi<any>("/public-record", 300_000);
  const d = v.data;
  const s = d?.summary ?? {};
  return (
    <>
      {d && isNum(s.closed) && s.closed > 0 && (
        <section className="lp-record" aria-label="Our record">
          <div className="lp-rec-nums">
            <div><b className="num">{isNum(s.win_rate) ? `${Math.round(s.win_rate * 100)}%` : "—"}</b><span>win rate</span></div>
            <div><b className="num">{s.closed}</b><span>signals closed</span></div>
            <div><b className={`num ${(s.total_return_pct ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{pct(s.total_return_pct)}</b><span>total, after fees</span></div>
            <div><b className={`num ${(d.last_7d?.total_return_pct ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{pct(d.last_7d?.total_return_pct)}</b><span>last 7 days</span></div>
          </div>
          <Spark pts={d.daily ?? []} />
          <Link to="/record" className="btn lp-rec-btn">See every result</Link>
          <p className="lp-rec-note">Wins and losses alike, after fees. Past results do not promise future results.</p>
        </section>
      )}
      <section className="lp-journey" aria-label="How a signal plays out">
        <h2 className="font-display text-center text-2xl font-semibold tracking-tight sm:text-3xl">How one signal plays out</h2>
        <p className="mx-auto mt-2 max-w-xl text-center text-sm text-mute">An example of the app's rules from start to finish. Not every signal reaches its targets.</p>
        <ol className="lp-steps">
          {STEPS.map(([t, p, tone], i) => (
            <li key={t} className={`is-${tone}`}>
              <span className="lp-dot">{i + 1}</span>
              <h3>{t}</h3>
              <p>{p}</p>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}
