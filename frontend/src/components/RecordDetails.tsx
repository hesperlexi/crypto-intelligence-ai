// Track record: live running status of open calls and the details sheet of one record row.
// Row fields (views.track_record): symbol, timeframe, side, grade, entry, stop, tp1-3, status, fill_status, leverage,
// tp1_hit/tp2_hit/tp3_hit/stop_hit, filled_at, horizon_bars, expires_at, peak_pct, exit_reason, adjustments, proof, ai.
// The live figures use the same formula as the signal card (price move vs the entry, side-aware, x the card's leverage);
// they are labelled "Live" and are never stored - the result in the record is only written when the call closes.
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { base, fmtPctRaw, fmtPrice, fmtTime, isNum, slug } from "../lib/format";
import { useTicker, useTickerThrottled } from "../lib/live";
import { CoinAvatar } from "./Polish";
import { AiNote, fillLabel, LevChip, livePnl, managedLabel, Pill, RoiFigure } from "./SignalExtras";
import { AdjustHistory, UpdatedBadge } from "./SignalAdjust";
import { useFocusTrap } from "./Shell";
import { closeEstimate } from "./SignalAdjust";
import { AdjustButton } from "./SignalAdjust";

const TF_MS: Record<string, number> = { "15m": 9e5, "1h": 36e5, "4h": 144e5, "12h": 432e5, "1d": 864e5, "3d": 2592e5, "1w": 6048e5 };
export const STATUS_LABEL: Record<string, [string, string]> = {
  TP3: ["Target 3", "text-bull"], TP2: ["Target 2", "text-bull"], TP1: ["Target 1", "text-bull"],
  STOPPED: ["Stopped", "text-bear"], EXPIRED: ["Expired", "text-mute"], OPEN: ["Open", "text-accent"],
  NOT_FILLED: ["Entry missed", "text-mute"], VOID: ["Void (no data)", "text-mute"],
};
export const statusOf = (x: any): [string, string] =>
  x.exit_reason === "admin_close" && x.status === "EXPIRED" ? ["Closed", "text-mute"] : STATUS_LABEL[x.status] ?? [x.status, ""];

const EXIT: Record<string, string> = {
  stop: "Stop-loss hit", break_even: "Stopped at break-even after target 1", trail: "Stopped at the trailed stop (target 1 after target 2)",
  tp3: "All targets hit", expired: "Time limit reached: closed at the market price", admin_stop: "Stop-loss moved by the admin was hit",
  admin_close: "Closed by the admin at the market price", giveback: "Give-back exit", time: "Time stop",
};

export const isOpen = (x: any) => x.status === "OPEN";
export const isPending = (x: any) => x.status === "OPEN" && x.fill_status === "PENDING";

/** Stop now in force: the published stop or the admin's latest one, tightened by the rules (break-even after TP1,
 *  TP1 after TP2) - an admin change never loosens a rule stop (engine/manage.py). */
export function stopNow(x: any): { price: number; why: string | null } {
  const adj = (x.adjustments ?? []).filter((a: any) => a.field === "stop");
  let price: number = adj.length ? adj[adj.length - 1].new : x.stop;
  let why: string | null = adj.length ? "moved by the admin" : null;
  const s = x.side === "SHORT" ? -1 : 1;
  const tighter = (lvl: unknown, w: string) => { if (isNum(lvl) && s * (lvl - price) > 0) { price = lvl; why = w; } };
  if (x.tp1_hit) tighter(x.entry, "break-even after target 1");
  if (x.tp2_hit) tighter(x.tp1, "target 1 after target 2");
  if (x.tp3_hit && x.runner?.on) tighter(x.tp2, "target 2 after target 3");
  return { price, why };
}

/** "Let it run" call (AI runner): nothing closes at the targets, the stop steps up, one exit at 1:rr (engine/manage.py). */
export const isRunner = (x: any): boolean => !!x?.runner?.on;
export const runnerLabel = (x: any): string => `Let it run · 1:${Number(x?.runner?.rr ?? 4)}`;

