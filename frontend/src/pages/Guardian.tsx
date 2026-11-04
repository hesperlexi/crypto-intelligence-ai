// v2.19 Trade Guardian (admin only, recommend-only): early warnings on open public calls with a concrete action
// (tighten the stop / close now). Nothing changes unless the admin presses Apply, which sends the normal adjust job
// (same checks and member notifications as Adjust / Close now); the engine re-validates it first.
// Data: views/guardian (backend services/guardian.py), admin only in the rules.
import { type ReactNode, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { Badge, Tile, type Tone } from "../components/kit";
import { CoinAvatar } from "../components/Polish";
import { useFocusTrap } from "../components/Shell";
import { Empty, ErrorBox } from "../components/ui";
import { queueJob, useApi } from "../lib/api";
import { ago, base, fmtPrice, isNum, slug } from "../lib/format";
import { useTickerThrottled } from "../lib/live";
import { track, useNotices } from "../lib/notice";

type Reason = { code: string; label: string; points: number; estimate?: boolean };
type Shadow = { action?: string; applied?: boolean; with_r?: number; without_r?: number; delta_r?: number; skipped?: string };
export type GuardianRec = {
  id: string; signal_id: string; symbol: string; timeframe: string; side: number; level: "TIGHTEN" | "CLOSE" | "NONE";
  rules_level: string; severity: number; created_at: number; expires_at: number; status: string; status_at?: number | null;
  status_reason?: string | null; reasons?: Reason[]; price?: number; entry?: number; stop_in_force?: number;
  proposed_stop?: number | null; atr?: number; tp1_hit?: boolean; ai?: { path: string; text: string; model?: string | null };
  shadow?: Shadow | null;
};
type Agg = { n: number; saved_r: number; cost_r: number; net_r: number; helped: number; hurt: number };

const NOTE = { TIGHTEN: "Trade Guardian: stop tightened after a sharp move against the trade.", CLOSE: "Trade Guardian: closed early after a sharp move against the trade." } as const;
const AI_BADGE: Record<string, [string, Tone, string]> = {
  ai_agreed: ["AI agreed", "ai", "Gemini read the numbers and agreed with the rules"],
  ai_downgraded: ["AI downgraded", "warn", "Gemini judged the facts weaker and lowered the action by one step (it can never raise it)"],
  rules_only: ["Rules only", "mute", "Gemini was off, over its daily budget or did not answer: the rules' text is shown"],
  ai_rejected: ["Rules only", "mute", "Gemini's answer failed the checks (numbers not in the input, predictions or advice) and was dropped"],
};
const STATUS: Record<string, [string, Tone]> = {
  live: ["Live", "accent"], applied: ["Applied", "bull"], dismissed: ["Dismissed", "mute"], expired: ["Expired", "mute"],
  rejected: ["Rejected", "bear"], void: ["Call closed", "mute"], superseded: ["Replaced", "mute"], downgraded: ["AI: no action", "warn"],
};
const r2 = (v: unknown) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(2)}R` : "—");
const rTone = (v: unknown) => (isNum(v) ? (v > 0.0001 ? "text-bull" : v < -0.0001 ? "text-bear" : "") : "text-mute");
const sideWord = (s: number) => (s > 0 ? "long" : "short");
const hhmm = (ms: unknown) => (isNum(ms) ? new Date(ms).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");

/** Re-render every `ms` (client-side countdowns). */
function useNow(ms = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), ms); return () => window.clearInterval(t); }, [ms]);
  return now;
}
const mmss = (ms: number) => { const s = Math.max(0, Math.round(ms / 1000)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };

export default function Guardian() {
  const q = useApi<any>("/guardian");
  const v = q.data;
  const live: GuardianRec[] = v?.live ?? [];
  const hist: GuardianRec[] = v?.history ?? [];
  return (
    <div className="space-y-4">
      <div>
        <h1 className="page-title"><span className="text-accent">Trade Guardian</span></h1>
        <p className="text-sm text-mute">Early warnings on open calls. Recommend-only: nothing changes until you apply it.</p>
      </div>
      {q.error && !v && <ErrorBox error={q.error} retry={q.reload} />}
      {!v && !q.error && <div className="skeleton h-64 rounded-xl" />}
      {v && (
        <>
          <StatusLine v={v} />
          <section aria-label="Live recommendations" className="space-y-3">
            <h2 className="label">Live recommendations{live.length ? <span className="num ml-1.5 text-accent">{live.length}</span> : null}</h2>
            {live.length ? live.map((r) => <RecCard key={r.id} r={r} />) : (
              <Empty>No warnings right now. Open calls are checked every engine run (about every 5 minutes).</Empty>
            )}
          </section>
          <Scoreboard sb={v.scoreboard} />
          <History rows={hist} />
          {v.config && (
            <p className="text-xs leading-relaxed text-mute">
              Severity {v.config.tighten_at}–{v.config.close_at - 1}: tighten the stop · {v.config.close_at}+: close now ·
              recommendations expire after {v.config.expires_min} min · proposed stops keep ≥ {v.config.min_gap_atr} ATR from the price ·
              no recommendation from data older than {v.config.fresh_m1_min} min. {v.note}
            </p>
          )}
        </>
      )}
    </div>
  );
}

function StatusLine({ v }: { v: any }) {
  const s = v.status ?? {};
  const t = s.today ?? {};
  const w = s.watched ?? {};
  useNow(15000);
  const late = isNum(s.last_check) && Date.now() - s.last_check > 20 * 60_000;
  return (
    <section aria-label="Guardian status" className="space-y-2">
      <div className="metric-strip">
        <Tile variant="strip" label="Last check" value={isNum(s.last_check) ? ago(s.last_check) : "—"} valueClass={late ? "text-warn" : ""}
          sub={v.enabled === false ? "switched off (GUARDIAN=0)" : late ? "engine late" : "every engine run"} />
        <Tile variant="strip" label="Watching" value={`${w.calls ?? 0} call${w.calls === 1 ? "" : "s"}`}
          sub={(w.coins ?? []).length ? (w.coins as string[]).join(" · ") : "no open calls"} />
        <Tile variant="strip" label="Skipped: stale" value={String(t.skipped_stale ?? 0)} valueClass={t.skipped_stale ? "text-warn" : ""}
          sub={`today · price check ${t.skipped_price ?? 0}`} />
        <Tile variant="strip" label="Errors" value={String(t.errors ?? 0)} valueClass={t.errors ? "text-bear" : ""}
          sub={`today · AI calls ${t.ai_calls ?? 0}`} />
      </div>
      {s.last_error && (
        <p className="break-words rounded-lg border border-bear/30 bg-bear/[0.06] px-3 py-2 text-xs text-bear">
          Last error {ago(s.last_error.at)} · {s.last_error.where}: {s.last_error.text}
        </p>
      )}
    </section>
  );
}

function SeverityBar({ value }: { value: number }) {
  const tone = value >= 75 ? "bg-bear" : value >= 50 ? "bg-warn" : "bg-accent";
  return (
    <div className="flex items-center gap-2" title="Severity 0–100: 50+ tighten, 75+ close">
      <div className="relative h-2 flex-1 overflow-hidden rounded-full bg-glass/[0.08]" role="meter" aria-label="Severity" aria-valuemin={0} aria-valuemax={100} aria-valuenow={value}>
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${Math.min(100, Math.max(2, value))}%` }} />
        <span className="absolute inset-y-0 left-1/2 w-px bg-text/30" aria-hidden="true" />
        <span className="absolute inset-y-0 left-3/4 w-px bg-text/30" aria-hidden="true" />
      </div>
      <span className={`num w-12 text-right text-sm font-semibold ${value >= 75 ? "text-bear" : "text-warn"}`}>{value}</span>
    </div>
  );
}

