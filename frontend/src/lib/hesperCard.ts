// Admin share image of the Hesper Challenge (views/hesper), drawn in the browser with the premium kit (lib/luxCard.ts).
// Nothing is uploaded or posted: the admin downloads the PNG.
import { curveChart, figure, foil, L, luxBackground, luxBrand, luxFooter, luxReady, sora, statRow, txt } from "./luxCard";
import { fmtPrice, isNum } from "./format";

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

// ---- v2.63: Last Stand card, and one card per closed trade / finished run (both challenges) ------------------------

const coinOf = (s: unknown) => { const x = String(s ?? ""); return x.startsWith("PAXG") ? "GOLD" : x.split("/")[0]; };
const signed = (v: unknown) => (isNum(v) ? `${v >= 0 ? "+" : "−"}${usd(Math.abs(v))}` : "—");
const pctTxt = (v: unknown, d = 0) => (isNum(v) ? `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(d)}%` : "—");
export const lasted = (ms: unknown) => {
  if (!isNum(ms) || ms <= 0) return "—";
  const h = ms / 3_600_000;
  return h < 1 ? `${Math.max(1, Math.round(ms / 60_000))} min` : h < 48 ? `${h.toFixed(h < 10 ? 1 : 0)} h` : `${(h / 24).toFixed(1)} days`;
};
const REASONS: Record<string, string> = { liquidated: "Liquidated", busted: "Busted", stopped: "Ended by admin", goal: "Goal reached" };

/** Distance from the price to the liquidation price, % of the price (positive = still safe). */
export const liqDistance = (o: any, px: number | null) =>
  o && isNum(o.liq) && isNum(px) && px > 0 ? (o.side > 0 ? (px - o.liq) / px : (o.liq - px) / px) * 100 : null;

function smallPrint(g: CanvasRenderingContext2D, W: number, M: number, H: number) {
  luxFooter(g, W, M, H - 150, "Watch the challenge in the app", [
    "All-in demo on the app's public grade-A calls. Virtual money only, no real orders.",
    "Past results don't guarantee future results. Not financial advice.",
  ]);
}

/** Last Stand: the live run. Balance, multiple of its start, time alive, distance to liquidation, the curve. */
export async function drawLastStandCard(cv: HTMLCanvasElement, v: any, balance: number | null, px: number | null) {
  const W = 1080, H = 1080, M = 84;
  cv.width = W; cv.height = H;
  const g = cv.getContext("2d")!;
  await luxReady();
  await luxBackground(g, W, H);
  const cur = v.current ?? {}, sc = v.score ?? {};
  const start = cur.start_balance ?? v.start ?? 10;
  let y = await luxBrand(g, W, M, 72, "LAST STAND");
  y += 64;
  txt(g, `Last Stand  ·  run #${cur.run ?? "—"}`, M, y, { f: sora, w: 600, px: 26, color: L.soft });
  y += 36;
  txt(g, `All-in from ${usd(start, start < 100 ? 2 : 0)}, until liquidation`, M, y, { w: 500, px: 21, color: L.mute });
  const bal = isNum(balance) ? balance : cur.balance;
  const up = (bal ?? start) >= start;
  y += 128;
  figure(g, usd(bal), M - 6, y, 128, up, { maxW: W - 2 * M });
  y += 52;
  const mult = isNum(bal) && start ? bal / start : null;
  txt(g, `${mult != null ? `${mult.toFixed(mult < 10 ? 2 : 1)}x` : "—"} the start  ·  alive ${lasted(Date.now() - (cur.started_at ?? Date.now()))}  ·  ${cur.trades ?? 0} trades`,
    M, y, { w: 600, px: 24, color: L.text, maxW: W - 2 * M });
  y += 44;
  const d = liqDistance(cur.open, px);
  if (d != null) {
    const bw = W - 2 * M, bh = 10, p = Math.max(0, Math.min(1, d / 10));      // a full bar = 10% or more away
    g.fillStyle = "rgba(245,241,230,0.08)"; g.beginPath(); g.roundRect(M, y, bw, bh, bh / 2); g.fill();
    g.fillStyle = d < 2 ? L.bear : foil(g, M, 0, M + bw, 0);
    g.beginPath(); g.roundRect(M, y, Math.max(bh, bw * p), bh, bh / 2); g.fill();
    txt(g, `${coinOf(cur.open.symbol)} ${cur.open.side > 0 ? "LONG" : "SHORT"} ${Math.round(cur.open.leverage)}x  ·  liquidation ${d.toFixed(1)}% away`,
      M, y + 42, { w: 600, px: 19, color: d < 2 ? L.bear : L.mute, maxW: W - 2 * M });
  } else {
    txt(g, "Flat, waiting for the next grade-A call", M, y + 26, { w: 500, px: 19, color: L.mute });
  }
  y += 70;
  const pts: number[][] = (v.curves ?? {})[String(cur.run)] ?? [];
  const series = (isNum(bal) ? [...pts.map((q) => q[1]), bal] : pts.map((q) => q[1])).filter((q) => isNum(q) && q > 0);
  if (series.length > 1) curveChart(g, M, y, W - 2 * M, 170, series.map((q) => Math.log10(q) - Math.log10(start)), up);
  y += 170 + 104;
  statRow(g, M, y, W - 2 * M, [
    ["peak", usd(isNum(bal) ? Math.max(cur.peak ?? 0, bal) : cur.peak, (cur.peak ?? 0) < 100 ? 2 : 0), L.gold],
    ["wins", `${cur.wins ?? 0}/${cur.trades ?? 0}`],
    ["runs", String(sc.runs ?? 0)],
    ["liquidated", String(sc.liquidations ?? 0), L.bear],
  ], 50);
  smallPrint(g, W, M, H);
}

