// Filters for Results → Signal log: coin, timeframe, side, grade, status, date range and sort, kept in the URL
// (?coin=&tf=&side=&grade=&status=&range=&from=&to=&sort=) so a filtered view can be shared as a link.
// Computer: one inline bar. Phone: a "Filters" button opens the same controls in a bottom sheet.
import { useCallback, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useSearchParams } from "react-router-dom";
import { useFocusTrap } from "./Shell";

/** Status chips: the record's real status values (backend schema / tracking.py); break-even is a TP1 call closed at entry. */
export const STATUS_OPTS: [string, string][] = [
  ["OPEN", "Open"], ["TP1", "TP1"], ["TP2", "TP2"], ["TP3", "TP3 / Won"], ["STOPPED", "Stopped"], ["BE", "Break-even"],
  ["EXPIRED", "Expired"], ["NOT_FILLED", "Not filled"], ["VOID", "Void"], ["INFO", "Not traded"],
];
const TFS = ["15m", "1h", "4h", "12h", "1d", "3d"];
const RANGES: [string, string][] = [["24h", "24h"], ["7d", "7 days"], ["30d", "30 days"], ["all", "All"], ["custom", "Custom"]];
const RANGE_MS: Record<string, number> = { "24h": 86_400_000, "7d": 7 * 86_400_000, "30d": 30 * 86_400_000 };
export const SORTS: [string, string][] = [["new", "Newest first"], ["old", "Oldest first"], ["best", "Best result"], ["worst", "Worst result"]];
const KEYS = ["coin", "tf", "side", "grade", "status", "range", "from", "to", "sort"] as const;

const statusOf = (s: any): string[] => {
  const out = [String(s.status)];
  if (s.exit_reason === "break_even") out.push("BE");
  return out;
};
const dayStart = (d: string) => new Date(`${d}T00:00:00`).getTime();

export function useLogFilters() {
  const [params, setParams] = useSearchParams();
  const get = (k: string) => params.get(k) ?? "";
  const coin = get("coin"), tf = get("tf"), side = get("side"), grade = get("grade"), range = get("range") || "all", from = get("from"), to = get("to");
  const sort = get("sort") || "new";
  const statuses = useMemo(() => get("status").split(",").filter(Boolean), [params]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = useCallback((patch: Partial<Record<(typeof KEYS)[number], string>>) => {
    setParams((cur) => {
      const p = new URLSearchParams(cur);
      for (const [k, v] of Object.entries(patch)) { if (v) p.set(k, v); else p.delete(k); }
      if (p.get("range") === "all") p.delete("range");
      if (p.get("sort") === "new") p.delete("sort");
      if (p.get("range") !== "custom") { p.delete("from"); p.delete("to"); }
      return p;
    }, { replace: true });
  }, [setParams]);
  const toggleStatus = (k: string) => set({ status: (statuses.includes(k) ? statuses.filter((x) => x !== k) : [...statuses, k]).join(",") });
  const clear = useCallback(() => set(Object.fromEntries(KEYS.map((k) => [k, ""])) as any), [set]);
  const active = [coin, tf, side, grade, range !== "all" ? range : "", statuses.length ? "s" : ""].filter(Boolean).length;
  const apply = useCallback((rows: any[]) => {
    const needle = coin.trim().toUpperCase();
    const now = Date.now();
    const lo = range === "custom" ? (from ? dayStart(from) : -Infinity) : RANGE_MS[range] ? now - RANGE_MS[range] : -Infinity;
    const hi = range === "custom" && to ? dayStart(to) + 86_400_000 : Infinity;
    const out = rows.filter((s) => {
      if (needle && !String(s.symbol ?? "").toUpperCase().replace("/", "").includes(needle.replace("/", ""))) return false;
      if (tf && s.timeframe !== tf) return false;
      if (side === "long" && !(s.side > 0)) return false;
      if (side === "short" && !(s.side < 0)) return false;
      if (grade && (s.payload?.grade ?? s.grade) !== grade) return false;
      if (statuses.length && !statusOf(s).some((x) => statuses.includes(x))) return false;
      if (!(s.created_at >= lo && s.created_at < hi)) return false;
      return true;
    });
    const res = (s: any) => (typeof s.roi_pct === "number" ? s.roi_pct : typeof s.return_pct === "number" ? s.return_pct : null);
    if (sort === "old") out.sort((a, b) => a.created_at - b.created_at);
    else if (sort === "best" || sort === "worst") {
      const k = sort === "best" ? -1 : 1;
      out.sort((a, b) => { const x = res(a), y = res(b); if (x == null && y == null) return b.created_at - a.created_at; if (x == null) return 1; if (y == null) return -1; return k * (x - y); });
    } else out.sort((a, b) => b.created_at - a.created_at);
    return out;
  }, [coin, tf, side, grade, statuses, range, from, to, sort]);
  return { coin, tf, side, grade, statuses, range, from, to, sort, active, set, toggleStatus, clear, apply };
}
export type LogFilterState = ReturnType<typeof useLogFilters>;

const chip = (on: boolean) => `min-h-[32px] rounded-lg border px-2.5 text-xs transition-colors ${on ? "border-accent/60 bg-accent/15 font-semibold text-accent" : "border-glass/10 text-mute hover:border-glass/25 hover:text-text"}`;

function Seg({ label, value, opts, onChange }: { label: string; value: string; opts: [string, string][]; onChange: (v: string) => void }) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1">
      {opts.map(([k, l]) => <button key={k || "all"} type="button" aria-pressed={value === k} className={chip(value === k)} onClick={() => onChange(k)}>{l}</button>)}
    </div>
  );
}

