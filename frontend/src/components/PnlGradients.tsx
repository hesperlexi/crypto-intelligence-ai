// v2.41 (owner, 15 Nov 2026: "lively red and green lines, everywhere they apply"): shared SVG gradients that colour a
// profit / loss line green above its baseline (0 %, the start balance) and red below, with a soft matching glow fill.
// userSpaceOnUse in the chart's own viewBox units, so they also work with preserveAspectRatio="none". No SVG filters
// (cheap on phones, v2.39).
export function PnlGradients({ id, y0, top, bottom, fill = 0.3 }: { id: string; y0: number; top: number; bottom: number; fill?: number }) {
  const f = Math.max(0, Math.min(1, (y0 - top) / (bottom - top || 1)));
  return (
    <>
      <linearGradient id={`${id}-s`} gradientUnits="userSpaceOnUse" x1="0" x2="0" y1={top} y2={bottom}>
        <stop offset="0" stopColor="rgb(var(--bull))" /><stop offset={f} stopColor="rgb(var(--bull))" />
        <stop offset={f} stopColor="rgb(var(--bear))" /><stop offset="1" stopColor="rgb(var(--bear))" />
      </linearGradient>
      <linearGradient id={`${id}-f`} gradientUnits="userSpaceOnUse" x1="0" x2="0" y1={top} y2={bottom}>
        <stop offset="0" stopColor={`rgb(var(--bull) / ${fill})`} /><stop offset={f} stopColor="rgb(var(--bull) / 0.02)" />
        <stop offset={f} stopColor="rgb(var(--bear) / 0.02)" /><stop offset="1" stopColor={`rgb(var(--bear) / ${fill})`} />
      </linearGradient>
    </>
  );
}
