// Achievements: milestones the app really reached (computed by the engine from the public record). Each one can be
// downloaded as a square badge image for social media, or all of them together as one poster.
import { useState } from "react";
import { ErrorBox, Loading } from "../components/ui";
import { useApi } from "../lib/api";
import { fmtDate } from "../lib/format";

const SITE = "crypapp-6a9b9.web.app";
const ICON: Record<string, string> = { signals: "◆", best_trade: "▲", win_streak: "⚡", all_targets: "◎", best_week: "★", green_weeks: "▣",
  win_rate_30d: "%", bot: "⚙", radar_star: "✦", proven_edges: "✓", live: "◷" };
const iconOf = (id: string) => ICON[Object.keys(ICON).find((k) => id.startsWith(k)) ?? ""] ?? "★";

function img(src: string): Promise<HTMLImageElement | null> {
  return new Promise((res) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => res(null); i.src = src; });
}
const F = (w: number, px: number, mono = false) => `${w} ${px}px ${mono ? "ui-monospace, Menlo, monospace" : "Inter, system-ui, sans-serif"}`;

/** Largest font (down to min) at which the text fits the width. */
function fit(g: CanvasRenderingContext2D, t: string, w: number, max: number, min: number, weight = 800, mono = false) {
  let px = max;
  g.font = F(weight, px, mono && t.length <= 7);
  while (px > min && g.measureText(t).width > w) { px -= 2; g.font = F(weight, px, mono && t.length <= 7); }
}

function lines(g: CanvasRenderingContext2D, t: string, w: number, n = 2): string[] {
  const out: string[] = []; let cur = "";
  for (const word of t.split(" ")) {
    const nx = cur ? `${cur} ${word}` : word;
    if (g.measureText(nx).width > w && cur) { out.push(cur); cur = word; } else cur = nx;
  }
  if (cur) out.push(cur);
  return out.length > n ? [...out.slice(0, n - 1), out.slice(n - 1).join(" ").slice(0, 40) + "…"] : out;
}

function backdrop(g: CanvasRenderingContext2D, W: number, H: number) {
  const bg = g.createLinearGradient(0, 0, W, H); bg.addColorStop(0, "#0b0e11"); bg.addColorStop(1, "#181a20");
  g.fillStyle = bg; g.fillRect(0, 0, W, H);
  const glow = g.createRadialGradient(W / 2, H * 0.36, 20, W / 2, H * 0.36, W * 0.6);
  glow.addColorStop(0, "rgba(240,185,11,0.25)"); glow.addColorStop(1, "rgba(240,185,11,0)");
  g.fillStyle = glow; g.fillRect(0, 0, W, H);
  g.strokeStyle = "rgba(240,185,11,0.35)"; g.lineWidth = 4; g.strokeRect(24, 24, W - 48, H - 48);
}

function medal(g: CanvasRenderingContext2D, cx: number, cy: number, r: number, icon: string) {
  const ring = g.createLinearGradient(cx - r, cy - r, cx + r, cy + r); ring.addColorStop(0, "#fcd535"); ring.addColorStop(1, "#b8860b");
  g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.fillStyle = ring; g.fill();
  g.beginPath(); g.arc(cx, cy, r * 0.82, 0, Math.PI * 2); g.fillStyle = "#14171c"; g.fill();
  g.fillStyle = "#f0b90b"; g.font = F(800, r * 0.8); g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(icon, cx, cy + r * 0.04);
  g.textBaseline = "alphabetic";
}

async function header(g: CanvasRenderingContext2D, W: number, y: number) {
  const logo = await img("/icons/icon-192.png");
  g.textAlign = "left";
  const t1 = "Crypto Intelligence ", t2 = "AI";
  g.font = F(800, 38);
  const w = (logo ? 76 : 0) + g.measureText(t1 + t2).width, x = (W - w) / 2;
  if (logo) g.drawImage(logo, x, y - 48, 62, 62);
  g.fillStyle = "#eaecef"; g.fillText(t1, x + (logo ? 76 : 0), y);
  g.fillStyle = "#f0b90b"; g.fillText(t2, x + (logo ? 76 : 0) + g.measureText(t1).width, y);
}

function footer(g: CanvasRenderingContext2D, W: number, H: number) {
  g.textAlign = "center"; g.fillStyle = "#eaecef"; g.font = F(700, 28); g.fillText(`Every signal & result is public: ${SITE}`, W / 2, H - 92);
  g.fillStyle = "#848e9c"; g.font = F(500, 20); g.fillText("Achieved by the app's published signals. Not financial advice; past results don't guarantee future ones.", W / 2, H - 58);
  g.textAlign = "left";
}

