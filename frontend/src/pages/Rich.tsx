// Hesper Challenge: an all-in demo bot on the public grade-A calls. A run keeps going until the admin stops it or it is
// liquidated / too small to trade; 10x the start is a milestone. v2.23: after a stop the admin starts the next run
// with a chosen amount.
// Data: views/hesper (backend services/hesper.py). Virtual money only.
import { PnlGradients } from "../components/PnlGradients";
import { PageHeader, Segmented } from "../components/kit";
import { AscentJourney, SingularityJourney } from "../components/Journeys";
import { useEffect, useMemo, useRef, useState } from "react";
import { botFacts, PositionGrid } from "../components/PositionInfo";
import { createPortal } from "react-dom";
import { Link, useSearchParams } from "react-router-dom";
import { CoinAvatar } from "../components/Polish";
import { useFocusTrap } from "../components/Shell";
import { ErrorBox } from "../components/ui";
import { queueJob, setHesperVisibility, useApi, useHesperVisibility } from "../lib/api";
import { download } from "../lib/cardCanvas";
import { base, fmtDate, fmtPrice, isNum, slug } from "../lib/format";
import { drawHesperCard, drawLastStandCard, drawRunCard, drawTradeCard, lasted, liqDistance, progressOf, usd } from "../lib/hesperCard";
import { postToTelegram } from "../lib/telegramShare";
import { useTickerThrottled } from "../lib/live";
import { useIsAdmin } from "../lib/session";

const pct = (v: unknown, d = 1) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "—");
const cents = (v: unknown) => usd(v, isNum(v) && Math.abs(v) < 1000 ? 2 : 0);
const money = (v: unknown) => usd(v, isNum(v) && Math.abs(v) < 10 ? 2 : 0);
const signedUsd = (v: unknown) => (isNum(v) ? `${v > 0 ? "+" : v < 0 ? "−" : ""}${usd(Math.abs(v))}` : "—");
const tone = (v: unknown) => (isNum(v) ? (v > 0 ? "text-bull" : v < 0 ? "text-bear" : "") : "text-mute");
const sideTxt = (s: number) => (s > 0 ? "LONG" : "SHORT");
const dur = (ms: unknown) => {
  if (!isNum(ms)) return "—";
  const h = ms / 3_600_000;
  return h < 1 ? `${Math.max(1, Math.round(ms / 60_000))} min` : h < 48 ? `${h.toFixed(h < 10 ? 1 : 0)} h` : `${(h / 24).toFixed(1)} d`;
};
const REASON: Record<string, string> = { goal: "Goal reached", liquidated: "Liquidated", busted: "Busted", stopped: "Stopped by admin" };

/** Live balance and open P/L of the current trade (ticker at most once a second). */
function useLiveRun(cur: any) {
  const o = cur?.open;
  const t = useTickerThrottled(o?.symbol, 1000);
  const px = isNum(t?.last) ? t!.last : null;
  if (!cur) return { px: null, balance: null as number | null, pnl: null as number | null, roi: null as number | null };
  if (!o || px == null) return { px, balance: isNum(cur.balance) ? cur.balance : cur.cash, pnl: null, roi: null };
  const upnl = o.side * o.qty_open * (px - o.entry);
  const value = Math.max(0, o.qty_open * o.coll + upnl);
  const pnl = (o.realized ?? 0) + upnl;
  return { px, balance: cur.cash + value, pnl, roi: o.margin ? (pnl / o.margin) * 100 : null };
}

function Tile({ k, v, sub, cls = "" }: { k: string; v: string; sub?: string; cls?: string }) {
  return (
    <div className="min-w-0 px-4 py-3">
      <div className="text-xs text-mute">{k}</div>
      <div className={`num mt-1 text-lg font-semibold leading-tight tracking-tight sm:text-xl ${cls}`}>{v}</div>
      {sub && <div className="mt-0.5 truncate text-xs text-mute">{sub}</div>}
    </div>
  );
}

function Progress({ bal, start, goal }: { bal: number | null; start: number; goal: number }) {
  const p = progressOf(bal, start, goal);
  return (
    <div>
      <div className="h-3 overflow-hidden rounded-full bg-glass/[0.08]" role="progressbar" aria-label="Progress to the milestone"
        aria-valuemin={start} aria-valuemax={goal} aria-valuenow={isNum(bal) ? Math.round(bal) : start}>
        <div className="h-full rounded-full bg-gradient-to-r from-accent/70 to-accent shadow-[0_0_14px_rgb(var(--accent)/0.6)] transition-[width] duration-700"
          style={{ width: `${Math.max(p > 0 ? 2 : 0, p * 100)}%` }} />
      </div>
      <div className="num mt-1.5 flex justify-between text-xs text-mute">
        <span>{usd(start, 0)}</span><span className="font-semibold text-text">{Math.round(p * 100)}%</span><span>{usd(goal, 0)}</span>
      </div>
    </div>
  );
}

function Level({ k, v, cls = "" }: { k: string; v: string; cls?: string }) {
  return <div className="min-w-0"><div className="label">{k}</div><div className={`num mt-0.5 truncate text-sm font-semibold ${cls}`}>{v}</div></div>;
}

function OpenTrade({ o, live }: { o: any; live: ReturnType<typeof useLiveRun> }) {
  const targets: number[] = o.targets ?? [];
  return (
    <div className="rounded-xl border border-accent/25 bg-accent/[0.04] p-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <CoinAvatar symbol={o.symbol} size={22} />
        <Link to={`/asset/${slug(o.symbol)}?tf=${o.timeframe}`} className="font-semibold hover:text-accent">{base(o.symbol)}</Link>
        <span className="rounded border border-glass/15 px-1.5 text-xs text-mute">{o.timeframe}</span>
        <span className={`rounded px-1.5 text-xs font-bold ${o.side > 0 ? "bg-bull/15 text-bull" : "bg-bear/15 text-bear"}`}>{sideTxt(o.side)} {Math.round(o.leverage)}x</span>
        <span className="ml-auto text-right">
          <span className={`num text-lg font-semibold ${tone(live.pnl)}`}>{signedUsd(live.pnl)}</span>
          <span className={`num ml-2 text-sm ${tone(live.roi)}`}>{pct(live.roi)}</span>
        </span>
      </div>
      <div className="mt-3"><PositionGrid p={botFacts(o, live.px)} allTps note={`Opened ${fmtDate(o.opened_at)}`} /></div>
    </div>
  );
}

