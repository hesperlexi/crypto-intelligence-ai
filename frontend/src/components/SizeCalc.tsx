// v2.75 Position-size calculator (owner, 22 Nov 2026): balance + risk % + entry / stop -> position size, margin at the
// chosen leverage, liquidation price (the practice account's formula, coin margin tier + closing fee), loss at the stop
// and profit at each target. Opened from every signal card ("Size it") and from the Trade page. Pure arithmetic in the
// browser; the inputs (balance, risk %, leverage) are remembered on this device only (localStorage `cia-calc`).
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { base, fmtPrice, isNum } from "../lib/format";
import { FEE, liqPrice } from "../lib/paperFutures";

type Saved = { balance: number; risk: number; lev: number };
const load = (): Saved => {
  try { const v = JSON.parse(localStorage.getItem("cia-calc") ?? "{}"); return { balance: v.balance > 0 ? v.balance : 1000, risk: v.risk > 0 ? v.risk : 1, lev: v.lev >= 1 ? v.lev : 10 }; }
  catch { return { balance: 1000, risk: 1, lev: 10 }; }
};

export type CalcSeed = { symbol?: string; side?: "LONG" | "SHORT"; entry?: number; stop?: number; targets?: number[]; lev?: number };

export function SizeCalcButton({ seed, className = "btn px-3", label = "Size it" }: { seed: CalcSeed; className?: string; label?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className={className} onClick={() => setOpen(true)} title="Position-size calculator: how big to trade for your risk">{label}</button>
      {open && <SizeCalc seed={seed} onClose={() => setOpen(false)} />}
    </>
  );
}

const num = (s: string) => { const v = parseFloat(s.replace(/,/g, "")); return Number.isFinite(v) ? v : NaN; };
const money = (v: number) => (isNum(v) ? `$${v.toLocaleString("en-US", { maximumFractionDigits: v >= 100 ? 0 : 2 })}` : "—");

