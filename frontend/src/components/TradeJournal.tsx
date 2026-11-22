// v2.75 Trade journal (owner, 22 Nov 2026). The member's own futures practice trades (already loaded on the Trade page; no
// extra reads, no writes): a month-by-month summary and the latest closed trades with a private note each. Notes stay on
// this device (localStorage `cia-journal-<uid>`), so the free-plan write budget is untouched.
import { useMemo, useState } from "react";
import { base, fmtPrice, isNum } from "../lib/format";
import { myUid } from "../lib/session";
import { SizeCalcButton } from "./SizeCalc";

const key = () => { try { return `cia-journal-${myUid()}`; } catch { return "cia-journal"; } };
const loadNotes = (): Record<string, string> => { try { return JSON.parse(localStorage.getItem(key()) ?? "{}"); } catch { return {}; } };
const money = (v: number) => `${v >= 0 ? "+" : "−"}$${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
const idOf = (t: any) => String(t.id ?? `${t.created_at}-${t.symbol}-${t.side}`);
const monthOf = (ms: number) => new Date(ms).toLocaleDateString(undefined, { month: "long", year: "numeric" });

export default function TradeJournal({ d }: { d: any }) {
  const [notes, setNotes] = useState<Record<string, string>>(loadNotes);
  const [all, setAll] = useState(false);
  const closes = useMemo(() => ((d?.trades ?? []) as any[]).filter((t) => t.type === "CLOSE" && isNum(t.created_at))
    .sort((a, b) => b.created_at - a.created_at), [d]);
  const months = useMemo(() => {
    const m = new Map<string, any[]>();
    for (const c of closes) { const k = monthOf(c.created_at); m.set(k, [...(m.get(k) ?? []), c]); }
    return [...m.entries()].slice(0, 3).map(([k, rows]) => {
      const p = rows.map((r) => Number(r.realized_pnl) || 0), won = p.filter((x) => x > 0).length;
      return { k, n: rows.length, won, net: p.reduce((a, b) => a + b, 0), best: Math.max(...p), worst: Math.min(...p) };
    });
  }, [closes]);
  const save = (id: string, text: string) => setNotes((n) => {
    const next = { ...n }; if (text.trim()) next[id] = text.slice(0, 280); else delete next[id];
    try { localStorage.setItem(key(), JSON.stringify(next)); } catch { /* ignore */ }
    return next;
  });
  const shown = all ? closes.slice(0, 50) : closes.slice(0, 6);
  return (
    <section className="panel p-4" aria-label="Trade journal">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div><h2 className="label">Trade journal</h2><p className="text-xs text-mute">Your practice trades by month · notes stay on this device</p></div>
        <SizeCalcButton seed={{}} className="btn btn-sm" label="Position-size calculator" />
      </div>
      {!closes.length ? <p className="mt-3 text-sm text-mute">Close a practice trade and it appears here, ready for a note.</p> : (
        <>
          <div className="jr-months mt-3">
            {months.map((m) => (
              <div key={m.k} className="jr-month">
                <div className="text-xs text-mute">{m.k}</div>
                <div className={`num font-display text-xl font-semibold ${m.net >= 0 ? "text-bull" : "text-bear"}`}>{money(m.net)}</div>
                <div className="text-xs text-mute"><span className="num">{m.n}</span> trades · <span className="num">{Math.round((m.won / m.n) * 100)}%</span> won</div>
                <div className="text-xs text-mute">best <span className="num text-bull">{money(m.best)}</span> · worst <span className="num text-bear">{money(m.worst)}</span></div>
              </div>
            ))}
          </div>
          <ul className="mt-4">
            {shown.map((c) => {
              const id = idOf(c), pnl = Number(c.realized_pnl) || 0;
              const long = c.side === "LONG" || Number(c.side) > 0 || c.side === "BUY";
              return (
                <li key={id} className="jr-row">
                  <div className="jr-head">
                    <b>{base(c.symbol)}</b>
                    <span className={`text-xs font-semibold ${long ? "text-bull" : "text-bear"}`}>{long ? "LONG" : "SHORT"}</span>
                    <span className="text-xs text-mute">{new Date(c.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })} · {c.reason ?? "closed"}{isNum(c.price) ? ` at ${fmtPrice(c.price)}` : ""}</span>
                    <span className={`num ml-auto font-semibold ${pnl >= 0 ? "text-bull" : "text-bear"}`}>{money(pnl)}</span>
                  </div>
                  <input className="input jr-note" placeholder="Why you took it, what you learned…" defaultValue={notes[id] ?? ""} maxLength={280}
                    onBlur={(e) => save(id, e.target.value)} aria-label={`Note for the ${base(c.symbol)} trade`} />
                </li>
              );
            })}
          </ul>
          {closes.length > 6 && <button type="button" className="mt-2 text-sm font-medium text-accent hover:underline" onClick={() => setAll((v) => !v)}>{all ? "Show fewer" : `Show more (${Math.min(50, closes.length)})`}</button>}
        </>
      )}
    </section>
  );
}
