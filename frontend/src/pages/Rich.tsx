// Road to Rich (admin only): Hesper, an all-in demo bot on the public grade-A calls. Each run starts at $100 and keeps
// going (v2.22, owner 14 Nov 2026) until the admin ends it ("End run & start new") or it is liquidated / too small to
// trade (failure); $1,000 is a milestone, not an end. A new run starts at once.
// Data: views/hesper (backend services/hesper.py). Virtual money only.
import { PageHeader } from "../components/kit";
import { useMemo, useRef, useState } from "react";
import { botFacts, PositionGrid } from "../components/PositionInfo";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { CoinAvatar } from "../components/Polish";
import { useFocusTrap } from "../components/Shell";
import { ErrorBox } from "../components/ui";
import { queueJob, setHesperVisibility, useApi, useHesperVisibility } from "../lib/api";
import { download } from "../lib/cardCanvas";
import { base, fmtDate, fmtPrice, isNum, slug } from "../lib/format";
import { drawHesperCard, progressOf, usd } from "../lib/hesperCard";
import { useTickerThrottled } from "../lib/live";
import { useIsAdmin } from "../lib/session";

const pct = (v: unknown, d = 1) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "—");
const money = (v: unknown) => usd(v, isNum(v) && Math.abs(v) < 10 ? 2 : 0);
const signedUsd = (v: unknown) => (isNum(v) ? `${v > 0 ? "+" : v < 0 ? "−" : ""}${usd(Math.abs(v))}` : "—");
const tone = (v: unknown) => (isNum(v) ? (v > 0 ? "text-bull" : v < 0 ? "text-bear" : "") : "text-mute");
const sideTxt = (s: number) => (s > 0 ? "LONG" : "SHORT");
const dur = (ms: unknown) => {
  if (!isNum(ms)) return "—";
  const h = ms / 3_600_000;
  return h < 1 ? `${Math.max(1, Math.round(ms / 60_000))} min` : h < 48 ? `${h.toFixed(h < 10 ? 1 : 0)} h` : `${(h / 24).toFixed(1)} d`;
};
const REASON: Record<string, string> = { goal: "$1,000 reached", liquidated: "Liquidated", busted: "Busted", stopped: "Stopped by admin" };
const SUBLINE = "$100 start · runs until stopped or liquidated · $1,000 milestone";

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
      <div className="h-3 overflow-hidden rounded-full bg-glass/[0.08]" role="progressbar" aria-label="Progress to $1,000"
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
      <div className="mt-3"><PositionGrid p={botFacts(o, live.px)} note={`Opened ${fmtDate(o.opened_at)}. Realized PNL includes closed targets and fees.`} /></div>
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
      <div className="mt-4"><Progress bal={live.balance} start={start} goal={goal} /></div>
      {cur.goal_reached_at && (
        <div className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-bull/40 bg-bull/10 px-2.5 py-0.5 text-xs font-semibold text-bull">
          ✓ {usd(goal, 0)} milestone reached {fmtDate(cur.goal_reached_at)} · still running{isNum(live.balance) ? ` · ${(live.balance / start).toFixed(1)}x` : ""}
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
function BalanceCurve({ pts, start, goal, liveBal }: { pts: number[][]; start: number; goal: number; liveBal?: number | null }) {
  const ys = [...pts.map((p) => p[1]), ...(isNum(liveBal) ? [liveBal] : [])];
  if (ys.length < 2) return <p className="py-10 text-center text-sm text-mute">No trades in this run yet.</p>;
  const L = (q: number) => Math.log10(Math.max(1, q));
  const w = 600, h = 180, top = Math.max(L(goal) + 0.12, ...ys.map(L)), bot = Math.min(L(start) - 0.6, ...ys.map(L)) - 0.05;
  const x = (i: number) => (i / (ys.length - 1)) * w, y = (q: number) => h - ((L(q) - bot) / (top - bot)) * h;
  const d = ys.map((q, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(q).toFixed(1)}`).join("");
  const mark = (q: number, cls: string, label: string) => (
    <span className={`num pointer-events-none absolute right-1 text-xs ${cls}`} style={{ top: `calc(${(y(q) / h) * 100}% - 14px)` }}>{label}</span>
  );
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${w} ${h}`} className="h-44 w-full sm:h-52" preserveAspectRatio="none" role="img" aria-label="Balance curve of the run">
        <defs><linearGradient id="rich-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="rgb(var(--accent))" stopOpacity="0.25" /><stop offset="1" stopColor="rgb(var(--accent))" stopOpacity="0" /></linearGradient></defs>
        <line x1="0" x2={w} y1={y(goal)} y2={y(goal)} stroke="rgb(var(--accent))" strokeOpacity="0.5" strokeDasharray="5 5" vectorEffect="non-scaling-stroke" />
        <line x1="0" x2={w} y1={y(start)} y2={y(start)} stroke="currentColor" className="text-glass/25" strokeDasharray="3 5" vectorEffect="non-scaling-stroke" />
        <path d={`${d}L${w},${h}L0,${h}Z`} fill="url(#rich-fill)" />
        <path d={d} fill="none" stroke="rgb(var(--accent))" strokeWidth="2.2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      </svg>
      {mark(goal, "text-accent", usd(goal, 0))}
      {mark(start, "text-mute", usd(start, 0))}
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
      {r.goal_reached_at && r.result !== "SUCCESS" && <span className="whitespace-nowrap rounded bg-bull/15 px-1.5 py-0.5 text-xs font-semibold text-bull" title="Reached the $1,000 milestone">$1k ✓</span>}
    </span>
  );
}

/** Share image: a 1080 x 1080 PNG drawn in the browser (no upload, no automatic posting). */
function Share({ v, balance }: { v: any; balance: number | null }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const cv = useRef<HTMLCanvasElement>(null);
  const ref = useFocusTrap(open, () => setOpen(false));
  const show = async () => { setOpen(true); setBusy(true); await new Promise((r) => setTimeout(r, 0)); if (cv.current) await drawHesperCard(cv.current, v, balance); setBusy(false); };
  return (
    <>
      <button type="button" className="btn btn-sm" onClick={() => void show()}>Share</button>
      {open && createPortal(
        <div className="fixed inset-0 z-[70] flex items-end justify-center bg-black/70 p-0 backdrop-blur-sm sm:items-center sm:p-4" onClick={() => setOpen(false)}>
          <div ref={ref} role="dialog" aria-modal="true" aria-label="Hesper Challenge share image" onClick={(e) => e.stopPropagation()}
            className="panel popover animate-in w-full max-w-lg rounded-b-none p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] sm:rounded-2xl">
            <canvas ref={cv} data-hesper-card className="aspect-square w-full rounded-xl border border-glass/10" aria-label="Hesper Challenge image" />
            <p className="mt-2 text-xs text-mute">Nothing is posted automatically.</p>
            <div className="mt-3 flex justify-end gap-2">
              <button type="button" className="btn btn-sm" onClick={() => setOpen(false)}>Close</button>
              <button type="button" className="btn btn-sm btn-primary" disabled={busy}
                onClick={() => cv.current && download(cv.current, `hesper-challenge-run-${v.current?.run ?? 0}.png`)}>Download PNG</button>
            </div>
          </div>
        </div>, document.body)}
    </>
  );
}

/** Admin switch: the challenge for the admin only, or view-only for active members too (never public). Asks first. */
/** Admin: end the current run now (open trade closed at the engine's price) and start the next one at $100. Asks first. */
function EndRun({ run, onDone }: { run: number; onDone: () => void }) {
  const [ask, setAsk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const ref = useFocusTrap(ask, () => setAsk(false));
  const go = async () => {
    setAsk(false); setBusy(true); setMsg("Ending the run on the next engine cycle (within 5 min)…");
    try {
      const j = await queueJob("hesper_new_run", { run });
      const r: any = await j.done;
      setMsg(r?.stopped_run ? `Run #${r.stopped_run} ended at ${usd(r.final_balance)} (${Number(r.multiple).toFixed(1)}x). Run #${r.next_run} started at $100.` : "Done.");
      onDone();
    } catch (e: any) { setMsg(`Not ended: ${e?.message ?? e}`); }
    setBusy(false);
  };
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" className="btn btn-sm" disabled={busy} onClick={() => setAsk(true)}>End run & start new</button>
      {msg && <span className="text-xs text-mute" role="status">{msg}</span>}
      {ask && createPortal(
        <div className="fixed inset-0 z-[70] flex items-end justify-center bg-black/70 p-0 backdrop-blur-sm sm:items-center sm:p-4" onClick={() => setAsk(false)}>
          <div ref={ref} role="alertdialog" aria-modal="true" aria-label="End this run" onClick={(e) => e.stopPropagation()}
            className="panel popover animate-in w-full max-w-md rounded-b-none p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] sm:rounded-2xl sm:pb-5">
            <h2 className="text-base font-semibold">End run #{run} and start a new one?</h2>
            <p className="mt-2 text-sm text-mute">An open trade closes at the engine's price, a waiting order is cancelled, and the run is saved as
              “Stopped” with its final balance. Run #{run + 1} starts at $100 straight away. This cannot be undone.</p>
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" className="btn btn-sm" onClick={() => setAsk(false)}>Cancel</button>
              <button type="button" className="btn btn-sm btn-primary" onClick={() => void go()}>End run</button>
            </div>
          </div>
        </div>, document.body)}
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
  const [all, setAll] = useState(false);
  const curve = useMemo(() => (v?.curves ?? {})[String(shown)] ?? [], [v, shown]);
  const sc = v?.score ?? {};
  const trades: any[] = v?.trades ?? [];
  return (
    <div className="space-y-4">
      {admin && !embedded ? (
        <PageHeader title="Hesper Challenge" sub={`${SUBLINE}. All-in, up to ${v?.max_leverage ?? 25}x (15m: 10–50x). Virtual money.`}
          actions={<><Visibility />{v?.current && <EndRun run={v.current.run} onDone={q.reload} />}{v?.current && <Share v={v} balance={live.balance} />}</>} />
      ) : (
        <div>
          <h2 className="text-lg font-semibold"><span className="text-accent">Hesper Challenge</span></h2>
          <p className="text-sm text-mute">{SUBLINE}</p>
          <p className="text-sm text-mute">Demo challenge with virtual money. Not a trading plan.</p>
        </div>
      )}
      {q.error && !v && <ErrorBox error={q.error} retry={q.reload} />}
      {!v && !q.error && <div className="skeleton h-64 rounded-xl" />}
      {v && !v.current && <p className="panel p-4 text-center text-sm text-mute">Hesper starts with the next engine cycle.</p>}
      {v?.current && (
        <>
          <RunCard v={v} live={live} />
          <div className="panel rich-facts grid grid-cols-2 p-0 sm:grid-cols-3 lg:grid-cols-6">
            <Tile k="Reached $1,000" v={String(sc.milestones ?? sc.successes ?? 0)} cls="text-bull" sub="runs that hit the milestone" />
            <Tile k="Failures" v={String(sc.failures ?? 0)} cls="text-bear" sub={`${sc.liquidations ?? 0} liquidated · ${sc.busted ?? 0} busted`} />
            <Tile k="Runs" v={String(sc.runs ?? 0)} sub={`now #${curRun}${sc.stopped ? ` · ${sc.stopped} stopped` : ""}`} />
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
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

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
                  <th className="px-4 py-2 text-right font-semibold">Balance</th>
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
                      <td className="num px-4 py-2 text-right">{usd(t.balance_after)}</td>
                    </tr>
                  ))}
                  {!trades.length && <tr><td colSpan={8} className="px-4 py-6 text-center text-mute">No closed trades yet.</td></tr>}
                </tbody>
              </table>
            </div>
            {trades.length > 25 && (
              <div className="border-t border-glass/[0.06] px-4 py-2 text-center">
                <button type="button" className="tap-h px-2 text-sm text-accent hover:underline" onClick={() => setAll((x) => !x)}>{all ? "Show fewer" : `Show all ${trades.length}`}</button>
              </div>
            )}
          </section>
          <p className="text-center text-xs text-mute">{v.label ?? "Demo · virtual money · not financial advice"}</p>
        </>
      )}
    </div>
  );
}
