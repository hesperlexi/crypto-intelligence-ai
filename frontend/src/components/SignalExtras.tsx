// v1 signal-card extras (docs/v1-contract.md). Every field is optional: old rows lack them and render as before.
//   row.call            the tracked call for this coin/timeframe {status, fill_status, side, entry, stop, peak_r, peak_pct, exit_reason, managed}
//   row.ai              {rationale, regime, model, at}  (advisor note, analysis only)
//   row.record_status   "logged" | "already_open" | "not_logged"
//   row.stale           true when candles are too old to trade on
import { useState } from "react";
import { fmtPctRaw, isNum } from "../lib/format";
import { roiOf, roiTone, signedPct } from "../lib/roi";
import { AiTag } from "./ui";

type Tone = "bull" | "bear" | "warn" | "accent" | "mute";
const PILL: Record<Tone, string> = {
  bull: "border-bull/30 bg-bull/[0.08] text-bull",
  bear: "border-bear/30 bg-bear/[0.08] text-bear",
  warn: "border-warn/30 bg-warn/[0.08] text-warn",
  accent: "border-accent/30 bg-accent/[0.08] text-accent",
  mute: "border-glass/[0.12] bg-glass/[0.04] text-mute",
};

export function Pill({ tone = "mute", children, title }: { tone?: Tone; children: React.ReactNode; title?: string }) {
  return <span title={title} className={`inline-flex items-center whitespace-nowrap rounded-[5px] border px-1.5 py-[3px] text-[11px] font-semibold leading-none ${PILL[tone]}`}>{children}</span>;
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
  const st = call.exit_reason === "admin_close" && call.status === "EXPIRED" ? (["Closed", "mute"] as [string, Tone]) : CALL_STATUS[call.status];
  const fill = fillLabel(call.fill_status);
  const managed = call.managed === 1 ? managedLabel(call.exit_reason) : null;
  const open = call.status === "OPEN" && call.fill_status !== "PENDING" && call.fill_status !== "NOT_FILLED";
  const pnl = open ? livePnl(call.side, call.entry, px) : null;
  const peak = isNum(call.peak_r) || isNum(call.peak_pct);
  const done = call.status !== "OPEN" && isNum(call.return_pct);
  const liveLev = isNum(call.leverage) && call.leverage > 1 ? call.leverage : null;
  if (!st && !fill && !managed && pnl == null && !peak && !done) return null;
  return (
    <div className="space-y-1.5">
    {done && (
      <div className={`relative flex items-center justify-between gap-3 overflow-hidden rounded-xl border px-3 py-2.5 ${call.return_pct > 0 ? "border-bull/35 bg-bull/[0.07]" : "border-bear/35 bg-bear/[0.07]"}`}>
        <div className={`pointer-events-none absolute -right-8 -top-10 h-24 w-24 rounded-full blur-2xl ${call.return_pct > 0 ? "bg-bull/20" : "bg-bear/20"}`} aria-hidden="true" />
        <div className="relative min-w-0">
          <div className="label">Call result</div>
          <div className="mt-1 text-xs font-semibold">{st ? st[0] : call.status}</div>
        </div>
        <span className="relative"><RoiFigure x={call} size="md" /></span>
      </div>
    )}
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      {st && !done && <Pill tone={st[1]}>{st[0]}</Pill>}
      {fill && <Pill tone={fill[1]} title={call.fill_status === "PENDING" ? "Pullback entry: the call counts once price trades through the entry" : "Price never reached the entry; not counted in the win rate"}>{fill[0]}</Pill>}
      {managed && <Pill tone="accent" title="Closed by a managed exit rule">{managed}</Pill>}
      {call.exit_reason === "admin_stop" && call.status !== "OPEN" && <Pill tone="warn" title="Closed at the stop-loss the admin moved (public change)">Admin stop</Pill>}
      {call.exit_reason === "admin_close" && call.status !== "OPEN" && <Pill tone="warn" title="Closed by the admin at the market price (public); the result is what that price gave">Closed by admin</Pill>}
      {pnl != null && (liveLev
        ? <span className={`num font-semibold ${pnl >= 0 ? "text-bull" : "text-bear"}`} title="Live, from the current price vs the entry, on margin at the suggested leverage (before fees)">Live {fmtPctRaw(pnl * liveLev, 2)} ROI <span className="font-normal text-mute">· {liveLev}x · price {fmtPctRaw(pnl, 2)}</span></span>
        : <span className={`num font-semibold ${pnl >= 0 ? "text-bull" : "text-bear"}`} title="Live, from the current price vs the entry (price move, before fees)">Live {fmtPctRaw(pnl, 2)} price</span>)}
      {peak && (
        <span className="num text-mute" title="Best open profit reached since the call was published">
          Peak {isNum(call.peak_pct) ? fmtPctRaw(call.peak_pct, 2) : ""}{isNum(call.peak_r) ? `${isNum(call.peak_pct) ? " · " : ""}${call.peak_r.toFixed(2)}R` : ""}
        </span>
      )}
    </div>
    </div>
  );
}