function RunCard({ v, live }: { v: any; live: ReturnType<typeof useLiveRun> }) {
  const cur = v.current;
  const start = v.start ?? 100, goal = v.goal ?? 1000;
  const st = v.score?.streak;
  return (
    <section className="panel panel-hero p-4 sm:p-6" aria-label="Current run">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="font-display text-sm font-semibold text-accent">Run #{cur.run}</div>
        <div className="text-xs text-mute">started {fmtDate(cur.started_at)} · {cur.trades} trades{st?.n ? ` · streak ${st.n}${st.kind === "win" ? "W" : "L"}` : ""}</div>
      </div>
      <div className="mt-2 flex flex-wrap items-end gap-x-6 gap-y-1">
        <div className={`num text-4xl font-bold tracking-tight sm:text-5xl ${isNum(live.balance) && live.balance < start ? "text-bear" : "text-accent"} drop-shadow-[0_0_18px_rgb(var(--accent)/0.35)]`}>{usd(live.balance)}</div>
        <div className="num pb-1 text-sm text-mute">peak <span className="font-semibold text-text">{usd(isNum(live.balance) && isNum(cur.peak) ? Math.max(cur.peak, live.balance) : cur.peak)}</span></div>
      </div>
      <div className="mx-auto mt-3 max-w-4xl"><AscentJourney start={start} goal={goal} balance={live.balance} reached={!!cur.goal_reached_at} /></div>
      <div className="mt-2"><Progress bal={live.balance} start={start} goal={goal} /></div>
      {cur.goal_reached_at && (
        <div className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-bull/40 bg-bull/10 px-2.5 py-0.5 text-xs font-semibold text-bull">
          ✓ {usd(goal, 0)} reached {fmtDate(cur.goal_reached_at)}{isNum(live.balance) ? ` · ${(live.balance / start).toFixed(1)}x` : ""}
        </div>
      )}
      <div className="mt-4">
        {cur.open ? <OpenTrade o={cur.open} live={live} />
          : cur.pending ? (
            <div className="rounded-xl border border-glass/10 p-3.5 text-sm">
              <span className="font-semibold">{base(cur.pending.symbol)}</span> <span className="text-mute">{cur.pending.timeframe} · {sideTxt(cur.pending.side)} {Math.round(cur.pending.leverage)}x</span>
              <span className="text-mute"> · waiting for entry at </span><span className="num font-semibold">{fmtPrice(cur.pending.limit)}</span>
            </div>
          ) : <div className="rounded-xl border border-dashed border-glass/15 p-3.5 text-sm text-mute">Waiting for a fresh grade-A call.</div>}
      </div>
    </section>
  );
}

/** Balance curve of one run (realised balance after each trade), log scale from $1 to above $1,000, with the $100
 *  start and $1,000 goal lines (a log scale shows a $100 -> $30 drop and a $300 -> $900 climb at their true weight). */
function BalanceCurve({ pts, start, goal, liveBal, floor = 1 }: { pts: number[][]; start: number; goal?: number; liveBal?: number | null; floor?: number }) {
  const ys = [...pts.map((p) => p[1]), ...(isNum(liveBal) ? [liveBal] : [])];
  if (ys.length < 2) return <p className="py-10 text-center text-sm text-mute">No trades in this run yet.</p>;
  const L = (q: number) => Math.log10(Math.max(floor, q));
  const w = 600, h = 180, top = Math.max(goal ? L(goal) + 0.12 : L(start) + 0.3, ...ys.map((q) => L(q) + (goal ? 0 : 0.08))), bot = Math.min(L(start) - (goal ? 0.6 : 0.2), ...ys.map(L)) - 0.05;
  const x = (i: number) => (i / (ys.length - 1)) * w, y = (q: number) => h - ((L(q) - bot) / (top - bot)) * h;
  const d = ys.map((q, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(q).toFixed(1)}`).join("");
  const mark = (q: number, cls: string, label: string) => (
    <span className={`num pointer-events-none absolute right-1 text-xs ${cls}`} style={{ top: `calc(${(y(q) / h) * 100}% - 14px)` }}>{label}</span>
  );
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${w} ${h}`} className="h-44 w-full sm:h-52" preserveAspectRatio="none" role="img" aria-label="Balance curve of the run">
        <defs><PnlGradients id="rich" y0={y(start)} top={0} bottom={h} /></defs>
        {goal ? <line x1="0" x2={w} y1={y(goal)} y2={y(goal)} stroke="rgb(var(--accent))" strokeOpacity="0.5" strokeDasharray="5 5" vectorEffect="non-scaling-stroke" /> : null}
        <line x1="0" x2={w} y1={y(start)} y2={y(start)} stroke="currentColor" className="text-glass/25" strokeDasharray="3 5" vectorEffect="non-scaling-stroke" />
        <path d={`${d}L${w},${y(start).toFixed(1)}L0,${y(start).toFixed(1)}Z`} fill="url(#rich-f)" />
        <path d={d} fill="none" stroke="url(#rich-s)" strokeWidth="2.8" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      </svg>
      {goal ? mark(goal, "text-accent", usd(goal, 0)) : null}
      {mark(start, "text-mute", usd(start, start < 100 ? 2 : 0))}
    </div>
  );
}

function ResultTag({ r }: { r: any }) {
  const cls = r.result === "SUCCESS" ? "bg-bull/15 text-bull" : r.result === "FAIL" ? "bg-bear/15 text-bear"
    : r.result === "STOPPED" ? "bg-glass/[0.08] text-text" : "bg-accent/15 text-accent";
  const txt = r.result === "SUCCESS" ? "Success" : r.result === "FAIL" ? (REASON[r.reason] ?? "Fail")
    : r.result === "STOPPED" ? `Stopped · ${isNum(r.end_balance) && isNum(r.start_balance) && r.start_balance ? `${(r.end_balance / r.start_balance).toFixed(1)}x` : ""}` : "Running";
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <span className={`whitespace-nowrap rounded px-1.5 py-0.5 text-xs font-semibold ${cls}`}>{txt}</span>
      {r.goal_reached_at && r.result !== "SUCCESS" && <span className="whitespace-nowrap rounded bg-bull/15 px-1.5 py-0.5 text-xs font-semibold text-bull" title="Reached 10x its start">10x ✓</span>}
    </span>
  );
}

