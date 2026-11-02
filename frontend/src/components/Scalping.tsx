// Admin "Scalping" scorecard: every live 15m grade-A demo call (never a public signal) logged when issued and followed
// with the track record's rules - backend views.scalping, table scalp_signals. Admin only, unless the admin opens it to
// members (config/scalping.visibility; the Firestore rules enforce it). Wins and losses alike, before fees.
import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { setScalpingVisibility, useApi, type ScalpingVisibility } from "../lib/api";
import { base, fmtDate, fmtPrice, fmtTime, isNum } from "../lib/format";
import { useIsAdmin } from "../lib/session";
import { download } from "../lib/cardCanvas";
import { drawScalpCard, holdText, scalpDate } from "../lib/scalpCard";
import { CoinAvatar } from "./Polish";
import { fillLabel, Pill, RoiFigure } from "./SignalExtras";
import { isOpen, LiveResult, LiveRoi, RecordSheet, statusOf } from "./RecordDetails";
import { Curve } from "./TrackRecord";
import { useFocusTrap } from "./Shell";

const pct = (v: unknown, d = 1) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "—");
const rate = (v: unknown) => (isNum(v) ? `${Math.round(v * 100)}%` : "—");
const tone = (v: unknown) => (isNum(v) ? (v > 0 ? "text-bull" : v < 0 ? "text-bear" : "") : "text-mute");
const fromControl = (e: React.SyntheticEvent) => (e.target as HTMLElement).closest("button, a") !== null;
export const SCALP_LABEL = "Demo results · 15m scalping · not public · before fees";

/** Who may read the scorecard: config/scalping.visibility ("admin" when the document is missing). */
export function useScalpingVisibility(): ScalpingVisibility {
  const c = useApi<any>("/scalping/config");
  return c.data?.visibility === "members" ? "members" : "admin";
}

function Kpi({ k, v, sub, cls = "" }: { k: string; v: string; sub?: string; cls?: string }) {
  return <div className="panel p-4"><div className="label">{k}</div><div className={`num mt-1.5 text-2xl font-semibold leading-none ${cls}`}>{v}</div>{sub && <div className="mt-1.5 text-[11px] leading-snug text-mute">{sub}</div>}</div>;
}

function HitBar({ k, v, cls = "bg-bull" }: { k: string; v: unknown; cls?: string }) {
  const w = isNum(v) ? Math.max(0, Math.min(100, v * 100)) : 0;
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="w-20 shrink-0 text-mute">{k}</span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-glass/[0.08]" role="img" aria-label={`${k}: ${rate(v)}`}><div className={`h-full rounded-full ${cls}`} style={{ width: `${w}%` }} /></div>
      <span className="num w-12 shrink-0 text-right font-semibold">{rate(v)}</span>
    </div>
  );
}

