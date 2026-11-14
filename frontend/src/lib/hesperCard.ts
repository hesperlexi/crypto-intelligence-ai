// Admin share image of the Hesper Challenge (views/hesper), drawn in the browser with the premium kit (lib/luxCard.ts).
// Nothing is uploaded or posted: the admin downloads the PNG.
import { curveChart, figure, foil, L, luxBackground, luxBrand, luxFooter, luxReady, sora, statRow, txt } from "./luxCard";
import { isNum } from "./format";

export const usd = (v: unknown, d = 2) => (isNum(v) ? `$${v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })}` : "—");

/** Share of the way from the start ($100) to the goal ($1,000), 0..1. */
export const progressOf = (bal: unknown, start = 100, goal = 1000) => (isNum(bal) ? Math.max(0, Math.min(1, (bal - start) / (goal - start))) : 0);

/** Draws the 1080 x 1080 card onto `cv`. `balance` = the live balance shown on the page. v2.37 premium layout. */
export async function drawHesperCard(cv: HTMLCanvasElement, v: any, balance: number | null) {
  const W = 1080, H = 1080, M = 84;
  cv.width = W; cv.height = H;
  const g = cv.getContext("2d")!;
  await luxReady();
  await luxBackground(g, W, H);
  const cur = v.current ?? {};
  const sc = v.score ?? {};
  const goal = v.goal ?? 1000, start = v.start ?? 100;
  let y = await luxBrand(g, W, M, 72, "DEMO CHALLENGE");
  y += 64;
  txt(g, `Hesper Challenge  ·  run #${cur.run ?? "—"}`, M, y, { f: sora, w: 600, px: 26, color: L.soft });
  y += 36;
  txt(g, `All-in demo bot, virtual money, ${usd(start, 0)} start`, M, y, { w: 500, px: 21, color: L.mute });
  const bal = isNum(balance) ? balance : cur.balance;
  const up = (bal ?? start) >= start;
  y += 128;
  figure(g, usd(bal), M - 6, y, 128, up, { maxW: W - 2 * M });
  y += 50;
  // progress to the 10x milestone: a foil bar with a glowing head
  const bw = W - 2 * M, bh = 10, p = progressOf(bal, start, goal);
  g.fillStyle = "rgba(245,241,230,0.08)"; g.beginPath(); g.roundRect(M, y, bw, bh, bh / 2); g.fill();
  if (p > 0) {
    g.save(); g.shadowColor = "rgba(240,185,11,0.8)"; g.shadowBlur = 18; g.fillStyle = foil(g, M, 0, M + bw, 0);
    g.beginPath(); g.roundRect(M, y, Math.max(bh, bw * p), bh, bh / 2); g.fill();
    g.fillStyle = "#fff1c4"; g.beginPath(); g.arc(M + Math.max(bh, bw * p), y + bh / 2, 9, 0, Math.PI * 2); g.fill(); g.restore();
  }
  txt(g, usd(start, 0), M, y + 42, { w: 600, px: 19, color: L.mute });
  txt(g, `${Math.round(p * 100)}% of the way to ${usd(goal, 0)}`, W / 2, y + 42, { w: 600, px: 19, color: L.text, align: "center" });
  txt(g, usd(goal, 0), W - M, y + 42, { w: 600, px: 19, color: L.mute, align: "right" });
  y += 70;

  // the run's balance curve (log scale, as the page)
  const pts: number[][] = (v.curves ?? {})[String(cur.run)] ?? [];
  const series = (isNum(bal) ? [...pts.map((q) => q[1]), bal] : pts.map((q) => q[1])).filter((q) => isNum(q) && q > 0);
  if (series.length > 1) {
    const base0 = Math.log10(start);
    curveChart(g, M, y, W - 2 * M, 190, series.map((q) => Math.log10(q) - base0), up);
  }
  y += 190 + 104;
  statRow(g, M, y, W - 2 * M, [
    ["reached 10x", String(sc.milestones ?? sc.successes ?? 0), L.bull],
    ["failures", String(sc.failures ?? 0), L.bear],
    ["runs", String(sc.runs ?? 0)],
    ["best peak", usd(sc.best_peak?.peak ?? sc.all_time_peak, 0), L.gold],
  ], 50);
  luxFooter(g, W, M, H - 150, "Watch the challenge in the app", [
    "All-in demo bot on the app's public grade-A calls. Virtual money only, no real orders.",
    "Past results don't guarantee future results. Not financial advice.",
  ]);
}
