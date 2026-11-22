// Achievements: milestones the app really reached (computed by the engine from the public record). Each one can be
// downloaded as a square badge image for social media, or all of them together as one poster.
import { useState } from "react";
import { PageHeader } from "../components/kit";
import { ErrorBox, Loading } from "../components/ui";
import { useApi } from "../lib/api";
import { fmtDate, isNum } from "../lib/format";
import { C, download, font } from "../lib/cardCanvas";
import { figure, foil, inter, L, luxBackground, luxBrand, luxFooter, luxReady, sora, txt, wrapLines } from "../lib/luxCard";
import { LevChip } from "../components/SignalExtras";
import AdminTabs from "../components/AdminTabs";

const ICON: Record<string, string> = { signals: "◆", best_trade: "▲", win_streak: "⚡", all_targets: "◎", best_week: "★", green_weeks: "▣",
  win_rate_30d: "%", bot: "⚙", radar_star: "✦", proven_edges: "✓", live: "◷" };
const iconOf = (id: string) => ICON[Object.keys(ICON).find((k) => id.startsWith(k)) ?? ""] ?? "★";

function medal(g: CanvasRenderingContext2D, cx: number, cy: number, r: number, icon: string) {
  g.save();
  g.shadowColor = "rgba(217,180,95,0.55)"; g.shadowBlur = r * 0.5;
  const ring = foil(g, cx - r, cy - r, cx + r, cy + r);
  g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.fillStyle = ring; g.fill();
  g.restore();
  const inner = g.createRadialGradient(cx, cy - r * 0.3, 0, cx, cy, r * 0.84); inner.addColorStop(0, "#221c10"); inner.addColorStop(1, "#0b0a08");
  g.beginPath(); g.arc(cx, cy, r * 0.84, 0, Math.PI * 2); g.fillStyle = inner; g.fill();
  g.beginPath(); g.arc(cx, cy, r * 0.84, 0, Math.PI * 2); g.strokeStyle = "rgba(217,180,95,0.35)"; g.lineWidth = 2; g.stroke();
  // icon glyph centred by its measured box, not the font's line box
  g.font = font(800, r * 0.8); g.textAlign = "center"; g.textBaseline = "alphabetic";
  const m = g.measureText(icon);
  const asc = m.actualBoundingBoxAscent, desc = m.actualBoundingBoxDescent;
  g.fillStyle = foil(g, cx - r * 0.5, cy - r * 0.5, cx + r * 0.5, cy + r * 0.5); g.fillText(icon, cx, cy + (asc - desc) / 2);
  g.textAlign = "left";
  // v2.35: the logo's language around the medal - a gold tick ring and a tilted light-gold orbit with a satellite
  g.save();
  g.strokeStyle = "rgba(217,180,95,0.75)"; g.lineCap = "round";
  for (let k = 0; k < 48; k++) {
    const a = (k / 48) * Math.PI * 2, r0 = r * 1.14, r1 = r * (k % 4 === 0 ? 1.24 : 1.2);
    g.lineWidth = k % 4 === 0 ? 3 : 2;
    g.beginPath(); g.moveTo(cx + Math.cos(a) * r0, cy + Math.sin(a) * r0); g.lineTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1); g.stroke();
  }
  g.translate(cx, cy); g.rotate(-0.38);
  g.strokeStyle = "rgba(255,214,107,0.55)"; g.lineWidth = Math.max(1.5, r / 50);
  g.beginPath(); g.ellipse(0, 0, r * 1.75, r * 0.5, 0, 0, Math.PI * 2); g.stroke();
  g.fillStyle = "#f2dfa6"; g.shadowColor = C.gold; g.shadowBlur = 18;
  g.beginPath(); g.arc(Math.cos(-0.5) * r * 1.75, Math.sin(-0.5) * r * 0.5, Math.max(3, r / 17), 0, Math.PI * 2); g.fill();
  g.restore();
}

const valueColor = (a: any) => (isNum(a.roi_pct) && a.roi_pct < 0 ? C.bear : C.bull);

