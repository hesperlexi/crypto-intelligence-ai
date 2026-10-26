// Animated Fear & Greed gauge (alternative.me index, 0-100) with a 30-day trend line.
// The needle sweeps to today's value and the number counts up when the card appears; it rests still afterwards
// and respects the system's "reduce motion" setting.
import { useEffect, useRef, useState } from "react";

type Point = { ts: number; value: number };
const ZONES = [
  { to: 25, color: "#f6465d", name: "Extreme fear" },
  { to: 45, color: "#f7931a", name: "Fear" },
  { to: 55, color: "#f0b90b", name: "Neutral" },
  { to: 75, color: "#8bd450", name: "Greed" },
  { to: 100, color: "#0ecb81", name: "Extreme greed" },
];
const zoneOf = (v: number) => ZONES.find((z) => v <= z.to) ?? ZONES[ZONES.length - 1];

// gauge geometry: half circle, 0 at the left, 100 at the right
const CX = 120, CY = 118, R = 96;
const ang = (v: number) => Math.PI * (1 - v / 100);
const pt = (v: number, r = R) => [CX + r * Math.cos(ang(v)), CY - r * Math.sin(ang(v))];
function arc(a: number, b: number, r = R) {
  const [x1, y1] = pt(a, r), [x2, y2] = pt(b, r);
  return `M${x1.toFixed(2)} ${y1.toFixed(2)} A${r} ${r} 0 0 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
}

function useSweep(target: number, ms = 1600) {
  const [v, setV] = useState(0);
  const from = useRef(0);
  useEffect(() => {
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce) { setV(target); from.current = target; return; }
    const start = performance.now(), a = from.current;
    let raf = 0;
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / ms);
      const e = 1 - Math.pow(1 - k, 3) + Math.sin(k * Math.PI) * 0.06 * (1 - k);   // ease out with a small overshoot
      const cur = a + (target - a) * e;
      setV(cur);
      if (k < 1) raf = requestAnimationFrame(step); else { from.current = target; setV(target); }
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}

export default function FearGreed({ value, label, change7d, history = [] }: { value: number; label: string; change7d?: number | null; history?: Point[] }) {
  const v = useSweep(value);
  const z = zoneOf(value);
  const marker = pt(Math.max(0, Math.min(100, v)));
  const hist = history.slice(-30);
  const yday = hist.length > 1 ? hist[hist.length - 2].value : null;
  const week = hist.length > 7 ? hist[hist.length - 8].value : null;
  const vals = hist.map((p) => p.value);
  const hi = vals.length ? Math.max(...vals) : null, lo = vals.length ? Math.min(...vals) : null;

  // sparkline
  const W = 260, H = 54;
  const line = hist.map((p, i) => `${(i / Math.max(1, hist.length - 1)) * W},${H - 4 - (p.value / 100) * (H - 8)}`).join(" ");
  const [drawn, setDrawn] = useState(false);
  useEffect(() => { const id = requestAnimationFrame(() => setDrawn(true)); return () => cancelAnimationFrame(id); }, []);

  return (
    <div>
      <div className="relative mx-auto w-full max-w-[280px]">
        <svg viewBox="0 0 240 132" className="w-full" role="img" aria-label={`Fear and Greed index ${value}, ${label}`}>
          <defs>
            <filter id="fg-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="3" /></filter>
          </defs>
          <path d={arc(0, 100)} stroke="rgb(var(--glass) / 0.08)" strokeWidth="18" fill="none" strokeLinecap="round" />
          {ZONES.map((zz, i) => {
            const a = i === 0 ? 0 : ZONES[i - 1].to;
            return <path key={zz.name} d={arc(a + 0.8, zz.to - 0.8)} stroke={zz.color} strokeWidth="14" fill="none" opacity={zz === z ? 1 : 0.35} />;
          })}
          {/* filled progress glow up to the current value */}
          <path d={arc(0.5, Math.max(1, v))} stroke={z.color} strokeWidth="4" fill="none" strokeLinecap="round" filter="url(#fg-glow)" opacity="0.8" transform={`translate(0 0)`} />
          {[0, 25, 50, 75, 100].map((t) => { const [x, y] = pt(t, R + 15); return <text key={t} x={x} y={y + 3} textAnchor="middle" fontSize="9" fill="rgb(var(--mute))">{t}</text>; })}
          {yday != null && (() => { const [x, y] = pt(yday, R + 1); return <circle cx={x} cy={y} r="3.2" fill="rgb(var(--ink))" stroke="rgb(var(--text))" strokeWidth="1.5"><title>Yesterday: {yday}</title></circle>; })()}
          <text x={CX} y={CY - 18} textAnchor="middle" fontSize="40" fontWeight="700" fill={z.color} style={{ fontVariantNumeric: "tabular-nums" }}>{Math.round(v)}</text>
          <text x={CX} y={CY - 2} textAnchor="middle" fontSize="10" fill="rgb(var(--mute))">out of 100</text>
          {/* marker riding on the arc */}
          <circle cx={marker[0]} cy={marker[1]} r="11" fill={z.color} opacity="0.35" filter="url(#fg-glow)" />
          <circle cx={marker[0]} cy={marker[1]} r="8" fill="rgb(var(--ink))" stroke={z.color} strokeWidth="3" />
          <circle cx={marker[0]} cy={marker[1]} r="3" fill={z.color} />
        </svg>
      </div>
      <div className="mt-2 text-center">
        <div className="text-base font-semibold" style={{ color: z.color }}>{label}</div>
        {change7d != null && <div className="text-xs text-mute"><span className={change7d > 0 ? "text-bull" : change7d < 0 ? "text-bear" : ""}>{change7d > 0 ? "▲ +" : change7d < 0 ? "▼ " : ""}{change7d}</span> over 7 days</div>}
      </div>

      <div className="mt-3 grid grid-cols-4 gap-1.5 text-center text-xs">
        {([["Now", value], ["Yesterday", yday], ["Last week", week], ["30d range", lo != null && hi != null ? `${lo}–${hi}` : null]] as const).map(([k, x]) => (
          <div key={k} className="rounded-lg bg-glass/[0.04] px-1 py-1.5">
            <div className="text-[10px] text-mute">{k}</div>
            <div className="num font-semibold" style={typeof x === "number" ? { color: zoneOf(x).color } : undefined}>{x ?? "—"}</div>
          </div>
        ))}
      </div>

      {hist.length > 2 && (
        <div className="mt-3">
          <div className="mb-1 flex justify-between text-[10px] text-mute"><span>30 days ago</span><span>today</span></div>
          <svg viewBox={`0 0 ${W} ${H}`} className="h-14 w-full" preserveAspectRatio="none" aria-hidden="true">
            <rect x="0" y={H - 4 - 0.45 * (H - 8)} width={W} height={0.1 * (H - 8)} fill="rgb(var(--glass) / 0.05)" />
            <polyline points={line} fill="none" stroke={z.color} strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke"
              pathLength={1} strokeDasharray="1" strokeDashoffset={drawn ? 0 : 1} style={{ transition: "stroke-dashoffset 1.6s ease-out" }} />
          </svg>
        </div>
      )}
    </div>
  );
}