/** Short name of where the stop now sits after targets (rules only), for the row line. */
function stopAt(x: any): string | null {
  if (!x.tp1_hit) return null;
  if (x.tp3_hit && isRunner(x)) return "TP2";
  return x.tp2_hit ? "TP1" : "break-even";
}

/** A record row as the admin Adjust / Close dialogs expect a call: the levels now in force (latest admin values). */
function adminCall(x: any) {
  const last = (f: string) => { const a = (x.adjustments ?? []).filter((y: any) => y.field === f); return a.length ? a[a.length - 1].new : null; };
  return { ...x, stop: last("stop") ?? x.stop, tp1: last("tp1") ?? x.tp1 };
}

const tp1Now = (x: any): number => {
  const adj = (x.adjustments ?? []).filter((a: any) => a.field === "tp1");
  return adj.length ? adj[adj.length - 1].new : x.tp1;
};

/** Live status numbers of an open, filled call at price `px`. */
export function liveOf(x: any, px: number | undefined) {
  // after target 1 / 2 the closed parts are banked at their targets: the live result blends them with the rest at `px`
  // (50/25/25 as the record; runner calls close as one piece)
  const move = (x.tp1_hit || x.tp2_hit) && !x.runner?.on ? closeEstimate(x, px) : livePnl(x.side, x.entry, px);
  const lev = isNum(x.leverage) && x.leverage >= 1 ? x.leverage : null;
  const st = stopNow(x);
  const s = x.side === "SHORT" ? -1 : 1;
  const dist = (lvl: unknown) => (isNum(px) && px && isNum(lvl) ? (s * (lvl - px) / px) * 100 : null);   // + = in the trade's favour
  const nextTp = !x.tp1_hit ? ["Target 1", tp1Now(x)] as const : !x.tp2_hit ? ["Target 2", x.tp2] as const : !x.tp3_hit ? ["Target 3", x.tp3] as const
    : isRunner(x) ? [`Final target 1:${Number(x.runner.rr ?? 4)}`, x.runner.target] as const : null;
  return { move, roi: move != null && lev ? move * lev : null, lev, stop: st, toStop: dist(st.price), next: nextTp, toNext: nextTp ? dist(nextTp[1]) : null };
}

export function expiresAt(x: any): number | null {
  if (isNum(x.expires_at)) return x.expires_at;
  const step = TF_MS[x.timeframe];
  return step && isNum(x.created_at) ? x.created_at + step * (isNum(x.horizon_bars) ? x.horizon_bars : 30) : null;
}

function left(ms: number): string {
  const m = Math.max(0, Math.round(ms / 60_000));
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return h < 48 ? `${h} h ${m % 60} min` : `${Math.floor(h / 24)} d ${h % 24} h`;
}

function HitTags({ x }: { x: any }) {
  const hits = [x.tp1_hit && "TP1", x.tp2_hit && "TP2", x.tp3_hit && "TP3"].filter(Boolean) as string[];
  if (!hits.length) return null;
  return <>{hits.map((h) => <Pill key={h} tone="bull">{h} hit</Pill>)}</>;
}

