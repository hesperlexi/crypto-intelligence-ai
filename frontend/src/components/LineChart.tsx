import { ColorType, createChart } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { chartColors, useAppearance } from "../lib/appearance";

export interface Series {
  name: string;
  color: string;
  points: { ts: number; value: number }[];
  dashed?: boolean;
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
      const line = chart.addLineSeries({
        color: s.color, lineWidth: 2, lineStyle: s.dashed ? 2 : 0, priceLineVisible: false, title: s.name,
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
            <span className="inline-block h-0.5 w-4" style={{ background: s.color }} />
            {s.name}
          </span>
        ))}
      </div>
      <div ref={el} style={{ height }} className="w-full" />
    </div>
  );
}
