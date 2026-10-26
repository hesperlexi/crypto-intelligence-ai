// "Wins of the day" for the sign-in page: real winning signals closed in the last 24 hours (else this week).
import { useApi } from "../lib/api";
import { base, fmtPrice, isNum } from "../lib/format";
import { CoinAvatar } from "./Polish";

const TARGET: Record<string, string> = { TP1: "Target 1 hit", TP2: "Target 2 hit", TP3: "All targets hit" };
const when = (ms: number) => {
  const h = Math.max(1, Math.round((Date.now() - ms) / 3_600_000));
  return h < 24 ? `${h} h ago` : `${Math.round(h / 24)} d ago`;
};

export default function WinsToday() {
  const v = useApi<any>("/wins-today", 60_000);
  const wins: any[] = v.data?.wins ?? [];
  if (!wins.length) return null;
  return (
    <section id="wins" className="scroll-mt-20 py-8">
      <h2 className="font-display text-center text-3xl font-bold tracking-tight sm:text-4xl">
        Wins of the <span className="text-accent">{v.data?.period === "today" ? "day" : "week"}</span>
      </h2>
      <p className="mx-auto mt-2 max-w-xl text-center text-sm text-mute">Real signals from the app that hit their targets {v.data?.period === "today" ? "in the last 24 hours" : "this week"}.</p>
      <ul className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {wins.map((w, i) => (
          <li key={i} className="panel relative overflow-hidden border-bull/30 p-4">
            <div className="pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full bg-bull/10 blur-2xl" aria-hidden="true" />
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <CoinAvatar symbol={w.symbol} size={36} />
                <div>
                  <div className="font-display text-lg font-bold leading-tight">{base(w.symbol)} <span className={`text-sm font-extrabold ${w.side === "LONG" ? "text-bull" : "text-bear"}`}>{w.side}</span></div>
                  <div className="text-xs text-mute">{String(w.timeframe).toUpperCase()} signal · {when(w.closed_at)}</div>
                </div>
              </div>
              <div className="num text-right text-2xl font-extrabold text-bull">+{isNum(w.return_pct) ? w.return_pct.toFixed(1) : "—"}%</div>
            </div>
            <div className="num mt-3 flex justify-between text-xs text-mute">
              <span>Entry <span className="text-text">{fmtPrice(w.entry)}</span></span>
              <span>{TARGET[w.status] ?? "Closed in profit"}{isNum(w.target) ? <> · <span className="text-bull">{fmtPrice(w.target)}</span></> : null}</span>
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-center text-[11px] text-mute">Selected winning signals; the full results, losses included, are available to members inside the app. Not financial advice.</p>
    </section>
  );
}