const esc = (t: string) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const coinName = (s: unknown) => (String(s ?? "").startsWith("PAXG") ? "GOLD" : base(String(s ?? "")));
const NOTE = "All-in demo on our public grade-A calls. Virtual money, no real orders. Not financial advice.";

/** Share image: a 1080 x 1080 picture drawn in the browser. Download it, or (v2.63) post it to the Telegram channel. */
function ShareSheet({ label, file, kind, caption, draw, onClose }: {
  label: string; file: string; kind: string; caption: string; draw: (cv: HTMLCanvasElement) => Promise<void>; onClose: () => void;
}) {
  const [busy, setBusy] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const cv = useRef<HTMLCanvasElement>(null);
  const ref = useFocusTrap(true, onClose);
  useEffect(() => { let on = true; (async () => { await new Promise((r) => setTimeout(r, 0)); if (cv.current) await draw(cv.current); if (on) setBusy(false); })(); return () => { on = false; }; }, [draw]);
  const post = async () => {
    if (!cv.current) return;
    setBusy(true); setMsg("Posting on the next engine run (within 5 min)…");
    try { await postToTelegram(cv.current, caption, kind); setMsg("Posted to the Telegram channel."); setSent(true); }
    catch (e: any) { setMsg(`Not posted: ${e?.message ?? e}`); }
    setBusy(false);
  };
  return createPortal(
    <div className="fixed inset-0 z-[70] flex items-end justify-center bg-black/70 p-0 backdrop-blur-sm sm:items-center sm:p-4" onClick={onClose}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={label} onClick={(e) => e.stopPropagation()}
        className="panel popover animate-in max-h-[100dvh] w-full max-w-lg overflow-y-auto rounded-b-none p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] sm:rounded-2xl">
        <canvas ref={cv} data-hesper-card className="aspect-square w-full rounded-xl border border-glass/10" aria-label={label} />
        <p className="mt-2 text-xs text-mute" role="status">{msg ?? "Nothing is posted until you press Post to Telegram."}</p>
        <div className="mt-3 flex flex-wrap justify-end gap-2">
          <button type="button" className="btn btn-sm" onClick={onClose}>Close</button>
          <button type="button" className="btn btn-sm" disabled={busy} onClick={() => cv.current && download(cv.current, file)}>Download PNG</button>
          <button type="button" className="btn btn-sm btn-primary" disabled={busy || sent} onClick={() => void post()}>{sent ? "Posted" : "Post to Telegram"}</button>
        </div>
      </div>
    </div>, document.body);
}

type ShareReq = { label: string; file: string; kind: string; caption: string; draw: (cv: HTMLCanvasElement) => Promise<void> };

/** A closed trade -> share request. */
function tradeShare(title: string, t: any): ShareReq {
  const side = t.side > 0 ? "LONG" : "SHORT";
  const cap = `<b>${esc(title)} · run #${t.run}</b>\n${esc(coinName(t.symbol))} ${side} ${Math.round(t.leverage)}x closed ${esc(signedUsd(t.pnl))} (${esc(pct(t.roi_pct, 0))} on margin, ${esc(String(t.exit_reason ?? ""))}).\nBalance ${esc(usd(t.balance_before))} → ${esc(usd(t.balance_after))}.\n<i>${NOTE}</i>`;
  return { label: `${title} trade image`, file: `${title.toLowerCase().replace(/\s+/g, "-")}-run-${t.run}-${coinName(t.symbol).toLowerCase()}.png`, kind: "challenge_trade",
    caption: cap, draw: (cv) => drawTradeCard(cv, title, t) };
}

/** A run (finished or running) -> share request. */
function runShare(title: string, r: any, curve: number[][], liveBal?: number | null): ShareReq {
  const start = r.start_balance ?? 100;
  const end = r.result === "RUNNING" ? liveBal : r.end_balance;
  const how = r.result === "RUNNING" ? "still running" : (REASON[r.reason] ?? r.result ?? "").toLowerCase();
  const cap = `<b>${esc(title)} · run #${r.run}</b> (${esc(how)})\nStart ${esc(money(start))} · peak ${esc(money(r.peak))}${isNum(end) ? ` · ${r.result === "RUNNING" ? "now" : "end"} ${esc(money(end))}` : ""}\n${r.trades} trades, ${r.wins ?? 0} wins, lasted ${esc(lasted((r.ended_at ?? Date.now()) - r.started_at))}.\n<i>${NOTE}</i>`;
  return { label: `${title} run image`, file: `${title.toLowerCase().replace(/\s+/g, "-")}-run-${r.run}.png`, kind: "challenge_run", caption: cap,
    draw: (cv) => drawRunCard(cv, title, { ...r, end_balance: end }, curve) };
}

function ShareBtn({ req, small = false }: { req: () => ShareReq; small?: boolean }) {
  const [open, setOpen] = useState<ShareReq | null>(null);
  return (
    <>
      <button type="button" className={small ? "tap-h rounded px-1.5 text-xs text-accent hover:underline" : "btn btn-sm"} onClick={() => setOpen(req())}
        aria-label={small ? "Share" : undefined}>Share</button>
      {open && <ShareSheet {...open} onClose={() => setOpen(null)} />}
    </>
  );
}

function Share({ v, balance }: { v: any; balance: number | null }) {
  return <ShareBtn req={() => {
    const cur = v.current ?? {};
    const start = cur.start_balance ?? v.start ?? 100;
    const cap = `<b>Hesper Challenge · run #${cur.run}</b>\nBalance ${esc(usd(balance ?? cur.balance))} from ${esc(usd(start, 0))} after ${cur.trades ?? 0} trades.\n<i>${NOTE}</i>`;
    return { label: "Hesper Challenge share image", file: `hesper-challenge-run-${cur.run ?? 0}.png`, kind: "challenge_hesper", caption: cap,
      draw: (cv) => drawHesperCard(cv, v, balance) };
  }} />;
}

