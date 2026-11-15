import { ColorType, createChart } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { chartColors, themeColor, useAppearance } from "../lib/appearance";

export interface Series {
  name: string;
  color: string;
  points: { ts: number; value: number }[];
  dashed?: boolean;
  /** v2.41: draw as a profit / loss line - green with a green glow fill above this value, red below */
  baseline?: number;
}

/** Multi-line time-series chart (equity curves, replay paths). A text legend is rendered next to it. */
export default function LineChart({ series, height = 260, percent = false }: { series: Series[]; height?: number; percent?: boolean }) {
  const el = useRef<HTMLDivElement>(null);
  const { resolved } = useAppearance();

  useEffect(() => {
    if (!el.current) return;
    const cc = chartColors();
    const chart = createChart(el.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: cc.text, fontSize: 11 },
      grid: { vertLines: { color: cc.grid }, horzLines: { color: cc.grid } },
      rightPriceScale: { borderColor: cc.border },
      timeScale: { borderColor: cc.border, timeVisible: true, secondsVisible: false },
    });
    for (const s of series) {
      const seen = new Set<number>();
      const data = s.points
        .map((p) => ({ time: Math.floor(p.ts / 1000) as any, value: p.value }))
        .filter((p) => Number.isFinite(p.value) && !seen.has(p.time) && seen.add(p.time));
      if (!data.length) continue;
      if (s.baseline != null) {
        const pf = percent ? { type: "percent" as const } : { type: "price" as const, precision: 2, minMove: 0.01 };
        const up = (a: number) => themeColor("--bull", a), dn = (a: number) => themeColor("--bear", a);
        const base = chart.addBaselineSeries({
          baseValue: { type: "price", price: s.baseline }, lineWidth: 3, priceLineVisible: false, title: s.name,
          topLineColor: up(1), topFillColor1: up(0.32), topFillColor2: up(0.02),
          bottomLineColor: dn(1), bottomFillColor1: dn(0.02), bottomFillColor2: dn(0.32),
          crosshairMarkerRadius: 5, priceFormat: pf, lastValueVisible: true,
        });
        base.setData(data);
        base.createPriceLine({ price: s.baseline, color: themeColor("--mute", 0.6), lineWidth: 1, lineStyle: 2,
          axisLabelVisible: false, title: "start" });
        const last = data[data.length - 1];
        base.setMarkers([{ time: last.time, position: "inBar", shape: "circle", size: 1,
          color: last.value >= s.baseline ? up(1) : dn(1) }]);
        continue;
      }
      const line = chart.addLineSeries({
        color: themeColor(s.color), lineWidth: 2, lineStyle: s.dashed ? 2 : 0, priceLineVisible: false, title: s.name,
        priceFormat: percent ? { type: "percent" } : { type: "price", precision: 2, minMove: 0.01 },
      });
      line.setData(data);
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [series, percent, resolved]);

  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {series.map((s) => (
          <span key={s.name} className="inline-flex items-center gap-1.5 text-mute">
            <span className="inline-block h-0.5 w-4" style={{ background: s.baseline != null ? "linear-gradient(90deg, rgb(var(--bear)), rgb(var(--bull)))" : s.color.startsWith("--") ? `rgb(var(${s.color}))` : s.color }} />
            {s.name}
          </span>
        ))}
      </div>
      <div ref={el} style={{ height }} className="w-full" />
    </div>
  );
}
