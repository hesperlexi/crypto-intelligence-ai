// Beginner vs Pro view. Pro (the default, so nothing changes for existing members) shows everything as before.
// Beginner hides the advanced numbers (scores, model statistics, confidence intervals, order-book depth) and adds
// short plain-language explanations. Saved per device; works without storage.
import { createContext, ReactNode, useCallback, useContext, useState } from "react";

export type ViewMode = "beginner" | "pro";
const KEY = "cia-view-mode";

function load(): ViewMode {
  try { return localStorage.getItem(KEY) === "beginner" ? "beginner" : "pro"; } catch { return "pro"; }
}

const Ctx = createContext<{ mode: ViewMode; setMode: (m: ViewMode) => void }>({ mode: "pro", setMode: () => {} });

export function ModeProvider({ children }: { children: ReactNode }) {
  const [mode, setM] = useState<ViewMode>(load);
  const setMode = useCallback((m: ViewMode) => {
    setM(m);
    try { localStorage.setItem(KEY, m); } catch { /* storage blocked: kept for this visit only */ }
  }, []);
  return <Ctx.Provider value={{ mode, setMode }}>{children}</Ctx.Provider>;
}

export const useMode = () => useContext(Ctx);
export const useIsPro = () => useContext(Ctx).mode === "pro";

/** Advanced content: shown in Pro mode only. */
export function ProOnly({ children }: { children: ReactNode }) {
  return useIsPro() ? <>{children}</> : null;
}

/** A short plain-language explanation: shown in Beginner mode only. */
export function Explain({ children, className = "" }: { children: ReactNode; className?: string }) {
  return useIsPro() ? null : <p className={`text-xs leading-snug text-mute ${className}`}>{children}</p>;
}

/** Plain-language glossary used next to trade-plan numbers in Beginner mode. */
export const PLAIN = {
  entry: "Entry: where to open the trade.",
  stop: "Stop-loss: where the trade closes to limit the loss.",
  targets: "Targets (TP1-TP3): where profit is taken.",
  leverage: "Leverage magnifies losses too. Lower is safer.",
  rr: "Reward/risk: possible gain per 1 of risk.",
  grade: "A: chart and AI agree. B: AI-led.",
} as const;

/** Compact header switch. */
export function ModeSwitch({ className = "" }: { className?: string }) {
  const { mode, setMode } = useMode();
  return (
    <div role="group" aria-label="View mode" className={`inline-flex rounded-lg border border-glass/10 p-0.5 text-[11px] ${className}`}>
      {(["beginner", "pro"] as const).map((m) => (
        <button key={m} type="button" aria-pressed={mode === m} onClick={() => setMode(m)}
          className={`rounded-md px-2 py-0.5 font-medium transition-colors ${mode === m ? "bg-accent/15 text-accent" : "text-mute hover:text-text"}`}
          title={m === "beginner" ? "Simpler view with short explanations" : "Every number and statistic"}>
          {m === "beginner" ? "Beginner" : "Pro"}
        </button>
      ))}
    </div>
  );
}
