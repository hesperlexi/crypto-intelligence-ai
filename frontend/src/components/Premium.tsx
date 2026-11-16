// v2.44 premium upgrade (owner, 16 Nov 2026: "an enhanced premium look of all the pages ... like a pro"). Real data only,
// gold-black theme, no SVG filters (cheap on phones, v2.39), motion off under reduced motion.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { fmtPrice, isNum } from "../lib/format";

const clamp = (v: number, a = 0, b = 1) => Math.max(a, Math.min(b, v));
const DUBAI = 4 * 3_600_000;
const dayOf = (ms: number) => Math.floor((ms + DUBAI) / 86_400_000);       // Dubai calendar day number

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

/* ------------------------------------------------------------------ results: proof wall */
type Row = { status: string; closed_at?: number | null; created_at?: number; return_pct?: number | null };
const CLOSED = new Set(["STOPPED", "TP1", "TP2", "TP3", "EXPIRED"]);

/** Every closed call of the record by Dubai day: a calendar of green / red days, monthly bars and the best / worst week.
 *  Built from the same rows the Track record lists (net, after fees). */
export function ProofWall({ rows, since }: { rows: Row[]; since?: number | null }) {
  const data = useMemo(() => {
    const closed = rows.filter((x) => CLOSED.has(x.status) && isNum(x.closed_at) && isNum(x.return_pct));
    const byDay = new Map<number, { sum: number; n: number; w: number }>();
    for (const x of closed) {
      const d = dayOf(x.closed_at!);
      const c = byDay.get(d) ?? { sum: 0, n: 0, w: 0 };
      c.sum += x.return_pct!; c.n += 1; c.w += x.return_pct! > 0 ? 1 : 0;
      byDay.set(d, c);
    }
    const today = dayOf(Date.now());
    const first = Math.min(today - 34, ...(since ? [dayOf(since)] : []), ...[...byDay.keys()]);
    const start = Math.max(first, today - 83);                       // up to 12 weeks
    const s0 = start - ((start + 3) % 7);                            // align to Monday (day 0 = Thu 1 Jan 1970)
    const weeks: { d: number; c?: { sum: number; n: number; w: number } }[][] = [];
    for (let d = s0; d <= today; d += 7) weeks.push(Array.from({ length: 7 }, (_, i) => ({ d: d + i, c: byDay.get(d + i) })));
    const months = new Map<string, number>();
    for (const x of closed) {
      const k = new Date(x.closed_at! + DUBAI).toISOString().slice(0, 7);
      months.set(k, (months.get(k) ?? 0) + x.return_pct!);
    }
    const wk = weeks.map((w) => ({ from: w[0].d, sum: w.reduce((a, q) => a + (q.c?.sum ?? 0), 0), n: w.reduce((a, q) => a + (q.c?.n ?? 0), 0) })).filter((w) => w.n);
    const best = wk.length ? wk.reduce((a, b) => (b.sum > a.sum ? b : a)) : null;
    const worst = wk.length ? wk.reduce((a, b) => (b.sum < a.sum ? b : a)) : null;
    const days = [...byDay.values()];
    return { weeks, today, months: [...months.entries()].slice(-6), best, worst, green: days.filter((c) => c.sum > 0).length, red: days.filter((c) => c.sum <= 0).length, closed: closed.length };
  }, [rows, since]);
  if (!data.closed) return null;
  const maxAbs = Math.max(0.5, ...data.weeks.flat().map((q) => Math.abs(q.c?.sum ?? 0)));
  const mMax = Math.max(0.5, ...data.months.map(([, v]) => Math.abs(v)));
  const label = (d: number) => new Date(d * 86_400_000).toLocaleDateString(undefined, { day: "numeric", month: "short", timeZone: "UTC" });
  const pct = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
  return (
    <section className="panel proof-wall p-4 sm:p-5" aria-label="Proof wall">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="label">Proof wall · every closed signal by day</h2>
        <span className="text-xs text-mute">after fees · Dubai days</span>
      </div>
      <div className="trust-strip mt-3">
        <span>✓ Every trade shown, losses included</span><span>✓ Real entry prices</span><span>✓ After fees and funding</span>
      </div>
      <div className="mt-4 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.8fr)]">
        <div className="min-w-0">
          <div className="pw-grid" style={{ gridTemplateColumns: `auto repeat(${data.weeks.length}, minmax(0, 20px))` }}>
            {["M", "", "W", "", "F", "", "S"].map((l, i) => <span key={`l${i}`} className="pw-dow" style={{ gridRow: i + 1, gridColumn: 1 }}>{l}</span>)}
            {data.weeks.map((w, wi) => w.map((q, di) => {
              const v = q.c?.sum;
              const future = q.d > data.today;
              const a = v == null ? 0 : 0.25 + 0.75 * clamp(Math.abs(v) / maxAbs);
              return (
                <span key={q.d} className={`pw-cell ${future ? "is-future" : v == null ? "" : v > 0 ? "is-up" : "is-down"} ${q.d === data.today ? "is-today" : ""}`}
                  style={{ gridRow: di + 1, gridColumn: wi + 2, ...(v != null ? { opacity: a } : {}) }}
                  title={v == null ? label(q.d) : `${label(q.d)}: ${pct(v)} · ${q.c!.n} closed, ${q.c!.w} won`} />
              );
            }))}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-mute">
            <span><span className="pw-key is-up" /> {data.green} green {data.green === 1 ? "day" : "days"}</span>
            <span><span className="pw-key is-down" /> {data.red} red {data.red === 1 ? "day" : "days"}</span>
            <span>stronger colour = bigger day</span>
          </div>
        </div>
        <div className="min-w-0 space-y-4">
          <div>
            <div className="text-xs text-mute">By month</div>
            <div className="mt-2 space-y-1.5">
              {data.months.map(([m, v]) => (
                <div key={m} className="grid grid-cols-[64px_minmax(0,1fr)_64px] items-center gap-2 text-xs">
                  <span className="num">{new Date(`${m}-01T00:00:00Z`).toLocaleDateString(undefined, { month: "short", year: "2-digit", timeZone: "UTC" })}</span>
                  <div className="pw-bar"><div className={v >= 0 ? "is-up" : "is-down"} style={{ width: `${clamp(Math.abs(v) / mMax) * 100}%` }} /></div>
                  <span className={`num text-right font-semibold ${v >= 0 ? "text-bull" : "text-bear"}`}>{pct(v)}</span>
                </div>
              ))}
            </div>
          </div>
          {data.best && data.worst && (
            <div className="grid grid-cols-2 gap-2">
              <div className="pw-week is-up"><div className="text-xs text-mute">Best week</div><div className="num text-lg font-semibold text-bull">{pct(data.best.sum)}</div><div className="text-xs text-mute">from {label(data.best.from)}</div></div>
              <div className="pw-week is-down"><div className="text-xs text-mute">Worst week</div><div className={`num text-lg font-semibold ${data.worst.sum >= 0 ? "text-bull" : "text-bear"}`}>{pct(data.worst.sum)}</div><div className="text-xs text-mute">from {label(data.worst.from)}</div></div>
            </div>
          )}
        </div>
      </div>
    </section>
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
export function Burst({ fire }: { fire: number }) {
  const [on, setOn] = useState(0);
  useEffect(() => {
    if (!fire) return;
    setOn(fire);
    const t = window.setTimeout(() => setOn(0), 1000);
    return () => window.clearTimeout(t);
  }, [fire]);
  if (!on) return null;
  return (
    <span className="burst" aria-hidden="true" key={on}>
      {Array.from({ length: 12 }, (_, i) => <i key={i} style={{ ["--a" as any]: `${i * 30}deg`, ["--d" as any]: `${46 + (i % 3) * 14}px` }} />)}
    </span>
  );
}

/* ------------------------------------------------------------------ live result ticker */
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
