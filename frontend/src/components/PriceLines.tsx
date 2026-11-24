/* AI Intelligence page background (owner's pick, 24 Nov 2026: "soft price lines, let them be moving around the page").
   A few faint gold price-like lines drift slowly across the screen, at different heights and speeds. Decoration only:
   no data, no pointer events, drawn once (SVG + CSS transform), still under reduced motion. */
import { memo, useMemo } from "react";
import { createPortal } from "react-dom";

function walk(seed: number, n: number, amp: number) {
  let s = seed;
  const rnd = () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
  const half: number[] = [];
  let v = 0;
  for (let i = 0; i < n; i++) { v += (rnd() - 0.5) * amp; v *= 0.96; half.push(v); }
  return half;
}

export const PriceLines = memo(function PriceLines() {
  const lines = useMemo(() => [
    { y: 160, amp: 26, seed: 11, dur: 110, op: 0.30, w: 1.6 },
    { y: 330, amp: 34, seed: 23, dur: 150, op: 0.20, w: 1.3 },
    { y: 520, amp: 22, seed: 37, dur: 95, op: 0.26, w: 1.5, rev: true },
    { y: 690, amp: 30, seed: 51, dur: 135, op: 0.18, w: 1.2 },
    { y: 860, amp: 24, seed: 67, dur: 120, op: 0.24, w: 1.5, rev: true },
  ].map((l) => {
    // one 1600-wide period drawn twice side by side, so sliding by 1600 loops without a seam
    const n = 80, pts = walk(l.seed, n, l.amp);
    const step = 1600 / n;
    const d = [0, 1].map((rep) => pts.map((v, i) => `${i === 0 && rep === 0 ? "M" : "L"}${(rep * 1600 + i * step).toFixed(1)} ${(l.y + v * 3).toFixed(1)}`).join(" ")).join(" ")
      + ` L3200 ${(l.y + pts[0] * 3).toFixed(1)}`;
    return { ...l, d };
  }), []);
  if (typeof document === "undefined") return null;
  return createPortal(
    <div className="pl-bg" aria-hidden="true">
      <svg viewBox="0 0 3200 1000" preserveAspectRatio="none">
        {lines.map((l, i) => (
          <g key={i} className={`pl-line ${l.rev ? "pl-rev" : ""}`} style={{ animationDuration: `${l.dur}s` }}>
            <path d={l.d} fill="none" stroke="rgb(var(--accent))" strokeOpacity={l.op} strokeWidth={l.w} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
          </g>
        ))}
      </svg>
    </div>,
    document.body,
  );
});
