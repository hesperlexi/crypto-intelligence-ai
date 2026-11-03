import { useEffect, useRef, useState } from "react";
import { CoinAvatar } from "./Polish";
import { Market, verdictOf } from "./TradeCall";
import { adjustedPlan } from "./SignalAdjust";
import { CALL_STATUS, fillLabel, livePnl } from "./SignalExtras";
import { base, fmtPctRaw, fmtPrice, isNum } from "../lib/format";

export const SIG_TFS = ["15m", "1h", "4h", "12h", "1d", "3d"] as const;

export type SortKey = "ready" | "strong" | "new" | "coin" | "tf";
export const SORTS: readonly (readonly [SortKey, string])[] = [
  ["ready", "Ready first"], ["strong", "Strongest"], ["new", "Newest"], ["coin", "Coin A–Z"], ["tf", "Timeframe"],
];
export const isSort = (s: string | null): s is SortKey => SORTS.some(([k]) => k === s);

/** "ready" when the live price is inside the call's entry zone, "wait" when outside, null for no call / no zone. */
export function entryState(r: any, market: Market, px: number | undefined): "ready" | "wait" | null {
  const vv = verdictOf(r, market);
  const z = r?.plan?.entry_zone;
  if (vv.tone === "wait" || !Array.isArray(z) || !isNum(px)) return null;
  if (market === "spot" && r.plan?.side !== "LONG") return null;
  const lo = Math.min(z[0], z[1]), hi = Math.max(z[0], z[1]);
  return px >= lo && px <= hi ? "ready" : "wait";
}

const tfIdx = (t: string) => { const i = (SIG_TFS as readonly string[]).indexOf(t); return i < 0 ? 99 : i; };
const when = (r: any) => Number(r?.call?.created_at ?? r?.bar_ts ?? 0) || 0;

/** Sort rows (each may carry `timeframe`). Trade calls always before waits except for Coin / Timeframe order. */
export function sortRows(rows: any[], sort: SortKey, market: Market, px: (s: string) => number | undefined): any[] {
  const call = (r: any) => (verdictOf(r, market).tone === "wait" ? 1 : 0);
  const g = (r: any) => (r.grade === "A" ? 0 : r.grade === "B" ? 1 : 2);
  const zone = (r: any) => (entryState(r, market, px(r.symbol)) === "ready" ? 0 : 1);
  const conf = (r: any) => -(Number(r.confidence) || 0);
  const ready = (a: any, b: any) => call(a) - call(b) || g(a) - g(b) || zone(a) - zone(b) || conf(a) - conf(b);
  const cmp: Record<SortKey, (a: any, b: any) => number> = {
    ready,
    strong: (a, b) => call(a) - call(b) || conf(a) - conf(b) || g(a) - g(b),
    new: (a, b) => call(a) - call(b) || when(b) - when(a) || ready(a, b),
    coin: (a, b) => base(a.symbol).localeCompare(base(b.symbol)) || tfIdx(a.timeframe) - tfIdx(b.timeframe),
    tf: (a, b) => tfIdx(a.timeframe) - tfIdx(b.timeframe) || ready(a, b),
  };
  return [...rows].sort(cmp[sort]);
}