/** Result-column content of an OPEN row: "Live" pill, targets hit, stop in force, distances. */
export function LiveResult({ x, compact = false }: { x: any; compact?: boolean }) {
  const px = useTickerThrottled(isOpen(x) ? x.symbol : undefined)?.last ?? undefined;
  // pending: the "Waiting for entry" pill comes from the row's fill status; here only the price now
  if (isPending(x)) return !compact && isNum(px) ? <div className="num mt-0.5 text-xs font-normal text-mute">now <span className="text-text">{fmtPrice(px)}</span> · entry {fmtPrice(x.entry)}</div> : null;
  const l = liveOf(x, px);
  return (
    <div className="font-normal">
      <div className="flex flex-wrap items-center gap-1">
        <Pill tone="accent" title="Still running. The figures follow the live price and are not a result yet">● Live</Pill>
        {isRunner(x) && <Pill tone="accent" title="The AI let this trade run: nothing closes at the targets, the stop moves up after each one, and the whole trade exits at the final target or the raised stop.">{runnerLabel(x)}</Pill>}
        <HitTags x={x} />
        {l.stop.why && x.tp1_hit ? <span className="text-xs text-mute">stop at {stopAt(x)}</span> : null}
      </div>
      {!compact && (
        <div className="num mt-0.5 text-xs text-mute">
          {isNum(px) ? <>now <span className="text-text">{fmtPrice(px)}</span></> : "waiting for the live price"}
          {isNum(l.toStop) && <> · stop {fmtPctRaw(Math.abs(l.toStop), 2, false)} away</>}
          {l.next && isNum(l.toNext) && <> · {l.next[0] === "Target 1" ? "TP1" : l.next[0] === "Target 2" ? "TP2" : l.next[0] === "Target 3" ? "TP3" : `1:${Number(x.runner?.rr ?? 4)}`} {fmtPctRaw(Math.abs(l.toNext), 2, false)} away</>}
        </div>
      )}
    </div>
  );
}

/** Closed-trade figure of the scalping board (owner request 2 Nov 2026): the trade's plain price return, no leverage. */
export function ReturnFigure({ x, size = "md", align = "right" }: { x: any; size?: "sm" | "md"; align?: "left" | "right" }) {
  if (!isNum(x.return_pct)) return <span className="num text-mute">—</span>;
  const cls = x.return_pct > 0 ? "text-bull" : x.return_pct < 0 ? "text-bear" : "text-mute";
  return (
    <span className={`inline-flex flex-col gap-0.5 ${align === "right" ? "items-end text-right" : "items-start text-left"}`}>
      <span className={`num font-extrabold leading-none tracking-tight ${size === "md" ? "text-xl" : "text-sm"} ${cls}`}>{fmtPctRaw(x.return_pct, 2)}</span>
      <span className="whitespace-nowrap text-xs leading-none text-mute">return · before fees</span>
    </span>
  );
}

/** ROI-column figure of an OPEN row: live ROI on margin (price move as small text), labelled Live. `plain`: the trade's
 * price return only (scalping board), no leverage. */
export function LiveRoi({ x, size = "sm", plain = false }: { x: any; size?: "sm" | "md"; plain?: boolean }) {
  const px = useTickerThrottled(isOpen(x) ? x.symbol : undefined)?.last ?? undefined;
  if (isPending(x)) return <span className="text-xs text-mute">waiting for entry</span>;
  const l = liveOf(x, px);
  if (plain) {
    if (l.move == null) return <span className="text-xs text-mute">Live · …</span>;
    const c = l.move > 0 ? "text-bull" : l.move < 0 ? "text-bear" : "text-mute";
    return (
      <span className="inline-flex flex-col items-end gap-0.5 text-right" title="Live return of the trade, from the current price vs the entry (no leverage). Before fees; not a result until the call closes.">
        <span className={`num font-bold leading-none ${size === "md" ? "text-lg" : "text-sm"} ${c}`}>{fmtPctRaw(l.move, 2)}</span>
        <span className="num text-xs leading-tight text-mute sm:whitespace-nowrap sm:leading-none"><span className="font-semibold text-accent">Live</span> · return</span>
      </span>
    );
  }
  const v = l.roi ?? l.move;
  if (v == null) return <span className="text-xs text-mute">Live · …</span>;
  const cls = v > 0 ? "text-bull" : v < 0 ? "text-bear" : "text-mute";
  return (
    <span className="inline-flex flex-col items-end gap-0.5 text-right" title="Live, from the current price vs the entry, on margin at the card's leverage. Before fees; not a result until the call closes.">
      <span className="flex flex-row-reverse items-center gap-1.5">
        <span className={`num font-bold leading-none ${size === "md" ? "text-lg" : "text-sm"} ${cls}`}>{fmtPctRaw(v, 2)}</span>
        {l.roi != null && l.lev && <LevChip lev={l.lev} />}
      </span>
      <span className="num text-xs leading-tight text-mute sm:whitespace-nowrap sm:leading-none"><span className="font-semibold text-accent">Live</span> · {l.roi != null ? <>ROI on margin · price {fmtPctRaw(l.move, 2)}</> : "price move"}</span>
    </span>
  );
}