/** Admin switch: the challenge for the admin only, or view-only for active members too (never public). Asks first. */
/** Admin: stop the current run now (open trade closed at the engine's price); the record is kept. Asks first. */
function StopRun({ run, onDone, job = "hesper_new_run", label = "Stop run" }: { run: number; onDone: () => void; job?: string; label?: string }) {
  const [ask, setAsk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const ref = useFocusTrap(ask, () => setAsk(false));
  const go = async () => {
    setAsk(false); setBusy(true); setMsg("Stopping…");
    try {
      const j = await queueJob(job, { run });
      const r: any = await j.done;
      setMsg(r?.stopped_run ? `Run #${r.stopped_run} stopped at ${usd(r.final_balance)} (${Number(r.multiple).toFixed(1)}x).` : "Stopped.");
      onDone();
    } catch (e: any) { setMsg(`Not stopped: ${e?.message ?? e}`); }
    setBusy(false);
  };
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" className="btn btn-sm" disabled={busy} onClick={() => setAsk(true)}>{label}</button>
      {msg && <span className="text-xs text-mute" role="status">{msg}</span>}
      {ask && createPortal(
        <div className="fixed inset-0 z-[70] flex items-end justify-center bg-black/70 p-0 backdrop-blur-sm sm:items-center sm:p-4" onClick={() => setAsk(false)}>
          <div ref={ref} role="alertdialog" aria-modal="true" aria-label="Stop this run" onClick={(e) => e.stopPropagation()}
            className="panel popover animate-in w-full max-w-md rounded-b-none p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] sm:rounded-2xl sm:pb-5">
            <h2 className="text-base font-semibold">{label} #{run}?</h2>
            <p className="mt-2 text-sm text-mute">An open trade closes at the engine's price. The run and its record are kept.</p>
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" className="btn btn-sm" onClick={() => setAsk(false)}>Cancel</button>
              <button type="button" className="btn btn-sm btn-primary" onClick={() => void go()}>{label}</button>
            </div>
          </div>
        </div>, document.body)}
    </div>
  );
}

/** Admin: start the next run with a chosen amount (USDT, virtual). */
function StartRun({ onDone, last, job = "hesper_start_run", min = 10, label = "Start new run" }: { onDone: () => void; last?: number; job?: string; min?: number; label?: string }) {
  const [amount, setAmount] = useState(String(last ?? 100));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const n = Number(amount);
  const ok = isNum(n) && n >= min && n <= 1_000_000;
  const go = async () => {
    setBusy(true); setMsg("Starting…");
    try {
      const j = await queueJob(job, { amount: n });
      const r: any = await j.done;
      setMsg(r?.run ? `Run #${r.run} started with ${money(r.start_balance)}.` : "Started.");
      onDone();
    } catch (e: any) { setMsg(`Not started: ${e?.message ?? e}`); }
    setBusy(false);
  };
  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="text-sm text-mute">Starting amount (USDT)
        <input className="input mt-1 block w-36" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} aria-label="Starting amount in USDT" />
      </label>
      <button type="button" className="btn btn-primary" disabled={busy || !ok} onClick={() => void go()}>{label}</button>
      {msg && <span className="text-xs text-mute" role="status">{msg}</span>}
    </div>
  );
}

function Visibility() {
  const vis = useHesperVisibility();
  const [ask, setAsk] = useState<"admin" | "members" | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const ref = useFocusTrap(!!ask, () => setAsk(null));
  const save = async (to: "admin" | "members") => {
    setMsg(null);
    try { await setHesperVisibility(to); setMsg(to === "members" ? "Members can see it now." : "Only you can see it now."); }
    catch (e: any) { setMsg(`Not saved: ${e?.message ?? e}`); }
  };
  return (
    <div className="flex flex-wrap items-center gap-2" data-hesper-visibility={vis}>
      <span className="text-xs text-mute">Who can see it</span>
      <span className="inline-flex rounded-xl border border-glass/10 p-1" role="radiogroup" aria-label="Who can see the Hesper challenge">
        {(["admin", "members"] as const).map((k) => (
          <button key={k} type="button" role="radio" aria-checked={vis === k} onClick={() => vis !== k && setAsk(k)}
            className={`tap-h rounded-lg px-3 py-1 text-sm ${vis === k ? "bg-accent font-semibold text-ink" : "text-mute hover:text-text"}`}>{k === "admin" ? "Admin only" : "Members too"}</button>
        ))}
      </span>
      {msg && <span className="text-xs text-mute" role="status">{msg}</span>}
      {ask && createPortal(
        <div className="fixed inset-0 z-[70] flex items-end justify-center bg-black/70 p-0 backdrop-blur-sm sm:items-center sm:p-4" onClick={() => setAsk(null)}>
          <div ref={ref} role="alertdialog" aria-modal="true" aria-label="Who can see it" onClick={(e) => e.stopPropagation()}
            className="panel popover animate-in w-full max-w-md rounded-b-none p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] sm:rounded-2xl sm:pb-5">
            <h2 className="text-base font-semibold">{ask === "members" ? "Show the Hesper challenge to members?" : "Hide it from members?"}</h2>
            <p className="mt-2 text-sm text-mute">{ask === "members"
              ? "Active members see it view-only on Results as “Hesper Challenge”. No share button, no admin controls."
              : "Only you will see it. Members lose access at once."}</p>
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" className="btn btn-sm" onClick={() => setAsk(null)}>Cancel</button>
              <button type="button" className="btn btn-sm btn-primary" onClick={() => { const to = ask; setAsk(null); void save(to); }}>{ask === "members" ? "Show to members" : "Admin only"}</button>
            </div>
          </div>
        </div>, document.body)}
    </div>
  );
}