function Controls({ f, stacked }: { f: LogFilterState; stacked: boolean }) {
  const lab = "mb-1 block text-[11px] uppercase tracking-wide text-mute";
  const box = stacked ? "space-y-4" : "grid gap-x-5 gap-y-3 md:grid-cols-[minmax(0,14rem)_auto_auto_auto] xl:grid-cols-[minmax(0,14rem)_auto_auto_auto_auto]";
  return (
    <div className={box}>
      <label className="block min-w-0"><span className={lab}>Coin</span>
        <input className="input input-sm" type="search" placeholder="Search coin, e.g. BTC" value={f.coin} onChange={(e) => f.set({ coin: e.target.value })} aria-label="Search coin" />
      </label>
      <div><span className={lab}>Timeframe</span><Seg label="Timeframe" value={f.tf} opts={[["", "All"], ...TFS.map((t) => [t, t.toUpperCase()] as [string, string])]} onChange={(v) => f.set({ tf: v })} /></div>
      <div><span className={lab}>Side</span><Seg label="Side" value={f.side} opts={[["", "All"], ["long", "Long"], ["short", "Short"]]} onChange={(v) => f.set({ side: v })} /></div>
      <div><span className={lab}>Grade</span><Seg label="Grade" value={f.grade} opts={[["", "All"], ["A", "A"], ["B", "B"]]} onChange={(v) => f.set({ grade: v })} /></div>
      <div className={stacked ? "" : "md:col-span-2 xl:col-span-1"}><span className={lab}>Sort</span>
        <select className="input input-sm w-auto" value={f.sort} onChange={(e) => f.set({ sort: e.target.value })} aria-label="Sort">{SORTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
      </div>
      <div className={stacked ? "" : "md:col-span-full"}><span className={lab}>Status</span>
        <div role="group" aria-label="Status" className="flex flex-wrap gap-1">
          <button type="button" aria-pressed={!f.statuses.length} className={chip(!f.statuses.length)} onClick={() => f.set({ status: "" })}>All</button>
          {STATUS_OPTS.map(([k, l]) => <button key={k} type="button" aria-pressed={f.statuses.includes(k)} className={chip(f.statuses.includes(k))} onClick={() => f.toggleStatus(k)}>{l}</button>)}
        </div>
      </div>
      <div className={stacked ? "" : "md:col-span-full"}><span className={lab}>Date</span>
        <div className="flex flex-wrap items-center gap-2">
          <Seg label="Date range" value={f.range} opts={RANGES} onChange={(v) => f.set({ range: v })} />
          {f.range === "custom" && (
            <span className="flex flex-wrap items-center gap-2 text-xs text-mute">
              <input type="date" className="input input-sm w-auto" value={f.from} max={f.to || undefined} onChange={(e) => f.set({ from: e.target.value })} aria-label="From date" />
              to
              <input type="date" className="input input-sm w-auto" value={f.to} min={f.from || undefined} onChange={(e) => f.set({ to: e.target.value })} aria-label="To date" />
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export function LogFilters({ f, total, shown }: { f: LogFilterState; total: number; shown: number }) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useFocusTrap(open, close);
  const clearBtn = f.active > 0 || f.sort !== "new" ? <button type="button" className="text-xs text-accent hover:underline" onClick={f.clear}>Clear all</button> : null;
  return (
    <div className="mb-3">
      {/* phone: one row with the button, the count and clear-all */}
      <div className="flex items-center gap-3 md:hidden">
        <button type="button" className="btn px-3 py-1.5 text-sm" onClick={() => setOpen(true)} aria-expanded={open} aria-controls="log-filter-sheet">
          Filters{f.active ? <span className="ml-1.5 rounded-full bg-accent px-1.5 text-[11px] font-bold text-ink">{f.active}</span> : null}
        </button>
        <span className="num text-xs text-mute" aria-live="polite">{shown} of {total} signals</span>
        <span className="ml-auto">{clearBtn}</span>
      </div>
      {/* computer: inline */}
      <div className="hidden rounded-xl border border-glass/[0.08] bg-ink/20 p-3 md:block">
        <Controls f={f} stacked={false} />
        <div className="mt-3 flex items-center justify-between border-t border-glass/[0.06] pt-2 text-xs text-mute">
          <span className="num" aria-live="polite">{shown} of {total} signals</span>{clearBtn}
        </div>
      </div>
      {open && createPortal(
        <div className="fixed inset-0 z-[60] md:hidden" onClick={close}>
          <div className="absolute inset-0 bg-ink/60 backdrop-blur-sm" />
          <div ref={ref} id="log-filter-sheet" role="dialog" aria-modal="true" aria-label="Signal log filters" onClick={(e) => e.stopPropagation()} className="absolute inset-x-0 bottom-0">
            <div className="panel animate-in flex max-h-[88dvh] flex-col rounded-b-none p-0">
              <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-glass/20" aria-hidden="true" />
              <div className="flex items-center justify-between border-b border-glass/[0.06] px-4 py-3">
                <h2 className="font-display text-base font-bold">Filters</h2>
                <button className="btn h-9 w-9 p-0" aria-label="Close filters" onClick={close}>✕</button>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3"><Controls f={f} stacked /></div>
              <div className="flex items-center gap-3 border-t border-glass/[0.06] px-4 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))]">
                <button type="button" className="btn px-3 py-2 text-sm" onClick={f.clear}>Clear all</button>
                <button type="button" className="btn btn-primary flex-1 py-2 text-sm" onClick={close}>Show {shown} of {total}</button>
              </div>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
