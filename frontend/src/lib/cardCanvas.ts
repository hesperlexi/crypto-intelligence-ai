// Shared drawing kit for the downloadable share images (Weekly report, Achievements). Same look as the Telegram
// cards (backend/app/services/cards.py): black + gold, radial gold glow, the real logo top-left, glowing hero
// numbers. Every text line is drawn on an alphabetic baseline and measured, so columns and rows line up exactly;
// long values are shrunk to fit their box. Layout uses an 8 px grid.
import { SITE_HOST } from "./brand";

export const C = {
  gold: "#f0b90b", goldSoft: "rgba(240,185,11,0.6)", bull: "#0ecb81", bear: "#f6465d", text: "#f2f2f0", mute: "#9a958a",
  dim: "#6f6a60", line: "rgba(240,185,11,0.16)", panel: "rgba(255,255,255,0.035)", panelHi: "rgba(240,185,11,0.08)", ink: "#08080a",
};
export const M = 72;                                                  // outer margin

type G = CanvasRenderingContext2D;
export const font = (w: number, px: number) => `${w} ${px}px Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`;

/** Wait for the web fonts so measurements match what is painted. */
export async function fontsReady() {
  try {
    await Promise.all([800, 700, 600, 500].map((w) => document.fonts.load(font(w, 32), "0123456789+-.%ABC")));
    await document.fonts.ready;
  } catch { /* system font fallback */ }
}

export function loadImg(src: string): Promise<HTMLImageElement | null> {
  return new Promise((res) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => res(null); i.src = src; });
}

/** Cap height of the current font (for centring capitals optically). */
export function cap(g: G): number {
  const m = g.measureText("H");
  return m.actualBoundingBoxAscent || parseFloat(g.font.split(" ")[1]) * 0.72;
}

/** Largest size (down to min) at which `t` fits `maxW`; sets g.font and returns the size. */
export function fit(g: G, t: string, maxW: number, maxPx: number, minPx = 12, weight = 800): number {
  let px = maxPx;
  g.font = font(weight, px);
  while (px > minPx && g.measureText(t).width > maxW) { px -= 2; g.font = font(weight, px); }
  return px;
}

export interface TextOpts { weight?: number; px?: number; color?: string; align?: CanvasTextAlign; maxW?: number; minPx?: number }
/** Text on an alphabetic baseline at (x, y). Returns its width. */
export function text(g: G, t: string, x: number, y: number, o: TextOpts = {}): number {
  const { weight = 600, px = 20, color = C.text, align = "left", maxW, minPx = 12 } = o;
  if (maxW) fit(g, t, maxW, px, minPx, weight); else g.font = font(weight, px);
  g.textAlign = align; g.textBaseline = "alphabetic"; g.fillStyle = color;
  g.fillText(t, x, y);
  const w = g.measureText(t).width;
  g.textAlign = "left";
  return w;
}

/** Glowing text (soft coloured halo behind it). */
export function glowText(g: G, t: string, x: number, y: number, color: string, o: TextOpts & { blur?: number } = {}) {
  g.save();
  g.shadowColor = color; g.shadowBlur = o.blur ?? 36;
  g.globalAlpha = 0.85;
  text(g, t, x, y, { ...o, color });
  g.restore();
  text(g, t, x, y, { ...o, color });                 // crisp copy on top of the halo
}

export function rrect(g: G, x: number, y: number, w: number, h: number, r: number) {
  g.beginPath();
  g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath();
}

export function panel(g: G, x: number, y: number, w: number, h: number, o: { r?: number; fill?: string; stroke?: string; lw?: number } = {}) {
  rrect(g, x, y, w, h, o.r ?? 24);
  g.fillStyle = o.fill ?? C.panel; g.fill();
  g.strokeStyle = o.stroke ?? C.line; g.lineWidth = o.lw ?? 2; g.stroke();
}

/** Pill with its text centred. align "right": x is the right edge. Returns the far edge (left edge for right-aligned). */
export function pill(g: G, x: number, y: number, label: string, o: { h?: number; px?: number; bg?: string; fg?: string; stroke?: string; minW?: number; align?: "left" | "right" } = {}): number {
  const { h = 36, px = 16, bg = C.panelHi, fg = C.gold, stroke, minW = 0, align = "left" } = o;
  g.font = font(800, px);
  const w = Math.max(minW, g.measureText(label).width + 32);
  const x0 = align === "right" ? x - w : x;
  rrect(g, x0, y, w, h, h / 2);
  g.fillStyle = bg; g.fill();
  if (stroke) { g.strokeStyle = stroke; g.lineWidth = 2; g.stroke(); }
  g.fillStyle = fg; g.textAlign = "center"; g.textBaseline = "alphabetic";
  g.fillText(label, x0 + w / 2, y + h / 2 + cap(g) / 2);
  g.textAlign = "left";
  return align === "right" ? x0 : x0 + w;
}
export const chip = (g: G, x: number, y: number, label: string, o: Parameters<typeof pill>[4] = {}) =>
  pill(g, x, y, label, { bg: C.panelHi, fg: C.gold, stroke: C.goldSoft, ...o });