/** Closed trades of a run, newest first (25, then "Show all"). Admin: a Share link per trade. */
function TradesSection({ trades, sc, share }: { trades: any[]; sc: any; share?: (t: any) => ShareReq }) {
  const [all, setAll] = useState(false);
  return (
  <section className="panel p-0" aria-label="Trades">
    <div className="flex items-center justify-between px-4 pt-4">
      <h2 className="label">Trades</h2>
      <span className="text-xs text-mute">{sc.trades ?? trades.length} total · {sc.wins ?? 0} wins</span>
    </div>
    <ul className="mt-2 sm:hidden">
      {(all ? trades : trades.slice(0, 25)).map((t) => (
        <li key={t.id} className="border-t border-glass/[0.06] px-4 py-2.5">
          <div className="flex items-center gap-2 text-sm">
            <span className="font-medium">{base(t.symbol)}</span><span className="text-xs text-mute">{t.timeframe}</span>
            <span className={`text-xs font-semibold ${t.side > 0 ? "text-bull" : "text-bear"}`}>{sideTxt(t.side)} {Math.round(t.leverage)}x</span>
            <span className={`num ml-auto font-semibold ${tone(t.pnl)}`}>{signedUsd(t.pnl)}</span>
          </div>
          <div className="num mt-0.5 flex items-center gap-2 text-xs text-mute">
            <span>#{t.run}</span><span className="truncate">{t.exit_reason}</span>
            <span className={`ml-auto ${tone(t.roi_pct)}`}>{pct(t.roi_pct, 0)}</span><span>→ {usd(t.balance_after)}</span>
            {share && <ShareBtn small req={() => share(t)} />}
          </div>
        </li>
      ))}
      {!trades.length && <li className="px-4 py-6 text-center text-sm text-mute">No closed trades yet.</li>}
    </ul>
    <div className="mt-2 hidden overflow-x-auto sm:block">
      <table className="w-full min-w-[640px] text-sm">
        <thead><tr className="text-left text-xs text-mute">
          <th className="px-4 py-2 font-semibold">Run</th><th className="px-2 py-2 font-semibold">Coin</th><th className="px-2 py-2 font-semibold">Side</th>
          <th className="px-2 py-2 text-right font-semibold">Entry → exit</th><th className="px-2 py-2 text-right font-semibold">P/L</th>
          <th className="px-2 py-2 text-right font-semibold">ROI</th><th className="px-2 py-2 font-semibold">Exit</th>
          <th className="px-4 py-2 text-right font-semibold">Balance</th>{share && <th className="py-2 pr-3"><span className="sr-only">Share</span></th>}
        </tr></thead>
        <tbody>
          {(all ? trades : trades.slice(0, 25)).map((t) => (
            <tr key={t.id} className="border-t border-glass/[0.06]">
              <td className="num px-4 py-2 text-mute">#{t.run}</td>
              <td className="px-2 py-2"><span className="font-medium">{base(t.symbol)}</span> <span className="text-xs text-mute">{t.timeframe}</span></td>
              <td className={`num px-2 py-2 text-xs font-semibold ${t.side > 0 ? "text-bull" : "text-bear"}`}>{sideTxt(t.side)} {Math.round(t.leverage)}x</td>
              <td className="num px-2 py-2 text-right text-xs">{fmtPrice(t.entry)} → {fmtPrice(t.exit)}</td>
              <td className={`num px-2 py-2 text-right font-semibold ${tone(t.pnl)}`}>{signedUsd(t.pnl)}</td>
              <td className={`num px-2 py-2 text-right ${tone(t.roi_pct)}`}>{pct(t.roi_pct, 0)}</td>
              <td className="px-2 py-2 text-xs text-mute">{t.exit_reason}</td>
              <td className="num px-4 py-2 text-right">{usd(t.balance_after)}</td>{share && <td className="py-2 pr-3 text-right"><ShareBtn small req={() => share(t)} /></td>}
            </tr>
          ))}
          {!trades.length && <tr><td colSpan={share ? 9 : 8} className="px-4 py-6 text-center text-mute">No closed trades yet.</td></tr>}
        </tbody>
      </table>
    </div>
    {trades.length > 25 && (
      <div className="border-t border-glass/[0.06] px-4 py-2 text-center">
        <button type="button" className="tap-h px-2 text-sm text-accent hover:underline" onClick={() => setAll((x) => !x)}>{all ? "Show fewer" : `Show all ${trades.length}`}</button>
      </div>
    )}
  </section>
  );
}

// ---- v2.63 Last Stand: a second all-in run inside the Hesper Challenge, any start, admin close, until liquidation ----

/** Admin: close the Last Stand trade now at the engine's price, all of it or half. Only this run's trade: the call, the
 *  main run and everyone else's trades are untouched. Asks first. */
function CloseTrade({ open, pending, onDone }: { open: any; pending: any; onDone: () => void }) {
  const [ask, setAsk] = useState<0.5 | 1 | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const ref = useFocusTrap(ask != null, () => setAsk(null));
  const go = async (f: 0.5 | 1) => {
    setAsk(null); setBusy(true); setMsg("Closing on the next engine run (within 5 min)…");
    try {
      const j = await queueJob("laststand_close", { fraction: f });
      const r: any = await j.done;
      setMsg(r?.cancelled_order ? "Entry order cancelled." : r?.closed === "half" ? `Half closed, ${signedUsd(r.pnl)}. The rest stays open.`
        : r?.closed ? `Closed, ${signedUsd(r.pnl)}. Balance ${usd(r.balance)}.` : "Done.");
      onDone();
    } catch (e: any) { setMsg(`Not closed: ${e?.message ?? e}`); }
    setBusy(false);
  };
  const what = open ? `${coinName(open.symbol)} ${sideTxt(open.side)}` : pending ? `${coinName(pending.symbol)} entry order` : "";
  return (
    <div className="flex flex-wrap items-center gap-2">
      {open && <button type="button" className="btn btn-sm" disabled={busy} onClick={() => setAsk(0.5)}>Close 50%</button>}
      <button type="button" className="btn btn-sm btn-danger" disabled={busy} onClick={() => setAsk(1)}>{open ? "Close all" : "Cancel order"}</button>
      {msg && <span className="text-xs text-mute" role="status">{msg}</span>}
      {ask != null && createPortal(
        <div className="fixed inset-0 z-[70] flex items-end justify-center bg-black/70 p-0 backdrop-blur-sm sm:items-center sm:p-4" onClick={() => setAsk(null)}>
          <div ref={ref} role="alertdialog" aria-modal="true" aria-label="Close the Last Stand trade" onClick={(e) => e.stopPropagation()}
            className="panel popover animate-in w-full max-w-md rounded-b-none p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] sm:rounded-2xl sm:pb-5">
            <h2 className="text-base font-semibold">{!open ? `Cancel the ${what}?` : ask === 1 ? `Close all of ${what}?` : `Close half of ${what}?`}</h2>
            <p className="mt-2 text-sm text-mute">{!open ? "The money goes back to the balance and the run waits for the next call."
              : ask === 1 ? "The trade closes at the engine's price. The run goes on with the next grade-A call."
              : "Half of what is still open closes at the engine's price. The rest keeps its stop and targets."} Only this Last Stand trade changes.</p>
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" className="btn btn-sm" onClick={() => setAsk(null)}>Keep it</button>
              <button type="button" className="btn btn-sm btn-primary" onClick={() => void go(ask)}>{!open ? "Cancel order" : ask === 1 ? "Close all" : "Close 50%"}</button>
            </div>
          </div>
        </div>, document.body)}
    </div>
  );
}