/** One closed trade of a challenge. */
export async function drawTradeCard(cv: HTMLCanvasElement, title: string, t: any) {
  const W = 1080, H = 1080, M = 84;
  cv.width = W; cv.height = H;
  const g = cv.getContext("2d")!;
  await luxReady();
  await luxBackground(g, W, H);
  let y = await luxBrand(g, W, M, 72, title.toUpperCase());
  y += 64;
  txt(g, `${title}  ·  run #${t.run}`, M, y, { f: sora, w: 600, px: 26, color: L.soft });
  y += 70;
  const side = t.side > 0 ? "LONG" : "SHORT";
  txt(g, `${coinOf(t.symbol)}  ${side}  ${Math.round(t.leverage)}x`, M, y, { f: sora, w: 700, px: 48, color: t.side > 0 ? L.bull : L.bear });
  txt(g, String(t.timeframe ?? ""), W - M, y, { f: sora, w: 600, px: 30, color: L.mute, align: "right" });
  y += 170;
  const good = (t.pnl ?? 0) >= 0;
  figure(g, signed(t.pnl), M - 6, y, 136, good, { maxW: W - 2 * M });
  y += 62;
  txt(g, `${pctTxt(t.roi_pct)} on margin  ·  ${String(t.exit_reason ?? "")}`, M, y, { w: 600, px: 26, color: good ? L.text : L.bear, maxW: W - 2 * M });
  y += 120;
  statRow(g, M, y, W - 2 * M, [
    ["entry", fmtPx(t.entry)],
    ["exit", fmtPx(t.exit)],
    ["held", lasted((t.closed_at ?? 0) - (t.opened_at ?? 0))],
  ], 46);
  y += 140;
  statRow(g, M, y, W - 2 * M, [
    ["balance before", usd(t.balance_before)],
    ["balance after", usd(t.balance_after), good ? L.gold : L.bear],
  ], 46);
  smallPrint(g, W, M, H);
}

/** One finished run (or the current run's story so far) of a challenge. */
export async function drawRunCard(cv: HTMLCanvasElement, title: string, r: any, curve: number[][]) {
  const W = 1080, H = 1080, M = 84;
  cv.width = W; cv.height = H;
  const g = cv.getContext("2d")!;
  await luxReady();
  await luxBackground(g, W, H);
  const start = r.start_balance ?? 100, end = r.end_balance;
  let y = await luxBrand(g, W, M, 72, title.toUpperCase());
  y += 64;
  txt(g, `${title}  ·  run #${r.run}`, M, y, { f: sora, w: 600, px: 26, color: L.soft });
  y += 36;
  txt(g, REASONS[r.reason] ?? (r.result === "RUNNING" ? "Still running" : String(r.result ?? "")), M, y, { w: 600, px: 22, color: r.result === "FAIL" ? L.bear : L.mute });
  y += 128;
  const mult = isNum(end) && start ? end / start : null;
  const peakMult = isNum(r.peak) && start ? r.peak / start : null;
  figure(g, `${(peakMult ?? 0).toFixed((peakMult ?? 0) < 10 ? 2 : 1)}x`, M - 6, y, 128, (peakMult ?? 0) >= 1, { maxW: W / 2 });
  txt(g, "peak, from the start", M, y + 40, { w: 500, px: 21, color: L.mute });
  y += 100;
  const ys = curve.map((q) => q[1]).filter((q) => isNum(q) && q > 0);
  if (ys.length > 1) curveChart(g, M, y, W - 2 * M, 200, ys.map((q) => Math.log10(Math.max(q, 0.01)) - Math.log10(start)), (end ?? start) >= start);
  y += 200 + 104;
  statRow(g, M, y, W - 2 * M, [
    ["start", usd(start, start < 100 ? 2 : 0)],
    ["peak", usd(r.peak, (r.peak ?? 0) < 100 ? 2 : 0), L.gold],
    ["end", isNum(end) ? usd(end) : "—", mult != null && mult < 1 ? L.bear : L.text],
    ["lasted", lasted((r.ended_at ?? Date.now()) - r.started_at)],
  ], 46);
  txt(g, `${r.trades ?? 0} trades, ${r.wins ?? 0} wins`, M, y + 76, { w: 500, px: 20, color: L.mute });
  smallPrint(g, W, M, H);
}

function fmtPx(v: unknown) {
  if (!isNum(v)) return "—";
  return v >= 1000 ? v.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : fmtPrice(v);
}