export const sidePill = (g: G, x: number, y: number, side: string, o: Parameters<typeof pill>[4] = {}) =>
  pill(g, x, y, side, { bg: side === "LONG" ? C.bull : C.bear, fg: C.ink, ...o });

function radial(g: G, cx: number, cy: number, r: number, rgba: string) {
  const gr = g.createRadialGradient(cx, cy, 0, cx, cy, r);
  gr.addColorStop(0, rgba); gr.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = gr; g.fillRect(0, 0, g.canvas.width, g.canvas.height);
}

/** Warm-black gradient, gold glows, double gold frame. */
export function backdrop(g: G, W: number, H: number) {
  const bg = g.createLinearGradient(0, 0, 0, H);
  bg.addColorStop(0, "#14110b"); bg.addColorStop(1, "#040406");
  g.fillStyle = bg; g.fillRect(0, 0, W, H);
  radial(g, W * 0.12, 70, W * 0.62, "rgba(240,185,11,0.16)");
  radial(g, W * 0.88, H * 0.55, W * 0.7, "rgba(240,185,11,0.09)");
  rrect(g, 16, 16, W - 32, H - 32, 36); g.strokeStyle = "rgba(199,160,64,0.85)"; g.lineWidth = 3; g.stroke();
  rrect(g, 26, 26, W - 52, H - 52, 30); g.strokeStyle = "rgba(240,185,11,0.14)"; g.lineWidth = 1.5; g.stroke();
}

/** Logo + brand name + gold subtitle, top-left. Returns the y below the header. */
export async function header(g: G, subtitle: string, top = 64): Promise<number> {
  const logo = await loadImg("/brand/logo-192.png");
  const s = 80;
  if (logo) {
    g.save();
    g.shadowColor = "rgba(240,185,11,0.55)"; g.shadowBlur = 28;
    rrect(g, M, top, s, s, 20); g.fillStyle = "#000"; g.fill();
    g.restore();
    g.save(); rrect(g, M, top, s, s, 20); g.clip(); g.drawImage(logo, M, top, s, s); g.restore();
  }
  const tx = M + (logo ? s + 24 : 0);
  text(g, "CRYPTO INTELLIGENCE AI", tx, top + 36, { weight: 800, px: 30, maxW: g.canvas.width - tx - M });
  text(g, subtitle, tx, top + 70, { weight: 600, px: 22, color: C.gold, maxW: g.canvas.width - tx - M });
  return top + s;
}

/** Hairline, site in gold left, note right, small disclaimer lines below. `top` = y of the hairline. */
export function footer(g: G, W: number, top: number, note: string, small: string[]) {
  g.fillStyle = C.line; g.fillRect(M, top, W - 2 * M, 2);
  text(g, SITE_HOST, M, top + 44, { weight: 800, px: 26, color: C.gold });
  g.font = font(800, 26);
  const siteW = g.measureText(SITE_HOST).width;
  text(g, note, W - M, top + 44, { weight: 500, px: 20, color: C.mute, align: "right", maxW: W - 2 * M - siteW - 32 });
  small.forEach((ln, k) => text(g, ln, M, top + 80 + k * 26, { weight: 500, px: 17, color: C.dim, maxW: W - 2 * M }));
}

/** Word-wrap to lines no wider than maxW in the current font (last line ellipsised when over n). Balanced: when
 *  the last line would be a lone short word, the width is narrowed so the lines come out even. */
export function wrap(g: G, t: string, maxW: number, n = 3): string[] {
  const first = wrapRaw(g, t, maxW, n);
  if (first.length < 2 || first.length > n) return first;
  let best = first;
  for (let w = maxW - 8; w > maxW * 0.55; w -= 8) {
    const alt = wrapRaw(g, t, w, n);
    if (alt.length !== first.length || alt[alt.length - 1].endsWith("…")) break;
    best = alt;
    const lastW = g.measureText(alt[alt.length - 1]).width;
    if (lastW >= w * 0.45) break;
  }
  return best;
}

function wrapRaw(g: G, t: string, maxW: number, n: number): string[] {
  const out: string[] = []; let line = "";
  for (const w of t.split(" ")) {
    const next = line ? `${line} ${w}` : w;
    if (g.measureText(next).width > maxW && line) { out.push(line); line = w; } else line = next;
  }
  if (line) out.push(line);
  if (out.length <= n) return out;
  const keep = out.slice(0, n);
  let last = keep[n - 1];
  while (last.length > 1 && g.measureText(last + "…").width > maxW) last = last.slice(0, -1);
  keep[n - 1] = last + "…";
  return keep;
}

export function download(cv: HTMLCanvasElement, name: string) {
  const a = document.createElement("a"); a.download = name; a.href = cv.toDataURL("image/png"); a.click();
}
