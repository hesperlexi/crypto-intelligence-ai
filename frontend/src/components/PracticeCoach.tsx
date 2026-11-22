// v2.68 practice coach (owner, 22 Nov 2026). Reads ONLY the member's own futures practice account (already open on the
// Trade page; no extra reads): the last closed trade gets a short review, and the last 20 closes show habits. Fixed,
// plain rules - it explains what happened and why it matters; it never tells anyone what to trade.
import { useMemo } from "react";
import { base, fmtPrice, isNum } from "../lib/format";

type Note = { tone: "good" | "warn" | "bad" | "info"; text: string };
const money = (v: number) => `${v >= 0 ? "+" : "−"}$${Math.abs(v).toFixed(2)}`;
const dur = (ms: number) => (ms < 3_600_000 ? `${Math.max(1, Math.round(ms / 60_000))} min` : ms < 86_400_000 ? `${(ms / 3_600_000).toFixed(1)} h` : `${(ms / 86_400_000).toFixed(1)} days`);

function review(c: any, open: any, wallet: number): Note[] {
  const out: Note[] = [];
  const pnl = Number(c.realized_pnl) || 0, lev = Number(c.leverage) || 1, roe = Number(c.roe_pct) || 0;
  const held = isNum(c.opened_at) && isNum(c.created_at) ? c.created_at - c.opened_at : null;
  if (c.reason === "liquidated") out.push({ tone: "bad", text: `Liquidated at ${lev}x: the price moved about ${(100 / lev).toFixed(1)}% against you and the whole margin was lost. Lower leverage gives a trade more room.` });
  else if (c.reason === "stop-loss") out.push({ tone: pnl < 0 ? "info" : "good", text: pnl < 0 ? "Your stop-loss closed this trade and kept the loss to what you planned. That is the stop doing its job." : "Your stop locked in a profit." });
  else if (c.reason === "take-profit") out.push({ tone: "good", text: "Your take-profit closed it at your target - planned and kept." });
  else if (pnl > 0 && held != null && held < 20 * 60_000 && roe < 20) out.push({ tone: "info", text: `Closed by hand after ${dur(held)} with a small gain. Quick exits are fine, but small wins need a high win rate to cover the losses.` });
  else if (pnl < 0 && Math.abs(roe) > 60) out.push({ tone: "warn", text: `Closed by hand at ${roe.toFixed(0)}% of the margin. A stop-loss set at the start decides the loss before emotions do.` });
  if (open && open.stop == null && c.reason !== "stop-loss") out.push({ tone: "warn", text: "This trade had no stop-loss when it opened. Every signal comes with a stop - adding it is the simplest protection." });
  if (lev > 20 && c.reason !== "liquidated") out.push({ tone: "warn", text: `${lev}x is high leverage: a ${(100 / lev).toFixed(1)}% move against you wipes the margin. Signal cards show a safer suggestion.` });
  const share = wallet > 0 && isNum(c.margin) ? (c.margin / (wallet + Math.max(0, -pnl))) * 100 : null;
  if (share != null && share > 30) out.push({ tone: "warn", text: `This trade used about ${share.toFixed(0)}% of your balance. Smaller trades make a losing streak much easier to survive.` });
  if (!out.length) out.push({ tone: pnl >= 0 ? "good" : "info", text: pnl >= 0 ? "Clean trade: sensible leverage and size." : "A normal loss with sensible leverage and size - losses are part of any method." });
  return out;
}