/** Compact sort menu: a button that opens a short list (radio items). Keyboard: arrows, Enter, Esc. */
export function SortMenu({ value, onChange, options }: { value: SortKey; onChange: (k: SortKey) => void; options: readonly (readonly [SortKey, string])[] }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", off);
    box.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
    return () => document.removeEventListener("mousedown", off);
  }, [open]);
  const label = options.find(([k]) => k === value)?.[1] ?? options[0][1];
  const onKey = (e: React.KeyboardEvent) => {
    const items = [...(box.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]') ?? [])];
    const i = items.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "Escape") { e.preventDefault(); setOpen(false); btn.current?.focus(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length]?.focus(); }
    else if (e.key === "Tab") setOpen(false);
  };
  return (
    <div className="relative" ref={box} onKeyDown={open ? onKey : undefined}>
      <button ref={btn} type="button" className="btn btn-ghost btn-sm !gap-1 border border-glass/[0.12]" aria-haspopup="menu" aria-expanded={open}
        onClick={() => setOpen((o) => !o)}>
        <span className="text-mute">Sort:</span> <span className="font-semibold">{label}</span> <span aria-hidden="true" className="text-mute">▾</span>
      </button>
      {open && (
        <div role="menu" aria-label="Sort" className="absolute right-0 z-30 mt-1 w-44 overflow-hidden rounded-lg border border-glass/[0.14] bg-raised py-1 shadow-xl">
          {options.map(([k, l]) => (
            <button key={k} type="button" role="menuitemradio" aria-checked={k === value}
              className={`flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-glass/[0.06] focus:bg-glass/[0.08] focus:outline-none ${k === value ? "font-semibold text-accent" : "text-text"}`}
              onClick={() => { onChange(k); setOpen(false); btn.current?.focus(); }}>
              {l}{k === value && <span aria-hidden="true">✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const TXT = { bull: "text-bull", bear: "text-bear", wait: "text-mute" } as const;
const TONE_TXT = { bull: "text-bull", bear: "text-bear", warn: "text-warn", accent: "text-accent", mute: "text-mute" } as const;

/** Every coin × timeframe in one compact list. Rows open the coin on its timeframe. */
export function AllList({ rows, market, px, onOpen }: { rows: any[]; market: Market; px: (s: string) => number | undefined; onOpen: (r: any) => void }) {
  return (
    <section className="panel overflow-hidden p-0" aria-label="All timeframes">
      <div className="all-row all-head label border-b border-glass/[0.06]" aria-hidden="true">
        <span>Coin</span><span>Call</span><span>Entry now</span><span className="text-right">Conf.</span>
        <span className="text-right">Entry</span><span className="text-right">Stop</span><span className="text-right">TP1</span><span className="text-right">Status</span>
      </div>
      <ul className="divide-y divide-glass/[0.06]">
        {rows.map((r) => {
          const vv = verdictOf(r, market);
          const p = adjustedPlan(r.plan, r.call);
          const show = vv.tone !== "wait" && p && (market === "futures" || p.side === "LONG");
          const price = px(r.symbol) ?? r.price;
          const es = entryState(r, market, price);
          const c = r.call;
          const st = c ? (c.exit_reason === "admin_close" && c.status === "EXPIRED" ? ["Closed", "mute"] as const : CALL_STATUS[c.status]) : null;
          const fill = c ? fillLabel(c.fill_status) : null;
          const pnl = c?.status === "OPEN" && c.fill_status !== "PENDING" && c.fill_status !== "NOT_FILLED" ? livePnl(c.side, c.entry, price) : null;
          const lev = isNum(c?.leverage) && c.leverage > 1 ? c.leverage : null;
          const conf = isNum(r.confidence) ? `${Math.round(r.confidence * 100)}%` : "—";
          const ready = es === "ready" ? <span className="font-semibold text-bull">Ready</span> : es === "wait" ? <span className="text-warn">Wait for entry</span> : <span className="text-mute">{vv.tone === "wait" ? (r.stale === true ? "Data delayed" : "No setup") : "—"}</span>;
          const status = (
            <>
              {fill ? <span className={TONE_TXT[fill[1]]}>{fill[0]}</span> : st ? <span className={`font-semibold ${TONE_TXT[st[1]]}`}>{st[0]}</span> : null}
              {pnl != null && <span className={`num font-semibold ${pnl >= 0 ? "text-bull" : "text-bear"}`} title={lev ? `Live ROI on margin at ${lev}x · price ${fmtPctRaw(pnl, 2)}` : "Live price move"}> {fmtPctRaw(lev ? pnl * lev : pnl, 1)}{lev ? " ROI" : ""}</span>}
              {c && c.status !== "OPEN" && isNum(c.return_pct) && <span className={`num ${c.return_pct >= 0 ? "text-bull" : "text-bear"}`}> {fmtPctRaw(c.return_pct, 1)}</span>}
            </>
          );
          const hasStatus = !!(fill || st || pnl != null);
          return (
            <li key={`${r.symbol}|${r.timeframe}`}>
              <button type="button" className="all-row" onClick={() => onOpen(r)}
                aria-label={`${base(r.symbol)} ${String(r.timeframe).toUpperCase()}: ${vv.label}${r.grade && vv.tone !== "wait" ? `, grade ${r.grade}` : ""}${es ? (es === "ready" ? ", ready" : ", wait for entry") : ""}`}
                style={{ ["--side" as any]: vv.tone === "bull" ? "rgb(var(--bull))" : vv.tone === "bear" ? "rgb(var(--bear))" : "rgb(var(--glass) / 0.15)" }}>
                <div className="flex min-w-0 items-center gap-2">
                  <CoinAvatar symbol={r.symbol} size={22} />
                  <span className="truncate font-semibold">{base(r.symbol)}</span>
                  <span className="tf-chip num">{String(r.timeframe).toUpperCase()}</span>
                  {vv.tone !== "wait" && (r.grade === "A" || r.grade === "B") && <span className={`grade-mini ${r.grade === "A" ? "is-a" : ""}`}>{r.grade}</span>}
                </div>
                <span className={`all-call text-xs font-extrabold tracking-wide ${TXT[vv.tone]}`}>{vv.tone === "bull" ? "▲ " : vv.tone === "bear" ? "▼ " : ""}{vv.label}</span>
                {/* phone: ready · conf · status, then the levels */}
                <div className="col-span-full flex min-w-0 flex-wrap items-center gap-x-1.5 text-xs lg:hidden">
                  {ready}<span className="text-mute/50" aria-hidden="true">·</span><span className="num text-mute">{conf}</span>
                  {hasStatus && <><span className="text-mute/50" aria-hidden="true">·</span>{status}</>}
                </div>
                {show && <div className="num col-span-full min-w-0 truncate text-xs text-mute lg:hidden">entry {fmtPrice(p.entry)} · stop {fmtPrice(p.stop)} · TP1 {fmtPrice(p.targets?.[0]?.price)}</div>}
                {/* desktop columns */}
                <span className="hidden text-xs lg:block">{ready}</span>
                <span className="num hidden text-right text-xs text-mute lg:block">{conf}</span>
                <span className="num hidden text-right text-sm text-accent lg:block">{show ? fmtPrice(p.entry) : "—"}</span>
                <span className="num hidden text-right text-sm text-bear lg:block">{show ? fmtPrice(p.stop) : "—"}</span>
                <span className="num hidden text-right text-sm text-bull lg:block">{show ? fmtPrice(p.targets?.[0]?.price) : "—"}</span>
                <span className="hidden truncate text-right text-xs lg:block">{hasStatus ? status : <span className="text-mute">—</span>}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
