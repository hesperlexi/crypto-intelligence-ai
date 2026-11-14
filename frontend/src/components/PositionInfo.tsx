// v2.22 (owner, 14 Nov 2026): the same position facts as the Binance futures app for every running trade - demo bots,
// Hesper Challenge, the public signals (for an example margin) and members' practice trades.
// Everything is computed in the browser from data the page already has plus the live price: no engine writes.
import { useState } from "react";
import { fmtNum, fmtPctRaw, fmtPrice, isNum } from "../lib/format";

export interface TpLevel { label: string; price: number; hit?: boolean; note?: string }

export interface PositionFacts {
  side: number;                  // +1 long, -1 short
  entry: number;
  mark?: number | null;
  lev: number;
  qty: number;                   // coins at the open
  qtyOpen: number;               // coins still open
  realized?: number | null;      // USDT, closed parts (+ fees / funding where known)
  liq?: number | null;
  stop?: number | null;
  stopNote?: string | null;
  tps?: TpLevel[];
}

/** Binance's numbers for the open part: unrealized PNL (USDT), ROI on the open margin, margin, size. */
export function positionNumbers(p: PositionFacts) {
  const lev = Math.max(1, p.lev || 1);
  const margin = (p.qtyOpen * p.entry) / lev;
  const pnl = isNum(p.mark) ? p.side * p.qtyOpen * ((p.mark as number) - p.entry) : null;
  return { margin, pnl, roi: pnl != null && margin > 0 ? (pnl / margin) * 100 : null, size: isNum(p.mark) ? p.qtyOpen * (p.mark as number) : p.qtyOpen * p.entry };
}

const tone = (v: number | null | undefined) => (!isNum(v) || v === 0 ? "" : v > 0 ? "text-bull" : "text-bear");
const usd = (v: number | null | undefined, d = 2) => (isNum(v) ? `${v < 0 ? "-" : ""}${fmtNum(Math.abs(v), d)}` : "—");

function Cell({ k, v, cls = "" }: { k: string; v: React.ReactNode; cls?: string }) {
  return (
    <div className="min-w-0">
      <dt className="truncate text-xs text-mute">{k}</dt>
      <dd className={`num truncate text-sm font-medium ${cls}`}>{v}</dd>
    </div>
  );
}

/** Binance-style block. `allTps`: show every target (detail sheets); otherwise the next target + "more". */
export function PositionGrid({ p, allTps = false, note }: { p: PositionFacts; allTps?: boolean; note?: string }) {
  const [open, setOpen] = useState(allTps);
  const n = positionNumbers(p);
  const tps = p.tps ?? [];
  const next = tps.find((t) => !t.hit) ?? null;
  return (
    <div className="space-y-2">
      <dl className="grid grid-cols-3 gap-x-3 gap-y-2 sm:grid-cols-3">
        <Cell k="PNL (USDT)" v={usd(n.pnl)} cls={tone(n.pnl)} />
        <Cell k="ROI" v={isNum(n.roi) ? fmtPctRaw(n.roi, 2) : "—"} cls={tone(n.roi)} />
        <Cell k="Realized PNL" v={usd(p.realized)} cls={tone(p.realized)} />
        <Cell k="Size (USDT)" v={usd(n.size)} />
        <Cell k="Margin (USDT)" v={usd(n.margin)} />
        <Cell k="Leverage" v={`${fmtNum(p.lev, p.lev % 1 ? 1 : 0)}x`} />
        <Cell k="Entry price" v={fmtPrice(p.entry)} />
        <Cell k="Mark price" v={isNum(p.mark) ? fmtPrice(p.mark) : "—"} />
        <Cell k="Liq. price" v={isNum(p.liq) && (p.liq as number) > 0 ? fmtPrice(p.liq) : "—"} cls="text-warn" />
      </dl>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-glass/[0.06] pt-2 text-xs">
        <span className="text-mute">TP/SL</span>
        {!open && next && <span className="num"><span className="text-mute">{next.label}</span> <span className="text-bull">{fmtPrice(next.price)}</span></span>}
        {!open && !next && tps.length > 0 && <span className="text-bull">all targets hit</span>}
        <span className="num"><span className="text-mute">SL</span> <span className="text-bear">{isNum(p.stop) ? fmtPrice(p.stop) : "—"}</span>{p.stopNote && <span className="text-mute"> ({p.stopNote})</span>}</span>
        {tps.length > 1 && !allTps && (
          <button type="button" className="tap-h text-accent hover:underline" onClick={() => setOpen((v) => !v)}>{open ? "Hide targets" : `All ${tps.length} targets`}</button>
        )}
      </div>
      {open && tps.length > 0 && (
        <ul className="grid gap-1 text-xs sm:grid-cols-2">
          {tps.map((t) => (
            <li key={t.label} className="flex items-baseline justify-between gap-2 rounded-md bg-glass/[0.03] px-2 py-1">
              <span className="text-mute">{t.label}{t.note && <span className="ml-1 opacity-80">· {t.note}</span>}</span>
              <span className="num"><span className="text-bull">{fmtPrice(t.price)}</span>{t.hit && <span className="ml-1.5 rounded-full bg-bull/15 px-1.5 text-bull">hit</span>}</span>
            </li>
          ))}
        </ul>
      )}
      {note && <p className="text-xs text-mute">{note}</p>}
    </div>
  );
}

const SPLIT = [0.5, 0.25, 0.25];

/** A bot / Hesper position (engine state as published) -> facts. targets = [tp1, tp2, tp3]; tp_hit = count. */
export function botFacts(pos: any, mark: number | null | undefined): PositionFacts {
  const tg: number[] = (pos.targets ?? []).filter(isNum);
  const hit = Number(pos.tp_hit ?? 0);
  const run = pos.info?.run_target ?? pos.run_target;
  const tps: TpLevel[] = tg.map((price, i) => ({ label: `TP${i + 1}`, price, hit: i < hit, note: run ? "stop moves up" : `${SPLIT[i] * 100}%` }));
  if (isNum(run)) tps.push({ label: "Final (let it run)", price: run, hit: false, note: "whole position" });
  return { side: pos.side, entry: pos.entry, mark, lev: pos.lev ?? pos.leverage ?? 1, qty: pos.qty, qtyOpen: pos.qty_open ?? pos.qty,
           realized: pos.realized ?? null, liq: pos.liq ?? null, stop: pos.stop ?? null, tps };
}