/** Details sheet of one record row (portal; bottom sheet on phones, side panel from sm up). */
/** `scalp`: a row of the admin scalping log (scalp_signals): not a published signal, so no admin Adjust / Close
 *  (those act on the public record) and its own wording. */
export function RecordSheet({ x, onClose, scalp = false }: { x: any; onClose: () => void; scalp?: boolean }) {
  const ref = useFocusTrap(true, onClose);
  const open = isOpen(x), pending = isPending(x);
  const px = useTicker(open ? x.symbol : undefined)?.last ?? undefined;
  const [, tick] = useState(0);
  useEffect(() => { const t = window.setInterval(() => tick((n) => n + 1), 30_000); return () => window.clearInterval(t); }, []);
  const l = liveOf(x, px);
  const [lab, cls] = statusOf(x);
  const end = expiresAt(x);
  const tf = String(x.timeframe ?? "").toUpperCase();
  const fill = fillLabel(x.fill_status);
  const managed = x.managed === 1 ? managedLabel(x.exit_reason) : null;
  const closedStop = !open && (x.stop_hit || x.status === "STOPPED");
  const level = (k: string, price: unknown, hit: boolean, tone: string, note?: string | null) => (
    <div key={k} className="flex items-start justify-between gap-4 py-2">
      <dt className="shrink-0 text-mute">{k}</dt>
      <dd className="num min-w-0 text-right font-medium"><span className={tone}>{fmtPrice(price)}</span>
        {hit && <span className="ml-1.5 align-middle"><Pill tone={k === "Stop-loss" ? "bear" : "bull"}>hit</Pill></span>}
        {note && <span className="block text-xs font-normal text-mute">{note}</span>}</dd>
    </div>
  );
  const paperQ = new URLSearchParams({ market: "futures", symbol: x.symbol, side: x.side,
    ...(isNum(x.leverage) ? { lev: String(x.leverage) } : {}), ...(isNum(l.stop.price) ? { sl: String(l.stop.price) } : {}),
    ...(isRunner(x) && isNum(x.runner.target) ? { tp: String(x.runner.target) }
      : isNum(x.tp2) && !x.tp2_hit ? { tp: String(x.tp2) } : isNum(x.tp3) ? { tp: String(x.tp3) } : {}) });
  const run = isRunner(x);
  const title = `${base(x.symbol)} ${x.side} · ${tf}`;
  return createPortal(
    <div className="fixed inset-0 z-[60]" onClick={onClose}>
      <div className="absolute inset-0 bg-ink/60 backdrop-blur-sm" />
      <div ref={ref} role="dialog" aria-modal="true" aria-label={`${title}: signal details`} onClick={(e) => e.stopPropagation()}
        className="absolute inset-x-0 bottom-0 max-h-[88dvh] sm:inset-x-auto sm:bottom-0 sm:right-0 sm:top-0 sm:max-h-none sm:w-[440px]">
        <div className="panel animate-in flex h-full max-h-[88dvh] flex-col rounded-b-none p-0 sm:max-h-none sm:rounded-none sm:rounded-l-2xl">
          <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-glass/20 sm:hidden" aria-hidden="true" />
          <div className="flex items-center justify-between gap-2 border-b border-glass/[0.06] px-4 py-3">
            <div className="flex min-w-0 items-center gap-2.5">
              <CoinAvatar symbol={x.symbol} size={30} />
              <div className="min-w-0">
                <h2 className="flex items-center gap-1.5 truncate font-display text-base font-bold">
                  {base(x.symbol)} <span className={x.side === "LONG" ? "text-bull" : "text-bear"}>{x.side}</span> <span className="text-sm font-medium text-mute">{tf}</span>
                  {x.grade && <span className={`inline-flex h-5 min-w-5 items-center justify-center rounded-md border px-1.5 text-xs font-bold ${x.grade === "A" ? "border-accent/50 bg-accent/15 text-accent" : "border-warn/45 bg-warn/10 text-warn"}`}>{x.grade}</span>}
                </h2>
                <p className="text-xs text-mute">{scalp ? (x.rebuilt ? "Rebuilt" : "Logged") : "Published"} {fmtTime(x.created_at)} · {scalp ? (x.rebuilt ? "15m scalping demo call, rebuilt by replay (not public)" : "15m scalping demo call (not public)") : "futures signal"}</p>
              </div>
            </div>
            <button className="btn h-9 w-9 shrink-0 p-0" aria-label="Close details" onClick={onClose}>✕</button>
          </div>
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3 pb-[calc(1rem+env(safe-area-inset-bottom))]">
            {/* headline: live status or the final result */}
            {open ? (
              <div className="rounded-xl border border-accent/30 bg-accent/[0.06] px-3 py-2.5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="label">{pending ? "Waiting for entry" : "Live · still running"}</div>
                    <div className="num mt-1 text-xs text-mute">{isNum(px) ? <>Price now <span className="font-semibold text-text">{fmtPrice(px)}</span></> : "Waiting for the live price…"}</div>
                    <div className="mt-1 flex flex-wrap gap-1">{run && <Pill tone="accent">{runnerLabel(x)}</Pill>}<HitTags x={x} /></div>
                  </div>
                  {!pending && <LiveRoi x={x} size="md" plain={scalp} />}
                </div>
                <p className="mt-2 text-xs text-mute">{pending
                  ? "Pullback entry: counts only once price reaches the entry."
                  : "Live price; not a result until it closes. Before fees."}</p>
              </div>
            ) : (
              <div className={`flex items-center justify-between gap-3 rounded-xl border px-3 py-2.5 ${isNum(x.return_pct) ? (x.return_pct > 0 ? "border-bull/35 bg-bull/[0.07]" : "border-bear/35 bg-bear/[0.07]") : "border-glass/[0.1]"}`}>
                <div className="min-w-0">
                  <div className="label">Final result</div>
                  <div className={`mt-1 text-sm font-semibold ${cls}`}>{lab}</div>
                  {x.exit_reason && <div className="text-xs text-mute">{EXIT[x.exit_reason] ?? x.exit_reason}</div>}
                  {x.closed_at && <div className="num text-xs text-mute">Closed {fmtTime(x.closed_at)}</div>}
                </div>
                {isNum(x.return_pct) ? (scalp ? <ReturnFigure x={x} /> : <RoiFigure x={x} size="md" />) : <span className="text-xs text-mute">no result (not counted)</span>}
              </div>
            )}
            <div className="flex flex-wrap items-center gap-1.5">
              <UpdatedBadge adj={x.adjustments} />
              {fill && <Pill tone={fill[1]}>{fill[0]}</Pill>}
              {managed && <Pill tone="accent">{managed}</Pill>}
              {isNum(x.peak_pct) && <span className="num text-xs text-mute">Best open profit: price {fmtPctRaw(x.peak_pct, 2)}{isNum(x.leverage) && !scalp ? ` · ${fmtPctRaw(x.peak_pct * x.leverage, 1)} on margin` : ""}</span>}
            </div>

            <dl className="divide-y divide-glass/[0.06] text-sm">
              {level("Entry", x.entry, false, "", x.filled_at ? `entered ${fmtTime(x.filled_at)}` : pending ? "not entered yet" : null)}
              {level("Stop-loss", x.stop, !!closedStop && x.exit_reason !== "break_even" && x.exit_reason !== "trail", "text-bear",
                open ? (l.stop.why ? `now ${fmtPrice(l.stop.price)} (${l.stop.why})` : null)
                  : x.exit_reason === "break_even" ? "the rest closed at break-even (entry)"
                  : x.exit_reason === "trail" ? (run && x.tp3_hit ? "closed at target 2 (raised stop after target 3)" : run ? "closed at target 1 (raised stop after target 2)" : "the rest closed at target 1 (trailed stop)")
                  : x.exit_reason === "admin_stop" ? `the admin's stop ${fmtPrice(l.stop.price)} was hit` : null)}
              {level("Target 1", tp1Now(x), !!x.tp1_hit, "text-bull", run ? "nothing closes, stop to break-even" : "closes 50%, stop to break-even")}
              {level("Target 2", x.tp2, !!x.tp2_hit, "text-bull", run ? "nothing closes, stop to target 1" : "closes 25%, stop to target 1")}
              {level("Target 3", x.tp3, !!x.tp3_hit, "text-bull", run ? "nothing closes, stop to target 2" : "closes the last 25%")}
              {run && level(`Final target 1:${Number(x.runner.rr ?? 4)}`, x.runner.target, !open && x.exit_reason === "tp3", "text-bull", "Let it run (AI): the whole trade closes here")}
              {open && !pending && (isNum(l.toStop) || isNum(l.toNext)) && (
                <div className="flex items-start justify-between gap-4 py-2"><dt className="text-mute">Distance</dt>
                  <dd className="num text-right text-xs">{isNum(l.toStop) && <span className="block">to stop {fmtPctRaw(Math.abs(l.toStop), 2, false)}</span>}{l.next && isNum(l.toNext) && <span className="block">to {l.next[0].toLowerCase()} {fmtPctRaw(Math.abs(l.toNext), 2, false)}</span>}</dd></div>
              )}
              {isNum(x.leverage) && <div className="flex items-start justify-between gap-4 py-2"><dt className="text-mute">{scalp ? "Card's leverage (info)" : "Suggested leverage"}</dt><dd className="num font-medium">{x.leverage}x{scalp && <span className="block text-xs font-normal text-mute">returns here are not multiplied by it</span>}</dd></div>}
              <div className="flex items-start justify-between gap-4 py-2">
                <dt className="text-mute">Time limit</dt>
                <dd className="num text-right font-medium">{isNum(x.horizon_bars) ? x.horizon_bars : 30} candles of {tf}
                  {end && open && <span className="block text-xs font-normal text-mute">{end > Date.now() ? `ends ${fmtTime(end)} · ${left(end - Date.now())} left` : "time is up; closes at the next update"}</span>}
                  {!open && x.exit_reason === "expired" && <span className="block text-xs font-normal text-mute">reached: the rest closed at the market price</span>}
                </dd>
              </div>
            </dl>

            {x.adjustments?.length > 0 && <AdjustHistory adj={x.adjustments} />}
            {x.ai?.rationale && <AiNote ai={x.ai} />}

            <div className="flex flex-wrap gap-2 pt-1">
              <Link className="btn btn-primary px-3 py-1.5 text-xs" to={`/asset/${slug(x.symbol)}?tf=${encodeURIComponent(x.timeframe ?? "4h")}`}>Open chart</Link>
              {open && !pending && <Link className="btn px-3 py-1.5 text-xs" to={`/paper?${paperQ}`}>Practise this trade</Link>}
              {open && x.id && !scalp && <AdjustButton call={adminCall(x)} symbol={x.symbol} timeframe={x.timeframe} />}
            </div>
            <p className="text-xs text-mute">{scalp ? "Demo results, before fees. Wins and losses alike; not part of the public record." : "Analysis only, not financial advice. Wins and losses alike, never edited."}</p>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
