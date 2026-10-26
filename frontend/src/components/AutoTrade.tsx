// Auto-trade: the app's futures signals are placed in the member's practice account automatically, also while the
// app is closed (the engine does it on every run). Settings in Firestore auto_paper/{uid}; the engine's log in
// auto_paper_state/{uid}. Virtual money only.
import { doc, onSnapshot, setDoc } from "firebase/firestore";
import { useEffect, useState } from "react";
import { db } from "../lib/firebase";
import { base, fmtPrice, fmtTime } from "../lib/format";
import { myUid } from "../lib/session";

const DEF = { enabled: false, margin: 100, leverage: "signal" as number | "signal", timeframes: ["1h", "4h"], grades: "AB", take: "tp2", max_open: 5, coins: "all", notify: true, scale: true, max_same_side: 3 };
type S = typeof DEF;

export default function AutoTrade() {
  const [s, setS] = useState<S>(DEF);
  const [saved, setSaved] = useState<S>(DEF);
  const [log, setLog] = useState<any[]>([]);
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => onSnapshot(doc(db, "auto_paper", myUid()), (d) => { const v = { ...DEF, ...(d.data() ?? {}) } as S; setS(v); setSaved(v); }, () => {}), []);
  useEffect(() => onSnapshot(doc(db, "auto_paper_state", myUid()), (d) => setLog(d.data()?.log ?? []), () => {}), []);
  const dirty = JSON.stringify(s) !== JSON.stringify(saved);
  const save = async (next: S, note: string) => {
    try { await setDoc(doc(db, "auto_paper", myUid()), { ...next, updated_at: Date.now() }); setMsg(note); } catch (e: any) { setMsg(e.message); }
  };
  const toggleTf = (tf: string) => setS({ ...s, timeframes: s.timeframes.includes(tf) ? s.timeframes.filter((x) => x !== tf) : [...s.timeframes, tf] });

  return (
    <section className={`panel border p-0 ${saved.enabled ? "border-accent/50" : ""}`}>
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div>
          <div className="flex items-center gap-2 font-semibold">Auto-trade signals {saved.enabled && <span className="rounded bg-bull/15 px-1.5 py-0.5 text-[10px] font-bold text-bull">ON</span>}</div>
          <p className="text-xs text-mute">{saved.enabled
            ? `Every new futures signal (${saved.timeframes.map((t) => t.toUpperCase()).join(" + ")}, grade ${saved.grades === "A" ? "A" : "A+B"}) opens with $${saved.margin} margin at ${saved.leverage === "signal" ? "the suggested" : `${saved.leverage}x`} leverage, also while the app is closed.`
            : "Let the app place its futures signals in this practice account automatically, with the margin you choose."}</p>
        </div>
        <div className="flex gap-2">
          <button className="btn px-3 py-1.5 text-xs" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? "Close" : "Settings"}</button>
          <button className={`btn px-3 py-1.5 text-xs ${saved.enabled ? "" : "btn-primary"}`} onClick={() => save({ ...s, enabled: !saved.enabled }, saved.enabled ? "Auto-trade is off. Open trades stay until they hit their stop or target." : "Auto-trade is on. New signals are placed on the next engine run (every few minutes).")}>
            {saved.enabled ? "Turn off" : "Turn on"}
          </button>
        </div>
      </div>
      {msg && <div role="status" className="mx-4 mb-3 rounded-lg border border-accent/40 bg-accent/10 px-3 py-2 text-xs">{msg}</div>}
      {open && (
        <div className="grid gap-3 border-t border-glass/[0.06] px-4 py-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <label className="block"><span className="text-xs text-mute">Margin per trade (USDT)</span>
            <input className="input mt-1" type="number" min={1} step={10} value={s.margin} onChange={(e) => setS({ ...s, margin: Math.max(1, Number(e.target.value) || 0) })} /></label>
          <label className="block"><span className="text-xs text-mute">Leverage</span>
            <select className="input mt-1" value={String(s.leverage)} onChange={(e) => setS({ ...s, leverage: e.target.value === "signal" ? "signal" : Number(e.target.value) })}>
              <option value="signal">Suggested by the signal (safest)</option>
              {[1, 2, 3, 5, 10, 20].map((l) => <option key={l} value={l}>{l}x (capped so liquidation stays beyond the stop)</option>)}
            </select></label>
          <div><span className="text-xs text-mute">Timeframes</span>
            <div className="mt-1 flex gap-1">{["1h", "4h", "12h", "1d"].map((tf) => <button key={tf} className={`btn flex-1 px-2 py-1.5 text-xs ${s.timeframes.includes(tf) ? "btn-on" : ""}`} aria-pressed={s.timeframes.includes(tf)} onClick={() => toggleTf(tf)}>{tf.toUpperCase()}</button>)}</div></div>
          <label className="block"><span className="text-xs text-mute">Signals</span>
            <select className="input mt-1" value={s.grades} onChange={(e) => setS({ ...s, grades: e.target.value })}>
              <option value="AB">Grade A and B (more trades)</option><option value="A">Grade A only (strongest)</option>
            </select></label>
          <label className="block"><span className="text-xs text-mute">Take profit at</span>
            <select className="input mt-1" value={s.take} onChange={(e) => setS({ ...s, take: e.target.value })}>
              <option value="tp1">Target 1 (quick, more wins)</option><option value="tp2">Target 2 (balanced)</option><option value="tp3">Target 3 (let it run)</option>
            </select></label>
          <label className="block"><span className="text-xs text-mute">Max open trades</span>
            <input className="input mt-1" type="number" min={1} max={50} value={s.max_open} onChange={(e) => setS({ ...s, max_open: Math.max(1, Math.min(50, Number(e.target.value) || 1)) })} /></label>
          <label className="block"><span className="text-xs text-mute">Coins</span>
            <select className="input mt-1" value={s.coins} onChange={(e) => setS({ ...s, coins: e.target.value })}>
              <option value="all">All coins</option><option value="mine">Only my own coins</option>
            </select></label>
          <label className="block"><span className="text-xs text-mute">Max trades in the same direction</span>
            <input className="input mt-1" type="number" min={1} max={50} value={s.max_same_side} onChange={(e) => setS({ ...s, max_same_side: Math.max(1, Math.min(50, Number(e.target.value) || 1)) })} /></label>
          <label className="flex items-center gap-2 self-end pb-2 text-sm" title="Grade A trades use 1.2x your margin, grade B 0.8x, up to 1.5x when the trade filter rates the setup highly"><input type="checkbox" checked={s.scale} onChange={(e) => setS({ ...s, scale: e.target.checked })} />Bigger size on stronger signals</label>
          <label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" checked={s.notify} onChange={(e) => setS({ ...s, notify: e.target.checked })} />Notify me on each auto-trade</label>
          <div className="sm:col-span-2 lg:col-span-4 flex flex-wrap items-center justify-between gap-2">
            <p className="text-[11px] text-mute">Inside the signal's entry zone the trade opens at market; otherwise a limit order waits at the ideal entry (cancelled after 6 candles if it never fills). Stop-loss and take-profit come from the signal. One entry per signal; a coin with an open trade is skipped.</p>
            <button className="btn btn-primary" disabled={!dirty || !s.timeframes.length} onClick={() => save(s, "Settings saved.")}>Save settings</button>
          </div>
        </div>
      )}
      {log.length > 0 && (
        <details className="border-t border-glass/[0.06] px-4 py-2 text-xs">
          <summary className="cursor-pointer text-mute">Auto-trade activity ({log.length})</summary>
          <ul className="mt-2 space-y-1">
            {log.slice(0, 20).map((x, i) => (
              <li key={i} className="flex flex-wrap justify-between gap-2">
                <span><span className="text-mute">{fmtTime(x.ts)}</span> · <b>{base(x.symbol)}</b> <span className={x.side === "LONG" ? "text-bull" : "text-bear"}>{x.side}</span> {String(x.timeframe).toUpperCase()}</span>
                <span className={x.action === "skipped" ? "text-mute" : "text-accent"}>{x.action === "skipped" ? `skipped: ${x.reason}` : `${x.action} at ${fmtPrice(x.price)} · $${Math.round(x.margin)} · ${x.leverage}x`}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
