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
import TelegramButton from "../components/TelegramButton";
import { SITE_HOST } from "../lib/brand";

const ICON: Record<string, string> = { signals: "◆", best_trade: "▲", win_streak: "⚡", all_targets: "◎", best_week: "★", green_weeks: "▣",
  win_rate_30d: "%", bot: "⚙", radar_star: "✦", proven_edges: "✓", live: "◷" };
const iconOf = (id: string) => ICON[Object.keys(ICON).find((k) => id.startsWith(k)) ?? ""] ?? "★";

// V3.1 (owner, 24 Nov 2026: achievements were still the old design): the "neural badge" - a rounded hexagon with a gold
// edge on graphite, the glyph in gold, and six neurons around it (green / red, linked in cyan) like the logo. No orbit.
const HEX = (r: number) => Array.from({ length: 6 }, (_, k) => { const a = -Math.PI / 2 + (k * Math.PI) / 3; return [Math.cos(a) * r, Math.sin(a) * r]; });
function hexPath(g: CanvasRenderingContext2D, cx: number, cy: number, r: number) {
  const p = HEX(r), rr = r * 0.16;
  g.beginPath();
  p.forEach(([x, y], k) => {
    const [nx, ny] = p[(k + 1) % 6], [px, py] = p[(k + 5) % 6];
    const a = [x + (px - x) * (rr / r), y + (py - y) * (rr / r)], b = [x + (nx - x) * (rr / r), y + (ny - y) * (rr / r)];
    if (k) g.lineTo(cx + a[0], cy + a[1]); else g.moveTo(cx + a[0], cy + a[1]);
    g.quadraticCurveTo(cx + x, cy + y, cx + b[0], cy + b[1]);
  });
  g.closePath();
}
function medal(g: CanvasRenderingContext2D, cx: number, cy: number, r: number, icon: string) {
  g.save();
  // neurons: six around the badge, linked to its corners and to each other
  const ring = HEX(r * 1.42).map(([x, y]) => [cx + x * 1.0, cy + y * 1.0]);
  const corner = HEX(r).map(([x, y]) => [cx + x, cy + y]);
  g.lineWidth = Math.max(1.2, r / 55);
  ring.forEach(([x, y], k) => {
    g.strokeStyle = "rgba(93,241,221,0.45)";
    g.beginPath(); g.moveTo(x, y); g.lineTo(corner[k][0], corner[k][1]); g.stroke();
    const [nx, ny] = ring[(k + 1) % 6];
    g.strokeStyle = "rgba(93,241,221,0.18)";
    g.beginPath(); g.moveTo(x, y); g.lineTo(nx, ny); g.stroke();
  });
  ring.forEach(([x, y], k) => { g.fillStyle = k % 2 ? "#f6465d" : "#0ecb81"; g.beginPath(); g.arc(x, y, Math.max(3, r * 0.07), 0, Math.PI * 2); g.fill(); });
  const fill = g.createLinearGradient(cx, cy - r, cx, cy + r); fill.addColorStop(0, "#24252c"); fill.addColorStop(1, "#15161a");
  hexPath(g, cx, cy, r); g.fillStyle = fill; g.fill();
  g.lineWidth = Math.max(3, r / 22); g.strokeStyle = C.gold; g.stroke();
  hexPath(g, cx, cy, r * 0.82); g.lineWidth = 1; g.strokeStyle = "rgba(232,182,55,0.28)"; g.stroke();
  g.font = font(700, r * 0.78); g.textAlign = "center"; g.textBaseline = "alphabetic";
  const m = g.measureText(icon);
  g.fillStyle = C.gold; g.fillText(icon, cx, cy + (m.actualBoundingBoxAscent - m.actualBoundingBoxDescent) / 2);
  g.restore();
}

const valueColor = (a: any) => (isNum(a.roi_pct) && a.roi_pct < 0 ? C.bear : C.bull);

