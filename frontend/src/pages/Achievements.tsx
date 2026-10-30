// Achievements: milestones the app really reached (computed by the engine from the public record). Each one can be
// downloaded as a square badge image for social media, or all of them together as one poster.
import { useState } from "react";
import { ErrorBox, Loading } from "../components/ui";
import { useApi } from "../lib/api";
import { fmtDate, isNum } from "../lib/format";
import { backdrop, C, cap, chip, download, fit, font, fontsReady, footer, glowText, header, M, panel, text, wrap } from "../lib/cardCanvas";
import { LevChip } from "../components/SignalExtras";

const ICON: Record<string, string> = { signals: "◆", best_trade: "▲", win_streak: "⚡", all_targets: "◎", best_week: "★", green_weeks: "▣",
  win_rate_30d: "%", bot: "⚙", radar_star: "✦", proven_edges: "✓", live: "◷" };
const iconOf = (id: string) => ICON[Object.keys(ICON).find((k) => id.startsWith(k)) ?? ""] ?? "★";

function medal(g: CanvasRenderingContext2D, cx: number, cy: number, r: number, icon: string) {
  g.save();
  g.shadowColor = "rgba(240,185,11,0.55)"; g.shadowBlur = r * 0.5;
  const ring = g.createLinearGradient(cx - r, cy - r, cx + r, cy + r); ring.addColorStop(0, "#fcd535"); ring.addColorStop(0.5, "#f0b90b"); ring.addColorStop(1, "#8a6508");
  g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.fillStyle = ring; g.fill();
  g.restore();
  const inner = g.createRadialGradient(cx, cy - r * 0.3, 0, cx, cy, r * 0.84); inner.addColorStop(0, "#221c10"); inner.addColorStop(1, "#0b0a08");
  g.beginPath(); g.arc(cx, cy, r * 0.84, 0, Math.PI * 2); g.fillStyle = inner; g.fill();
  g.beginPath(); g.arc(cx, cy, r * 0.84, 0, Math.PI * 2); g.strokeStyle = "rgba(240,185,11,0.35)"; g.lineWidth = 2; g.stroke();
  // icon glyph centred by its measured box, not the font's line box
  g.font = font(800, r * 0.8); g.textAlign = "center"; g.textBaseline = "alphabetic";
  const m = g.measureText(icon);
  const asc = m.actualBoundingBoxAscent, desc = m.actualBoundingBoxDescent;
  g.fillStyle = C.gold; g.fillText(icon, cx, cy + (asc - desc) / 2);
  g.textAlign = "left";
}

const valueColor = (a: any) => (isNum(a.roi_pct) && a.roi_pct < 0 ? C.bear : C.bull);

