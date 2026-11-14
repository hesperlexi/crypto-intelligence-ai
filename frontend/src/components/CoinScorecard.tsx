// v2.33 coin scorecard on Radar (owner, 14 Nov 2026): every watchlist coin sorted into a category from the real record
// (after fees), and - for the admin - the coins that give no good signals, suggested for removal (nothing automatic).
import { useState } from "react";
import { CoinAvatar } from "./Polish";
import { Badge } from "./kit";
import { Info } from "./ui";
import { del, post } from "../lib/api";
import { ago, base, isNum, slug } from "../lib/format";

type Coin = {
  symbol: string; pinned: boolean; calls: number; closed: number; wins: number; win_rate: number | null;
  avg_net_pct: number | null; total_net_pct: number | null; open: number; blocked: number; last_call_at: number | null;
  category: "best" | "working" | "early" | "losing" | "quiet"; suggest_remove: boolean; why: string | null; watched_days: number;
  past_test?: { avg_r: number | null; trades: number; win_rate: number | null } | null;
};
type Cand = { symbol: string; trades: number; avg_r: number | null; win_rate: number | null; trades_per_week: number;
  listings: Record<string, boolean | null>; verdict: "add" | "promising" | "no_mexc" | "weak" | "avoid" };
type Card = { since: number; days: number; coins: Coin[]; labels: Record<string, string>; counts: Record<string, number>;
  suggest_remove: string[]; method: string;
  study?: { stamp: string; method: string; candidates: Cand[]; baseline?: { expectancy_r: number } } | null };

const TONE: Record<Coin["category"], "bull" | "accent" | "mute" | "bear" | "warn"> =
  { best: "bull", working: "accent", early: "mute", losing: "bear", quiet: "warn" };
