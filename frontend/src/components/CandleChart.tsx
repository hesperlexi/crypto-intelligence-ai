import { ColorType, createChart, CrosshairMode, IChartApi, ISeriesApi, LineStyle } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { chartColors, useAppearance } from "../lib/appearance";
import { isNum, pricePrecision } from "../lib/format";

export type Candle = [number, number, number, number, number, number]; // ts(ms), o, h, l, c, v

export interface PriceLine {
  price: number;
  title: string;
  color: string;
  dashed?: boolean;
}

export interface Marker {
  ts: number;
  text: string;
  up: boolean;
}

export const OVERLAY_COLORS: Record<string, string> = {
  ema_9: "#e8b339",
  ema_21: "#5aa0ff",
  ema_50: "#c084fc",
  ema_200: "#f97316",
  vwap: "#22d3ee",
  bb_upper: "#64748b",
  bb_mid: "#475569",
  bb_lower: "#64748b",
};

interface Props {
  candles: Candle[];
  overlays?: Record<string, (number | null)[]> | null;
  show?: string[];
  lines?: PriceLine[];
  markers?: Marker[];
  livePrice?: number | null;
  /** the forming candle from a live stream: updated in place, and appended when a new period starts */
  liveCandle?: Candle | null;
  height?: number;
  /** extra candles drawn dimmed after `candles` (used by Replay to reveal the future) */
  future?: Candle[];
  /** remembers the zoom / scroll under this key (e.g. symbol + timeframe), also across reloads in this tab */
  viewKey?: string;
}

const t = (ms: number) => Math.floor(ms / 1000) as any;
const NONE: Candle[] = [];
const NO_KEYS: string[] = [];

// Zoom is stored relative to the newest candle, so a remembered view keeps following new candles.
type View = { from: number; to: number };
const views = new Map<string, View>();
function loadView(key?: string): View | null {
  if (!key) return null;
  if (views.has(key)) return views.get(key)!;
  try { const v = JSON.parse(sessionStorage.getItem("cia-chart-view:" + key) ?? "null"); if (v && isNum(v.from) && isNum(v.to)) return v; } catch { /* ignore */ }
  return null;
}
function saveView(key: string | undefined, v: View) {
  if (!key) return;
  views.set(key, v);
  try { sessionStorage.setItem("cia-chart-view:" + key, JSON.stringify(v)); } catch { /* ignore */ }
}

