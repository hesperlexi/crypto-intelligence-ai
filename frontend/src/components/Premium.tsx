// v2.44 premium upgrade (owner, 16 Nov 2026: "an enhanced premium look of all the pages ... like a pro"). Real data only,
// gold-black theme, no SVG filters (cheap on phones, v2.39), motion off under reduced motion.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { fmtPrice, isNum } from "../lib/format";

const clamp = (v: number, a = 0, b = 1) => Math.max(a, Math.min(b, v));

/* ------------------------------------------------------------------ signal card: trade progress */
/** The trade as one track from the stop to the last target: entry and targets marked, the live price as a glowing
 *  dot, the part already won / lost filled. Works for longs and shorts (always drawn stop -> targets, left -> right). */
export function TradeProgress({ side, entry, stop, targets, px, hits = 0 }: {
  side: "LONG" | "SHORT"; entry: number; stop: number; targets: number[]; px?: number | null; hits?: number;
}) {
  const end = targets[targets.length - 1];
  if (![entry, stop, end].every(isNum) || entry === stop) return null;
  const s = side === "SHORT" ? -1 : 1;
  const span = s * (end - stop);
  if (span <= 0) return null;
  const at = (p: number) => clamp((s * (p - stop)) / span);
  const e = at(entry), p = isNum(px) ? at(px) : null;
  const r = isNum(px) ? (s * (px - entry)) / Math.abs(entry - stop) : null;
  const marks = [{ k: "SL", x: 0, cls: "pt-bear" }, { k: "Entry", x: e, cls: "pt-gold" },
    ...targets.map((t, i) => ({ k: `TP${i + 1}`, x: at(t), cls: i < hits ? "pt-bull pt-hit" : "pt-bull" }))];
  return (
    <div className="ptrack" role="img" aria-label={`Trade progress: price ${r == null ? "unknown" : `${r >= 0 ? "+" : ""}${r.toFixed(2)}R`} between the stop and TP${targets.length}`}>
      <div className="ptrack-bar">
        <div className="ptrack-risk" style={{ width: `${e * 100}%` }} />
        {p != null && (p >= e
          ? <div className="ptrack-won" style={{ left: `${e * 100}%`, width: `${(p - e) * 100}%` }} />
          : <div className="ptrack-lost" style={{ left: `${p * 100}%`, width: `${(e - p) * 100}%` }} />)}
        {marks.map((m) => <span key={m.k} className={`ptrack-tick ${m.cls}`} style={{ left: `${m.x * 100}%` }} />)}
        {p != null && <span className={`ptrack-now ${r != null && r < 0 ? "is-down" : ""}`} style={{ left: `${p * 100}%` }} />}
      </div>
      <div className="ptrack-labels">
        {marks.map((m) => <span key={m.k} className={m.cls} style={{ left: `${m.x * 100}%` }}>{m.k}</span>)}
      </div>
      {r != null && (
        <div className="mt-1 flex items-center justify-between text-xs text-mute">
          <span>Now <b className={r >= 0 ? "text-bull" : "text-bear"}>{r >= 0 ? "+" : ""}{r.toFixed(2)}R</b> from entry</span>
          <span className="num">{fmtPrice(px)}</span>
        </div>
      )}
    </div>
  );
}

/** Three short reasons behind a call, from the analysis the card already has (no new data). */
export function WhyChips({ r }: { r: any }) {
  const chips: [string, string][] = [];
  const side = r?.plan?.side ?? (r?.side > 0 ? "LONG" : r?.side < 0 ? "SHORT" : null);
  if (r?.grade === "A") chips.push(["Trend + AI agree", "accent"]);
  else if (r?.grade === "B") chips.push(["AI-led call", "text"]);
  if (typeof r?.regime === "string" && r.regime) chips.push([`Trend: ${r.regime.replace(/_/g, " ").toLowerCase()}`, "mute"]);
  const up = r?.p_up, down = r?.p_down;
  if (isNum(up) && isNum(down) && side) {
    const lean = side === "LONG" ? up : down;
    chips.push([`AI ${side === "LONG" ? "up" : "down"} ${Math.round(lean * 100)}%`, side === "LONG" ? "bull" : "bear"]);
  }
  if (isNum(r?.plan?.risk_reward)) chips.push([`Reward ${r.plan.risk_reward.toFixed(1)} : 1`, "mute"]);
  if (!chips.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5" aria-label="Why this call">
      {chips.slice(0, 4).map(([t, tone]) => <span key={t} className={`why-chip why-${tone}`}>{t}</span>)}
    </div>
  );
}

/* ------------------------------------------------------------------ rings */
export function Ring({ value, size = 84, stroke = 8, tone = "--accent", children, label }: {
  value: number; size?: number; stroke?: number; tone?: string; children?: React.ReactNode; label?: string;
}) {
  const R = (size - stroke) / 2, C = 2 * Math.PI * R;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="img" aria-label={label}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={R} fill="none" stroke="rgb(var(--glass) / 0.10)" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={R} fill="none" stroke={`rgb(var(${tone}))`} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={`${clamp(value) * C} ${C}`} className="ring-draw" />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">{children}</div>
    </div>
  );
}

