// v2.22 market turn detector (admin only, recommend-only). Data: views/market_turn (backend services/turn_detector.py),
// admin only in the rules. Shown on Health (full card) and on the Trade Guardian page (compact). It never changes a call.
import { doc, onSnapshot } from "firebase/firestore";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { db } from "../lib/firebase";
import { ago, base, fmtNum, fmtPctRaw } from "../lib/format";
import { Badge, type Tone } from "./kit";

export type TurnReason = { code: string; points: number; text: string };
export type TurnCoin = { symbol: string; state: string; trend: string; points: number; reasons: TurnReason[]; price?: number };
export type MarketTurnView = {
  generated_at: number;
  market: { state: string; trend: string; score: number; btc_points?: number; btc_state?: string;
            breadth: { trending: number; turning: number; weakening: number }; reasons: TurnReason[] };
  stablecoins?: { usd: number; chg_7d_pct: number; day: number } | null;
  data?: { at?: number; done?: string[]; rows_total?: number; supported?: number; errors?: string[] };
  coins: TurnCoin[];
  note?: string;
};

/** views/market_turn (null while missing or unreadable). */
export function useMarketTurn(): MarketTurnView | null {
  const [raw, setRaw] = useState<any>(null);
  useEffect(() => onSnapshot(doc(db, "views", "market_turn"), (d) => setRaw(d.data() ?? null), () => setRaw(null)), []);
  return useMemo(() => { try { return raw?.json ? JSON.parse(raw.json) : null; } catch { return null; } }, [raw]);
}

export function stateTone(s: string | undefined): Tone {
  if (!s) return "mute";
  if (s.startsWith("turning")) return "warn";
  if (s === "weakening") return "accent";
  return "mute";
}

const label = (s: string | undefined) => (s ? s[0].toUpperCase() + s.slice(1) : "—");

/** compact: one line for the Trade Guardian page; full: market, top coins, data health. */
export function MarketTurnCard({ v, compact = false }: { v: MarketTurnView; compact?: boolean }) {
  const m = v.market;
  const movers = v.coins.filter((c) => c.points > 0).slice(0, compact ? 3 : 6);
  return (
    <section aria-label="Market turn" className={`panel ${compact ? "p-3" : "p-4"} space-y-2`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="label">Market turn</span>
        <Badge tone={stateTone(m.state)} caps>{label(m.state)}</Badge>
        <span className="text-xs text-mute">trend {m.trend} · score <span className="num text-text">{m.score}</span>/100 · BTC {m.btc_state ?? "—"}</span>
        <span className="ml-auto text-xs text-mute">{ago(v.generated_at)}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-glass/[0.08]" aria-hidden="true">
        <div className={`h-full rounded-full ${m.score >= 50 ? "bg-warn" : m.score >= 25 ? "bg-accent" : "bg-mute/50"}`} style={{ width: `${Math.min(100, Math.max(2, m.score))}%` }} />
      </div>
      <p className="text-xs text-mute">
        {m.breadth.turning} of {m.breadth.trending} trending coins turning, {m.breadth.weakening} weakening
        {v.stablecoins ? <> · stablecoins {fmtNum(v.stablecoins.usd / 1e9, 0)}B ({fmtPctRaw(v.stablecoins.chg_7d_pct, 2)} 7d)</> : null}
      </p>
      {!compact && m.reasons.length > 0 && (
        <ul className="space-y-0.5 text-xs">{m.reasons.map((r) => <li key={r.code}><span className="num text-accent">+{r.points}</span> BTC: {r.text}</li>)}</ul>
      )}
      {movers.length > 0 && (
        <ul className={`grid gap-1.5 ${compact ? "sm:grid-cols-3" : "sm:grid-cols-2"}`}>
          {movers.map((c) => (
            <li key={c.symbol} className="rounded-lg bg-glass/[0.03] px-2 py-1.5 text-xs">
              <div className="flex items-center gap-1.5">
                <Link to={`/asset/${base(c.symbol).toLowerCase()}?tf=4h`} className="font-semibold hover:text-accent">{base(c.symbol)}</Link>
                <span className="text-mute">{c.trend}trend</span>
                <Badge tone={stateTone(c.state)} className="ml-auto">{label(c.state)} · {c.points}</Badge>
              </div>
              {!compact && c.reasons.slice(0, 3).map((r) => <div key={r.code} className="mt-0.5 text-mute">+{r.points} {r.text}</div>)}
            </li>
          ))}
        </ul>
      )}
      {!compact && v.data && (
        <p className="text-xs text-mute">Live OKX data: {v.data.supported ?? 0} coins available · {fmtNum(v.data.rows_total ?? 0, 0)} hourly rows recorded
          {v.data.at ? ` · last read ${ago(v.data.at)}` : ""}{v.data.errors?.length ? ` · ${v.data.errors.length} source problem(s)` : ""}</p>
      )}
    </section>
  );
}
