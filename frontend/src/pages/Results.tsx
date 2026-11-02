// Results: one place for "does it work?" - track record, demo bots, model accuracy, signal log, and the tools.
import { lazy, Suspense } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useHesperVisibility } from "../lib/api";
import TrackRecord from "../components/TrackRecord";
import Accuracy from "./Accuracy";
import Bots from "./Bots";
import History from "./History";

const Rich = lazy(() => import("./Rich"));
const TABS = [["track", "Track record"], ["bots", "Demo bots"], ["accuracy", "Accuracy"], ["log", "Signal log"], ["tools", "Tools"]] as const;
// the Hesper challenge tab appears only when the admin shows it to members (config/hesper.visibility)
const CHALLENGE = ["challenge", "Hesper Challenge"] as const;
type Tab = (typeof TABS)[number][0] | (typeof CHALLENGE)[0];

const TOOLS = [
  ["/backtest", "Backtest", "Test a strategy on past data vs buy & hold."],
  ["/replay", "Replay", "See what the app said at a past moment."],
  ["/scanner", "Scanner", "All coins side by side."],
] as const;

export default function Results() {
  const [params, setParams] = useSearchParams();
  const hesper = useHesperVisibility();
  const tabs: readonly (readonly [Tab, string])[] = hesper === "members" ? [...TABS, CHALLENGE] : TABS;
  const tab = (tabs.some(([k]) => k === params.get("tab")) ? params.get("tab") : "track") as Tab;
  const go = (k: Tab) => { const p = new URLSearchParams(params); p.set("tab", k); setParams(p, { replace: true }); };
  return (
    <div className="space-y-4">
      <div>
        <h1 className="page-title">Results</h1>
        <p className="page-sub">Every signal's outcome, wins and losses.</p>
      </div>
      <div className="-mx-3 flex gap-1 overflow-x-auto border-b border-glass/[0.08] px-3 sm:mx-0 sm:px-0" role="tablist">
        {tabs.map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => go(k)}
            className={`-mb-px min-h-[44px] whitespace-nowrap border-b-2 px-3 text-sm transition-colors ${tab === k ? "border-accent font-semibold text-text" : "border-transparent text-mute hover:text-text"}`}>{l}</button>
        ))}
      </div>
      {tab === "track" && <TrackRecord />}
      {tab === "bots" && <Bots />}
      {tab === "accuracy" && <Accuracy />}
      {tab === "log" && <History />}
      {tab === "challenge" && <Suspense fallback={<div className="skeleton h-64 rounded-xl" />}><Rich embedded /></Suspense>}
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
