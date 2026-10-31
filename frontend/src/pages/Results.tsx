// Results: one place for "does it work?" - track record, demo bots, model accuracy, signal log, and the tools.
import { Link, useSearchParams } from "react-router-dom";
import TrackRecord from "../components/TrackRecord";
import Accuracy from "./Accuracy";
import Bots from "./Bots";
import History from "./History";
import { VerifyBox } from "../components/SealProof";

const TABS = [["track", "Track record"], ["bots", "Demo bots"], ["accuracy", "Accuracy"], ["log", "Signal log"], ["tools", "Tools"]] as const;
type Tab = (typeof TABS)[number][0];

const TOOLS = [
  ["/backtest", "Backtest", "Run a strategy over past data with fees and slippage, and compare it with buy & hold."],
  ["/replay", "Replay", "Pick a past moment and see exactly what the app said then, with proof that nothing from the future was used."],
  ["/scanner", "Scanner", "Every coin's signal, regime and volatility side by side, sortable."],
] as const;

export default function Results() {
  const [params, setParams] = useSearchParams();
  const tab = (TABS.some(([k]) => k === params.get("tab")) ? params.get("tab") : "track") as Tab;
  const go = (k: Tab) => { const p = new URLSearchParams(params); p.set("tab", k); setParams(p, { replace: true }); };
  return (
    <div className="space-y-4">
      <div>
        <h1 className="page-title">Results</h1>
        <p className="page-sub">Does it work? Every signal's outcome, the demo bots that trade them, and how accurate the AI is on data it never saw.</p>
      </div>
      <div className="-mx-3 flex gap-1 overflow-x-auto border-b border-glass/[0.08] px-3 sm:mx-0 sm:px-0" role="tablist">
        {TABS.map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => go(k)}
            className={`-mb-px min-h-[44px] whitespace-nowrap border-b-2 px-3 text-sm transition-colors ${tab === k ? "border-accent font-semibold text-text" : "border-transparent text-mute hover:text-text"}`}>{l}</button>
        ))}
      </div>
      {tab === "track" && <><TrackRecord /><VerifyBox /></>}
      {tab === "bots" && <Bots />}
      {tab === "accuracy" && <Accuracy />}
      {tab === "log" && <History />}
      {tab === "tools" && (
        <ul className="grid gap-3 sm:grid-cols-3">
          {TOOLS.map(([to, title, text]) => (
            <li key={to}><Link to={to} className="panel block h-full p-4 transition hover:border-accent/50">
              <div className="font-semibold">{title} <span className="text-accent">→</span></div>
              <p className="mt-1 text-sm text-mute">{text}</p>
            </Link></li>
          ))}
        </ul>
      )}
    </div>
  );
}