async function drawBadge(cv: HTMLCanvasElement, a: any) {
  const W = 1080, H = 1080; cv.width = W; cv.height = H;
  const g = cv.getContext("2d")!;
  await fontsReady();
  backdrop(g, W, H);
  await header(g, "Achievement unlocked");
  medal(g, W / 2, 352, 132, iconOf(a.id));
  text(g, a.title, W / 2, 560, { weight: 800, px: 56, align: "center", maxW: W - 2 * M - 48 });
  // hero value: "+31.2% ROI" -> the number glows, the unit sits beside it on the same baseline
  const raw = String(a.value);
  const roi = / ROI$/.test(raw);
  const num = roi ? raw.replace(/ ROI$/, "") : raw;
  const lev = isNum(a.leverage) ? a.leverage : null;
  const unit = roi ? "ROI" : "";
  const px = fit(g, num, W - 2 * M - (unit ? 200 : 0), 112, 48, 800);
  g.font = font(800, px);
  const nw = g.measureText(num).width;
  g.font = font(800, Math.round(px * 0.42));
  const uw = unit ? g.measureText(unit).width + 20 : 0;
  const x0 = W / 2 - (nw + uw) / 2, by = 690;
  glowText(g, num, x0, by, valueColor(a), { weight: 800, px, blur: 40 });
  if (unit) text(g, unit, x0 + nw + 20, by, { weight: 800, px: Math.round(px * 0.42), color: C.gold });
  // detail line(s), centred, wrapped
  g.font = font(500, 28);
  const det = wrap(g, String(a.detail), W - 2 * M - 80, 2);
  let y = by + 64;
  if (lev && isNum(a.return_pct)) {
    // leverage chip + price move, centred as one group
    const chipLabel = `${lev}x MARGIN`, mv = `price ${a.return_pct > 0 ? "+" : ""}${a.return_pct.toFixed(2)}%`;
    g.font = font(800, 18); const cw = g.measureText(chipLabel).width + 32;
    g.font = font(500, 24); const mw = g.measureText(mv).width;
    const gx = W / 2 - (cw + 16 + mw) / 2;
    const e = chip(g, gx, y - 28, chipLabel, { h: 40, px: 18 });
    g.font = font(500, 24);
    text(g, mv, e + 16, y - 8 + cap(g) / 2, { weight: 500, px: 24, color: C.text });
    y += 48;
    const sub = `${String(a.detail).split(" · ")[0]}`;
    text(g, sub, W / 2, y, { weight: 500, px: 28, color: C.mute, align: "center", maxW: W - 2 * M - 80 });
    y += 40;
  } else {
    det.forEach((ln, k) => text(g, ln, W / 2, y + k * 38, { weight: 500, px: 28, color: C.mute, align: "center" }));
    y += det.length * 38;
  }
  if (a.achieved_at) text(g, fmtDate(a.achieved_at), W / 2, y + 8, { weight: 600, px: 22, color: C.dim, align: "center" });
  g.font = font(500, 17);
  footer(g, W, H - 168, "AI crypto signals · join the app",
    wrap(g, "Achieved by the app's published signals, wins and losses all counted. ROI on margin = price move × the signal card's suggested leverage. Not financial advice.", W - 2 * M, 2));
}

async function drawPoster(cv: HTMLCanvasElement, list: any[]) {
  const items = list.slice(0, 9);
  const W = 1080;
  const cols = Math.min(3, Math.max(1, items.length)), gap = 24;
  const cw = (W - 2 * M - (3 - 1) * gap) / 3, ch = 336;
  const rows = Math.ceil(items.length / cols);
  const gridH = rows * ch + (rows - 1) * gap;
  // the poster grows with the number of rows, so tiles never run into the footer
  cv.width = W; cv.height = 1350;
  const g = cv.getContext("2d")!;
  await fontsReady();
  const hy0 = await header(g, "Our achievements");          // measure the header height once
  const H = Math.max(1350, hy0 + 40 + gridH + 48 + 168);
  cv.height = H;                                             // resizing clears the canvas: draw for real
  backdrop(g, W, H);
  const hy = await header(g, "Our achievements");
  const fy = H - 168;
  const top = hy + 40 + Math.max(0, (fy - 48 - (hy + 40) - gridH) / 2);
  items.forEach((a, i) => {
    const row = Math.floor(i / cols), inRow = Math.min(cols, items.length - row * cols);
    const rowW = inRow * cw + (inRow - 1) * gap, x0 = (W - rowW) / 2;
    const x = x0 + (i % cols) * (cw + gap), y = top + row * (ch + gap), cx = x + cw / 2;
    panel(g, x, y, cw, ch, { r: 24 });
    medal(g, cx, y + 92, 56, iconOf(a.id));
    const raw = String(a.value), roi = / ROI$/.test(raw), num = roi ? raw.replace(/ ROI$/, "") : raw;
    // value + optional ROI unit centred together on one baseline
    const px = fit(g, num, cw - (roi ? 96 : 40), 44, 24, 800);
    g.font = font(800, px); const nw = g.measureText(num).width;
    g.font = font(800, Math.round(px * 0.5)); const uw = roi ? g.measureText("ROI").width + 10 : 0;
    const vx = cx - (nw + uw) / 2;
    glowText(g, num, vx, y + 214, valueColor(a), { weight: 800, px, blur: 14 });
    if (roi) text(g, "ROI", vx + nw + 10, y + 214, { weight: 800, px: Math.round(px * 0.5), color: C.gold });
    text(g, a.title, cx, y + 256, { weight: 700, px: 24, align: "center", maxW: cw - 32, minPx: 16 });
    g.font = font(500, 17);
    wrap(g, String(a.detail), cw - 40, 2).forEach((ln, k) => text(g, ln, cx, y + 288 + k * 23, { weight: 500, px: 17, color: C.mute, align: "center" }));
  });
  g.font = font(500, 17);
  footer(g, W, fy, "AI crypto signals · join the app",
    wrap(g, "Achieved by the app's published signals, wins and losses all counted. ROI on margin = price move × the signal card's suggested leverage. Not financial advice; past results don't guarantee future ones.", W - 2 * M, 2));
}

