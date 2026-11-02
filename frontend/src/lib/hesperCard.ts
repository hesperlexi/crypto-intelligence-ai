// Admin share image of Road to Rich (views/hesper), drawn in the browser with the share-card kit (lib/cardCanvas.ts:
// black + gold, logo, glowing hero number). Nothing is uploaded or posted: the admin downloads the PNG.
import { backdrop, C, fontsReady, footer, glowText, header, M, panel, text } from "./cardCanvas";
import { isNum } from "./format";

export const usd = (v: unknown, d = 2) => (isNum(v) ? `$${v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })}` : "—");

/** Share of the way from the start ($100) to the goal ($1,000), 0..1. */
export const progressOf = (bal: unknown, start = 100, goal = 1000) => (isNum(bal) ? Math.max(0, Math.min(1, (bal - start) / (goal - start))) : 0);

/** Draws the 1080 x 1080 card onto `cv`. `balance` = the live balance shown on the page. */
export async function drawHesperCard(cv: HTMLCanvasElement, v: any, balance: number | null) {
  const W = 1080, H = 1080;
  cv.width = W; cv.height = H;
  const g = cv.getContext("2d")!;
  await fontsReady();
  backdrop(g, W, H);
  const cur = v.current ?? {};
  const sc = v.score ?? {};
  const goal = v.goal ?? 1000, start = v.start ?? 100;
  let y = await header(g, `Road to Rich · Hesper · run #${cur.run ?? "—"}`) + 40;

  // hero: the run's balance and the way to $1,000
  const bal = isNum(balance) ? balance : cur.balance;
  const up = (bal ?? start) >= start;
  const hh = 300;
  panel(g, M, y, W - 2 * M, hh, { r: 32, stroke: "rgba(240,185,11,0.5)", fill: "rgba(240,185,11,0.05)" });
  text(g, `RUN #${cur.run ?? "—"} · BALANCE`, W / 2, y + 52, { weight: 800, px: 22, color: C.gold, align: "center" });
  glowText(g, usd(bal), W / 2, y + 170, up ? C.gold : C.bear, { weight: 800, px: 120, align: "center", maxW: W - 2 * M - 64, blur: 44 });
  const bx = M + 48, bw = W - 2 * M - 96, by = y + 214, bh = 18;
  g.fillStyle = "rgba(255,255,255,0.08)"; g.beginPath(); g.roundRect(bx, by, bw, bh, bh / 2); g.fill();
  const p = progressOf(bal, start, goal);
  if (p > 0) {
    const gr = g.createLinearGradient(bx, 0, bx + bw, 0);
    gr.addColorStop(0, "#c7a040"); gr.addColorStop(1, C.gold);
    g.save(); g.shadowColor = C.gold; g.shadowBlur = 18; g.fillStyle = gr;
    g.beginPath(); g.roundRect(bx, by, Math.max(bh, bw * p), bh, bh / 2); g.fill(); g.restore();
  }
  text(g, usd(start, 0), bx, by + 52, { weight: 600, px: 20, color: C.mute });
  text(g, `${Math.round(p * 100)}% of the way`, W / 2, by + 52, { weight: 700, px: 20, color: C.text, align: "center" });
  text(g, usd(goal, 0), bx + bw, by + 52, { weight: 600, px: 20, color: C.mute, align: "right" });
  y += hh + 32;

  // scoreboard
  const tiles: [string, string, string][] = [
    ["SUCCESSES", String(sc.successes ?? 0), C.bull],
    ["FAILURES", String(sc.failures ?? 0), C.bear],
    ["RUNS", String(sc.runs ?? 0), C.text],
    ["BEST PEAK", usd(sc.best_peak?.peak ?? sc.all_time_peak, 0), C.gold],
  ];
  const kw = (W - 2 * M - 3 * 20) / 4, kh = 132;
  tiles.forEach(([k, val, c], i) => {
    const x = M + i * (kw + 20);
    panel(g, x, y, kw, kh, { r: 24 });
    text(g, k, x + kw / 2, y + 42, { weight: 700, px: 17, color: C.mute, align: "center", maxW: kw - 24 });
    text(g, val, x + kw / 2, y + kh - 30, { weight: 800, px: 48, color: c, align: "center", maxW: kw - 28, minPx: 20 });
  });
  y += kh + 32;

  // the run's balance curve
  const pts: number[][] = (v.curves ?? {})[String(cur.run)] ?? [];
  const series = isNum(bal) ? [...pts.map((q) => q[1]), bal] : pts.map((q) => q[1]);
  const ch = 196;
  panel(g, M, y, W - 2 * M, ch, { r: 24 });
  text(g, "THIS RUN", M + 24, y + 36, { weight: 700, px: 16, color: C.mute });
  if (series.length > 1) {
    const L = (q: number) => Math.log10(Math.max(1, q));          // log scale, as the page
    const hi = Math.max(L(goal) + 0.12, ...series.map(L)), lo = Math.min(L(start) - 0.6, ...series.map(L)) - 0.05;
    const x0 = M + 24, x1 = W - M - 24, top = y + 52, bot = y + ch - 20;
    const px = (i: number) => x0 + (i / (series.length - 1)) * (x1 - x0), py = (q: number) => bot - ((L(q) - lo) / (hi - lo || 1)) * (bot - top);
    g.save();
    g.setLineDash([6, 6]); g.lineWidth = 1.5;
    g.strokeStyle = "rgba(240,185,11,0.45)"; g.beginPath(); g.moveTo(x0, py(goal)); g.lineTo(x1, py(goal)); g.stroke();
    g.strokeStyle = "rgba(255,255,255,0.18)"; g.beginPath(); g.moveTo(x0, py(start)); g.lineTo(x1, py(start)); g.stroke();
    g.setLineDash([]);
    g.strokeStyle = C.gold; g.lineWidth = 4; g.lineJoin = "round"; g.shadowColor = C.gold; g.shadowBlur = 14;
    g.beginPath(); series.forEach((q, i) => (i ? g.lineTo(px(i), py(q)) : g.moveTo(px(i), py(q)))); g.stroke();
    g.restore();
  }
  footer(g, W, H - 152, "Demo · virtual money · not financial advice",
    ["All-in demo bot on the app's public grade-A calls. Virtual money only - no real orders.", "Past results don't guarantee future results."]);
}