async function drawBadge(cv: HTMLCanvasElement, a: any) {
  // v2.37 premium layout (lib/luxCard.ts): centred medal, metallic gold figure, editorial type
  const W = 1080, H = 1080, M = 84;
  cv.width = W; cv.height = H;
  const g = cv.getContext("2d")!;
  await luxReady();
  await luxBackground(g, W, H);
  await luxBrand(g, W, M, 72, "ACHIEVEMENT");
  medal(g, W / 2, 352, 118, iconOf(a.id));
  txt(g, "Achievement unlocked", W / 2, 560, { f: sora, w: 600, px: 22, color: L.soft, align: "center", track: 2 });
  txt(g, a.title, W / 2, 618, { f: sora, w: 800, px: 50, color: L.text, align: "center", maxW: W - 2 * M - 40 });
  const raw = String(a.value);
  const roi = / ROI$/.test(raw);
  const num = roi ? raw.replace(/ ROI$/, "") : raw;
  const neg = isNum(a.roi_pct) && a.roi_pct < 0;
  const fg = figure(g, num + (roi ? " ROI" : ""), W / 2, 742, 104, !neg, { align: "center", maxW: W - 2 * M - 40 });
  let y = 742 + 58;
  const lev = isNum(a.leverage) ? a.leverage : null;
  if (lev && isNum(a.return_pct)) {
    txt(g, `${lev}x margin  ·  price ${a.return_pct > 0 ? "+" : ""}${a.return_pct.toFixed(2)}%  ·  ${String(a.detail).split(" · ")[0]}`, W / 2, y,
      { w: 500, px: 23, color: L.mute, align: "center", maxW: W - 2 * M - 40 });
    y += 36;
  } else {
    wrapLines(g, String(a.detail), inter(500, 24), W - 2 * M - 80, 2).forEach((ln, k) => txt(g, ln, W / 2, y + k * 34, { w: 500, px: 24, color: L.mute, align: "center" }));
    y += 36 * Math.min(2, wrapLines(g, String(a.detail), inter(500, 24), W - 2 * M - 80, 2).length);
  }
  if (a.achieved_at) txt(g, fmtDate(a.achieved_at), W / 2, y + 6, { w: 600, px: 19, color: L.dim, align: "center", track: 1 });
  void fg;
  luxFooter(g, W, M, H - 150, "Every signal public, wins and losses", wrapLines(g,
    "Achieved by the app's published signals, all results counted. ROI on margin = price move × the signal card's suggested leverage. Not financial advice.",
    inter(500, 16), W - 2 * M, 2));
}

async function drawPoster(cv: HTMLCanvasElement, list: any[]) {
  const items = list.slice(0, 9);
  const W = 1080, M = 84, gapX = 28, cols = 3;
  const cw = (W - 2 * M - (cols - 1) * gapX) / cols, ch = 300;
  const rows = Math.ceil(items.length / cols);
  const head = 300, foot = 170;
  const H = Math.max(1350, head + rows * ch + foot + 40);
  cv.width = W; cv.height = H;
  const g = cv.getContext("2d")!;
  await luxReady();
  await luxBackground(g, W, H);
  await luxBrand(g, W, M, 72, "ACHIEVEMENTS");
  txt(g, "Milestones reached", M, 228, { f: sora, w: 800, px: 54, color: foil(g, M, 180, M + 560, 230) });
  txt(g, `${list.length} unlocked from the public record`, M, 268, { w: 500, px: 21, color: L.mute });
  const top = head + Math.max(0, (H - foot - head - rows * ch) / 2 - 10);
  items.forEach((a, i) => {
    const row = Math.floor(i / cols), inRow = Math.min(cols, items.length - row * cols);
    const rowW = inRow * cw + (inRow - 1) * gapX, x0 = (W - rowW) / 2;
    const x = x0 + (i % cols) * (cw + gapX), y = top + row * ch, cx = x + cw / 2;
    if (row) { g.fillStyle = L.hair; g.fillRect(x + 20, y - 4, cw - 40, 1); }
    medal(g, cx, y + 74, 46, iconOf(a.id));
    const raw = String(a.value), neg = isNum(a.roi_pct) && a.roi_pct < 0;
    figure(g, raw, cx, y + 182, 38, !neg, { align: "center", maxW: cw - 24 });
    txt(g, a.title, cx, y + 222, { f: sora, w: 700, px: 21, align: "center", maxW: cw - 20 });
    wrapLines(g, String(a.detail), inter(500, 16), cw - 30, 2).forEach((ln, k) => txt(g, ln, cx, y + 250 + k * 21, { w: 500, px: 16, color: L.mute, align: "center" }));
  });
  luxFooter(g, W, M, H - foot + 20, "Every signal public, wins and losses", wrapLines(g,
    "Achieved by the app's published signals, all results counted. ROI on margin = price move × the signal card's suggested leverage. Not financial advice; past results don't guarantee future ones.",
    inter(500, 16), W - 2 * M, 2));
}