export default function Achievements() {
  const v = useApi<any>("/track-record");
  const [busy, setBusy] = useState<string | null>(null);
  if (v.loading && !v.data) return <Loading />;
  if (v.error) return <ErrorBox error={v.error} retry={v.reload} />;
  const list: any[] = v.data?.achievements ?? [];
  const unlocked = list.filter((a) => a.unlocked);
  const dl = async (a: any) => { setBusy(a.id); const cv = document.createElement("canvas"); await drawBadge(cv, a); download(cv, `achievement-${a.id}.png`); setBusy(null); };
  const dlAll = async () => { setBusy("all"); const cv = document.createElement("canvas"); await drawPoster(cv, unlocked); download(cv, "crypto-intelligence-achievements.png"); setBusy(null); };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="page-title">Achievements</h1>
          <p className="text-sm text-mute">Milestones the app has really reached, worked out by the engine from the app's real track record. Download any of them as an image to share.</p>
        </div>
        <button className="btn btn-primary" disabled={!unlocked.length || busy === "all"} onClick={dlAll}>{busy === "all" ? "Preparing…" : `Download all (${unlocked.length})`}</button>
      </div>
      {!list.length && <p className="panel p-4 text-sm text-mute">Achievements appear as soon as the first signals have closed.</p>}
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {list.map((a) => (
          <li key={a.id} className={`panel flex flex-col items-center p-5 text-center ${a.unlocked ? "border-accent/40" : "opacity-60"}`}>
            <span className={`flex h-16 w-16 items-center justify-center rounded-full border-4 text-2xl font-extrabold ${a.unlocked ? "border-accent bg-accent/10 text-accent" : "border-glass/20 text-mute"}`}>{iconOf(a.id)}</span>
            <div className="mt-3 font-semibold">{a.title}</div>
            <div className="mt-1 flex items-center justify-center gap-1.5">
              <span className={`num text-2xl font-extrabold tracking-tight ${a.unlocked ? (isNum(a.roi_pct) && a.roi_pct < 0 ? "text-bear" : "text-bull drop-shadow-[0_0_12px_rgba(14,203,129,0.35)]") : "text-mute"}`}>{String(a.value).replace(/ ROI$/, "")}</span>
              {/ ROI$/.test(String(a.value)) && <span className="text-xs font-bold text-accent">ROI</span>}
              {isNum(a.leverage) && <LevChip lev={a.leverage} />}
            </div>
            <div className="mt-1 text-xs text-mute">{a.detail}</div>
            {a.unlocked ? (
              <>
                {a.achieved_at && <div className="mt-1 text-[11px] text-mute">{fmtDate(a.achieved_at)}</div>}
                <button className="btn mt-3 px-3 py-1.5 text-xs" disabled={busy === a.id} onClick={() => dl(a)}>{busy === a.id ? "Preparing…" : "Download image"}</button>
              </>
            ) : (
              <div className="mt-3 w-full">
                <div className="h-1.5 overflow-hidden rounded-full bg-glass/10"><div className="h-full rounded-full bg-accent" style={{ width: `${Math.round((a.progress ?? 0) * 100)}%` }} /></div>
                <div className="mt-1 text-[11px] text-mute">locked · {Math.round((a.progress ?? 0) * 100)}%</div>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
