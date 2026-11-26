// V3.4 Stage 5: the engine's setup checklist (services/opportunity_score) on a signal card, with the advisory strategy
// fit (services/strategy_select). A score of how many quality boxes the setup ticks - never a chance of winning.
import { useState } from "react";

const NAMES: Record<string, string> = {
  trend: "Trend", momentum: "Momentum", relative: "vs BTC", volume: "Volume", liquidity: "Liquidity", volatility: "Volatility",
  regime: "Market regime", entry: "Entry", reward: "Reward : risk", stop: "Stop distance", costs: "Costs", correlation: "Open positions",
};
const FIT: Record<string, string> = {
  TRADE: "v3-ok", WAIT: "v3-watch", "NO TRADE": "v3-muted", "STRATEGY UNSUITABLE": "v3-act", "INSUFFICIENT DATA": "v3-muted",
};
const tone = (s: number) => (s >= 70 ? "--bull" : s >= 45 ? "--warn" : "--bear");

export default function SetupScore({ op, fit }: { op?: any; fit?: any }) {
  const [open, setOpen] = useState(false);
  if (!op || typeof op.score !== "number") return fit ? <FitLine fit={fit} /> : null;
  const comps = Object.entries(op.components ?? {}).filter(([, v]) => typeof v === "number") as [string, number][];
  return (
    <div className="setup-score">
      <button type="button" className="setup-head" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="text-xs text-mute">Setup checklist</span>
        <span className="setup-bar" aria-hidden="true"><span style={{ width: `${op.score}%`, background: `rgb(var(${tone(op.score)}))` }} /></span>
        <span className="num text-sm font-semibold">{op.score}<span className="text-xs font-normal text-mute">/100</span></span>
        <span className="text-xs text-mute">{open ? "Hide" : "Details"}</span>
      </button>
      {fit && <FitLine fit={fit} />}
      {open && (
        <div className="mt-2 space-y-2 text-xs">
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
            {comps.map(([k, v]) => (
              <div key={k} className="flex items-center justify-between gap-2"><span className="text-mute">{NAMES[k] ?? k}</span><span className="num" style={{ color: `rgb(var(${tone(v)}))` }}>{v}</span></div>
            ))}
          </div>
          {!!(op.positive ?? []).length && <p><span className="text-bull">For:</span> <span className="text-mute">{op.positive.join(" · ")}</span></p>}
          {!!(op.negative ?? []).length && <p><span className="text-bear">Against:</span> <span className="text-mute">{op.negative.join(" · ")}</span></p>}
          {!!(op.warnings ?? []).length && <p className="text-warn">⚠ {op.warnings.join(" · ")}</p>}
          {!!(op.rejection ?? []).length && <p><span className="text-mute">Held back by:</span> {op.rejection.join(", ")}</p>}
          <p className="text-mute">Each part scores 0-100 and the total is their plain average{typeof op.coverage === "number" && op.coverage < 1 ? ` (${Math.round(op.coverage * 12)} of 12 parts measured)` : ""}. It rates the setup's quality; it is not a chance of winning.</p>
        </div>
      )}
    </div>
  );
}

function FitLine({ fit }: { fit: any }) {
  if (!fit?.action) return null;
  return (
    <p className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
      <span className={`v3-pill ${FIT[fit.action] ?? "v3-muted"}`}>{fit.action === "TRADE" ? "Strategy fit: ok" : fit.action.toLowerCase().replace(/^./, (c: string) => c.toUpperCase())}</span>
      <span className="text-mute">{fit.reason}</span>
    </p>
  );
}
