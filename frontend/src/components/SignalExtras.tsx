// v1 signal-card extras (docs/v1-contract.md). Every field is optional: old rows lack them and render as before.
//   row.call            the tracked call for this coin/timeframe {status, fill_status, side, entry, stop, peak_r, peak_pct, exit_reason, managed}
//   row.ai              {rationale, regime, model, at}  (advisor note, analysis only)
//   row.record_status   "logged" | "already_open" | "not_logged"
//   row.stale           true when candles are too old to trade on
import { useState } from "react";
import { fmtPctRaw, isNum } from "../lib/format";

type Tone = "bull" | "bear" | "warn" | "accent" | "mute";
const PILL: Record<Tone, string> = {
  bull: "border-bull/40 bg-bull/10 text-bull",
  bear: "border-bear/40 bg-bear/10 text-bear",
  warn: "border-warn/40 bg-warn/10 text-warn",
  accent: "border-accent/40 bg-accent/10 text-accent",
  mute: "border-glass/15 bg-glass/[0.05] text-mute",
};

export function Pill({ tone = "mute", children, title }: { tone?: Tone; children: React.ReactNode; title?: string }) {
  return <span title={title} className={`inline-flex items-center whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px] font-semibold leading-none ${PILL[tone]}`}>{children}</span>;
}

/** Call status as shown on cards (same words as the track record). */
export const CALL_STATUS: Record<string, [string, Tone]> = {
  OPEN: ["Open", "accent"], TP1: ["Target 1 hit", "bull"], TP2: ["Target 2 hit", "bull"], TP3: ["Target 3 hit", "bull"],
  STOPPED: ["Stopped", "bear"], EXPIRED: ["Expired", "mute"],
};

/** Managed exits (managed == 1): label by exit_reason. */
export function managedLabel(reason?: string | null): string | null {
  if (reason === "giveback") return "Give-back exit";
  if (reason === "trail") return "Trailing stop";
  if (reason === "time") return "Time stop";
  return null;
}

/** Fill status of pullback entries. FILLED shows nothing extra. */
export function fillLabel(fill?: string | null): [string, Tone] | null {
  if (fill === "PENDING") return ["Waiting for entry", "warn"];
  if (fill === "NOT_FILLED") return ["Entry missed", "mute"];
  return null;
}

/**
 * Risk level of a plan, from how far the stop is and the suggested leverage.
 * Loss on margin if the stop is hit ≈ stop distance % × leverage (spot: leverage 1).
 *   Low:    loss at stop < 10% of the margin and leverage ≤ 5x
 *   Medium: loss at stop < 30% of the margin and leverage ≤ 10x
 *   High:   anything above (≥ 30% of the margin at the stop, or leverage above 10x)
 */
export const RISK_THRESHOLDS = { lowLoss: 10, lowLev: 5, medLoss: 30, medLev: 10 } as const;
export function riskLevel(entry?: number, stop?: number, leverage?: number | null): { level: "Low" | "Medium" | "High"; lossAtStop: number } | null {
  if (!isNum(entry) || !isNum(stop) || !entry) return null;
  const stopPct = Math.abs(entry - stop) / entry * 100;
  const lev = isNum(leverage) && leverage > 1 ? leverage : 1;
  const loss = stopPct * lev;
  const t = RISK_THRESHOLDS;
  const level = loss < t.lowLoss && lev <= t.lowLev ? "Low" : loss < t.medLoss && lev <= t.medLev ? "Medium" : "High";
  return { level, lossAtStop: loss };
}

export function RiskBadge({ entry, stop, leverage }: { entry?: number; stop?: number; leverage?: number | null }) {
  const r = riskLevel(entry, stop, leverage);
  if (!r) return null;
  const tone: Tone = r.level === "Low" ? "bull" : r.level === "Medium" ? "warn" : "bear";
  const lev = isNum(leverage) && leverage > 1 ? ` at ${leverage}x` : "";
  return <Pill tone={tone} title={`If the stop is hit: about ${r.lossAtStop.toFixed(1)}% of the position's margin${lev}`}>{r.level} risk</Pill>;
}

/** Live P&L of an open call in % price move (side-aware), from the live price vs the entry. */
export function livePnl(side: string | undefined, entry: number | undefined, px: number | undefined): number | null {
  if (!isNum(entry) || !isNum(px) || !entry) return null;
  const m = (px / entry - 1) * 100;
  return side === "SHORT" ? -m : m;
}

/** Status, fill, managed exit, live P&L and peak profit of the tracked call. Renders nothing for old rows. */
export function CallStatusRow({ call, px }: { call?: any; px?: number }) {
  if (!call) return null;
  const st = CALL_STATUS[call.status];
  const fill = fillLabel(call.fill_status);
  const managed = call.managed === 1 ? managedLabel(call.exit_reason) : null;
  const open = call.status === "OPEN" && call.fill_status !== "PENDING" && call.fill_status !== "NOT_FILLED";
  const pnl = open ? livePnl(call.side, call.entry, px) : null;
  const peak = isNum(call.peak_r) || isNum(call.peak_pct);
  if (!st && !fill && !managed && pnl == null && !peak) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      {st && <Pill tone={st[1]}>{st[0]}</Pill>}
      {fill && <Pill tone={fill[1]} title={call.fill_status === "PENDING" ? "Pullback entry: the call counts once price trades through the entry" : "Price never reached the entry; not counted in the win rate"}>{fill[0]}</Pill>}
      {managed && <Pill tone="accent" title="Closed by a managed exit rule">{managed}</Pill>}
      {pnl != null && <span className={`num font-semibold ${pnl >= 0 ? "text-bull" : "text-bear"}`} title="Live, from the current price vs the entry (price move, before fees)">Live {fmtPctRaw(pnl, 2)}</span>}
      {peak && (
        <span className="num text-mute" title="Best open profit reached since the call was published">
          Peak {isNum(call.peak_pct) ? fmtPctRaw(call.peak_pct, 2) : ""}{isNum(call.peak_r) ? `${isNum(call.peak_pct) ? " · " : ""}${call.peak_r.toFixed(2)}R` : ""}
        </span>
      )}
    </div>
  );
}

/** Collapsible AI advisor note. */
export function AiNote({ ai }: { ai?: any }) {
  const [open, setOpen] = useState(false);
  const text: string | undefined = typeof ai?.rationale === "string" ? ai.rationale.trim() : undefined;
  if (!text) return null;
  return (
    <div className="rounded-lg border border-glass/[0.08] bg-ink/30 text-xs">
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)} className="flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left text-mute hover:text-text">
        <span className="font-semibold">AI note · analysis only</span>
        <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" className={`transition-transform ${open ? "rotate-180" : ""}`}><path d="M6 9l6 6 6-6" /></svg>
      </button>
      {open && <p className="px-2.5 pb-2 leading-relaxed text-text/90">{text}</p>}
    </div>
  );
}
