// Animated Fear & Greed gauge (alternative.me index, 0-100) with a 30-day trend.
// The needle sweeps to today's value and the number counts up when the card appears; afterwards the needle
// breathes gently and the marker pulses. Everything rests still with the system's "reduce motion" setting.
import { useEffect, useId, useRef, useState } from "react";

type Point = { ts: number; value: number };
const ZONES = [
  { to: 25, color: "#f6465d", name: "Extreme fear", note: "Panic selling. Prices are often stretched to the downside." },
  { to: 45, color: "#f7931a", name: "Fear", note: "Traders are nervous; rallies are being sold." },
  { to: 55, color: "#f0b90b", name: "Neutral", note: "No strong crowd emotion either way." },
  { to: 75, color: "#8bd450", name: "Greed", note: "Buyers are confident; pullbacks get bought." },
  { to: 100, color: "#0ecb81", name: "Extreme greed", note: "Euphoria. The market can be overheated." },
];
const zoneOf = (v: number) => ZONES.find((z) => v <= z.to) ?? ZONES[ZONES.length - 1];

// gauge geometry: half circle, 0 at the left, 100 at the right
const CX = 130, CY = 128, R = 100;
const ang = (v: number) => Math.PI * (1 - v / 100);
const pt = (v: number, r = R) => [CX + r * Math.cos(ang(v)), CY - r * Math.sin(ang(v))];
function arc(a: number, b: number, r = R) {
  const [x1, y1] = pt(a, r), [x2, y2] = pt(b, r);
  return `M${x1.toFixed(2)} ${y1.toFixed(2)} A${r} ${r} 0 0 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
}

function useSweep(target: number, ms = 1800) {
  const [v, setV] = useState(0);
  const [done, setDone] = useState(false);
  const from = useRef(0);
  useEffect(() => {
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce) { setV(target); from.current = target; setDone(true); return; }
    setDone(false);
    const start = performance.now(), a = from.current;
    let raf = 0;
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / ms);
      const e = 1 - Math.pow(1 - k, 3) + Math.sin(k * Math.PI) * 0.07 * (1 - k);   // ease out with a small overshoot
      setV(a + (target - a) * e);
      if (k < 1) raf = requestAnimationFrame(step); else { from.current = target; setV(target); setDone(true); }
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return { v, done };
}

export default function FearGreed({ value, label, change7d, history = [] }: { value: number; label: string; change7d?: number | null; history?: Point[] }) {
  const id = useId().replace(/:/g, "");
  const { v, done } = useSweep(value);
  const z = zoneOf(value);
  const cur = Math.max(0, Math.min(100, v));
  const tip = pt(cur, R - 22);
  const marker = pt(cur);
  const hist = history.slice(-30);
  const yday = hist.length > 1 ? hist[hist.length - 2].value : null;
  const week = hist.length > 7 ? hist[hist.length - 8].value : null;
  const vals = hist.map((p) => p.value);
  const hi = vals.length ? Math.max(...vals) : null, lo = vals.length ? Math.min(...vals) : null;

  // 30-day area chart
  const W = 280, H = 64;
  const xy = hist.map((p, i) => [(i / Math.max(1, hist.length - 1)) * W, H - 4 - (p.value / 100) * (H - 8)] as const);
  const line = xy.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = xy.length ? `M0 ${H} L${xy.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join(" L")} L${W} ${H} Z` : "";
  const last = xy[xy.length - 1];
  const [drawn, setDrawn] = useState(false);
  const [settled, setSettled] = useState(false);      // the dash trick stops once drawn (it clips the line's end when stretched)
  useEffect(() => { const t = requestAnimationFrame(() => setDrawn(true)); const u = window.setTimeout(() => setSettled(true), 1800); return () => { cancelAnimationFrame(t); window.clearTimeout(u); }; }, []);

  return (
    <div>
      <div className="relative mx-auto w-full max-w-[300px]">
        <svg viewBox="0 0 260 150" className="w-full overflow-visible" role="img" aria-label={`Fear and Greed index ${value}, ${label}`}>
          <defs>
            <linearGradient id={`fg-grad-${id}`} x1="30" y1="0" x2="230" y2="0" gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor="#f6465d" /><stop offset="0.3" stopColor="#f7931a" /><stop offset="0.5" stopColor="#f0b90b" />
              <stop offset="0.72" stopColor="#8bd450" /><stop offset="1" stopColor="#0ecb81" />
            </linearGradient>
            <filter id={`fg-glow-${id}`} x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="4" /></filter>
          </defs>
          {/* track, faint full scale, bright part up to the value */}
          <path d={arc(0, 100)} stroke="rgb(var(--glass) / 0.07)" strokeWidth="20" fill="none" strokeLinecap="round" />
          <path d={arc(0, 100)} stroke={`url(#fg-grad-${id})`} strokeWidth="14" fill="none" strokeLinecap="round" opacity="0.22" />
          <path d={arc(0, Math.max(0.6, cur))} stroke={`url(#fg-grad-${id})`} strokeWidth="14" fill="none" strokeLinecap="round" />
          <path d={arc(0, Math.max(0.6, cur))} stroke={`url(#fg-grad-${id})`} strokeWidth="8" fill="none" strokeLinecap="round" opacity="0.55" filter={`url(#fg-glow-${id})`} />
          {/* ticks */}
          {Array.from({ length: 21 }, (_, i) => i * 5).map((t) => {
            const major = t % 25 === 0;
            const [x1, y1] = pt(t, R - 13), [x2, y2] = pt(t, R - (major ? 21 : 17));
            return <line key={t} x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgb(var(--mute))" strokeWidth={major ? 1.6 : 1} opacity={major ? 0.8 : 0.4} strokeLinecap="round" />;
          })}
          {[0, 25, 50, 75, 100].map((t) => { const [x, y] = pt(t, R + 17); return <text key={t} x={x} y={y + 3.5} textAnchor="middle" fontSize="10" fill="rgb(var(--mute))" className="tabular-nums">{t}</text>; })}
          {yday != null && (() => { const [x, y] = pt(yday, R); return <circle cx={x} cy={y} r="3.4" fill="rgb(var(--ink))" stroke="rgb(var(--text))" strokeWidth="1.5"><title>Yesterday: {yday}</title></circle>; })()}
          {/* needle */}
          <g className={done ? "fg-breathe" : undefined} style={{ transformOrigin: `${CX}px ${CY}px` }}>
            <line x1={CX} y1={CY} x2={tip[0]} y2={tip[1]} stroke="rgb(var(--text))" strokeWidth="3.2" strokeLinecap="round" />
            <circle cx={tip[0]} cy={tip[1]} r="3.2" fill="rgb(var(--text))" />
          </g>
          <circle cx={CX} cy={CY} r="9" fill="rgb(var(--raised))" stroke="rgb(var(--text))" strokeWidth="2.5" />
          <circle cx={CX} cy={CY} r="3" fill={z.color} />
          {/* marker riding on the arc */}
          <circle cx={marker[0]} cy={marker[1]} r="12" fill={z.color} className={done ? "fg-pulse" : undefined} style={{ transformOrigin: `${marker[0]}px ${marker[1]}px` }} opacity="0.35" />
          <circle cx={marker[0]} cy={marker[1]} r="7.5" fill="rgb(var(--ink))" stroke={z.color} strokeWidth="3" />
          {/* value */}
          <text x={CX} y={CY - 34} textAnchor="middle" fontSize="38" fontWeight="700" fill={z.color} className="tabular-nums" style={{ letterSpacing: "-0.02em" }}>{Math.round(cur)}</text>
        </svg>
      </div>

      <div className="-mt-1 flex flex-col items-center gap-1 text-center">
        <span className="rounded-full px-3 py-0.5 text-sm font-semibold" style={{ color: z.color, background: `${z.color}1f`, boxShadow: `inset 0 0 0 1px ${z.color}55` }}>{label}</span>
        <p className="max-w-[300px] text-xs text-mute">{z.note}</p>
        {change7d != null && <p className="text-xs text-mute"><span className={`tabular-nums font-medium ${change7d > 0 ? "text-bull" : change7d < 0 ? "text-bear" : ""}`}>{change7d > 0 ? "▲ +" : change7d < 0 ? "▼ " : ""}{change7d}</span> over 7 days</p>}
      </div>

      <div className="mt-3 grid grid-cols-4 gap-1.5 text-center text-xs">
        {([["Now", value], ["Yesterday", yday], ["Last week", week], ["30d range", lo != null && hi != null ? `${lo}–${hi}` : null]] as const).map(([k, x]) => (
          <div key={k} className="rounded-lg bg-glass/[0.04] px-1 py-1.5">
            <div className="text-[11px] text-mute">{k}</div>
            <div className="num font-semibold" style={typeof x === "number" ? { color: zoneOf(x).color } : undefined}>{x ?? "—"}</div>
          </div>
        ))}
      </div>

      {hist.length > 2 && (
        <div className="mt-3">
          <div className="mb-1 flex justify-between text-[11px] text-mute"><span>30 days ago</span><span>today</span></div>
          <svg viewBox={`0 0 ${W} ${H}`} className="h-16 w-full overflow-visible" preserveAspectRatio="none" aria-hidden="true">
            <defs>
              <linearGradient id={`fg-area-${id}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor={z.color} stopOpacity="0.35" /><stop offset="1" stopColor={z.color} stopOpacity="0" />
              </linearGradient>
            </defs>
            {/* fear / greed bands */}
            <rect x="0" y={H - 4 - 0.25 * (H - 8)} width={W} height={0.25 * (H - 8)} fill="#f6465d" opacity="0.05" />
            <rect x="0" y={4} width={W} height={0.25 * (H - 8)} fill="#0ecb81" opacity="0.05" />
            <line x1="0" x2={W} y1={H - 4 - 0.5 * (H - 8)} y2={H - 4 - 0.5 * (H - 8)} stroke="rgb(var(--glass) / 0.12)" strokeDasharray="3 4" vectorEffect="non-scaling-stroke" />
            <path d={area} fill={`url(#fg-area-${id})`} style={{ opacity: drawn ? 1 : 0, transition: "opacity 1.2s ease-out 0.4s" }} />
            <polyline points={line} fill="none" stroke={z.color} strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke"
              pathLength={1} strokeDasharray={settled ? undefined : "1"} strokeDashoffset={settled ? undefined : drawn ? 0 : 1} style={{ transition: "stroke-dashoffset 1.6s ease-out" }} />
            {last && <circle cx={last[0]} cy={last[1]} r="3" fill={z.color} vectorEffect="non-scaling-stroke" />}
          </svg>
        </div>
      )}
    </div>
  );
}