async function drawBadge(cv: HTMLCanvasElement, a: any) {
  const W = 1080, H = 1080; cv.width = W; cv.height = H;
  const g = cv.getContext("2d")!;
  backdrop(g, W, H);
  await header(g, W, 120);
  g.textAlign = "center"; g.fillStyle = "#f0b90b"; g.font = F(700, 28); g.fillText("ACHIEVEMENT UNLOCKED", W / 2, 200);
  medal(g, W / 2, 400, 150, iconOf(a.id));
  g.fillStyle = "#ffffff"; g.font = F(800, 64); g.fillText(a.title, W / 2, 650);
  g.fillStyle = "#0ecb81"; fit(g, a.value, W - 200, 96, 48, 800, true); g.fillText(a.value, W / 2, 770);
  g.fillStyle = "#b7bdc6"; g.font = F(500, 32); g.fillText(a.detail, W / 2, 830);
  if (a.achieved_at) { g.fillStyle = "#848e9c"; g.font = F(500, 26); g.fillText(fmtDate(a.achieved_at), W / 2, 876); }
  footer(g, W, H);
}

async function drawPoster(cv: HTMLCanvasElement, list: any[]) {
  const items = list.slice(0, 9);
  const W = 1080, H = 1350; cv.width = W; cv.height = H;
  const g = cv.getContext("2d")!;
  backdrop(g, W, H);
  await header(g, W, 120);
  g.textAlign = "center"; g.fillStyle = "#f0b90b"; g.font = F(700, 30); g.fillText("OUR ACHIEVEMENTS", W / 2, 190);
  const cols = Math.min(3, Math.max(1, items.length)), cw = 300, ch = 340, gap = 30;
  const rows = Math.ceil(items.length / cols);
  const gridH = rows * ch + (rows - 1) * gap, top = 230 + Math.max(0, (H - 230 - 160 - gridH) / 2);
  items.forEach((a, i) => {
    const row = Math.floor(i / cols), inRow = Math.min(cols, items.length - row * cols);
    const rowW = inRow * cw + (inRow - 1) * gap, x0 = (W - rowW) / 2;
    const x = x0 + (i % cols) * (cw + gap), y = top + row * (ch + gap);
    g.fillStyle = "rgba(255,255,255,0.045)"; g.fillRect(x, y, cw, ch);
    g.strokeStyle = "rgba(240,185,11,0.25)"; g.lineWidth = 2; g.strokeRect(x, y, cw, ch);
    medal(g, x + cw / 2, y + 90, 60, iconOf(a.id));
    g.textAlign = "center";
    g.fillStyle = "#0ecb81"; fit(g, a.value, cw - 30, 44, 26, 800, true); g.fillText(a.value, x + cw / 2, y + 210);
    g.fillStyle = "#ffffff"; fit(g, a.title, cw - 24, 26, 18, 700); g.fillText(a.title, x + cw / 2, y + 252);
    g.fillStyle = "#848e9c"; g.font = F(500, 18);
    lines(g, String(a.detail), cw - 30).forEach((ln, k) => g.fillText(ln, x + cw / 2, y + 286 + k * 24));
  });
  footer(g, W, H);
}

function save(cv: HTMLCanvasElement, name: string) {
  const a = document.createElement("a"); a.download = name; a.href = cv.toDataURL("image/png"); a.click();
}

export default function Achievements() {
  const v = useApi<any>("/track-record");
  const [busy, setBusy] = useState<string | null>(null);
  if (v.loading && !v.data) return <Loading />;
  if (v.error) return <ErrorBox error={v.error} retry={v.reload} />;
  const list: any[] = v.data?.achievements ?? [];
  const unlocked = list.filter((a) => a.unlocked);
  const dl = async (a: any) => { setBusy(a.id); const cv = document.createElement("canvas"); await drawBadge(cv, a); save(cv, `achievement-${a.id}.png`); setBusy(null); };
  const dlAll = async () => { setBusy("all"); const cv = document.createElement("canvas"); await drawPoster(cv, unlocked); save(cv, "crypto-intelligence-achievements.png"); setBusy(null); };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Achievements</h1>
          <p className="text-sm text-mute">Milestones the app has really reached, worked out by the engine from the public track record. Download any of them as an image to share.</p>
        </div>
        <button className="btn btn-primary" disabled={!unlocked.length || busy === "all"} onClick={dlAll}>{busy === "all" ? "Preparing…" : `Download all (${unlocked.length})`}</button>
      </div>
      {!list.length && <p className="panel p-4 text-sm text-mute">Achievements appear as soon as the first signals have closed.</p>}
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {list.map((a) => (
          <li key={a.id} className={`panel flex flex-col items-center p-5 text-center ${a.unlocked ? "border-accent/40" : "opacity-60"}`}>
            <span className={`flex h-16 w-16 items-center justify-center rounded-full border-4 text-2xl font-extrabold ${a.unlocked ? "border-accent bg-accent/10 text-accent" : "border-glass/20 text-mute"}`}>{iconOf(a.id)}</span>
            <div className="mt-3 font-semibold">{a.title}</div>
            <div className={`num mt-1 text-2xl font-bold ${a.unlocked ? "text-bull" : "text-mute"}`}>{a.value}</div>
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