/** Collapsible AI advisor note (the shared AI marker: .ai-block + AiTag). The advisor's regime label, when present,
 *  is shown as its own words next to the tag. */
export function AiNote({ ai }: { ai?: any }) {
  const [open, setOpen] = useState(false);
  const text: string | undefined = typeof ai?.rationale === "string" ? ai.rationale.trim() : undefined;
  if (!text) return null;
  const regime: string | undefined = typeof ai?.regime === "string" && ai.regime.trim() ? ai.regime.trim() : undefined;
  return (
    <div className="ai-block text-xs">
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)} className="flex w-full items-center justify-between gap-2 px-2.5 py-2 text-left text-mute transition-colors hover:text-text">
        <span className="flex min-w-0 items-center gap-2">
          <AiTag />
          <span className="truncate font-medium">Advisor note · analysis only{regime ? <span className="text-mute/80"> · regime: {regime}</span> : null}</span>
        </span>
        <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" className={`shrink-0 transition-transform ${open ? "rotate-180" : ""}`}><path d="M6 9l6 6 6-6" /></svg>
      </button>
      {open && <p className="px-2.5 pb-2.5 leading-relaxed text-text/90">{text}</p>}
    </div>
  );
}

/** Gold leverage chip ("10x"). */
export function LevChip({ lev, className = "" }: { lev: number; className?: string }) {
  return <span title="Leverage the signal card suggested" className={`num inline-flex h-[18px] items-center rounded-md border border-accent/45 bg-accent/10 px-1.5 text-[10px] font-bold leading-none text-accent ${className}`}>{lev}x</span>;
}

/** The headline result of a closed call: ROI on margin with its leverage chip, the price move as small text.
 *  Without a leverage it shows the price move, labelled as such. align: text alignment of the block. */
export function RoiFigure({ x, size = "md", align = "right", label = true }: { x: any; size?: "sm" | "md" | "lg"; align?: "left" | "right" | "center"; label?: boolean }) {
  const r = roiOf(x);
  if (!r) return <span className="num text-mute">—</span>;
  const big = size === "lg" ? "text-3xl" : size === "md" ? "text-xl" : "text-sm";
  const just = align === "right" ? "items-end text-right" : align === "center" ? "items-center text-center" : "items-start text-left";
  return (
    <span className={`inline-flex flex-col gap-0.5 ${just}`}>
      <span className={`flex items-center gap-1.5 ${align === "right" ? "flex-row-reverse" : ""}`}>
        <span className={`num font-extrabold leading-none tracking-tight ${big} ${roiTone(r.value)}`}>{signedPct(r.value)}</span>
        {r.leverage && <LevChip lev={r.leverage} />}
      </span>
      {label && (
        <span className="num whitespace-nowrap text-[10px] leading-none text-mute">
          {r.onMargin ? <>ROI on margin · price {signedPct(r.price)}</> : "price move"}
        </span>
      )}
    </span>
  );
}