export default function CandleChart({ candles, overlays, show = NO_KEYS, lines = [], markers = [], livePrice, liveCandle = null, height = 460, future = NONE, viewKey }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const lastRef = useRef<Candle | null>(null);
  const countRef = useRef(0);                 // number of bars on the chart (to keep zoom relative to the newest)
  const keyRef = useRef(viewKey);
  keyRef.current = viewKey;
  const priceLinesRef = useRef<any[]>([]);
  // candles that arrived live after `candles` was loaded; kept so a rebuild (new lines, theme) does not drop them
  const tailRef = useRef<Map<number, Candle>>(new Map());
  const histRef = useRef<Candle[] | null>(null);
  if (histRef.current !== candles) { histRef.current = candles; tailRef.current = new Map(); }
  const { resolved } = useAppearance();
  const [ready, setReady] = useState(0);        // bumps after each (re)build so lines and markers are redrawn

  useEffect(() => {
    if (!el.current || !candles.length) return;
    const cc = chartColors();
    const chart = createChart(el.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: cc.text, fontSize: 11 },
      grid: { vertLines: { color: cc.grid }, horzLines: { color: cc.grid } },
      rightPriceScale: { borderColor: cc.border },
      timeScale: { borderColor: cc.border, timeVisible: true, secondsVisible: false },
      crosshair: { mode: CrosshairMode.Normal },
    });
    chartRef.current = chart;
    const last = candles[candles.length - 1];
    const precision = pricePrecision(last[4]);
    const priceFormat = { type: "price" as const, precision, minMove: 1 / 10 ** precision };
    const series = chart.addCandlestickSeries({
      upColor: "#0ecb81", downColor: "#f6465d", wickUpColor: "#0ecb81", wickDownColor: "#f6465d", borderVisible: false, priceFormat,
    });
    const all = tailRef.current.size ? (() => {
      const m = new Map<number, Candle>(candles.map((c) => [c[0], c]));
      tailRef.current.forEach((c, k) => m.set(k, c));
      return [...m.values()].sort((a, b) => a[0] - b[0]);
    })() : candles;
    series.setData(all.map((c) => ({ time: t(c[0]), open: c[1], high: c[2], low: c[3], close: c[4] })));
    seriesRef.current = series;
    lastRef.current = [...all[all.length - 1]] as Candle;
    countRef.current = all.length;

    if (future.length) {
      const fs = chart.addCandlestickSeries({
        upColor: "rgba(14,203,129,0.35)", downColor: "rgba(246,70,93,0.35)", wickUpColor: "rgba(14,203,129,0.35)",
        wickDownColor: "rgba(246,70,93,0.35)", borderVisible: false, priceFormat, priceLineVisible: false, lastValueVisible: false,
      });
      fs.setData(future.map((c) => ({ time: t(c[0]), open: c[1], high: c[2], low: c[3], close: c[4] })));
    }

    const volume = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "", priceLineVisible: false, lastValueVisible: false });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.86, bottom: 0 } });
    volume.setData(candles.map((c) => ({ time: t(c[0]), value: c[5], color: c[4] >= c[1] ? "rgba(14,203,129,0.3)" : "rgba(246,70,93,0.3)" })));

    if (overlays?.ts) {
      const first = candles[0][0];
      for (const key of show) {
        const vals = overlays[key];
        if (!vals) continue;
        const data: { time: any; value: number }[] = [];
        overlays.ts.forEach((ts, i) => {
          const v = vals[i];
          if (isNum(ts) && ts >= first && isNum(v)) data.push({ time: t(ts), value: v });
        });
        const line = chart.addLineSeries({
          color: OVERLAY_COLORS[key] ?? "#94a3b8", lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
          crosshairMarkerVisible: false, lineStyle: key.startsWith("bb_") ? LineStyle.Dotted : LineStyle.Solid, priceFormat,
        });
        line.setData(data);
      }
    }
    // restore the last zoom for this chart (or show everything the first time)
    const v = loadView(keyRef.current);
    if (v) chart.timeScale().setVisibleLogicalRange({ from: countRef.current - 1 + v.from, to: countRef.current - 1 + v.to } as any);
    else chart.timeScale().fitContent();
    const onRange = (r: any) => { if (r && countRef.current) saveView(keyRef.current, { from: r.from - (countRef.current - 1), to: r.to - (countRef.current - 1) }); };
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRange);
    setReady((n) => n + 1);
    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRange);
      seriesRef.current = null;
      chartRef.current = null;
      priceLinesRef.current = [];
      chart.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candles, overlays, show.join(","), future, resolved]);

  // entry / SL / TP / liquidation lines change without rebuilding the chart (so zoom and scroll stay put)
  const linesKey = JSON.stringify(lines.filter((l) => isNum(l.price)).map((l) => [+l.price.toPrecision(8), l.title, l.color, !!l.dashed]));
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    for (const pl of priceLinesRef.current) { try { series.removePriceLine(pl); } catch { /* ignore */ } }
    priceLinesRef.current = lines.filter((l) => isNum(l.price)).map((l) =>
      series.createPriceLine({ price: l.price, color: l.color, lineWidth: 1, lineStyle: l.dashed ? LineStyle.Dashed : LineStyle.Solid, axisLabelVisible: true, title: l.title }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linesKey, ready]);

  const markersKey = JSON.stringify(markers);
  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !candles.length) return;
    const first = candles[0][0];
    series.setMarkers(markers
      .filter((m) => m.ts >= first)
      .sort((a, b) => a.ts - b.ts)
      .map((m) => ({
        time: t(m.ts), position: (m.up ? "belowBar" : "aboveBar") as "belowBar" | "aboveBar", color: m.up ? "#0ecb81" : "#f6465d",
        shape: (m.up ? "arrowUp" : "arrowDown") as "arrowUp" | "arrowDown", text: m.text,
      })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [markersKey, ready]);

  // live stream: update or append the forming candle without rebuilding the chart
  useEffect(() => {
    const s = seriesRef.current;
    if (!s || !liveCandle || future.length) return;
    const c = liveCandle;
    if (lastRef.current && c[0] < lastRef.current[0]) return;
    const fresh = !lastRef.current || c[0] > lastRef.current[0];
    tailRef.current.set(c[0], [...c] as Candle);
    lastRef.current = [...c] as Candle;
    if (fresh) countRef.current += 1;
    s.update({ time: t(c[0]), open: c[1], high: c[2], low: c[3], close: c[4] });
  }, [liveCandle, future.length]);

  // live tick: move the forming candle without rebuilding the chart
  useEffect(() => {
    if (liveCandle) return;
    const s = seriesRef.current;
    const last = lastRef.current;
    if (!s || !last || !isNum(livePrice) || future.length) return;
    last[4] = livePrice;
    last[2] = Math.max(last[2], livePrice);
    last[3] = Math.min(last[3], livePrice);
    s.update({ time: t(last[0]), open: last[1], high: last[2], low: last[3], close: last[4] });
  }, [livePrice, future.length]);

  if (!candles.length) return <div className="flex items-center justify-center text-sm text-mute" style={{ height }}>No candles stored for this series yet</div>;
  return <div ref={el} style={{ height }} className="w-full" aria-label="Candlestick chart (times in UTC)" role="img" />;
}