/** How far the price is from the liquidation price: the number a run lives or dies by. */
function LiqMeter({ o, px }: { o: any; px: number | null }) {
  const d = liqDistance(o, px);
  if (d == null) return null;
  const p = Math.max(0, Math.min(1, d / 10));
  const cls = d < 2 ? "bg-bear" : d < 5 ? "bg-accent" : "bg-bull";
  return (
    <div className="ls-liq" aria-label={`Liquidation ${d.toFixed(1)}% away`}>
      <div className="flex items-baseline justify-between gap-3 text-xs">
        <span className="text-mute">Distance to liquidation</span>
        <span className={`num text-sm font-semibold ${d < 2 ? "text-bear" : "text-text"}`}>{d.toFixed(1)}%</span>
      </div>
      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-glass/[0.08]" role="meter" aria-valuemin={0} aria-valuemax={10} aria-valuenow={Math.round(d * 10) / 10}>
        <div className={`h-full rounded-full ${cls} transition-[width] duration-700`} style={{ width: `${Math.max(2, p * 100)}%` }} />
      </div>
      <div className="num mt-1 flex justify-between text-xs text-mute"><span>liquidation {fmtPrice(o.liq)}</span><span>price {fmtPrice(px)}</span></div>
    </div>
  );
}

function LastStandPanel({ v, owner, reload }: { v: any; owner: boolean; reload: () => void }) {
  const cur = v.current;
  const live = useLiveRun(cur);
  const runs: any[] = v.runs ?? [];
  const trades: any[] = v.trades ?? [];
  const sc = v.score ?? {};
  const [pick, setPick] = useState<number | null>(null);
  const shown = pick ?? cur?.run ?? runs[0]?.run;
  const curve = useMemo(() => (v.curves ?? {})[String(shown)] ?? [], [v, shown]);
  const start = cur?.start_balance ?? v.start ?? 10;
  const mult = isNum(live.balance) && start ? live.balance / start : null;
  const last = runs.find((r) => r.result !== "RUNNING");
  const longest = runs.reduce<any>((a, r) => { const ms = (r.ended_at ?? Date.now()) - r.started_at; return !a || ms > a.ms ? { run: r.run, ms } : a; }, null);
  const bestMult = runs.reduce<any>((a, r) => { const m = r.start_balance ? r.peak / r.start_balance : 0; return !a || m > a.m ? { run: r.run, m } : a; }, null);
  const bestTrade = trades.reduce<any>((a, t) => (!a || t.pnl > a.pnl ? t : a), null);
  const lsShare = (): ShareReq => ({
    label: "Last Stand share image", file: `last-stand-run-${cur?.run ?? 0}.png`, kind: "challenge_laststand",
    caption: `<b>Last Stand · run #${cur?.run}</b>\nAll-in from ${esc(cents(start))}, until liquidation. Now ${esc(cents(live.balance))}${mult != null ? ` (${mult.toFixed(2)}x)` : ""} after ${cur?.trades ?? 0} trades, alive ${esc(lasted(Date.now() - (cur?.started_at ?? Date.now())))}.\n<i>${NOTE}</i>`,
    draw: (cv) => drawLastStandCard(cv, v, live.balance, live.px),
  });
  return (
    <div className="space-y-4">
      {!cur && (
        <section className="panel panel-hero p-4 sm:p-6" aria-label="Last Stand">
          <div className="font-display text-lg font-semibold">Last Stand</div>
          <p className="mt-1 max-w-2xl text-sm text-mute">One account, all-in on every fresh grade-A call, one trade at a time. It starts from any amount and keeps going until it is liquidated.</p>
          {last && (
            <p className="num mt-3 text-sm">
              Run #{last.run} <span className={last.result === "FAIL" ? "text-bear" : "text-text"}>{(REASON[last.reason] ?? last.result).toLowerCase()}</span> at {cents(last.end_balance)} after {last.trades} trades
              · peak {cents(last.peak)} · lasted {dur((last.ended_at ?? 0) - last.started_at)}
            </p>
          )}
          {owner ? <div className="mt-4"><StartRun onDone={reload} last={v.start ?? 10} job="laststand_start" min={v.min_start ?? 5} label={last ? "Start next run" : "Start Last Stand"} /></div>
            : <p className="mt-3 text-sm text-mute">{last ? "The next run starts soon." : "Not started yet."}</p>}
        </section>
      )}
      {cur && (
        <section className="panel panel-hero ls-hero p-4 sm:p-6" aria-label="Current Last Stand run">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div className="font-display text-sm font-semibold text-accent">Last Stand · run #{cur.run}</div>
            <div className="text-xs text-mute">started {fmtDate(cur.started_at)} · {cur.trades} trades · alive {lasted(Date.now() - cur.started_at)}</div>
          </div>
          <div className="mt-2 flex flex-wrap items-end gap-x-6 gap-y-1">
            <div className={`num text-4xl font-bold tracking-tight sm:text-5xl ${isNum(live.balance) && live.balance < start ? "text-bear" : "text-accent"}`}>{cents(live.balance)}</div>
            <div className="num pb-1 text-sm text-mute">
              <span className={`font-semibold ${mult != null && mult < 1 ? "text-bear" : "text-text"}`}>{mult != null ? `${mult.toFixed(mult < 10 ? 2 : 1)}x` : "—"}</span> the {cents(start)} start
              · peak <span className="font-semibold text-text">{cents(isNum(live.balance) && isNum(cur.peak) ? Math.max(cur.peak, live.balance) : cur.peak)}</span>
            </div>
          </div>
          <div className="mx-auto mt-3 max-w-4xl"><SingularityJourney start={start} goal={start * 10} balance={live.balance} /></div>
          {cur.open && <div className="mt-4 max-w-xl"><LiqMeter o={cur.open} px={live.px} /></div>}
          <div className="mt-4">
            {cur.open ? <OpenTrade o={cur.open} live={live} />
              : cur.pending ? (
                <div className="rounded-xl border border-glass/10 p-3.5 text-sm">
                  <span className="font-semibold">{coinName(cur.pending.symbol)}</span> <span className="text-mute">{cur.pending.timeframe} · {sideTxt(cur.pending.side)} {Math.round(cur.pending.leverage)}x</span>
                  <span className="text-mute"> · waiting for entry at </span><span className="num font-semibold">{fmtPrice(cur.pending.limit)}</span>
                </div>
              ) : <div className="rounded-xl border border-dashed border-glass/15 p-3.5 text-sm text-mute">Flat. The whole balance goes into the next fresh grade-A call.</div>}
          </div>
          {owner && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
              {(cur.open || cur.pending) ? <CloseTrade open={cur.open} pending={cur.pending} onDone={reload} /> : <span />}
              <div className="flex flex-wrap items-center gap-2">
                <ShareBtn req={lsShare} />
                <StopRun run={cur.run} onDone={reload} job="laststand_stop" label="End run" />
              </div>
            </div>
          )}
        </section>
      )}
      {(cur || runs.length > 0) && (
        <>
          <div className="panel rich-facts grid grid-cols-2 p-0 sm:grid-cols-3 lg:grid-cols-6">
            <Tile k="Runs" v={String(sc.runs ?? 0)} sub={cur ? `now #${cur.run}` : "none running"} />
            <Tile k="Liquidated" v={String(sc.liquidations ?? 0)} cls="text-bear" sub={`${sc.busted ?? 0} busted · ${sc.stopped ?? 0} ended`} />
            <Tile k="Best peak" v={bestMult ? `${bestMult.m.toFixed(bestMult.m < 10 ? 2 : 1)}x` : "—"} cls="text-accent" sub={bestMult ? `run #${bestMult.run}` : undefined} />
            <Tile k="Longest alive" v={longest ? lasted(longest.ms) : "—"} sub={longest ? `run #${longest.run}` : undefined} />
            <Tile k="Trades" v={String(sc.trades ?? 0)} sub={`${sc.wins ?? 0} wins`} />
            <Tile k="Best trade" v={bestTrade ? signedUsd(bestTrade.pnl) : "—"} cls={tone(bestTrade?.pnl)} sub={bestTrade ? `${coinName(bestTrade.symbol)} · run #${bestTrade.run}` : undefined} />
          </div>

          <section className="panel p-4" aria-label="Balance curve">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <h2 className="label">Balance</h2>
              <select className="input h-8 !w-auto py-0 pr-8 text-sm" value={shown} onChange={(e) => setPick(Number(e.target.value))} aria-label="Run">
                {runs.filter((r) => (v.curves ?? {})[String(r.run)]).map((r) => (
                  <option key={r.run} value={r.run}>Run #{r.run}{r.run === cur?.run ? " (now)" : ` · ${(REASON[r.reason] ?? r.result).toLowerCase()}`}</option>
                ))}
              </select>
            </div>
            <BalanceCurve pts={curve} start={(runs.find((r) => r.run === shown) ?? {}).start_balance ?? start} floor={0.01}
              liveBal={shown === cur?.run ? live.balance : null} />
          </section>

          <section className="panel p-0" aria-label="Runs">
            <h2 className="label px-4 pt-4">Runs</h2>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="text-left text-xs text-mute">
                  <th className="py-2 pl-4 pr-2 font-semibold">Run</th><th className="px-2 py-2 font-semibold">Result</th>
                  <th className="px-2 py-2 text-right font-semibold">Start</th><th className="px-2 py-2 text-right font-semibold">Peak</th>
                  <th className="py-2 pl-2 pr-4 text-right font-semibold sm:pr-2">End</th>
                  <th className="hidden px-2 py-2 text-right font-semibold sm:table-cell">Trades</th>
                  <th className="hidden px-4 py-2 text-right font-semibold sm:table-cell">Lasted</th>
                  {owner && <th className="py-2 pr-3"><span className="sr-only">Share</span></th>}
                </tr></thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.run} className="border-t border-glass/[0.06]">
                      <td className="num py-2 pl-4 pr-2 font-semibold">#{r.run}</td>
                      <td className="px-2 py-2"><ResultTag r={r} /></td>
                      <td className="num px-2 py-2 text-right">{cents(r.start_balance)}</td>
                      <td className="num px-2 py-2 text-right text-accent">{cents(r.peak)}</td>
                      <td className="num py-2 pl-2 pr-4 text-right sm:pr-2">{cents(r.result === "RUNNING" ? (r.run === cur?.run ? live.balance : null) : r.end_balance)}</td>
                      <td className="num hidden px-2 py-2 text-right sm:table-cell">{r.trades}</td>
                      <td className="num hidden px-4 py-2 text-right text-mute sm:table-cell">{lasted((r.ended_at ?? Date.now()) - r.started_at)}</td>
                      {owner && <td className="py-2 pr-3 text-right"><ShareBtn small req={() => runShare("Last Stand", r, (v.curves ?? {})[String(r.run)] ?? [], r.run === cur?.run ? live.balance : null)} /></td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <TradesSection trades={trades} sc={sc} share={owner ? (t) => tradeShare("Last Stand", t) : undefined} />
        </>
      )}
    </div>
  );
}

