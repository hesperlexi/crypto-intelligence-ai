// VRVP - Visible Range Volume Profile (owner, 14 Nov 2026). Drawn by the browser on our own candle chart from the candles
// already loaded: no request, no engine work, no Firestore reads or writes.
// For the candles on screen: price range split into BINS rows; each candle's volume is spread over the rows its high-low
// range covers (a candle-level approximation - real VRVP uses trades). POC = the row with the most volume; the value area
// is the 70 % of volume around the POC (VAH / VAL). Bars grow from the right edge; up / down volume shown in two tones.
import type { IChartApi, ISeriesApi, ISeriesPrimitive, ISeriesPrimitivePaneRenderer, ISeriesPrimitivePaneView, SeriesAttachedParameter, Time } from "lightweight-charts";
import { themeColor } from "./appearance";

export type VCandle = [number, number, number, number, number, number];   // ts, o, h, l, c, v

export const BINS = 48;
export const VALUE_AREA = 0.7;

export interface Profile {
  lo: number; hi: number; step: number;
  up: number[]; down: number[]; total: number[];
  poc: number; vah: number; val: number;     // prices (POC = middle of its row; VAH / VAL = row edges)
  max: number;
}

/** Profile of `candles` (pure: unit-testable). null when there is no range or no volume. */
export function profile(candles: VCandle[], bins = BINS, area = VALUE_AREA): Profile | null {
  if (!candles.length) return null;
  let lo = Infinity, hi = -Infinity;
  for (const c of candles) { if (c[3] < lo) lo = c[3]; if (c[2] > hi) hi = c[2]; }
  if (!(hi > lo)) return null;
  const step = (hi - lo) / bins;
  const up = new Array(bins).fill(0), down = new Array(bins).fill(0);
  for (const [, o, h, l, c, v] of candles) {
    if (!(v > 0)) continue;
    const a = Math.max(0, Math.floor((l - lo) / step)), b = Math.min(bins - 1, Math.floor((h - lo) / step));
    const span = Math.max(h - l, step * 1e-9);
    for (let i = a; i <= b; i++) {
      const top = lo + (i + 1) * step, bot = lo + i * step;
      const share = h === l ? 1 / (b - a + 1) : (Math.min(h, top) - Math.max(l, bot)) / span;
      if (share <= 0) continue;
      (c >= o ? up : down)[i] += v * share;
    }
  }
  const total = up.map((u, i) => u + down[i]);
  const sum = total.reduce((s, x) => s + x, 0);
  if (!(sum > 0)) return null;
  let p = 0;
  total.forEach((x, i) => { if (x > total[p]) p = i; });
  // value area: grow from the POC towards the larger neighbour until 70 % of the volume is inside
  let a = p, b = p, inside = total[p];
  while (inside < area * sum && (a > 0 || b < bins - 1)) {
    const below = a > 0 ? total[a - 1] : -1, above = b < bins - 1 ? total[b + 1] : -1;
    if (above >= below) inside += total[++b]; else inside += total[--a];
  }
  return { lo, hi, step, up, down, total, poc: lo + (p + 0.5) * step, vah: lo + (b + 1) * step, val: lo + a * step, max: total[p] };
}

class Renderer implements ISeriesPrimitivePaneRenderer {
  constructor(private src: VolumeProfilePrimitive) {}
  draw(target: any) {
    const pr = this.src.prof, series = this.src.series;
    if (!pr || !series) return;
    target.useBitmapCoordinateSpace((scope: any) => {
      const ctx: CanvasRenderingContext2D = scope.context;
      const hr = scope.horizontalPixelRatio, vr = scope.verticalPixelRatio;
      const W = scope.bitmapSize.width;
      const maxW = W * 0.26;
      const upC = themeColor("--bull", 0.32), dnC = themeColor("--bear", 0.32);
      const upA = themeColor("--bull", 0.5), dnA = themeColor("--bear", 0.5);
      for (let i = 0; i < pr.total.length; i++) {
        if (!pr.total[i]) continue;
        const y1 = series.priceToCoordinate(pr.lo + (i + 1) * pr.step), y2 = series.priceToCoordinate(pr.lo + i * pr.step);
        if (y1 == null || y2 == null) continue;
        const top = Math.round(Math.min(y1, y2) * vr) + 1, h = Math.max(1, Math.round(Math.abs(y2 - y1) * vr) - 1);
        const inVA = pr.lo + (i + 0.5) * pr.step >= pr.val && pr.lo + (i + 0.5) * pr.step <= pr.vah;
        const wu = (pr.up[i] / pr.max) * maxW, wd = (pr.down[i] / pr.max) * maxW;
        ctx.fillStyle = inVA ? upA : upC;
        ctx.fillRect(W - wu - wd, top, wu, h);
        ctx.fillStyle = inVA ? dnA : dnC;
        ctx.fillRect(W - wd, top, wd, h);
      }
      const line = (price: number, color: string, dash: number[]) => {
        const y = series.priceToCoordinate(price);
        if (y == null) return;
        ctx.save();
        ctx.strokeStyle = color;
        ctx.lineWidth = Math.max(1, Math.round(hr));
        ctx.setLineDash(dash.map((d) => d * hr));
        ctx.beginPath();
        ctx.moveTo(0, Math.round(y * vr) + 0.5);
        ctx.lineTo(W, Math.round(y * vr) + 0.5);
        ctx.stroke();
        ctx.restore();
      };
      line(pr.poc, themeColor("--accent", 0.9), []);
      line(pr.vah, themeColor("--mute", 0.7), [4, 4]);
      line(pr.val, themeColor("--mute", 0.7), [4, 4]);
    });
  }
}

class PaneView implements ISeriesPrimitivePaneView {
  private r: Renderer;
  constructor(src: VolumeProfilePrimitive) { this.r = new Renderer(src); }
  zOrder() { return "bottom" as const; }
  renderer() { return this.r; }
}

/** Attach to the candle series; call `setData` with the same candles (time order) that the series shows. */
export class VolumeProfilePrimitive implements ISeriesPrimitive<Time> {
  prof: Profile | null = null;
  series: ISeriesApi<"Candlestick"> | null = null;
  private chart: IChartApi | null = null;
  private data: VCandle[] = [];
  private views = [new PaneView(this)];
  private request: (() => void) | null = null;
  private onRange = () => { this.compute(); this.request?.(); };
  onChange?: (p: Profile | null) => void;

  attached(p: SeriesAttachedParameter<Time>) {
    this.chart = p.chart as unknown as IChartApi;
    this.series = p.series as ISeriesApi<"Candlestick">;
    this.request = p.requestUpdate;
    this.chart.timeScale().subscribeVisibleLogicalRangeChange(this.onRange);
    this.compute();
  }
  detached() {
    this.chart?.timeScale().unsubscribeVisibleLogicalRangeChange(this.onRange);
    this.chart = null; this.series = null; this.request = null;
  }
  setData(d: VCandle[]) { this.data = d; this.compute(); this.request?.(); }
  paneViews() { return this.views; }
  private compute() {
    const r = this.chart?.timeScale().getVisibleLogicalRange();
    if (!r || !this.data.length) { this.prof = null; return; }
    const a = Math.max(0, Math.floor(r.from)), b = Math.min(this.data.length - 1, Math.ceil(r.to));
    this.prof = b >= a ? profile(this.data.slice(a, b + 1)) : null;
    this.onChange?.(this.prof);
  }
}
