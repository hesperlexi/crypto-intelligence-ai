// v2.7 admin adjustment of an open call's stop-loss / take-profit 1 (public, forward-only; engine: services/adjust.py).
//   call.adjustments  [{at, field: "stop" | "tp1", old, new, note}] oldest first (absent when none)
//   call.stop / tp1   the levels now in force; stop0 / tp1_0 the published ones
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { queueJob } from "../lib/api";
import { base, fmtPrice, isNum, pricePrecision } from "../lib/format";
import { useLive } from "../lib/live";
import { useIsAdmin } from "../lib/session";
import { Pill } from "./SignalExtras";

export type Adjustment = { at: number; field: "stop" | "tp1"; old: number; new: number; note: string };
/** The plan with the admin's levels for the fields that were adjusted on the same-side open call (else the plan as is). */
export function adjustedPlan(plan: any, call: any): any {
  const adj: Adjustment[] | undefined = call?.adjustments;
  if (!plan || !adj?.length || call.status !== "OPEN" || plan.side !== call.side) return plan;
  const f = new Set(adj.map((a) => a.field));
  return {
    ...plan,
    ...(f.has("stop") ? { stop: call.stop } : {}),
    ...(f.has("tp1") ? { targets: (plan.targets ?? []).map((tg: any, i: number) => (i === 0 ? { ...tg, price: call.tp1 } : tg)) } : {}),
  };
}

const LABEL = { stop: "Stop-loss", tp1: "Take-profit 1" } as const;
const MAX_DIST = 0.5;

const hhmm = (ms: number) => new Date(ms).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

/** "Updated" pill for a call or record row that the admin changed. */
export function UpdatedBadge({ adj }: { adj?: Adjustment[] | null }) {
  if (!adj?.length) return null;
  const last = adj[adj.length - 1];
  return <Pill tone="warn" title={`Changed by the admin ${hhmm(last.at)}. Results use the original levels before each change and the new ones after it.`}>Updated</Pill>;
}

