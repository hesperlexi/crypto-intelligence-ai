// Results: one place for "does it work?" - track record, demo bots, model accuracy, signal log, and the tools.
import { PageHeader, Segmented, TabStrip } from "../components/kit";
import { lazy, ReactNode, Suspense } from "react";
import { useSearchParams } from "react-router-dom";
import { useHesperVisibility } from "../lib/api";
import TrackRecord from "../components/TrackRecord";
import Accuracy from "./Accuracy";
import Bots from "./Bots";
import History from "./History";

const Rich = lazy(() => import("./Rich"));
const Leaderboard = lazy(() => import("../components/Leaderboard"));   // v2.16 practice leaderboard
// v2.60 (owner, 18 Nov 2026): 4 tabs instead of 7, nothing removed. Accuracy sits with the Signal log, the Hesper
// Challenge with the Demo bots; the old Tools tab only linked to the Tools menu (Backtest, Replay, Scanner).
// Old links (?tab=accuracy / challenge / tools) still open the right place.
type Tab = "track" | "bots" | "log" | "leaderboard";
const short = (full: string, phone: string) => <><span className="sm:hidden">{phone}</span><span className="hidden sm:inline">{full}</span></>;
// short labels on phones so all four fit one row
const TABS: readonly (readonly [Tab, ReactNode])[] = [["track", short("Track record", "Record")], ["bots", short("Demo bots", "Bots")], ["log", short("Signal log", "Log")], ["leaderboard", short("Leaderboard", "Leaders")]];
const PARENT: Record<string, Tab> = { accuracy: "log", challenge: "bots", tools: "track" };

export default function Results() {
  const [params, setParams] = useSearchParams();
  const hesper = useHesperVisibility();
  const raw = params.get("tab") ?? "track";
  const tab: Tab = (TABS.some(([k]) => k === raw) ? raw : PARENT[raw] ?? "track") as Tab;
  const challenge = hesper === "members";
  // the sub view inside a tab: Signal log | Accuracy, Demo bots | Hesper Challenge
  const sub = raw === "accuracy" || (raw === "challenge" && challenge) ? raw : tab;
  const go = (k: string) => { const p = new URLSearchParams(params); p.set("tab", k); setParams(p, { replace: true }); };
  return (
    <div className="space-y-4">
      <PageHeader title="Results" />
      <TabStrip label="Results" value={tab} options={TABS} onChange={(k) => go(k)} className="-mx-3 px-3 sm:mx-0 sm:px-0" />
      {tab === "track" && <TrackRecord />}
      {tab === "bots" && challenge && <Segmented label="Demo results" value={sub} options={[["bots", "Demo bots"], ["challenge", "Hesper Challenge"]] as const} onChange={go} />}
      {tab === "bots" && (sub === "challenge" ? <Suspense fallback={<div className="skeleton h-64 rounded-xl" />}><Rich embedded /></Suspense> : <Bots />)}
      {tab === "log" && <Segmented label="Signal log or model accuracy" value={sub} options={[["log", "Signal log"], ["accuracy", "Model accuracy"]] as const} onChange={go} />}
      {tab === "log" && (sub === "accuracy" ? <Accuracy /> : <History />)}
      {tab === "leaderboard" && <Suspense fallback={<div className="skeleton h-64 rounded-xl" />}><Leaderboard /></Suspense>}
    </div>
  );
}