const ORDER: Coin["category"][] = ["best", "working", "early", "losing", "quiet"];
const pct = (v: number | null, d = 2) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "—");
const r = (v: number | null) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(2)}R` : "—");
const tone = (v: number | null) => (isNum(v) ? (v > 0 ? "text-bull" : v < 0 ? "text-bear" : "") : "text-mute");

function Row({ c }: { c: Coin }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2.5">
      <div className="flex min-w-0 items-center gap-2.5">
        <CoinAvatar symbol={c.symbol} size={28} />
        <div className="min-w-0">
          <div className="font-semibold leading-tight">{base(c.symbol)}{c.open > 0 && <span className="ml-1.5 text-xs font-normal text-accent">{c.open} running</span>}</div>
          <div className="num text-xs text-mute">
            {c.calls} signal{c.calls === 1 ? "" : "s"}{c.closed ? ` · ${c.wins}/${c.closed} won` : ""}
            {c.last_call_at ? ` · last ${ago(c.last_call_at)}` : ""}
          </div>
        </div>
      </div>
      <div className="num shrink-0 text-right">
        <div className={`text-sm font-semibold ${tone(c.total_net_pct)}`}>{pct(c.total_net_pct, 1)}</div>
        <div className="text-xs text-mute">{isNum(c.avg_net_pct) ? `avg ${pct(c.avg_net_pct)}` : "no closed calls"}</div>
        {c.past_test && isNum(c.past_test.avg_r) && <div className={`text-xs ${tone(c.past_test.avg_r)}`} title="Past test: unseen history replayed with the live rules and fees">test {r(c.past_test.avg_r)}</div>}
      </div>
    </div>
  );
}

function RemoveList({ coins, onDone }: { coins: Coin[]; onDone: (m: string) => void }) {
  const [ask, setAsk] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [gone, setGone] = useState<Set<string>>(new Set());
  const remove = async (s: string) => {
    setBusy(s);
    try {
      await del(`/watchlist/${slug(s)}`);
      setGone(new Set([...gone, s]));
      onDone(`${base(s)} removed. Signals already running on it still finish and count.`);
    } catch (e: any) { onDone(e.message); }
    setBusy(null); setAsk(null);
  };
  const list = coins.filter((c) => !gone.has(c.symbol));
  if (!list.length) return null;
  return (
    <section className="panel h-full border-warn/30 p-4">
      <h2 className="label">Suggested to remove</h2>
      <p className="mt-1 text-xs text-mute">Admin only. These give no good signals. Nothing is removed until you confirm.</p>
      <ul className="mt-2 divide-y divide-glass/[0.06]">
        {list.map((c) => (
          <li key={c.symbol} className="flex items-center justify-between gap-3 py-2.5">
            <div className="flex min-w-0 flex-1 items-center gap-2.5">
              <CoinAvatar symbol={c.symbol} size={28} />
              <div className="min-w-0"><div className="font-semibold">{base(c.symbol)}</div><div className="text-xs text-mute">{c.why}</div></div>
            </div>
            {ask === c.symbol ? (
              <div className="flex shrink-0 flex-col gap-2 sm:flex-row">
                <button className="btn btn-sm" onClick={() => setAsk(null)}>Cancel</button>
                <button className="btn btn-sm btn-danger" disabled={busy === c.symbol} onClick={() => remove(c.symbol)}>{busy === c.symbol ? "Removing…" : `Remove ${base(c.symbol)}`}</button>
              </div>
            ) : <button className="btn btn-sm shrink-0" onClick={() => setAsk(c.symbol)}>Remove</button>}
          </li>
        ))}
      </ul>
    </section>
  );
}

const VERDICT: Record<Cand["verdict"], [string, "bull" | "accent" | "warn" | "mute" | "bear"]> = {
  add: ["Worth adding", "bull"], promising: ["Promising, few trades", "accent"], no_mexc: ["Not on MEXC futures", "warn"],
  weak: ["About break-even", "mute"], avoid: ["Avoid", "bear"] };

function Tested({ study, admin, onMsg }: { study: NonNullable<Card["study"]>; admin: boolean; onMsg: (m: string) => void }) {
  const [added, setAdded] = useState<Set<string>>(new Set());
  const [all, setAll] = useState(false);
  const list = all ? study.candidates : study.candidates.filter((c) => c.verdict === "add" || c.verdict === "promising");
  if (!study.candidates?.length) return null;
  const add = async (s: string) => {
    try { await post("/watchlist", { symbol: s }); setAdded(new Set([...added, s])); onMsg(`${base(s)} added. Signals start once its AI model is trained (usually within a day).`); }
    catch (e: any) { onMsg(e.message); }
  };
  return (
    <section className="panel h-full p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="label">Tested new coins <Info label="How the coins were tested">{study.method} {isNum(study.baseline?.expectancy_r) ? `Your current coins scored ${r(study.baseline!.expectancy_r)} per trade in the same test.` : ""} A past test is not a promise of future results.</Info></h2>
        <button className="text-xs text-accent underline-offset-2 hover:underline" onClick={() => setAll(!all)}>{all ? "Show the best only" : `Show all ${study.candidates.length}`}</button>
      </div>
      <ul className="mt-2 divide-y divide-glass/[0.06]">
        {list.map((c) => {
          const [word, t] = VERDICT[c.verdict];
          const both = c.listings?.binance_futures && c.listings?.mexc_futures;
          return (
            <li key={c.symbol} className="flex items-center justify-between gap-3 py-2.5">
              <div className="flex min-w-0 flex-1 items-center gap-2.5">
                <CoinAvatar symbol={c.symbol} size={28} />
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-1.5 font-semibold">{base(c.symbol)} <Badge tone={t}>{word}</Badge></div>
                  <div className="num text-xs text-mute">{c.trades} test trades · won {isNum(c.win_rate) ? Math.round(c.win_rate * 100) : "—"}% · ~{c.trades_per_week.toFixed(1)}/week · {both ? "Binance + MEXC futures" : c.listings?.mexc_futures === false ? "not on MEXC futures" : "listing not confirmed"}</div>
                </div>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1.5 sm:flex-row sm:items-center sm:gap-3">
                <span className={`num text-sm font-semibold ${tone(c.avg_r)}`}>{r(c.avg_r)}<span className="ml-1 text-xs font-normal text-mute">/ trade</span></span>
                {admin && (c.verdict === "add" || c.verdict === "promising") && (added.has(c.symbol)
                  ? <span className="text-xs text-mute">Added</span>
                  : <button className="btn btn-sm btn-primary" onClick={() => add(c.symbol)}>+ Add</button>)}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export default function CoinScorecard({ card, admin }: { card?: Card | null; admin: boolean }) {
  const [msg, setMsg] = useState<string | null>(null);
  if (!card?.coins?.length) return null;
  const groups = ORDER.map((k) => [k, card.coins.filter((c) => c.category === k)] as const).filter(([, l]) => l.length);
  return (
    <div className="space-y-3">
      <section className="panel p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="label">Your coins: how their signals did <Info label="How coins are sorted">{card.method}</Info></h2>
          <span className="text-xs text-mute">last {Math.round(card.days)} days · after fees</span>
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {groups.map(([k, l]) => <Badge key={k} tone={TONE[k]}>{card.labels[k] ?? k} · {l.length}</Badge>)}
        </div>
        {/* one flowing list in balanced columns: rows never split, a group heading stays with its first row */}
        <div className="mt-3 gap-x-8 md:columns-2 xl:columns-3">
          {groups.map(([k, l]) => (
            <div key={k} className="contents">
              <h3 className="break-after-avoid pt-2 text-xs font-semibold text-mute">{card.labels[k] ?? k}</h3>
              {l.map((c) => <div key={c.symbol} className="break-inside-avoid border-b border-glass/[0.06] last:border-b-0"><Row c={c} /></div>)}
            </div>
          ))}
        </div>
      </section>
      {msg && <div role="status" className="rounded-lg border border-accent/40 bg-accent/10 px-3 py-2 text-sm">{msg}</div>}
      {(card.study || admin) && (
        <div className="grid items-stretch gap-3 lg:grid-cols-2 [&>*:only-child]:lg:col-span-2">
          {card.study && <Tested study={card.study} admin={admin} onMsg={setMsg} />}
          {admin && <RemoveList coins={card.coins.filter((c) => c.suggest_remove)} onDone={setMsg} />}
        </div>
      )}
    </div>
  );
}
