// v2.34 News page visuals (owner, 14 Nov 2026: "alienistic ... futuristic, cosmic, AI-inspired"). Both are real data drawn
// in an observatory style, not decoration: Intercept = every headline of the last 24 h arriving at a deep-space receiver
// (x = time, lane = source, the news-mood signal as the carrier wave); OrbitTrack = the next 7 days of releases as worlds
// on an orbit, with the windows in which the engine pauses new signals (45 min before → 30 min after a high-impact
// release) as dark bands. Colours from theme tokens; motion off under reduced motion (index.css "v2.34").
import { type RefObject, useEffect, useMemo, useRef, useState } from "react";
import { ago, isNum } from "../lib/format";

const H = 3_600_000;
const SRC_TONE: Record<string, string> = { CoinDesk: "--accent", Cointelegraph: "--bull", Decrypt: "--warn" };
const tok = (s?: string) => SRC_TONE[s ?? ""] ?? "--ai";

/** The element's width in CSS pixels, so the SVG can be drawn 1:1 (round dots, never stretched). */
function useWidth<T extends Element>(fallback: number): [RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(120, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

type Head = { title: string; url?: string; source?: string; ts?: number; coins?: string[] };

/** Headlines of the last 24 h as packets arriving at a receiver dish; the mood series is the carrier wave. */
export function Intercept({ heads, series, now, score }: { heads: Head[]; series?: { ts: number; score: number }[]; now: number; score?: number | null }) {
  const [box, W] = useWidth<HTMLDivElement>(800);
  const HT = 180, X0 = 14, X1 = W - 18;
  const [hover, setHover] = useState<Head | null>(null);
  const srcs = useMemo(() => Array.from(new Set(heads.map((h) => h.source).filter(Boolean))).slice(0, 4) as string[], [heads]);
  const t0 = now - 24 * H;
  const X = (t: number) => X0 + ((t - t0) / (24 * H)) * (X1 - X0);
  const lanes = Math.max(1, srcs.length);
  const laneY = (s?: string) => 24 + ((srcs.indexOf(s ?? "") + 0.5) / lanes) * (HT - 66);
  const recent = heads.filter((h) => isNum(h.ts) && h.ts! >= t0 && h.ts! <= now + 60_000);
  const wave = useMemo(() => {
    const pts = (series ?? []).filter((p) => p.ts >= t0);
    if (pts.length < 2) return null;
    return pts.map((p, i) => `${i ? "L" : "M"}${X(p.ts).toFixed(1)},${(HT / 2 - 6 - Math.max(-1, Math.min(1, p.score)) * 60).toFixed(1)}`).join(" ");
  }, [series, t0, W]); // eslint-disable-line react-hooks/exhaustive-deps
  const waveTok = isNum(score) ? (score! >= 0.1 ? "--bull" : score! <= -0.1 ? "--bear" : "--ai") : "--ai";
  const newest = recent.reduce<Head | null>((a, h) => (!a || (h.ts ?? 0) > (a.ts ?? 0) ? h : a), null);
  return (
    <section className="panel intercept relative overflow-hidden p-0" aria-label={`${recent.length} headlines received in the last 24 hours`}>
      <div className="pointer-events-none absolute left-4 top-3 z-10">
        <div className="label flex items-center gap-2"><span className="intercept-led" />Incoming transmissions</div>
        <div className="num mt-0.5 font-display text-2xl font-semibold">{recent.length}<span className="ml-1.5 text-sm font-normal text-mute">headlines · 24 h</span></div>
      </div>
      <div className="pointer-events-none absolute right-4 top-3 z-10 hidden flex-wrap justify-end gap-x-3 gap-y-1 text-xs text-mute sm:flex">
        {srcs.map((s) => <span key={s} className="flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full" style={{ background: `rgb(var(${tok(s)}))`, boxShadow: `0 0 6px rgb(var(${tok(s)}))` }} />{s}</span>)}
        <span className="flex items-center gap-1.5"><span className="h-px w-4" style={{ background: `rgb(var(${waveTok}))` }} />news mood</span>
      </div>
      <div className="flex items-stretch pt-14 sm:pt-12">
      {/* the receiver: a dish catching the beam, rings pulsing out (own square box, so it never stretches) */}
      <svg viewBox="-60 -60 120 120" className="hidden w-[84px] shrink-0 self-center min-[360px]:block sm:w-[120px]" aria-hidden="true">
        <defs><radialGradient id="ic-core" cx="50%" cy="50%" r="50%"><stop offset="0%" stopColor="rgb(var(--ai) / 0.55)" /><stop offset="100%" stopColor="rgb(var(--ai) / 0)" /></radialGradient></defs>
        <circle r="50" fill="url(#ic-core)" />
        {[0, 1, 2].map((i) => <circle key={i} r="16" fill="none" stroke="rgb(var(--ai) / 0.5)" className="ic-ring" style={{ animationDelay: `${i * 1.1}s` }} />)}
        <path d="M-20 -26 Q 18 0 -20 26" fill="none" stroke="rgb(var(--accent))" strokeWidth="3.5" strokeLinecap="round" />
        <line x1="-4" y1="0" x2="22" y2="0" stroke="rgb(var(--accent) / 0.8)" strokeWidth="1.6" />
        <circle cx="24" cy="0" r="3.4" fill="rgb(var(--ai))" className="ic-blink" />
        <line x1="-20" y1="0" x2="-32" y2="26" stroke="rgb(var(--mute))" strokeWidth="2.4" />
        <line x1="-40" y1="28" x2="-24" y2="28" stroke="rgb(var(--mute))" strokeWidth="2.4" strokeLinecap="round" />
      </svg>
      <div ref={box} className="min-w-0 flex-1">
      <svg viewBox={`0 0 ${W} ${HT}`} width={W} height={HT} className="block" role="img" aria-hidden="true">
        <defs>
          <linearGradient id="ic-beam" x1="1" x2="0"><stop offset="0%" stopColor="rgb(var(--ai) / 0)" /><stop offset="100%" stopColor="rgb(var(--ai) / 0.18)" /></linearGradient>
        </defs>
        {/* hour grid: the sky is ruled every 6 h */}
        {[0, 6, 12, 18, 24].map((h) => {
          const x = X(t0 + h * H);
          return <g key={h}><line x1={x} x2={x} y1={10} y2={HT - 22} stroke="rgb(var(--text) / 0.06)" strokeDasharray="2 6" />
</g>;
        })}
        <polygon points={`0,${HT / 2} ${X1},8 ${X1},${HT - 22}`} fill="url(#ic-beam)" />
        {/* carrier wave = the news mood over the same 24 h */}
        {wave && <>
          <path d={wave} fill="none" stroke={`rgb(var(${waveTok}) / 0.22)`} strokeWidth="6" vectorEffect="non-scaling-stroke" />
          <path d={wave} fill="none" stroke={`rgb(var(${waveTok}) / 0.8)`} strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
          <path d={wave} fill="none" stroke="rgb(var(--text) / 0.9)" strokeWidth="1.6" vectorEffect="non-scaling-stroke" strokeDasharray="40 1600" className="wave-glint" />
        </>}
        {/* source lanes and the packets */}
        {srcs.map((s) => <line key={s} x1={X0} x2={X1} y1={laneY(s)} y2={laneY(s)} stroke={`rgb(var(${tok(s)}) / 0.12)`} />)}
        {recent.map((h, i) => {
          const x = X(h.ts!), y = laneY(h.source) + (((i * 37) % 13) - 6);
          const isNew = h === newest;
          return (
            <a key={(h.url ?? h.title) + i} href={h.url} target="_blank" rel="noopener noreferrer" onMouseEnter={() => setHover(h)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(h)} onBlur={() => setHover(null)}>
              <line x1={x} x2={Math.min(X1, x + 18)} y1={y} y2={y} stroke={`rgb(var(${tok(h.source)}) / 0.35)`} strokeWidth="1.2" />
              <circle cx={x} cy={y} r={isNew ? 5 : 3.4} fill={`rgb(var(${tok(h.source)}))`} style={{ filter: `drop-shadow(0 0 4px rgb(var(${tok(h.source)})))` }} className={isNew ? "ic-new" : undefined} />
              <circle cx={x} cy={y} r="10" fill="transparent" />
            </a>
          );
        })}
      </svg>
      </div>
      </div>
      <div className="num flex justify-between pb-1 pl-[8px] pr-3 text-xs text-mute min-[360px]:ml-[84px] sm:ml-[120px]" aria-hidden="true">{["24h ago", "18h", "12h", "6h", "now"].map((t) => <span key={t}>{t}</span>)}</div>
      <div className="intercept-read border-t border-glass/[0.06] px-4 py-2 text-xs" aria-live="polite">
        {hover ? <span><span className="text-mute">{hover.source}{hover.ts ? ` · ${ago(hover.ts)}` : ""} · </span>{hover.title}</span>
          : newest ? <span><span className="text-mute">Latest · {newest.source} · {ago(newest.ts!)} · </span>{newest.title}</span>
          : <span className="text-mute">No headlines in the last 24 hours.</span>}
      </div>
    </section>
  );
}

type Ev = { id?: string; title: string; ts: number; impact?: string; country?: string };

/** The next 7 days as an orbit: releases are worlds (high impact large, red), the signal-pause windows dark bands. */
export function OrbitTrack({ events, now }: { events: Ev[]; now: number }) {
  const W = 440, HT = 78, X0 = 20, X1 = W - 12, Y = 42;
  const span = 7 * 24 * H;
  const X = (t: number) => X0 + ((t - now) / span) * (X1 - X0);
  const list = events.filter((e) => e.ts >= now - H && e.ts <= now + span && (e.impact === "High" || e.impact === "Medium"));
  const [hover, setHover] = useState<Ev | null>(null);
  const next = list.find((e) => e.impact === "High" && e.ts > now);
  const days = Array.from({ length: 8 }, (_, i) => {
    const d = new Date(now); d.setHours(0, 0, 0, 0); return d.getTime() + i * 24 * H;
  }).filter((t) => t >= now && t <= now + span);
  return (
    <div className="orbit-track border-b border-glass/[0.06] px-2 pt-2">
      <svg viewBox={`0 0 ${W} ${HT}`} className="block w-full" role="img" aria-label={`${list.filter((e) => e.impact === "High").length} high-impact releases in the next 7 days`}>
        <path d={`M${X0} ${Y} Q ${(X0 + X1) / 2} ${Y - 30} ${X1} ${Y}`} fill="none" stroke="rgb(var(--ai) / 0.25)" strokeDasharray="3 6" />
        <line x1={X0} x2={X1} y1={Y} y2={Y} stroke="rgb(var(--text) / 0.12)" />
        {days.map((t) => <g key={t}><line x1={X(t)} x2={X(t)} y1={Y - 6} y2={Y + 6} stroke="rgb(var(--text) / 0.2)" />
          <text x={X(t) + 3} y={HT - 4} fontSize="10" fill="rgb(var(--mute))">{new Date(t).toLocaleDateString(undefined, { weekday: "short" })}</text></g>)}
        {list.filter((e) => e.impact === "High").map((e) => (
          <rect key={`b${e.id ?? e.ts}`} x={X(e.ts - 45 * 60_000)} y={Y - 13} width={Math.max(2, X(e.ts + 30 * 60_000) - X(e.ts - 45 * 60_000))} height="26" fill="rgb(var(--bear) / 0.16)" rx="2" />
        ))}
        {list.map((e) => {
          const hi = e.impact === "High";
          const x = X(e.ts);
          return (
            <g key={e.id ?? `${e.ts}${e.title}`} onMouseEnter={() => setHover(e)} onMouseLeave={() => setHover(null)} tabIndex={0} onFocus={() => setHover(e)} onBlur={() => setHover(null)} className="cursor-default outline-none">
              {hi && <circle cx={x} cy={Y} r="9" fill="none" stroke="rgb(var(--bear) / 0.45)" className={e === next ? "ic-ring" : undefined} />}
              <circle cx={x} cy={Y} r={hi ? 5 : 3} fill={hi ? "rgb(var(--bear))" : "rgb(var(--warn))"} style={{ filter: `drop-shadow(0 0 5px rgb(var(${hi ? "--bear" : "--warn"})))` }} />
              <circle cx={x} cy={Y} r="12" fill="transparent" />
            </g>
          );
        })}
        {/* now: the observer */}
        <g transform={`translate(${X0} ${Y})`}>
          <circle r="9" fill="rgb(var(--ai) / 0.18)" className="ic-blink" />
          <circle r="4" fill="rgb(var(--ai))" />
          <text y="-13" textAnchor="middle" fontSize="9" fill="rgb(var(--ai))">now</text>
        </g>
      </svg>
      <div className="min-h-[1.75rem] px-2 pb-2 text-xs text-mute" aria-live="polite">
        {hover ? <><span className="font-semibold text-text">{hover.country} {hover.title}</span> · {new Date(hover.ts).toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" })} · {hover.impact} impact{hover.impact === "High" ? " · new signals pause 45 min before to 30 min after" : ""}</>
          : <>Red worlds: high-impact releases; the dark band around each is when new signals pause. Hover a world for details.</>}
      </div>
    </div>
  );
}

/** Coins in the news as a constellation: each mentioned coin a star around the AI core (bigger = more headlines);
 *  tapping one filters the headlines to it. */
export function CoinConstellation({ heads, coin, onPick }: { heads: Head[]; coin: string; onPick: (c: string) => void }) {
  const list = useMemo(() => {
    const c: Record<string, number> = {};
    for (const h of heads) for (const x of h.coins ?? []) c[x] = (c[x] ?? 0) + 1;
    return Object.entries(c).sort((a, b) => b[1] - a[1]).slice(0, 12);
  }, [heads]);
  if (!list.length) return null;
  const S = 300, C = S / 2, max = list[0][1];
  const pos = list.map(([n, k], i) => {
    const ring = i < 5 ? 78 : 122, per = i < 5 ? Math.min(5, list.length) : list.length - 5;
    const a = ((i < 5 ? i : i - 5) / Math.max(1, per)) * Math.PI * 2 - Math.PI / 2 + (i < 5 ? 0 : Math.PI / Math.max(1, per));
    return { n, k, x: C + Math.cos(a) * ring, y: C + Math.sin(a) * ring * 0.82, r: 5 + (k / max) * 9 };
  });
  return (
    <section className="panel p-0">
      <div className="card-head flex items-center justify-between border-b border-glass/[0.06] px-4 py-2.5">
        <h2 className="label">Coins in the transmissions</h2>
        {coin !== "all" && <button type="button" className="text-xs text-accent hover:underline" onClick={() => onPick("all")}>Show all coins</button>}
      </div>
      <svg viewBox={`0 0 ${S} ${S * 0.86}`} className="mx-auto block w-full max-w-[420px]" role="group" aria-label="Coins mentioned in the headlines">
        <g transform={`translate(0 ${-S * 0.07})`}>
          <ellipse cx={C} cy={C} rx="78" ry={78 * 0.82} fill="none" stroke="rgb(var(--ai) / 0.18)" strokeDasharray="2 6" />
          <ellipse cx={C} cy={C} rx="122" ry={122 * 0.82} fill="none" stroke="rgb(var(--ai) / 0.12)" strokeDasharray="2 8" />
          <circle cx={C} cy={C} r="26" fill="rgb(var(--ai) / 0.12)" className="ic-blink" />
          <circle cx={C} cy={C} r="7" fill="rgb(var(--ai))" style={{ filter: "drop-shadow(0 0 8px rgb(var(--ai)))" }} />
          {pos.map((p) => <line key={`l${p.n}`} x1={C} y1={C} x2={p.x} y2={p.y} stroke={`rgb(var(--ai) / ${coin === p.n ? 0.6 : 0.14})`} />)}
          {pos.map((p) => {
            const on = coin === p.n;
            return (
              <g key={p.n} role="button" tabIndex={0} aria-pressed={on} aria-label={`${p.n}: ${p.k} headline${p.k === 1 ? "" : "s"}`} className="cursor-pointer outline-none"
                onClick={() => onPick(on ? "all" : p.n)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(on ? "all" : p.n); } }}>
                <circle cx={p.x} cy={p.y} r={p.r + 8} fill="transparent" />
                <circle cx={p.x} cy={p.y} r={p.r} fill={`rgb(var(${on ? "--accent" : "--ai"}) / ${on ? 0.95 : 0.35})`} stroke={`rgb(var(${on ? "--accent" : "--ai"}))`}
                  style={{ filter: `drop-shadow(0 0 ${on ? 10 : 5}px rgb(var(${on ? "--accent" : "--ai"})))` }} />
                <text x={p.x} y={p.y + p.r + 12} textAnchor="middle" fontSize="11" fontWeight="600" fill="rgb(var(--text) / 0.85)">{p.n}</text>
                <text x={p.x} y={p.y + 3.5} textAnchor="middle" fontSize="9" fontWeight="700" fill="rgb(var(--ink))">{p.k}</text>
              </g>
            );
          })}
        </g>
      </svg>
      <p className="px-4 pb-3 text-xs text-mute">Bigger star = more headlines. Tap a coin to read only its news.</p>
    </section>
  );
}

/** Headlines per hour over the last 24 h as a spectrum analyser; the busiest hour glows. */
export function NewsSpectrum({ heads, now }: { heads: Head[]; now: number }) {
  const bins = useMemo(() => {
    const b = Array.from({ length: 24 }, () => ({ n: 0, src: {} as Record<string, number> }));
    for (const h of heads) {
      if (!isNum(h.ts)) continue;
      const i = 23 - Math.floor((now - h.ts!) / H);
      if (i >= 0 && i < 24) { b[i].n += 1; b[i].src[h.source ?? ""] = (b[i].src[h.source ?? ""] ?? 0) + 1; }
    }
    return b;
  }, [heads, now]);
  const max = Math.max(1, ...bins.map((b) => b.n));
  const peak = bins.reduce((a, b, i) => (b.n >= bins[a].n ? i : a), 0);      // ties: the most recent hour
  const total = bins.reduce((a, b) => a + b.n, 0);
  const W = 240, HT = 90, bw = W / 24;
  return (
    <section className="panel flex flex-1 flex-col p-0">
      <div className="card-head flex items-center justify-between border-b border-glass/[0.06] px-4 py-2.5">
        <h2 className="label">News activity, hour by hour</h2>
        <span className="num text-xs text-mute">{total} in 24 h</span>
      </div>
      <div className="flex flex-1 flex-col justify-end px-4 pb-3 pt-4">
        <svg viewBox={`0 0 ${W} ${HT}`} preserveAspectRatio="none" className="block h-24 w-full" role="img" aria-label={`Busiest hour: ${bins[peak].n} headlines`}>
          <defs>
            <linearGradient id="spec-ai" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="rgb(var(--ai) / 0.7)" /><stop offset="100%" stopColor="rgb(var(--ai) / 0.08)" /></linearGradient>
            <linearGradient id="spec-hot" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="rgb(var(--accent))" /><stop offset="100%" stopColor="rgb(var(--accent) / 0.15)" /></linearGradient>
          </defs>
          {[0.25, 0.5, 0.75].map((f) => <line key={f} x1="0" x2={W} y1={HT * f} y2={HT * f} stroke="rgb(var(--text) / 0.05)" />)}
          {bins.map((b, i) => {
            const h = (b.n / max) * (HT - 6);
            const hot = i === peak && b.n > 0;
            return <g key={i}>
              <rect x={i * bw + 2} y={HT - h} width={bw - 4} height={h} rx="1" fill={`url(#spec-${hot ? "hot" : "ai"})`} />
              {b.n > 0 && <rect x={i * bw + 2} y={HT - h} width={bw - 4} height="1.5" fill={`rgb(var(${hot ? "--accent" : "--ai"}))`} />}
            </g>;
          })}
        </svg>
        <div className="num mt-1 flex justify-between text-xs text-mute"><span>24h ago</span><span>12h</span><span>now</span></div>
        <p className="mt-2 text-xs text-mute">{total ? <>Busiest hour: <span className="text-text">{bins[peak].n} headline{bins[peak].n === 1 ? "" : "s"}</span>, {23 - peak === 0 ? "this hour" : `${23 - peak} h ago`}.</> : "Quiet: no headlines in the last 24 hours."}</p>
      </div>
    </section>
  );
}