function RecCard({ r }: { r: GuardianRec }) {
  const now = useNow(1000);
  const t = useTickerThrottled(r.symbol, 2000);
  const px = isNum(t?.last) ? t!.last : null;
  const { pending } = useNotices();
  const [ask, setAsk] = useState<null | "apply" | "dismiss">(null);
  const left = r.expires_at - now;
  const expired = left <= 0;
  const busy = pending.get(r.signal_id);
  const ai = AI_BADGE[r.ai?.path ?? "rules_only"] ?? AI_BADGE.rules_only;
  const close = r.level === "CLOSE";
  const tf = r.timeframe.toUpperCase();
  return (
    <article className={`panel space-y-3 p-4 ${close ? "border-bear/40" : "border-warn/40"}`} aria-label={`${base(r.symbol)} ${tf} ${sideWord(r.side)}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2.5">
          <CoinAvatar symbol={r.symbol} size={30} />
          <div className="min-w-0">
            <Link to={`/asset/${slug(r.symbol)}?tf=${r.timeframe}`} className="font-semibold hover:text-accent">{base(r.symbol)} <span className="num text-mute">{tf}</span></Link>
            <div className="mt-0.5 flex flex-wrap gap-1.5">
              <Badge tone={r.side > 0 ? "bull" : "bear"} caps>{sideWord(r.side)}</Badge>
              {r.tp1_hit && <Badge tone="bull">TP1 hit</Badge>}
              <Badge tone={ai[1]} title={ai[2]}>{ai[0]}</Badge>
            </div>
          </div>
        </div>
        <div className="text-right text-xs text-mute">
          <div>{ago(r.created_at)}</div>
          <div className={`num ${expired ? "text-bear" : left < 5 * 60_000 ? "text-warn" : ""}`}>{expired ? "expired" : `expires in ${mmss(left)}`}</div>
        </div>
      </div>

      <SeverityBar value={r.severity} />

      <div className={`rounded-lg border px-3 py-2 ${close ? "border-bear/40 bg-bear/[0.07]" : "border-warn/40 bg-warn/[0.07]"}`}>
        {close ? (
          <div className="text-base font-semibold text-bear">Close now</div>
        ) : (
          <div className="num text-base font-semibold">
            <span className="text-warn">Tighten stop</span> {fmtPrice(r.stop_in_force)} → <span className="text-bear">{fmtPrice(r.proposed_stop)}</span>
          </div>
        )}
        <div className="num mt-1 grid grid-cols-3 gap-2 text-xs text-mute">
          <div>Entry<div className="text-text">{fmtPrice(r.entry)}</div></div>
          <div>At warning<div className="text-text">{fmtPrice(r.price)}</div></div>
          <div>Now<div className="text-text">{fmtPrice(px)}</div></div>
        </div>
        {r.rules_level !== r.level && <p className="mt-1 text-xs text-warn">The rules said {r.rules_level.toLowerCase()}; the AI lowered it one step.</p>}
      </div>

      {!!r.reasons?.length && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Reasons">
          {r.reasons.map((x, i) => (
            <li key={i}><Badge tone={x.points >= 20 ? "bear" : x.points >= 10 ? "warn" : "mute"} title={x.estimate ? "estimate" : undefined}>
              {x.label}<span className="num ml-1 opacity-70">+{x.points}</span>
            </Badge></li>
          ))}
        </ul>
      )}
      {r.ai?.text && <p className="text-sm leading-relaxed text-text/90">{r.ai.text}</p>}

      <div className="flex flex-wrap items-center justify-end gap-2">
        {busy ? <Badge tone="warn">Waiting for the engine…</Badge> : (
          <>
            <button type="button" className="btn btn-sm" onClick={() => setAsk("dismiss")}>Dismiss</button>
            <button type="button" className={`btn btn-sm ${close ? "btn-danger" : "btn-primary"}`} disabled={expired} onClick={() => setAsk("apply")}
              title={expired ? "Expired: a new warning comes if the conditions persist" : undefined}>
              {close ? "Apply: close now" : "Apply: tighten"}
            </button>
          </>
        )}
      </div>
      {ask === "apply" && <ApplySheet r={r} px={px} onClose={() => setAsk(null)} />}
      {ask === "dismiss" && <DismissSheet r={r} onClose={() => setAsk(null)} />}
    </article>
  );
}

function Sheet({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const ref = useFocusTrap(true, onClose);
  return createPortal(
    <div className="fixed inset-0 z-[75] flex items-end justify-center bg-black/70 p-0 backdrop-blur-sm sm:items-center sm:p-4" onClick={onClose}>
      <div ref={ref} role="alertdialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}
        className="panel popover animate-in max-h-[92vh] w-full max-w-md overflow-y-auto rounded-b-none p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] sm:rounded-2xl sm:pb-5">
        <h2 className="text-base font-semibold">{title}</h2>
        {children}
      </div>
    </div>,
    document.body,
  );
}

function ApplySheet({ r, px, onClose }: { r: GuardianRec; px: number | null; onClose: () => void }) {
  const close = r.level === "CLOSE";
  const [note, setNote] = useState<string>(NOTE[close ? "CLOSE" : "TIGHTEN"]);
  const n = note.trim();
  const tooClose = !close && isNum(px) && isNum(r.proposed_stop) && isNum(r.atr)
    && (r.side > 0 ? px - r.proposed_stop : r.proposed_stop - px) < 0.2 * r.atr;
  const problem = n.length < 3 || n.length > 200 ? "Write a note of 3 to 200 characters: members see it." :
    tooClose ? "The price is now too close to the proposed stop; the engine would refuse it." : null;
  const send = async () => {
    const params: Record<string, any> = close
      ? { signal_id: r.signal_id, action: "close", note: n, guardian_id: r.id }
      : { signal_id: r.signal_id, stop: r.proposed_stop, note: n, guardian_id: r.id };
    try {
      const j = await queueJob("adjust_signal", params);
      track(r.signal_id, close ? "close" : "adjust", j.done, (x: any) => `${base(r.symbol)} ${r.timeframe.toUpperCase()}: ${x?.message ?? "applied."}`);
      onClose();
    } catch (e: any) {
      track(r.signal_id, "adjust", Promise.reject(e), () => "");
      onClose();
    }
  };
  return (
    <Sheet title={close ? `Close ${base(r.symbol)} ${r.timeframe.toUpperCase()} now?` : `Tighten ${base(r.symbol)} ${r.timeframe.toUpperCase()} stop?`} onClose={onClose}>
      <p className="mt-2 text-sm text-mute">
        {close ? "The call closes at the engine's market price on its next run (within about 5 minutes)."
          : <>The stop moves <span className="num text-text">{fmtPrice(r.stop_in_force)} → {fmtPrice(r.proposed_stop)}</span> from the next 15-minute candle.</>}
        {" "}This is the normal admin change: public in the record for good, the demo bots follow it and every member gets a notification. The engine checks it again first.
      </p>
      <label className="mt-3 block">
        <span className="text-xs text-mute">Note for members (3–200 characters)</span>
        <textarea className="input mt-1 min-h-[72px] w-full py-2" maxLength={200} value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      {problem && <p className="mt-2 rounded-lg border border-warn/40 bg-warn/[0.08] px-2.5 py-1.5 text-xs text-warn" role="status">{problem}</p>}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" className="btn btn-sm" onClick={onClose}>Cancel</button>
        <button type="button" className={`btn btn-sm ${close ? "btn-danger" : "btn-primary"}`} disabled={!!problem} onClick={send}>
          {close ? "Close and publish" : "Tighten and publish"}
        </button>
      </div>
    </Sheet>
  );
}

function DismissSheet({ r, onClose }: { r: GuardianRec; onClose: () => void }) {
  const send = async () => {
    try {
      const j = await queueJob("guardian_dismiss", { guardian_id: r.id });
      track(r.signal_id, "dismiss", j.done, () => `${base(r.symbol)} ${r.timeframe.toUpperCase()}: warning dismissed.`);
    } catch (e: any) {
      track(r.signal_id, "dismiss", Promise.reject(e), () => "");
    }
    onClose();
  };
  return (
    <Sheet title="Dismiss this warning?" onClose={onClose}>
      <p className="mt-2 text-sm text-mute">Nothing about the call changes. The Guardian will not raise the same action again for this call; a stronger one still comes if things get worse.</p>
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" className="btn btn-sm" onClick={onClose}>Cancel</button>
        <button type="button" className="btn btn-sm btn-primary" onClick={send}>Dismiss</button>
      </div>
    </Sheet>
  );
}

function Scoreboard({ sb }: { sb?: any }) {
  if (!sb) return null;
  const line = (a?: Agg) => (a && a.n ? `${a.n} · net ${r2(a.net_r)}` : "none yet");
  return (
    <section aria-label="Shadow scoreboard" className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="label">Shadow scoreboard</h2>
        <span className="text-xs text-mute">What each warning would have changed, applied or not (net R, after fees)</span>
      </div>
      <div className="metric-strip">
        <Tile variant="strip" label="Net effect" value={r2(sb.net_r)} valueClass={rTone(sb.net_r)} sub={`${sb.n ?? 0} judged · ${sb.pending ?? 0} waiting`} />
        <Tile variant="strip" label="Saved" value={r2(sb.saved_r)} valueClass="text-bull" sub={`${sb.helped ?? 0} helped`} />
        <Tile variant="strip" label="Cost" value={r2(sb.cost_r)} valueClass={sb.cost_r < 0 ? "text-bear" : ""} sub={`${sb.hurt ?? 0} hurt`} />
        <Tile variant="strip" label="Applied" value={line(sb.applied)} sub={`not applied: ${line(sb.not_applied)}`} />
      </div>
      <p className="text-xs text-mute">Tighten {line(sb.by_level?.TIGHTEN)} · Close {line(sb.by_level?.CLOSE)}. A positive number means the warning would have helped. Judge it after a few weeks; small samples mislead.</p>
    </section>
  );
}

function History({ rows }: { rows: GuardianRec[] }) {
  return (
    <section aria-label="Recent warnings" className="panel p-0">
      <h2 className="label px-4 pt-4">Recent</h2>
      {!rows.length ? <p className="px-4 pb-4 pt-2 text-sm text-mute">No past warnings yet.</p> : (
        <ul className="mt-2 divide-y divide-glass/[0.06]">
          {rows.map((r) => {
            const [st, tone] = STATUS[r.status] ?? [r.status, "mute" as Tone];
            const act = r.level === "CLOSE" ? "Close now" : r.level === "TIGHTEN" ? `Stop → ${fmtPrice(r.proposed_stop)}` : `No action (rules: ${r.rules_level.toLowerCase()})`;
            const d = r.shadow?.delta_r;
            return (
              <li key={r.id} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1 px-4 py-2.5 text-sm sm:grid-cols-[9rem_minmax(0,1fr)_7rem_6rem]">
                <div className="min-w-0">
                  <span className="font-semibold">{base(r.symbol)}</span> <span className="num text-mute">{r.timeframe.toUpperCase()}</span>{" "}
                  <span className={r.side > 0 ? "text-bull" : "text-bear"}>{sideWord(r.side)}</span>
                  <div className="num text-xs text-mute">{hhmm(r.created_at)}</div>
                </div>
                <div className="text-right sm:order-3 sm:text-left"><Badge tone={tone}>{st}</Badge></div>
                <div className="min-w-0 text-xs text-mute sm:order-2 sm:text-sm">
                  <span className="num text-text">{act}</span> · severity <span className="num">{r.severity}</span>
                  {r.status_reason && <div className="break-words text-xs">{r.status_reason}</div>}
                </div>
                <div className={`num text-right text-xs sm:order-4 sm:text-sm ${rTone(d)}`} title="Net R with the warning minus without it">
                  {r.shadow?.skipped ? <span className="text-mute">{r.shadow.skipped}</span> : isNum(d) ? `${r2(d)} ${d > 0 ? "saved" : d < 0 ? "cost" : ""}` : <span className="text-mute">open</span>}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