/** Admin: "Hesper Challenge" page with the visibility switch and Share. Members (Results tab, when the admin allows it):
 *  the same figures view-only as "Hesper Challenge". */
export default function Rich({ embedded = false }: { embedded?: boolean }) {
  const admin = useIsAdmin();
  const q = useApi<any>("/hesper");
  const v = q.data;
  const live = useLiveRun(v?.current);
  const runs: any[] = v?.runs ?? [];
  const curRun = v?.current?.run;
  const [pick, setPick] = useState<number | null>(null);
  const shown = pick ?? curRun ?? runs[0]?.run;
  const curve = useMemo(() => (v?.curves ?? {})[String(shown)] ?? [], [v, shown]);
  const sc = v?.score ?? {};
  const trades: any[] = v?.trades ?? [];
  const owner = admin && !embedded;
  const [params, setParams] = useSearchParams();
  const which: "hesper" | "laststand" = params.get("c") === "laststand" ? "laststand" : "hesper";
  const pickChallenge = (k: "hesper" | "laststand") => {
    const p = new URLSearchParams(params);
    if (k === "laststand") p.set("c", k); else p.delete("c");
    setParams(p, { replace: true });
  };
  const ls = v?.laststand;
  return (
    <div className="space-y-4">
      {owner ? (
        <PageHeader title="Hesper Challenge"
          actions={<><Visibility />{which === "hesper" && v?.current && <StopRun run={v.current.run} onDone={q.reload} />}{which === "hesper" && v?.current && <Share v={v} balance={live.balance} />}</>} />
      ) : embedded ? null : (
        <h2 className="text-lg font-semibold"><span className="text-accent">Hesper Challenge</span></h2>
      )}
      {(owner || ls?.started || ls?.runs?.length) && (
        <Segmented label="Challenge" value={which} onChange={pickChallenge} strong
          options={[["hesper", "Main run"], ["laststand", "Last Stand"]] as const} />
      )}
      {q.error && !v && <ErrorBox error={q.error} retry={q.reload} />}
      {!v && !q.error && <div className="skeleton h-64 rounded-xl" />}
      {v && which === "laststand" && <LastStandPanel v={ls ?? {}} owner={owner} reload={q.reload} />}
      {v && which === "hesper" && !v.current && (
        <section className="panel panel-hero flex flex-wrap items-end justify-between gap-4 p-4 sm:p-5" aria-label="No run in progress">
          <div>
            <div className="font-display text-base font-semibold">{v.idle ? "Stopped" : "Not started"}</div>
            <div className="text-sm text-mute">{v.idle ? "No run in progress." : "Starts with the next engine cycle."}</div>
          </div>
          {admin && !embedded && v.idle && <StartRun onDone={q.reload} last={v.start} />}
        </section>
      )}
      {v && which === "hesper" && (
        <>
          {v.current && <RunCard v={v} live={live} />}
          <div className="panel rich-facts grid grid-cols-2 p-0 sm:grid-cols-3 lg:grid-cols-6">
            <Tile k="Reached 10x" v={String(sc.milestones ?? sc.successes ?? 0)} cls="text-bull" />
            <Tile k="Failures" v={String(sc.failures ?? 0)} cls="text-bear" sub={`${sc.liquidations ?? 0} liquidated · ${sc.busted ?? 0} busted`} />
            <Tile k="Runs" v={String(sc.runs ?? 0)} sub={`${curRun ? `now #${curRun}` : "none running"}${sc.stopped ? ` · ${sc.stopped} stopped` : ""}`} />
            <Tile k="Best peak" v={usd(sc.best_peak?.peak, 0)} cls="text-accent" sub={sc.best_peak ? `run #${sc.best_peak.run}` : undefined} />
            <Tile k="Avg trades / run" v={isNum(sc.avg_trades_per_run) ? sc.avg_trades_per_run.toFixed(1) : "—"} sub="finished runs" />
            <Tile k="Fastest success" v={sc.fastest_success ? dur(sc.fastest_success.ms) : "—"} sub={sc.fastest_success ? `run #${sc.fastest_success.run} · ${sc.fastest_success.trades} trades` : "none yet"} />
          </div>

          <section className="panel p-4" aria-label="Balance curve">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <h2 className="label">Balance</h2>
              <select className="input h-8 !w-auto py-0 pr-8 text-sm" value={shown} onChange={(e) => setPick(Number(e.target.value))} aria-label="Run">
                {runs.filter((r) => (v.curves ?? {})[String(r.run)]).map((r) => (
                  <option key={r.run} value={r.run}>Run #{r.run}{r.run === curRun ? " (now)" : r.result === "SUCCESS" ? " · success" : r.result === "STOPPED" ? " · stopped" : " · fail"}</option>
                ))}
              </select>
            </div>
            <BalanceCurve pts={curve} start={v.start ?? 100} goal={v.goal ?? 1000} liveBal={shown === curRun ? live.balance : null} />
          </section>

          <section className="panel p-0" aria-label="Runs">
            <h2 className="label px-4 pt-4">Runs</h2>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="text-left text-xs text-mute">
                  <th className="py-2 pl-4 pr-2 font-semibold">Run</th><th className="px-2 py-2 font-semibold">Result</th>
                  <th className="px-2 py-2 text-right font-semibold">Trades</th><th className="px-2 py-2 text-right font-semibold">Peak</th>
                  <th className="py-2 pl-2 pr-4 text-right font-semibold sm:pr-2">End</th><th className="hidden px-2 py-2 font-semibold sm:table-cell">Best trade</th>
                  <th className="hidden px-4 py-2 text-right font-semibold sm:table-cell">Time</th>
                  {owner && <th className="py-2 pr-3"><span className="sr-only">Share</span></th>}
                </tr></thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.run} className="border-t border-glass/[0.06]">
                      <td className="num py-2 pl-4 pr-2 font-semibold">#{r.run}</td>
                      <td className="px-2 py-2"><ResultTag r={r} /></td>
                      <td className="num px-2 py-2 text-right">{r.trades}</td>
                      <td className="num px-2 py-2 text-right text-accent">{usd(r.peak, 0)}</td>
                      <td className="num py-2 pl-2 pr-4 text-right sm:pr-2">{money(r.result === "RUNNING" ? (r.run === curRun ? live.balance : null) : r.end_balance)}</td>
                      <td className="hidden px-2 py-2 sm:table-cell">{r.best_trade ? <span className="num"><span className="font-medium">{base(r.best_trade.symbol)}</span> <span className={tone(r.best_trade.pnl)}>{signedUsd(r.best_trade.pnl)}</span></span> : <span className="text-mute">—</span>}</td>
                      <td className="num hidden px-4 py-2 text-right text-mute sm:table-cell">{dur((r.ended_at ?? Date.now()) - r.started_at)}</td>
                      {owner && <td className="py-2 pr-3 text-right"><ShareBtn small req={() => runShare("Hesper Challenge", r, (v.curves ?? {})[String(r.run)] ?? [], r.run === curRun ? live.balance : null)} /></td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <TradesSection trades={trades} sc={sc} share={owner ? (t) => tradeShare("Hesper Challenge", t) : undefined} />
        </>
      )}
    </div>
  );
}