/* ------------------------------------------------------------------ small celebration */
/** A short gold burst (CSS only, ~0.9 s). `fire` changes -> one burst. Nothing under reduced motion. */
export function Burst({ fire, big = false }: { fire: number; big?: boolean }) {
  const [on, setOn] = useState(0);
  useEffect(() => {
    if (!fire) return;
    setOn(fire);
    const t = window.setTimeout(() => setOn(0), 1300);
    return () => window.clearTimeout(t);
  }, [fire]);
  if (!on) return null;
  const n = big ? 18 : 12;
  return (
    <span className="burst" aria-hidden="true" key={on}>
      {Array.from({ length: n }, (_, i) => <i key={i} style={{ ["--a" as any]: `${(i * 360) / n}deg`, ["--d" as any]: `${(big ? 70 : 46) + (i % 3) * (big ? 22 : 14)}px` }} />)}
    </span>
  );
}

/* ------------------------------------------------------------------ live result ticker */
const CLOSED = new Set(["STOPPED", "TP1", "TP2", "TP3", "EXPIRED"]);
/** A slow marquee of the latest closed calls of the real record: wins and losses alike. */
export function ResultTicker({ rows, max = 12 }: { rows: any[]; max?: number }) {
  const items = rows.filter((x) => CLOSED.has(x.status) && isNum(x.return_pct)).slice(0, max);
  const ref = useRef<HTMLDivElement>(null);
  if (items.length < 2) return null;
  const one = (x: any, k: string) => (
    <span key={k} className="tick-item">
      <b>{String(x.symbol).split("/")[0] === "PAXG" ? "GOLD" : String(x.symbol).split("/")[0]}</b>
      <span className="text-mute">{x.side} {String(x.timeframe).toUpperCase()}</span>
      <span className={`num font-semibold ${x.return_pct > 0 ? "text-bull" : "text-bear"}`}>{x.return_pct > 0 ? "▲ +" : "▼ "}{x.return_pct.toFixed(2)}%</span>
    </span>
  );
  return (
    <div className="result-ticker" aria-label="Latest closed signals, wins and losses" ref={ref}>
      <div className="result-ticker-track">{items.map((x, i) => one(x, `a${i}`))}{items.map((x, i) => one(x, `b${i}`))}</div>
    </div>
  );
}

/* ------------------------------------------------------------------ first week guide */
type Step = { k: string; title: string; text: string; to?: string; href?: string; done: boolean };
/** First-week guide: remember that the member opened a page / link (this browser only). */
export const markVisited = (k: string) => { try { localStorage.setItem(`cia-fw-${k}`, "1"); } catch { /* ignore */ } };
export const wasVisited = (k: string) => { try { return localStorage.getItem(`cia-fw-${k}`) === "1"; } catch { return false; } };
export function useMarkVisited(k: string) { useEffect(() => markVisited(k), [k]); }
/** A short checklist for new members (first 14 days of the account). Hidden for good with "Done" / once all done. */
export function FirstWeek({ uid, createdAt, steps }: { uid?: string | null; createdAt?: number | null; steps: Step[] }) {
  const key = `cia-firstweek-${uid ?? "anon"}`;
  const [hidden, setHidden] = useState(() => { try { return localStorage.getItem(key) === "1"; } catch { return false; } });
  const done = steps.filter((s) => s.done).length;
  if (hidden || !uid || (isNum(createdAt) && Date.now() - createdAt > 14 * 86_400_000) || done === steps.length) return null;
  const hide = () => { try { localStorage.setItem(key, "1"); } catch { /* ignore */ } setHidden(true); };
  return (
    <section className="panel first-week p-4 sm:p-5" aria-label="Your first week">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-lg font-semibold">Your first week</h2>
          <p className="text-sm text-mute">{done} of {steps.length} done. A few minutes each.</p>
        </div>
        <Ring value={done / steps.length} size={56} stroke={6} label={`${done} of ${steps.length} done`}>
          <span className="num text-sm font-semibold">{done}/{steps.length}</span>
        </Ring>
      </div>
      <ol className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {steps.map((s, i) => (
          <li key={s.k}>
            {s.href ? (
              <a href={s.href} target="_blank" rel="noopener" onClick={() => markVisited(s.k)} className={`fw-step ${s.done ? "is-done" : ""}`}>
                <span className="fw-num" aria-hidden="true">{s.done ? "✓" : i + 1}</span>
                <span className="min-w-0"><span className="block font-medium">{s.title}</span><span className="block text-xs text-mute">{s.text}</span></span>
              </a>
            ) : (
              <Link to={s.to ?? "/"} className={`fw-step ${s.done ? "is-done" : ""}`}>
                <span className="fw-num" aria-hidden="true">{s.done ? "✓" : i + 1}</span>
                <span className="min-w-0"><span className="block font-medium">{s.title}</span><span className="block text-xs text-mute">{s.text}</span></span>
              </Link>
            )}
          </li>
        ))}
      </ol>
      <div className="mt-2 text-right"><button className="text-xs text-mute underline-offset-2 hover:underline" onClick={hide}>Hide this guide</button></div>
    </section>
  );
}