export default function SizeCalc({ seed, onClose }: { seed: CalcSeed; onClose: () => void }) {
  const saved = useMemo(load, []);
  const [balance, setBalance] = useState(String(saved.balance));
  const [risk, setRisk] = useState(String(saved.risk));
  const [entry, setEntry] = useState(isNum(seed.entry) ? String(seed.entry) : "");
  const [stop, setStop] = useState(isNum(seed.stop) ? String(seed.stop) : "");
  const [lev, setLev] = useState(String(seed.lev ?? saved.lev));
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  const B = num(balance), R = num(risk), E = num(entry), S = num(stop), L = Math.max(1, Math.min(125, num(lev) || 1));
  useEffect(() => { try { if (B > 0 && R > 0) localStorage.setItem("cia-calc", JSON.stringify({ balance: B, risk: R, lev: L })); } catch { /* ignore */ } }, [B, R, L]);

  const ok = B > 0 && R > 0 && E > 0 && S > 0 && E !== S;
  const side = ok ? (S < E ? 1 : -1) : (seed.side === "SHORT" ? -1 : 1);
  const riskUsd = ok ? (B * R) / 100 : NaN;
  const dist = ok ? Math.abs(E - S) / E : NaN;                         // stop distance as a fraction of the entry
  const notional = ok ? riskUsd / (dist + 2 * FEE) : NaN;             // includes opening + closing fees in the loss
  const qty = ok ? notional / E : NaN;
  const margin = ok ? notional / L : NaN;
  const liq = ok ? liqPrice(E, side, L, seed.symbol) : NaN;
  const liqFirst = ok && (side > 0 ? liq >= S : liq <= S);
  const tooBig = ok && margin > B;
  const targets = (seed.targets ?? []).filter(isNum);
  const coin = seed.symbol ? base(seed.symbol) : "coins";

  return createPortal(
    <div className="fixed inset-0 z-[70]" onClick={onClose}>
      <div className="absolute inset-0 bg-ink/60 backdrop-blur-sm" />
      <div role="dialog" aria-modal="true" aria-label="Position-size calculator" onClick={(e) => e.stopPropagation()}
        className="absolute inset-x-0 bottom-0 max-h-[90dvh] sm:inset-auto sm:left-1/2 sm:top-1/2 sm:w-[480px] sm:-translate-x-1/2 sm:-translate-y-1/2">
        <div className="panel calc-panel animate-in flex max-h-[90dvh] flex-col overflow-y-auto rounded-b-none p-0 sm:rounded-2xl">
          <div className="flex items-center justify-between gap-2 border-b border-glass/[0.07] px-5 py-3.5">
            <div><h2 className="font-display text-lg font-semibold">Position size</h2>
              <p className="text-xs text-mute">{seed.symbol ? `${base(seed.symbol)} · ${side > 0 ? "long" : "short"}` : "Any trade"} · for practice and planning</p></div>
            <button type="button" className="btn btn-sm" onClick={onClose}>Close</button>
          </div>
          <div className="grid grid-cols-2 gap-3 px-5 pt-4">
            <Field label="Account balance (USDT)" v={balance} set={setBalance} />
            <Field label="Risk per trade (%)" v={risk} set={setRisk} hint="1–2% is common" />
            <Field label="Entry price" v={entry} set={setEntry} />
            <Field label="Stop-loss" v={stop} set={setStop} />
            <Field label="Leverage (x)" v={lev} set={setLev} hint="changes margin and liquidation, not the risk" />
          </div>
          <div className="px-5 py-4">
            {!ok ? <p className="text-sm text-mute">Fill in the balance, risk, entry and stop to see the size.</p> : (
              <>
                <div className="calc-hero">
                  <div><span>Position size</span><b className="num">{qty >= 1 ? qty.toLocaleString("en-US", { maximumFractionDigits: 3 }) : qty.toPrecision(4)} <small>{coin}</small></b><em className="num">{money(notional)} worth</em></div>
                  <div><span>Margin at {L}x</span><b className="num">{money(margin)}</b><em className="num">{isNum(margin) && B > 0 ? `${((margin / B) * 100).toFixed(1)}% of balance` : ""}</em></div>
                </div>
                <dl className="calc-list">
                  <div><dt>Loss if the stop is hit</dt><dd className="num text-bear">−{money(riskUsd)} <small>incl. fees</small></dd></div>
                  <div><dt>Stop distance</dt><dd className="num">{(dist * 100).toFixed(2)}%</dd></div>
                  <div><dt>Liquidation at {L}x</dt><dd className={`num ${liqFirst ? "text-bear" : ""}`}>{fmtPrice(liq)}</dd></div>
                  {targets.map((t, i) => {
                    const g = (side * (t - E)) / E * notional - notional * 2 * FEE;
                    return <div key={i}><dt>Profit at TP{i + 1} <small className="num">{fmtPrice(t)}</small></dt><dd className="num text-bull">+{money(g)} · {(g / riskUsd).toFixed(2)}R</dd></div>;
                  })}
                </dl>
                {liqFirst && <p className="calc-warn">At {L}x the position is liquidated before the stop. Lower the leverage.</p>}
                {tooBig && !liqFirst && <p className="calc-warn">The margin needed is more than the balance. Raise the leverage or the stop distance is too small for this risk.</p>}
                <p className="mt-3 text-xs text-mute">Profits assume the whole position closes at that target. Fees 0.05% each side included. Planning help only, not advice.</p>
              </>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function Field({ label, v, set, hint }: { label: string; v: string; set: (s: string) => void; hint?: string }) {
  return (
    <label className="block min-w-0">
      <span className="text-xs text-mute">{label}</span>
      <input className="input num mt-1 w-full" inputMode="decimal" value={v} onChange={(e) => set(e.target.value)} />
      {hint && <span className="mt-0.5 block text-[12px] leading-tight text-mute/80">{hint}</span>}
    </label>
  );
}
