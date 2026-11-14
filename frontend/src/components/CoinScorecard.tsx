// v2.33 coin scorecard on Radar (owner, 14 Nov 2026): every watchlist coin sorted into a category from the real record
// (after fees), and - for the admin - the coins that give no good signals, suggested for removal (nothing automatic).
import { useState } from "react";
import { CoinAvatar } from "./Polish";
import { Badge } from "./kit";
import { Info } from "./ui";
import { del } from "../lib/api";
import { ago, base, isNum, slug } from "../lib/format";

type Coin = {
  symbol: string; pinned: boolean; calls: number; closed: number; wins: number; win_rate: number | null;
  avg_net_pct: number | null; total_net_pct: number | null; open: number; blocked: number; last_call_at: number | null;
  category: "best" | "working" | "early" | "losing" | "quiet"; suggest_remove: boolean; why: string | null; watched_days: number;
};
type Card = { since: number; days: number; coins: Coin[]; labels: Record<string, string>; counts: Record<string, number>;
  suggest_remove: string[]; method: string };

const TONE: Record<Coin["category"], "bull" | "accent" | "mute" | "bear" | "warn"> =
  { best: "bull", working: "accent", early: "mute", losing: "bear", quiet: "warn" };
const ORDER: Coin["category"][] = ["best", "working", "early", "losing", "quiet"];
const pct = (v: number | null, d = 2) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "—");
const tone = (v: number | null) => (isNum(v) ? (v > 0 ? "text-bull" : v < 0 ? "text-bear" : "") : "text-mute");

function Row({ c }: { c: Coin }) {
  return (
    <li className="flex items-center justify-between gap-3 py-2.5">
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
      </div>
    </li>
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
    <section className="panel border-warn/30 p-4">
      <h2 className="label">Suggested to remove</h2>
      <p className="mt-1 text-xs text-mute">Admin only. These give no good signals. Nothing is removed until you confirm.</p>
      <ul className="mt-2 divide-y divide-glass/[0.06]">
        {list.map((c) => (
          <li key={c.symbol} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
            <div className="flex min-w-0 items-center gap-2.5">
              <CoinAvatar symbol={c.symbol} size={28} />
              <div className="min-w-0"><div className="font-semibold">{base(c.symbol)}</div><div className="text-xs text-mute">{c.why}</div></div>
            </div>
            {ask === c.symbol ? (
              <div className="flex gap-2">
                <button className="btn btn-sm" onClick={() => setAsk(null)}>Cancel</button>
                <button className="btn btn-sm btn-danger" disabled={busy === c.symbol} onClick={() => remove(c.symbol)}>{busy === c.symbol ? "Removing…" : `Remove ${base(c.symbol)}`}</button>
              </div>
            ) : <button className="btn btn-sm" onClick={() => setAsk(c.symbol)}>Remove</button>}
          </li>
        ))}
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
        <div className="mt-3 grid gap-x-6 md:grid-cols-2">
          {groups.map(([k, l]) => (
            <div key={k} className="mt-2">
              <h3 className="text-xs font-semibold text-mute">{card.labels[k] ?? k}</h3>
              <ul className="divide-y divide-glass/[0.06]">{l.map((c) => <Row key={c.symbol} c={c} />)}</ul>
            </div>
          ))}
        </div>
      </section>
      {msg && <div role="status" className="rounded-lg border border-accent/40 bg-accent/10 px-3 py-2 text-sm">{msg}</div>}
      {admin && <RemoveList coins={card.coins.filter((c) => c.suggest_remove)} onDone={setMsg} />}
    </div>
  );
}