function Confirm({ title, body, confirm, run, onClose }: { title: string; body: string; confirm: string; run: () => void; onClose: () => void }) {
  const ref = useFocusTrap(true, onClose);
  return createPortal(
    <div className="fixed inset-0 z-[70] flex items-end justify-center bg-black/70 p-0 backdrop-blur-sm sm:items-center sm:p-4" onClick={onClose}>
      <div ref={ref} role="alertdialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}
        className="panel popover animate-in w-full max-w-md rounded-b-none p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] sm:rounded-2xl sm:pb-5">
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="mt-2 text-sm text-mute">{body}</p>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" className="btn btn-sm" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-sm btn-primary" onClick={() => { onClose(); run(); }}>{confirm}</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/** Admin switch: scorecard for the admin only, or for active members too (never public). Asks first. */
export function VisibilityToggle() {
  const vis = useScalpingVisibility();
  const [ask, setAsk] = useState<ScalpingVisibility | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const save = async (to: ScalpingVisibility) => {
    setMsg(null);
    try { await setScalpingVisibility(to); setMsg(to === "members" ? "Members can now see the scorecard." : "Only you can see the scorecard now."); }
    catch (e: any) { setMsg(`Not saved: ${e?.message ?? e}`); }
  };
  return (
    <div className="flex flex-wrap items-center gap-2" data-scalp-visibility={vis}>
      <span className="text-xs text-mute">Who can see it</span>
      <span className="inline-flex rounded-xl border border-glass/10 p-1" role="radiogroup" aria-label="Who can see the scalping scorecard">
        {(["admin", "members"] as const).map((k) => (
          <button key={k} type="button" role="radio" aria-checked={vis === k} onClick={() => vis !== k && setAsk(k)}
            className={`rounded-lg px-3 py-1 text-sm ${vis === k ? "bg-accent font-semibold text-ink" : "text-mute hover:text-text"}`}>{k === "admin" ? "Admin only" : "Members too"}</button>
        ))}
      </span>
      {msg && <span className="text-xs text-mute" role="status">{msg}</span>}
      {ask && <Confirm title={ask === "members" ? "Show the scalping scorecard to members?" : "Hide the scalping scorecard from members?"}
        body={ask === "members"
          ? "Active members will see this demo scorecard (15m scalping, not public signals, before fees) on Results. Signed-out visitors never can. You can switch it back at any time."
          : "Only you (the admin) will see the scorecard. Members lose access at once."}
        confirm={ask === "members" ? "Show to members" : "Admin only"} run={() => void save(ask)} onClose={() => setAsk(null)} />}
    </div>
  );
}

/** Share image: a 1080 x 1080 PNG drawn in the browser (no upload, no automatic posting). */
function ShareImage({ v }: { v: any }) {
  const [open, setOpen] = useState(false);
  const cv = useRef<HTMLCanvasElement>(null);
  const [busy, setBusy] = useState(false);
  const show = async () => { setOpen(true); setBusy(true); await new Promise((r) => setTimeout(r, 0)); if (cv.current) await drawScalpCard(cv.current, v); setBusy(false); };
  const name = `crypto-intelligence-scalping-15m-${new Date(v.since ?? Date.now()).toISOString().slice(0, 10)}.png`;
  return (
    <>
      <button type="button" className="btn btn-sm" onClick={() => void show()}>Share image</button>
      {open && createPortal(
        <div className="fixed inset-0 z-[70] flex items-end justify-center bg-black/70 p-0 backdrop-blur-sm sm:items-center sm:p-4" onClick={() => setOpen(false)}>
          <div role="dialog" aria-modal="true" aria-label="Scalping share image" onClick={(e) => e.stopPropagation()}
            className="panel popover animate-in w-full max-w-lg rounded-b-none p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] sm:rounded-2xl">
            <canvas ref={cv} data-scalp-card className="aspect-square w-full rounded-xl border border-glass/10" aria-label="Scalping scorecard image" />
            <p className="mt-2 text-[11px] text-mute">Labelled “Demo results - 15m scalping - since {scalpDate(v.since)}”. Nothing is posted automatically.</p>
            <div className="mt-3 flex justify-end gap-2">
              <button type="button" className="btn btn-sm" onClick={() => setOpen(false)}>Close</button>
              <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={() => cv.current && download(cv.current, name)}>Download PNG</button>
            </div>
          </div>
        </div>, document.body)}
    </>
  );
}

function Trades({ rows, empty, onOpen }: { rows: any[]; empty: string; onOpen: (x: any) => void }) {
  if (!rows.length) return <p className="p-4 text-sm text-mute">{empty}</p>;
  const props = (x: any) => ({
    tabIndex: 0, "aria-haspopup": "dialog" as const, "aria-label": `${x.symbol} ${x.side} 15M: details`,
    onClick: (e: React.MouseEvent) => { if (!fromControl(e)) onOpen(x); },
    onKeyDown: (e: React.KeyboardEvent) => { if ((e.key === "Enter" || e.key === " ") && e.target === e.currentTarget) { e.preventDefault(); onOpen(x); } },
  });
  return (
    <>
      <ul className="divide-y divide-glass/[0.06] sm:hidden">
        {rows.map((x) => {
          const [lab, cls] = statusOf(x);
          const fill = fillLabel(x.fill_status);
          return (
            <li key={x.id} {...props(x)} className="cursor-pointer px-4 py-3 outline-none hover:bg-glass/[0.03] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/60">
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2.5">
                  <CoinAvatar symbol={x.symbol} size={28} />
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5"><span className="font-semibold">{base(x.symbol)}</span><span className={`text-[11px] font-bold ${x.side === "LONG" ? "text-bull" : "text-bear"}`}>{x.side}</span>{fill && isOpen(x) && <Pill tone={fill[1]}>{fill[0]}</Pill>}</div>
                    <div className={`mt-0.5 whitespace-nowrap text-[11px] font-semibold ${cls}`}>{lab}{isNum(x.hold_min) && <span className="num font-normal text-mute"> · held {holdText(x.hold_min)}</span>}</div>
                    <div className="num whitespace-nowrap text-[11px] text-mute">{fmtTime(x.created_at)}</div>
                  </div>
                </div>
                {isOpen(x) ? <LiveRoi x={x} size="md" /> : isNum(x.return_pct) ? <RoiFigure x={x} size="md" /> : <span className="text-[11px] text-mute">not counted</span>}
              </div>
              {isOpen(x) && <div className="mt-1.5"><LiveResult x={x} /></div>}
            </li>
          );
        })}
      </ul>
      <table className="grid-table hidden min-w-[680px] sm:table">
        <thead><tr><th>Call</th><th className="text-right">Entry</th><th className="text-right">Stop</th><th className="text-right">Target 1</th><th>Result</th><th className="text-right">ROI on margin</th></tr></thead>
        <tbody>
          {rows.map((x) => {
            const [lab, cls] = statusOf(x);
            const fill = fillLabel(x.fill_status);
            return (
              <tr key={x.id} {...props(x)} className="cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/60">
                <td><div className="flex items-center gap-2"><CoinAvatar symbol={x.symbol} size={22} /><span className="font-semibold">{base(x.symbol)}</span><span className={`text-xs font-bold ${x.side === "LONG" ? "text-bull" : "text-bear"}`}>{x.side}</span></div><div className="num mt-0.5 pl-[30px] text-[11px] text-mute">{fmtTime(x.created_at)}{isNum(x.hold_min) ? ` · held ${holdText(x.hold_min)}` : ""}</div></td>
                <td className="num text-right">{fmtPrice(x.entry)}</td><td className="num text-right text-bear">{fmtPrice(x.stop)}</td><td className="num text-right text-bull">{fmtPrice(x.tp1)}</td>
                <td className={`text-xs font-semibold ${cls}`}>{lab}{fill && isOpen(x) && <span className="ml-1"><Pill tone={fill[1]}>{fill[0]}</Pill></span>}{isOpen(x) && <LiveResult x={x} />}</td>
                <td className="text-right align-middle">{isOpen(x) ? <LiveRoi x={x} /> : isNum(x.return_pct) ? <RoiFigure x={x} size="sm" /> : <span className="text-[11px] text-mute">not counted</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}

function BotBlock({ b }: { b: any }) {
  if (!b) return <p className="panel p-4 text-sm text-mute">The 15m demo bot is not running, so there is no bot book to show.</p>;
  return (
    <section className="panel p-0" aria-label="15m demo bot">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-glass/[0.06] px-4 py-3">
        <div><h3 className="font-semibold">{b.name ?? "15m demo bot"}</h3><p className="text-[11px] text-mute">Virtual money{b.started_at ? ` · since ${fmtDate(b.started_at)}` : ""} · fees and funding included · its own exits (whole position at target 1)</p></div>
        {!b.enabled && <Pill tone="warn">paused</Pill>}
      </div>
      <dl className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-5">
        {([["Equity", isNum(b.equity) ? `${b.equity.toFixed(0)} USDT` : "—", ""], ["Return", pct(b.return_pct), tone(b.return_pct)], ["Trades", String(b.trades ?? 0), ""],
          ["Win rate", rate(b.win_rate), ""], ["Max drop", isNum(b.max_drawdown_pct) ? `${b.max_drawdown_pct.toFixed(1)}%` : "—", "text-bear"]] as const).map(([k, v, c]) => (
          <div key={k}><dt className="label">{k}</dt><dd className={`num mt-1 text-lg font-semibold ${c}`}>{v}</dd></div>
        ))}
      </dl>
      {(b.recent ?? []).length > 0 && (
        <ul className="divide-y divide-glass/[0.06] border-t border-glass/[0.06]">
          {b.recent.slice(0, 8).map((t: any, i: number) => (
            <li key={i} className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
              <span className="flex min-w-0 items-center gap-1.5"><span className="font-semibold">{base(t.symbol)}</span><span className={`text-[11px] font-bold ${t.side === "LONG" ? "text-bull" : "text-bear"}`}>{t.side}</span><span className="num truncate text-[11px] text-mute">{fmtTime(t.closed_at)} · {t.exit_reason}</span></span>
              <span className={`num font-semibold ${tone(t.roe_pct ?? t.return_pct)}`}>{pct(t.roe_pct ?? t.return_pct, 2)}{isNum(t.roe_pct) && <span className="ml-1 text-[10px] font-normal text-mute">on margin</span>}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function Scalping() {
  const v = useApi<any>("/scalping");
  const admin = useIsAdmin();
  const [detail, setDetail] = useState<string | null>(null);
  const d = v.data;
  if (!d && v.error) return <p className="panel p-4 text-center text-sm text-mute">{/permission/i.test(v.error) || /owner/i.test(v.error) ? "The scalping scorecard is for the admin only." : "The scalping scorecard appears after the next engine run."}</p>;
  if (!d) return <div className="skeleton h-40 rounded-xl" />;
  const s = d.summary ?? {};
  const roi = isNum(s.avg_roi_pct);
  const open: any[] = d.open ?? [];
  const recent: any[] = d.recent ?? [];
  const all = [...open, ...recent];
  const shown = detail ? all.find((x) => x.id === detail) : null;
  const st = s.streak ?? {};
  return (
    <div className="space-y-3" data-scalping>
      <div className="panel flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-display text-lg font-bold">Scalping · 15M grade A</h2>
            <span className="rounded-md border border-warn/45 bg-warn/10 px-1.5 py-0.5 text-[11px] font-bold text-warn">{SCALP_LABEL}</span>
          </div>
          <p className="mt-1 text-xs text-mute">{d.since ? `Counted since ${fmtDate(d.since)} · ${open.length} open · ${d.not_filled ?? 0} ${d.not_filled === 1 ? "entry" : "entries"} missed · ${d.void ?? 0} void (listed, not counted)` : "Logging starts with the next engine run."}</p>
        </div>
        {admin && <div className="flex flex-wrap items-center gap-2"><VisibilityToggle /><ShareImage v={d} /></div>}
      </div>

      {!(s.closed > 0) ? (
        <p className="panel p-5 text-center text-sm text-mute">No 15m grade-A call has closed yet{d.since ? ` since ${fmtDate(d.since)}` : ""}. Every result, win or loss, appears here as soon as one closes.</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Kpi k="Closed calls" v={String(s.closed)} sub={`${s.wins} wins · ${s.losses} losses`} />
            <Kpi k="Win rate" v={rate(s.win_rate)} sub="return above 0 counts as a win" />
            {roi ? <Kpi k="Avg ROI per call" v={pct(s.avg_roi_pct, 2)} cls={tone(s.avg_roi_pct)} sub={`on margin · price ${pct(s.avg_return_pct, 2)}`} />
              : <Kpi k="Avg price move" v={pct(s.avg_return_pct, 2)} cls={tone(s.avg_return_pct)} sub="per call" />}
            {roi ? <Kpi k="Total ROI on margin" v={pct(s.total_roi_pct)} cls={tone(s.total_roi_pct)} sub={`price ${pct(s.total_return_pct)}`} />
              : <Kpi k="Total price move" v={pct(s.total_return_pct)} cls={tone(s.total_return_pct)} sub="equal size" />}
            <Kpi k="Profit factor" v={isNum(s.profit_factor) ? s.profit_factor.toFixed(2) : "—"} sub={isNum(s.profit_factor) ? "gains ÷ losses (price)" : "no loss yet"} />
            <Kpi k="Max drawdown" v={isNum(roi ? s.max_drawdown_roi_pct : s.max_drawdown_pct) ? `-${(roi ? s.max_drawdown_roi_pct : s.max_drawdown_pct).toFixed(1)}%` : "—"} cls="text-bear" sub={roi ? `of the ROI curve · price -${(s.max_drawdown_pct ?? 0).toFixed(1)}%` : "of the cumulative curve"} />
            <Kpi k="Current streak" v={st.n ? `${st.n} ${st.kind === "win" ? (st.n === 1 ? "win" : "wins") : (st.n === 1 ? "loss" : "losses")}` : "—"} cls={st.kind === "win" ? "text-bull" : st.kind === "loss" ? "text-bear" : ""} sub={`best ${st.best_win ?? 0} wins · worst ${st.best_loss ?? 0} losses`} />
            <Kpi k="Avg hold" v={holdText(s.avg_hold_min)} sub="from entry to close" />
          </div>
          {(d.curve?.length ?? 0) > 1 && (
            <div className="panel px-4 pt-3">
              <div className="flex items-center justify-between text-xs text-mute"><span>{roi ? "Cumulative ROI on margin (equal margin per call)" : "Cumulative price move (equal size)"}</span><span className={`num font-semibold ${tone(roi ? s.total_roi_pct : s.total_return_pct)}`}>{pct(roi ? s.total_roi_pct : s.total_return_pct)}</span></div>
              <Curve pts={d.curve} roi={roi} id="scalp-fill" label="Cumulative result of all closed scalping calls" />
            </div>
          )}
          <div className="grid gap-3 md:grid-cols-2">
            <section className="panel space-y-2.5 p-4" aria-label="Target hit rates">
              <h3 className="label">Targets reached (of closed calls)</h3>
              <HitBar k="Target 1" v={s.hit_rates?.tp1} /><HitBar k="Target 2" v={s.hit_rates?.tp2} /><HitBar k="Target 3" v={s.hit_rates?.tp3} />
              <HitBar k="Stopped" v={s.stop_rate} cls="bg-bear" />
            </section>
            <section className="panel grid grid-cols-2 gap-3 p-4" aria-label="Best and worst call">
              {([["Best call", s.best], ["Worst call", s.worst]] as const).map(([k, t]) => (
                <div key={k} className="min-w-0"><div className="label">{k}</div>
                  {t ? <><div className="mt-1 flex items-center gap-1.5 text-sm"><span className="font-semibold">{base(t.symbol)}</span><span className={`text-[11px] font-bold ${t.side === "LONG" ? "text-bull" : "text-bear"}`}>{t.side}</span></div><div className="mt-1"><RoiFigure x={t} size="sm" align="left" /></div><div className="num text-[11px] text-mute">{fmtTime(t.closed_at)}</div></> : <div className="text-mute">—</div>}
                </div>
              ))}
            </section>
          </div>
        </>
      )}

      <section className="panel p-0" aria-label="Open scalping calls">
        <h3 className="border-b border-glass/[0.06] px-4 py-2.5 text-sm font-semibold">Open now ({open.length})</h3>
        <div className="overflow-x-auto"><Trades rows={open} empty="No 15m grade-A call is open right now." onOpen={(x) => setDetail(x.id)} /></div>
      </section>
      <section className="panel p-0" aria-label="Recent scalping calls">
        <h3 className="border-b border-glass/[0.06] px-4 py-2.5 text-sm font-semibold">Recent calls · wins and losses ({recent.length})</h3>
        <div className="overflow-x-auto"><Trades rows={recent} empty="No call has closed yet." onOpen={(x) => setDetail(x.id)} /></div>
      </section>
      <BotBlock b={d.bot} />
      <p className="px-1 text-[11px] text-mute">{d.method} Live figures follow the current price and are not a result until the call closes. Never part of the public track record.</p>
      {shown && <RecordSheet x={shown} scalp onClose={() => setDetail(null)} />}
    </div>
  );
}

/** Health page summary (admin): a few numbers and a link to the full scorecard. */
export function ScalpingSummary() {
  const v = useApi<any>("/scalping");
  const d = v.data;
  if (!d) return null;
  const s = d.summary ?? {};
  const roi = isNum(s.total_roi_pct);
  return (
    <section className="panel p-4" aria-label="Scalping summary" data-scalping-summary>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">Scalping · 15M grade A</h2>
        <span className="rounded-md border border-warn/45 bg-warn/10 px-1.5 py-0.5 text-[11px] font-bold text-warn">{SCALP_LABEL}</span>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-5">
        {([["Closed", String(s.closed ?? 0), ""], ["Win rate", rate(s.win_rate), ""], [roi ? "Total ROI" : "Total move", pct(roi ? s.total_roi_pct : s.total_return_pct), tone(roi ? s.total_roi_pct : s.total_return_pct)],
          ["Open", String((d.open ?? []).length), ""], ["Demo bot", pct(d.bot?.return_pct), tone(d.bot?.return_pct)]] as const).map(([k, val, c]) => (
          <div key={k}><dt className="label">{k}</dt><dd className={`num mt-1 text-lg font-semibold ${c}`}>{val}</dd></div>
        ))}
      </dl>
      <p className="mt-2 text-xs text-mute">{d.since ? `Since ${fmtDate(d.since)}. ` : ""}<Link className="text-accent" to="/results?tab=scalping">Open the scorecard →</Link></p>
    </section>
  );
}