/** v2.38 the on-page medal (same design as the image): foil ring, tick ring, tilted orbit with a satellite. */
function Medal({ icon, on }: { icon: string; on: boolean }) {
  const id = `m${icon.charCodeAt(0)}`;
  const ticks = Array.from({ length: 40 }, (_, k) => (k / 40) * Math.PI * 2);
  return (
    <svg viewBox="-60 -60 120 120" className={`h-24 w-24 ${on ? "" : "opacity-40 grayscale"}`} aria-hidden="true">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#9c6f0a" /><stop offset=".3" stopColor="#f0b90b" /><stop offset=".5" stopColor="#fff1c4" /><stop offset=".72" stopColor="#e7ae17" /><stop offset="1" stopColor="#8f650a" />
        </linearGradient>
        <radialGradient id={`${id}i`} cx=".5" cy=".35" r=".7"><stop offset="0" stopColor="#2a2213" /><stop offset="1" stopColor="#0b0a08" /></radialGradient>
      </defs>
      {ticks.map((a, k) => <line key={k} x1={Math.cos(a) * 41} y1={Math.sin(a) * 41} x2={Math.cos(a) * (k % 4 ? 44 : 46)} y2={Math.sin(a) * (k % 4 ? 44 : 46)} stroke="#f0b90b" strokeOpacity=".7" strokeWidth={k % 4 ? 1 : 1.6} />)}
      <circle r="36" fill={`url(#${id})`} style={{ filter: on ? "drop-shadow(0 0 8px rgba(240,185,11,.45))" : undefined }} />
      <circle r="30" fill={`url(#${id}i)`} stroke="rgba(240,185,11,.35)" />
      <text y="9" textAnchor="middle" fontSize="26" fontWeight="800" fill={`url(#${id})`}>{icon}</text>
      <g transform="rotate(-22)"><ellipse rx="56" ry="15" fill="none" stroke="#ffd66b" strokeOpacity=".55" strokeWidth="1.2" />
        <circle cx="48" cy="-8" r="2.6" fill="#fff1c4" style={{ filter: "drop-shadow(0 0 3px #f0b90b)" }} /></g>
    </svg>
  );
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
        <AdminTabs family="share" />
        <button className="btn btn-primary" disabled={!unlocked.length || busy === "all"} onClick={dlAll}>{busy === "all" ? "Preparing…" : `Download all (${unlocked.length})`}</button>
      </div>
      {!list.length && <p className="panel p-4 text-sm text-mute">No achievements yet.</p>}
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {list.map((a) => (
          <li key={a.id} className={`panel lux-tile flex flex-col items-center p-5 text-center ${a.unlocked ? "" : "opacity-70"}`}>
            <Medal icon={iconOf(a.id)} on={a.unlocked} />
            <div className="mt-1 text-xs font-semibold tracking-wide text-accent/80">{a.unlocked ? "Unlocked" : "Locked"}</div>
            <div className="mt-1 font-display text-lg font-semibold">{a.title}</div>
            <div className="mt-1 flex items-center justify-center gap-1.5">
              <span className={`font-display text-3xl font-extrabold tracking-tight ${a.unlocked ? (isNum(a.roi_pct) && a.roi_pct < 0 ? "text-bear" : "foil-text") : "text-mute"}`}>{String(a.value).replace(/ ROI$/, "")}</span>
              {/ ROI$/.test(String(a.value)) && <span className="text-xs font-bold text-accent">ROI</span>}
              {isNum(a.leverage) && <LevChip lev={a.leverage} />}
            </div>
            <div className="mt-1 text-xs text-mute">{a.detail}</div>
            {a.unlocked ? (
              <>
                {a.achieved_at && <div className="mt-1 text-xs text-mute">{fmtDate(a.achieved_at)}</div>}
                <button className="btn mt-3 px-3 py-1.5 text-xs" disabled={busy === a.id} onClick={() => dl(a)}>{busy === a.id ? "Preparing…" : "Download image"}</button>
              </>
            ) : (
              <div className="mt-3 w-full">
                <div className="h-1.5 overflow-hidden rounded-full bg-glass/10"><div className="h-full rounded-full bg-accent" style={{ width: `${Math.round((a.progress ?? 0) * 100)}%` }} /></div>
                <div className="mt-1 text-xs text-mute">locked · {Math.round((a.progress ?? 0) * 100)}%</div>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
