// Admin share image of the 15m scalping scorecard (views/scalping), drawn in the browser with the same kit as the
// Weekly report / Achievements images (lib/cardCanvas.ts: black + gold, logo, glowing hero number). Clearly labelled
// as demo results, not public signals, before fees. Nothing is uploaded or posted: the admin downloads the PNG.
// Owner request 2 Nov 2026: every figure is the trade's plain price return (no leverage / ROI on margin).
import { backdrop, C, fontsReady, footer, glowText, header, M, panel, text, wrap, font } from "./cardCanvas";
import { isNum } from "./format";

const sp = (v: unknown, d = 1) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "—");
const rate = (v: unknown) => (isNum(v) ? `${Math.round(v * 100)}%` : "—");
export const scalpDate = (ms: unknown) => (isNum(ms) ? new Date(ms).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }) : "—");
export const holdText = (min: unknown) => (!isNum(min) ? "—" : min < 90 ? `${Math.round(min)} min` : `${(min / 60).toFixed(1)} h`);
export const scalpTitle = (since: unknown) => `Demo results - 15m scalping - since ${scalpDate(since)}`;

/** Draws the 1080 x 1080 scorecard onto `cv`. */
export async function drawScalpCard(cv: HTMLCanvasElement, v: any) {
  const W = 1080, H = 1080;
  cv.width = W; cv.height = H;
  const g = cv.getContext("2d")!;
  await fontsReady();
  backdrop(g, W, H);
  let y = await header(g, scalpTitle(v.since)) + 36;
  const s = v.summary ?? {};
  const head = s.total_return_pct;
  const up = (head ?? 0) >= 0;
  const col = up ? C.bull : C.bear;

  // hero: total return of every closed scalping call (sum of the trades' price returns, equal size)
  const hh = 232;
  panel(g, M, y, W - 2 * M, hh, { r: 32, stroke: up ? "rgba(14,203,129,0.45)" : "rgba(246,70,93,0.45)", fill: up ? "rgba(14,203,129,0.06)" : "rgba(246,70,93,0.06)" });
  text(g, "TOTAL RETURN · ALL CLOSED CALLS", W / 2, y + 48, { weight: 800, px: 22, color: C.gold, align: "center" });
  glowText(g, sp(head, 2), W / 2, y + 160, col, { weight: 800, px: 112, align: "center", maxW: W - 2 * M - 64, blur: 44 });
  const rb = v.backfill && v.counts?.rebuilt ? ` · ${v.split?.rebuilt?.closed ?? 0} rebuilt (1-2 Nov)` : "";
  text(g, `avg ${sp(s.avg_return_pct, 2)} per call · ${s.closed ?? 0} closed calls${rb}, wins and losses, before fees`,
    W / 2, y + hh - 28, { weight: 500, px: 20, color: C.mute, align: "center", maxW: W - 2 * M - 48 });
  y += hh + 24;

  // two rows of three tiles
  const st = s.streak ?? {};
  const tiles: [string, string, string][] = [
    ["WIN RATE", rate(s.win_rate), C.text],
    ["WINS · LOSSES", `${s.wins ?? 0} · ${s.losses ?? 0}`, C.text],
    ["PROFIT FACTOR", isNum(s.profit_factor) ? s.profit_factor.toFixed(2) : (s.closed ? "no loss yet" : "—"), C.text],
    ["TP1 · TP2 · TP3", s.hit_rates ? `${rate(s.hit_rates.tp1)} · ${rate(s.hit_rates.tp2)} · ${rate(s.hit_rates.tp3)}` : "—", C.text],
    ["MAX DRAWDOWN", isNum(s.max_drawdown_pct) ? `-${s.max_drawdown_pct.toFixed(2)}%` : "—", C.bear],
    ["STREAK · AVG HOLD", `${st.n ? `${st.n} ${st.kind === "win" ? "W" : "L"}` : "—"} · ${holdText(s.avg_hold_min)}`, C.text],
  ];
  const kw = (W - 2 * M - 2 * 24) / 3, kh = 112;
  tiles.forEach(([k, val, c], i) => {
    const x = M + (i % 3) * (kw + 24), ty = y + Math.floor(i / 3) * (kh + 20);
    panel(g, x, ty, kw, kh, { r: 24 });
    text(g, k, x + kw / 2, ty + 38, { weight: 700, px: 17, color: C.mute, align: "center", maxW: kw - 32 });
    text(g, val, x + kw / 2, ty + kh - 24, { weight: 800, px: 40, color: c, align: "center", maxW: kw - 36, minPx: 18 });
  });
  y += 2 * kh + 20 + 24;

  // cumulative return of every closed call (equal size), zero line dashed
  const pts: any[] = v.curve ?? [];
  const ch = 132;
  panel(g, M, y, W - 2 * M, ch, { r: 24 });
  text(g, "CUMULATIVE RETURN", M + 24, y + 34, { weight: 700, px: 16, color: C.mute });
  if (pts.length > 1) {
    const val = (p: any) => p.cum_return_pct;
    const ys = pts.map(val), lo = Math.min(0, ...ys), hi = Math.max(0, ...ys);
    const x0 = M + 24, x1 = W - M - 24, top = y + 48, bot = y + ch - 18;
    const px = (i: number) => x0 + (i / (pts.length - 1)) * (x1 - x0), py = (q: number) => bot - ((q - lo) / (hi - lo || 1)) * (bot - top);
    g.save();
    g.setLineDash([6, 6]); g.strokeStyle = "rgba(255,255,255,0.18)"; g.lineWidth = 1.5;
    g.beginPath(); g.moveTo(x0, py(0)); g.lineTo(x1, py(0)); g.stroke(); g.setLineDash([]);
    g.strokeStyle = col; g.lineWidth = 4; g.lineJoin = "round"; g.shadowColor = col; g.shadowBlur = 14;
    g.beginPath(); pts.forEach((p, i) => (i ? g.lineTo(px(i), py(val(p))) : g.moveTo(px(i), py(val(p))))); g.stroke();
    g.restore();
  }
  y += ch + 40;

  const b = v.bot;
  if (b && isNum(b.return_pct)) {
    text(g, `15m demo bot · virtual money, fees included · equity ${sp(b.return_pct, 1)} · ${b.trades ?? 0} trades · win rate ${rate(b.win_rate)}`,
      W / 2, y + 8, { weight: 600, px: 21, color: C.text, align: "center", maxW: W - 2 * M });
  }
  g.font = font(500, 17);
  footer(g, W, H - 152, "Demo · not public signals · before fees",
    wrap(g, `15m grade-A calls, track record rules (50/25/25). Return = price return, no leverage.${v.backfill ? " 1-2 Nov rebuilt by replay, then logged live." : ""} Past results don't guarantee future results.`, W - 2 * M, 2));
}