/** The change history: "14:32 · Stop-loss 66,900 → 67,500 · note". */
export function AdjustHistory({ adj, compact = false }: { adj?: Adjustment[] | null; compact?: boolean }) {
  if (!adj?.length) return null;
  return (
    <div className={`rounded-lg border border-warn/30 bg-warn/[0.05] ${compact ? "mt-1 px-2 py-1" : "px-2.5 py-2"}`}>
      {!compact && <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-warn">Updated by the admin · applies from the time shown</div>}
      <ul className="space-y-0.5">
        {[...adj].reverse().map((a, i) => (
          <li key={i} className="text-[11px] leading-snug text-mute">
            <span className="num">{hhmm(a.at)}</span> · <span className="font-semibold text-text">{LABEL[a.field] ?? a.field}</span>{" "}
            <span className="num">{fmtPrice(a.old)} → <span className={a.field === "stop" ? "text-bear" : "text-bull"}>{fmtPrice(a.new)}</span></span>
            {a.note ? <> · <span className="break-words">{a.note}</span></> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Same checks as the engine (services/adjust.validate); the engine re-checks at its own latest price. */
export function adjustProblem(call: any, px: number | undefined, stop: number | null, tp1: number | null, note: string): string | null {
  if (!call || call.status !== "OPEN") return "Only an open or pending signal can be changed.";
  const long = call.side !== "SHORT";
  const entry = Number(call.entry);
  const curStop = Number(call.stop), curTp1 = Number(call.tp1);
  const chStop = stop != null && Math.abs(stop - curStop) > 1e-12;
  const chTp1 = tp1 != null && Math.abs(tp1 - curTp1) > 1e-12;
  for (const [v, k] of [[stop, "stop-loss"], [tp1, "take-profit 1"]] as const) {
    if (v != null && (!isNum(v) || v <= 0)) return `The new ${k} must be a positive price.`;
    if (v != null && isNum(v) && Math.abs(v / entry - 1) > MAX_DIST) return `The new ${k} is more than 50% away from the entry (${fmtPrice(entry)}).`;
  }
  if (!chStop && !chTp1) return "Change the stop-loss or take-profit 1.";
  if (chTp1 && call.tp1_hit) return "Take-profit 1 was already hit, so it can no longer be changed.";
  if (!isNum(px)) return "Waiting for the live price…";
  const ns = chStop ? stop! : curStop, nt = chTp1 ? tp1! : curTp1;
  if (chStop && long && ns >= px) return `For a long, the stop-loss must be below the current price (${fmtPrice(px)}).`;
  if (chStop && !long && ns <= px) return `For a short, the stop-loss must be above the current price (${fmtPrice(px)}).`;
  if (chStop && call.fill_status === "PENDING" && (long ? ns >= entry : ns <= entry)) return `The entry (${fmtPrice(entry)}) has not filled yet: the stop-loss must stay ${long ? "below" : "above"} it.`;
  if (chTp1 && long && nt <= px) return `For a long, take-profit 1 must be above the current price (${fmtPrice(px)}).`;
  if (chTp1 && !long && nt >= px) return `For a short, take-profit 1 must be below the current price (${fmtPrice(px)}).`;
  if (!call.tp1_hit && (long ? nt <= entry : nt >= entry)) return `Take-profit 1 must stay on the profit side of the entry (${fmtPrice(entry)}).`;
  if (long ? nt <= ns : nt >= ns) return "The stop-loss must be on the other side of take-profit 1.";
  const n = note.trim();
  if (n.length < 3 || n.length > 200) return "Write a note of 3 to 200 characters: members see it.";
  return null;
}

/** Admin-only "Adjust" button for an open / pending call; nothing for anyone else. */
export function AdjustButton({ call, symbol, timeframe }: { call: any; symbol: string; timeframe?: string }) {
  const admin = useIsAdmin();
  const [open, setOpen] = useState(false);
  if (!admin || !call || call.status !== "OPEN" || !call.id) return null;
  return (
    <>
      <button type="button" className="btn btn-sm px-2.5 text-xs" onClick={() => setOpen(true)} title="Move the stop-loss or take-profit 1 (admin, public)">Adjust</button>
      {open && <AdjustModal call={call} symbol={symbol} timeframe={timeframe} onClose={() => setOpen(false)} />}
    </>
  );
}

const num = (s: string): number | null => { const v = parseFloat(s.replace(/,/g, "")); return s.trim() === "" ? null : Number.isFinite(v) ? v : NaN; };

export function AdjustModal({ call, symbol, timeframe, onClose }: { call: any; symbol: string; timeframe?: string; onClose: () => void }) {
  const { tickers } = useLive();
  const px: number | undefined = tickers[symbol]?.last ?? undefined;
  // prefilled at the price's display precision; an untouched field equal to the current level is no change
  const pre = (v: any) => (isNum(v) ? v.toFixed(pricePrecision(v)) : "");
  const [stop, setStop] = useState(pre(call.stop));
  const [tp1, setTp1] = useState(pre(call.tp1));
  const [note, setNote] = useState("");
  const [step, setStep] = useState<"edit" | "confirm" | "sending" | "done" | "failed">("edit");
  const [msg, setMsg] = useState("");
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && step !== "sending" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose, step]);
  const same = (txt: string, cur: any) => txt === pre(cur);
  const s = same(stop, call.stop) ? null : num(stop), t = same(tp1, call.tp1) ? null : num(tp1);
  const problem = adjustProblem(call, px, s, t, note);
  const changes = ([["stop", call.stop, s], ["tp1", call.tp1, t]] as const).filter(([, o, n]) => n != null && isNum(n) && Math.abs(n - o) > 1e-12);
  const tf = String(timeframe ?? "").toUpperCase();
  const send = async () => {
    setStep("sending");
    setMsg("Queued: the engine applies it on its next run (within about 5 minutes).");
    try {
      const params: Record<string, any> = { signal_id: call.id, note: note.trim() };
      for (const [f, , n] of changes) params[f] = n;
      const j = await queueJob("adjust_signal", params);
      const r: any = await j.done;
      setStep("done");
      setMsg(`${r?.message ?? "Saved."}${isNum(r?.push?.sent) ? ` Notification sent to ${r.push.sent} device${r.push.sent === 1 ? "" : "s"}.` : ""}`);
    } catch (e: any) {
      setStep("failed");
      setMsg(e?.message ?? "The change was refused.");
    }
  };
  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-end justify-center bg-black/75 p-0 backdrop-blur-sm sm:items-center sm:p-4" onClick={() => step !== "sending" && onClose()} role="dialog" aria-modal="true" aria-label="Adjust signal">
      <div className="panel max-h-[92vh] w-full max-w-md overflow-y-auto rounded-b-none sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between gap-2 border-b border-glass/[0.06] px-4 py-2.5">
          <h2 className="label">Adjust {base(symbol)} {tf} {call.side === "SHORT" ? "short" : "long"}</h2>
          <button className="btn btn-ghost px-3" onClick={onClose} disabled={step === "sending"} aria-label="Close">Close</button>
        </div>
        <div className="space-y-3 p-4 text-sm">
          <div className="num grid grid-cols-3 gap-2 text-xs">
            <div><div className="text-mute">Entry</div><div className="font-semibold text-accent">{fmtPrice(call.entry)}</div></div>
            <div><div className="text-mute">Price now</div><div className="font-semibold">{fmtPrice(px)}</div></div>
            <div><div className="text-mute">Status</div><div className="font-semibold">{call.fill_status === "PENDING" ? "waiting for entry" : call.tp1_hit ? "TP1 hit" : "open"}</div></div>
          </div>
          {step === "edit" && (
            <>
              <label className="block">
                <span className="text-xs text-mute">Stop-loss · now <span className="num text-bear">{fmtPrice(call.stop)}</span></span>
                <input className="input num mt-1 w-full" inputMode="decimal" value={stop} onChange={(e) => setStop(e.target.value)} />
              </label>
              <label className="block">
                <span className="text-xs text-mute">Take-profit 1 · now <span className="num text-bull">{fmtPrice(call.tp1)}</span>{call.tp1_hit ? " · already hit, locked" : ""}</span>
                <input className="input num mt-1 w-full" inputMode="decimal" value={tp1} disabled={!!call.tp1_hit} onChange={(e) => setTp1(e.target.value)} />
              </label>
              <label className="block">
                <span className="text-xs text-mute">Note for members (required, 3–200 characters)</span>
                <textarea className="input mt-1 min-h-[72px] w-full py-2" maxLength={200} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Locking in profit before the CPI release" />
                <span className="num block text-right text-[11px] text-mute">{note.trim().length}/200</span>
              </label>
              {problem && <p className="rounded-lg border border-warn/40 bg-warn/[0.08] px-2.5 py-1.5 text-xs text-warn" role="status">{problem}</p>}
              <p className="text-[11px] text-mute">Forward-only: the record keeps the original levels for everything before the change; the new level counts from the next 15-minute candle. The demo bots holding this call follow it too.</p>
              <div className="flex justify-end gap-2">
                <button className="btn" onClick={onClose}>Cancel</button>
                <button className="btn btn-primary" disabled={!!problem} onClick={() => setStep("confirm")}>Review</button>
              </div>
            </>
          )}
          {step === "confirm" && (
            <>
              <div className="rounded-lg border border-glass/10 bg-ink/40 p-3">
                <ul className="num space-y-1">
                  {changes.map(([f, o, n]) => <li key={f}><span className="font-semibold">{LABEL[f]}</span> {fmtPrice(o)} → <span className={f === "stop" ? "text-bear" : "text-bull"}>{fmtPrice(n)}</span></li>)}
                </ul>
                <p className="mt-2 break-words text-xs text-mute">Note: {note.trim()}</p>
              </div>
              <p className="text-xs text-warn">This change is public: it is shown on the signal and in the track record for good, and every member gets a notification.</p>
              <div className="flex justify-end gap-2">
                <button className="btn" onClick={() => setStep("edit")}>Back</button>
                <button className="btn btn-primary" onClick={send}>Confirm and publish</button>
              </div>
            </>
          )}
          {(step === "sending" || step === "done" || step === "failed") && (
            <>
              <p className={`rounded-lg border px-2.5 py-2 text-sm ${step === "done" ? "border-bull/40 bg-bull/[0.08] text-bull" : step === "failed" ? "border-bear/40 bg-bear/[0.08] text-bear" : "border-glass/15 text-mute"}`} role="status">
                {step === "failed" ? `Not changed: ${msg}` : msg}
              </p>
              <div className="flex justify-end gap-2">
                {step === "failed" && <button className="btn" onClick={() => setStep("edit")}>Edit again</button>}
                <button className="btn" onClick={onClose} disabled={step === "sending"}>{step === "sending" ? "Waiting…" : "Close"}</button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