export async function drawBadge(cv: HTMLCanvasElement, a: any) {
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

export async function drawPoster(cv: HTMLCanvasElement, list: any[]) {
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

/** The on-page badge: the same neural hexagon as the share image. */
function Medal({ icon, on }: { icon: string; on: boolean }) {
  const pt = (r: number) => HEX(r).map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const ring = HEX(50), corner = HEX(35);
  return (
    <svg viewBox="-60 -60 120 120" className={`h-24 w-24 ${on ? "" : "opacity-40 grayscale"}`} aria-hidden="true">
      {ring.map(([x, y], k) => <line key={`a${k}`} x1={x} y1={y} x2={corner[k][0]} y2={corner[k][1]} stroke="#5df1dd" strokeOpacity=".45" strokeWidth="1" />)}
      {ring.map(([x, y], k) => <line key={`b${k}`} x1={x} y1={y} x2={ring[(k + 1) % 6][0]} y2={ring[(k + 1) % 6][1]} stroke="#5df1dd" strokeOpacity=".18" strokeWidth="1" />)}
      {ring.map(([x, y], k) => <circle key={`c${k}`} cx={x} cy={y} r="2.6" fill={k % 2 ? "#f6465d" : "#0ecb81"} className={on ? "badge-neuron" : ""} style={{ animationDelay: `${k * 0.3}s` }} />)}
      <polygon points={pt(35)} fill="rgb(var(--raised))" stroke="#e8b637" strokeWidth="2.4" strokeLinejoin="round" />
      <polygon points={pt(29)} fill="none" stroke="#e8b637" strokeOpacity=".28" strokeWidth="1" strokeLinejoin="round" />
      <text y="9" textAnchor="middle" fontSize="26" fontWeight="700" fill="#e8b637">{icon}</text>
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
  const badgeCv = async (a: any) => { const cv = document.createElement("canvas"); await drawBadge(cv, a); return cv; };
  const posterCv = async () => { const cv = document.createElement("canvas"); await drawPoster(cv, unlocked); return cv; };
  const capOf = (a: any) => `🏆 Achievement unlocked: ${a.title}\n${String(a.value)} · ${a.detail}\n\nEvery signal is public, wins and losses: https://${SITE_HOST}\nNot financial advice.`;
  const capAll = `🏆 Crypto Intelligence AI · ${unlocked.length} milestones reached from the public record\n` + unlocked.slice(0, 9).map((a) => `• ${a.title}: ${a.value}`).join("\n") + `\n\nhttps://${SITE_HOST} · Not financial advice.`;
  const dlAll = async () => { setBusy("all"); const cv = document.createElement("canvas"); await drawPoster(cv, unlocked); download(cv, "crypto-intelligence-achievements.png"); setBusy(null); };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <AdminTabs family="share" />
        <span className="flex flex-wrap items-center gap-2">
          <button className="btn btn-primary" disabled={!unlocked.length || busy === "all"} onClick={dlAll}>{busy === "all" ? "Preparing…" : `Download all (${unlocked.length})`}</button>
          {unlocked.length > 0 && <TelegramButton canvas={posterCv} caption={capAll} kind="achievements" />}
        </span>
      </div>
      {!list.length && <p className="panel p-4 text-sm text-mute">No achievements yet.</p>}
      <ul className="grid-even grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {list.map((a) => (
          <li key={a.id} className={`panel ach-tile flex flex-col items-center p-5 text-center ${a.unlocked ? "is-on" : "opacity-70"}`}>
            <Medal icon={iconOf(a.id)} on={a.unlocked} />
            <span className={`mt-2 rounded-md px-2 py-0.5 text-xs font-semibold ${a.unlocked ? "bg-accent/15 text-accent" : "bg-glass/[0.06] text-mute"}`}>{a.unlocked ? "Unlocked" : "Locked"}</span>
            <div className="mt-2 text-lg font-semibold">{a.title}</div>
            <div className="mt-1 flex items-center justify-center gap-1.5">
              <span className={`num text-3xl font-bold tracking-tight ${a.unlocked ? (isNum(a.roi_pct) && a.roi_pct < 0 ? "text-bear" : "text-bull") : "text-mute"}`}>{String(a.value).replace(/ ROI$/, "")}</span>
              {/ ROI$/.test(String(a.value)) && <span className="text-xs font-bold text-accent">ROI</span>}
              {isNum(a.leverage) && <LevChip lev={a.leverage} />}
            </div>
            <div className="mt-1 text-xs text-mute">{a.detail}</div>
            {a.unlocked ? (
              <>
                {a.achieved_at && <div className="mt-1 text-xs text-mute">{fmtDate(a.achieved_at)}</div>}
                <div className="mt-auto flex flex-wrap items-center justify-center gap-2 pt-3">
                  <button className="btn btn-sm" disabled={busy === a.id} onClick={() => dl(a)}>{busy === a.id ? "Preparing…" : "Download image"}</button>
                  <TelegramButton canvas={() => badgeCv(a)} caption={capOf(a)} kind="achievement" className="btn btn-sm" />
                </div>
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
