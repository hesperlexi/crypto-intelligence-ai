// "Wins of the day" for the sign-in page: real winning signals closed in the last 24 hours (else this week).
import { Link } from "react-router-dom";
import { useApi } from "../lib/api";
import { base, fmtPrice, isNum } from "../lib/format";
import { CoinAvatar } from "./Polish";
import { LevChip } from "./SignalExtras";
import { roiOf, signedPct } from "../lib/roi";

const TARGET: Record<string, string> = { TP1: "Target 1 hit", TP2: "Target 2 hit", TP3: "All targets hit" };
const when = (ms: number) => {
  const h = Math.max(1, Math.round((Date.now() - ms) / 3_600_000));
  return h < 24 ? `${h} h ago` : `${Math.round(h / 24)} d ago`;
};

export default function WinsToday() {
  const v = useApi<any>("/wins-today", 60_000);
  const wins: any[] = v.data?.wins ?? [];
  if (!wins.length) return null;
  // v1 contract: `closed` (all closed calls in the same window: a list or a count) and `losses` (count). Old payloads lack them.
  const d = v.data ?? {};
  const closedN: number | null = Array.isArray(d.closed) ? d.closed.length : isNum(d.closed) ? d.closed : null;
  const lossesN: number | null = isNum(d.losses) ? d.losses : null;
  const winsN = closedN != null && lossesN != null ? Math.max(0, closedN - lossesN) : wins.length;
  const showTally = lossesN != null || closedN != null;
  return (
    <section id="wins" className="scroll-mt-20 py-8">
      <h2 className="font-display text-center text-3xl font-bold tracking-tight sm:text-4xl">
        Wins of the <span className="text-accent">{v.data?.period === "today" ? "day" : "week"}</span>
      </h2>
      <p className="mx-auto mt-2 max-w-xl text-center text-sm text-mute">Real signals from the app that hit their targets {v.data?.period === "today" ? "in the last 24 hours" : "this week"}.</p>
      <ul className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
        {wins.map((w, i) => {
          const r = roiOf(w);
          return (
          <li key={i} className={`panel relative flex flex-col overflow-hidden border-bull/30 p-0 ${evenCut(i, wins.length)}`}>
            <div className="pointer-events-none absolute -right-12 -top-12 h-40 w-40 rounded-full bg-bull/15 blur-3xl" aria-hidden="true" />
            <div className="pointer-events-none absolute -left-16 bottom-0 h-32 w-32 rounded-full bg-accent/10 blur-3xl" aria-hidden="true" />
            <div className="relative flex items-center gap-3 px-4 pt-4">
              <CoinAvatar symbol={w.symbol} size={36} />
              <div className="min-w-0 flex-1">
                <div className="font-display truncate text-lg font-bold leading-tight">{base(w.symbol)}</div>
                <div className="mt-1 flex items-center gap-1.5 text-xs">
                  <span className={`rounded-md px-1.5 py-0.5 font-extrabold leading-none text-ink ${w.side === "LONG" ? "bg-bull" : "bg-bear"}`}>{w.side}</span>
                  <span className="rounded-md border border-accent/45 px-1.5 py-0.5 font-bold leading-none text-accent">{String(w.timeframe).toUpperCase()}</span>
                  <span className="truncate text-mute">{when(w.closed_at)}</span>
                </div>
              </div>
            </div>
            <div className="relative mt-3 flex items-end justify-between gap-3 px-4">
              <div>
                <div className="label">{r?.onMargin ? "ROI on margin" : r?.net ? "After fees" : "Price move"}</div>
                <div className="num mt-1 text-[32px] font-extrabold leading-none tracking-tight text-bull">{r ? signedPct(r.value) : "—"}</div>
              </div>
              {r?.leverage && (
                <div className="text-right">
                  <LevChip lev={r.leverage} />
                  <div className="num mt-1 text-xs leading-none text-mute">price {signedPct(r.price)}</div>
                </div>
              )}
            </div>
            <dl className="num relative mt-4 grid grid-cols-2 border-t border-glass/[0.07] text-xs">
              <div className="px-4 py-2.5"><dt className="text-[0.8125rem] font-medium text-mute">Entry</dt><dd className="mt-0.5 font-semibold text-text">{fmtPrice(w.entry)}</dd></div>
              <div className="border-l border-glass/[0.07] px-4 py-2.5 text-right"><dt className="text-[0.8125rem] font-medium text-mute">{TARGET[w.status] ?? "Closed in profit"}</dt><dd className="mt-0.5 font-semibold text-bull">{isNum(w.target) ? fmtPrice(w.target) : "—"}</dd></div>
            </dl>
          </li>
          );
        })}
      </ul>
      {showTally && (
        <p className="num mt-5 text-center text-sm">
          <span className="font-semibold text-bull">{winsN} {winsN === 1 ? "win" : "wins"}</span> · <span className="font-semibold text-bear">{lossesN ?? 0} {lossesN === 1 ? "loss" : "losses"}</span> <span className="text-mute">in the same period</span>
          {" · "}<Link to="/results" className="text-accent hover:underline">full record, losses included, on Results (members)</Link>
        </p>
      )}
      <p className="mt-3 text-center text-xs text-mute">After fees. Leverage magnifies losses.</p>
      <p className="mt-1 text-center text-xs text-mute">Past results do not guarantee future results. <Link to="/risk-disclosure" className="underline hover:text-text">Risk disclosure</Link></p>
    </section>
  );
}

/** v2.76 (owner: one card alone on the last row): rows end level - on computers two left-over cards share the last row
 *  (half width each), a single left-over card is left out at that width (also on tablets' two columns). */
function evenCut(i: number, n: number): string {
  const r3 = n % 3, r2 = n % 2;
  const lg = n >= 3 && r3 === 1 && i === n - 1 ? "lg:hidden" : n >= 3 && r3 === 2 && i >= n - 2 ? "lg:col-span-3" : "lg:col-span-2";
  const sm = n >= 2 && r2 === 1 && i === n - 1 ? "sm:max-lg:hidden" : "";
  return `${lg} ${sm}`;
}