export default function PracticeCoach({ d }: { d: any }) {
  const data = useMemo(() => {
    const trades: any[] = d?.trades ?? [];
    const closes = trades.filter((t) => t.type === "CLOSE").sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0));
    if (!closes.length) return null;
    const last = closes[0];
    const open = trades.filter((t) => t.type === "OPEN" && t.symbol === last.symbol && t.side === last.side && (t.created_at ?? 0) <= (last.opened_at ?? 0) + 60_000)
      .sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))[0];
    const recent = closes.slice(0, 20);
    const wins = recent.filter((c) => Number(c.realized_pnl) > 0), losses = recent.filter((c) => Number(c.realized_pnl) <= 0);
    const avg = (a: any[]) => (a.length ? a.reduce((s, c) => s + (Number(c.realized_pnl) || 0), 0) / a.length : 0);
    const opens = trades.filter((t) => t.type === "OPEN").slice(-20);
    return {
      last, notes: review(last, open, Number(d?.wallet ?? d?.equity ?? 0)),
      n: recent.length, winRate: wins.length / recent.length, avgWin: avg(wins), avgLoss: avg(losses),
      withStop: opens.length ? opens.filter((t) => t.stop != null).length / opens.length : null,
      avgLev: recent.reduce((s, c) => s + (Number(c.leverage) || 1), 0) / recent.length,
      liqs: recent.filter((c) => c.reason === "liquidated").length,
    };
  }, [d]);
  if (!data) return null;
  const { last } = data;
  const pnl = Number(last.realized_pnl) || 0;
  const balanceNote = data.avgLoss < 0 && data.avgWin > 0 ? (data.avgWin / Math.abs(data.avgLoss)) : null;
  return (
    <section className="panel coach p-4" aria-label="Practice coach">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="label">Practice coach</h2>
        <span className="text-xs text-mute">your practice trades only · not advice</span>
      </div>
      <div className="coach-grid mt-3">
        <div className="coach-last">
          <div className="text-xs text-mute">Last closed trade</div>
          <div className="mt-1 flex flex-wrap items-baseline gap-x-2">
            <b>{base(last.symbol)}</b>
            <span className={`text-xs font-bold ${last.side > 0 ? "text-bull" : "text-bear"}`}>{last.side > 0 ? "LONG" : "SHORT"} {last.leverage}x</span>
            <span className={`num ml-auto font-semibold ${pnl >= 0 ? "text-bull" : "text-bear"}`}>{money(pnl)}{isNum(last.roe_pct) ? ` · ${last.roe_pct >= 0 ? "+" : ""}${last.roe_pct.toFixed(1)}%` : ""}</span>
          </div>
          <div className="text-xs text-mute">{isNum(last.entry) ? `entry ${fmtPrice(last.entry)} → ` : ""}exit {fmtPrice(last.price)}{isNum(last.opened_at) ? ` · held ${dur(last.created_at - last.opened_at)}` : ""}</div>
          <ul className="coach-notes">{data.notes.map((x) => <li key={x.text} className={`is-${x.tone}`}>{x.text}</li>)}</ul>
        </div>
        <div className="coach-habits">
          <div className="text-xs text-mute">Your habits · last {data.n} closed</div>
          <dl>
            <dt>Win rate</dt><dd className="num">{Math.round(data.winRate * 100)}%</dd>
            <dt>Average win / loss</dt><dd className="num"><span className="text-bull">{money(data.avgWin)}</span> / <span className="text-bear">{money(data.avgLoss)}</span></dd>
            <dt>Trades with a stop-loss</dt><dd className={`num ${data.withStop != null && data.withStop < 0.7 ? "text-warn" : ""}`}>{data.withStop == null ? "—" : `${Math.round(data.withStop * 100)}%`}</dd>
            <dt>Average leverage</dt><dd className={`num ${data.avgLev > 20 ? "text-warn" : ""}`}>{data.avgLev.toFixed(0)}x</dd>
            <dt>Liquidations</dt><dd className={`num ${data.liqs ? "text-bear" : ""}`}>{data.liqs}</dd>
          </dl>
          {balanceNote != null && (
            <p className="mt-2 text-xs text-mute">Your average win is {balanceNote.toFixed(1)}× your average loss{balanceNote < 1 ? `, so you need to win more than ${Math.round((1 / (1 + balanceNote)) * 100)}% of trades to come out ahead` : " - wins pay for losses"}.</p>
          )}
        </div>
      </div>
    </section>
  );
}
