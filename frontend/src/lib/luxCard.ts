// v2.37 premium share images (owner, 14 Nov 2026: "a premium look that attracts users"): weekly report, achievements,
// Hesper Challenge. Private-bank black and gold: warm black with a diagonal gold light, fine gold grain, the round logo
// artwork as a faint watermark, a gold-foil frame, Sora display figures filled with a metallic gold gradient (losses stay
// red), an editorial left-aligned layout with hairline dividers instead of boxes. Numbers are exactly the page's.
import { SITE_HOST } from "./brand";

export const L = {
  gold: "#f0b90b", soft: "#c9a24a", text: "#f5f1e6", mute: "#a39c8c", dim: "#76705f", bull: "#16c784", bear: "#f6465d",
  line: "rgba(240,185,11,0.18)", hair: "rgba(245,241,230,0.10)",
};
type G = CanvasRenderingContext2D;

// v2.38: older phones (Chrome < 99, Safari < 16) have no canvas roundRect, which stopped the share images there
if (typeof CanvasRenderingContext2D !== "undefined" && !(CanvasRenderingContext2D.prototype as any).roundRect) {
  (CanvasRenderingContext2D.prototype as any).roundRect = function (this: G, x: number, y: number, w: number, h: number, r: number) {
    const rr = Math.max(0, Math.min(r, w / 2, h / 2));
    this.moveTo(x + rr, y); this.arcTo(x + w, y, x + w, y + h, rr); this.arcTo(x + w, y + h, x, y + h, rr);
    this.arcTo(x, y + h, x, y, rr); this.arcTo(x, y, x + w, y, rr); this.closePath();
  };
}
export const sora = (w: number, px: number) => `${w} ${px}px Sora, Inter, system-ui, sans-serif`;
export const inter = (w: number, px: number) => `${w} ${px}px Inter, system-ui, -apple-system, "Segoe UI", sans-serif`;

export async function luxReady() {
  try {
    await Promise.all([
      ...[800, 700, 600].map((w) => document.fonts.load(sora(w, 40), "0123456789+-.%$ABCabc")),
      ...[700, 600, 500].map((w) => document.fonts.load(inter(w, 20), "0123456789ABCabc")),
    ]);
    await document.fonts.ready;
  } catch { /* system fallback */ }
}

function img(src: string): Promise<HTMLImageElement | null> {
  return new Promise((res) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => res(null); i.src = src; });
}

/** Metallic gold for large figures and the frame. */
export function foil(g: G, x0: number, y0: number, x1: number, y1: number): CanvasGradient {
  const gr = g.createLinearGradient(x0, y0, x1, y1);
  gr.addColorStop(0, "#9c6f0a"); gr.addColorStop(0.28, "#f0b90b"); gr.addColorStop(0.5, "#fff1c4");
  gr.addColorStop(0.7, "#e7ae17"); gr.addColorStop(1, "#8f650a");
  return gr;
}

function spaced(g: G, px: number) { try { (g as any).letterSpacing = `${px}px`; } catch { /* older browsers */ } }

/** Text on an alphabetic baseline; shrinks to maxW. Returns the drawn width. */
export function txt(g: G, t: string, x: number, y: number, o: { f?: (w: number, px: number) => string; w?: number; px?: number; color?: string | CanvasGradient; align?: CanvasTextAlign; maxW?: number; track?: number; glow?: string; blur?: number } = {}): number {
  const f = o.f ?? inter;
  let px = o.px ?? 24;
  g.save();
  spaced(g, o.track ?? 0);
  g.font = f(o.w ?? 500, px);
  while (o.maxW && px > 12 && g.measureText(t).width > o.maxW) { px -= 2; g.font = f(o.w ?? 500, px); }
  g.textAlign = o.align ?? "left"; g.textBaseline = "alphabetic";
  if (o.glow) { g.shadowColor = o.glow; g.shadowBlur = o.blur ?? 30; }
  g.fillStyle = o.color ?? L.text;
  g.fillText(t, x, y);
  const w = g.measureText(t).width;
  g.restore();
  return w;
}

/** Background, grain, watermark and the gold-foil frame. */
export async function luxBackground(g: G, W: number, H: number) {
  const bg = g.createLinearGradient(0, 0, W * 0.3, H);
  bg.addColorStop(0, "#15120c"); bg.addColorStop(0.55, "#0a0907"); bg.addColorStop(1, "#050505");
  g.fillStyle = bg; g.fillRect(0, 0, W, H);
  // a diagonal beam of warm light from the top left
  g.save();
  g.translate(W * 0.15, -H * 0.05); g.rotate(0.62);
  const beam = g.createLinearGradient(-W * 0.18, 0, W * 0.18, 0);
  beam.addColorStop(0, "rgba(240,185,11,0)"); beam.addColorStop(0.5, "rgba(240,185,11,0.075)"); beam.addColorStop(1, "rgba(240,185,11,0)");
  g.fillStyle = beam; g.fillRect(-W * 0.18, -H, W * 0.36, H * 3);
  g.restore();
  const glow = g.createRadialGradient(W * 0.85, H * 0.12, 0, W * 0.85, H * 0.12, W * 0.6);
  glow.addColorStop(0, "rgba(240,185,11,0.10)"); glow.addColorStop(1, "rgba(240,185,11,0)");
  g.fillStyle = glow; g.fillRect(0, 0, W, H);
  // watermark: the round logo artwork, very faint, bottom right
  const art = await img("/brand/logo-art-384.webp");
  if (art) {
    const s = W * 0.74;
    g.save(); g.globalAlpha = 0.04; g.filter = "grayscale(1) sepia(1)"; g.translate(W - s * 0.36, H - s * 0.42); g.rotate(-0.18);
    g.beginPath(); g.arc(0, 0, s / 2, 0, Math.PI * 2); g.clip(); g.drawImage(art, -s / 2, -s / 2, s, s); g.restore();
  }
  // fine gold grain
  let seed = 3;
  const r = () => ((seed = (seed * 9301 + 49297) % 233280) / 233280);
  g.save();
  for (let i = 0; i < (W * H) / 260; i++) {
    g.globalAlpha = 0.03 + r() * 0.06;
    g.fillStyle = r() < 0.5 ? "#f0b90b" : "#fff1c4";
    g.fillRect(r() * W, r() * H, 1, 1);
  }
  g.restore();
  // vignette
  const v = g.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.35, W / 2, H / 2, Math.max(W, H) * 0.75);
  v.addColorStop(0, "rgba(0,0,0,0)"); v.addColorStop(1, "rgba(0,0,0,0.55)");
  g.fillStyle = v; g.fillRect(0, 0, W, H);
  // frame: gold foil line, a faint inner line, small diamonds at the corners
  const o = 30;
  g.save();
  g.strokeStyle = foil(g, 0, 0, W, H); g.lineWidth = 2.5;
  g.beginPath(); g.roundRect(o, o, W - 2 * o, H - 2 * o, 26); g.stroke();
  g.strokeStyle = "rgba(240,185,11,0.16)"; g.lineWidth = 1;
  g.beginPath(); g.roundRect(o + 10, o + 10, W - 2 * o - 20, H - 2 * o - 20, 20); g.stroke();
  g.fillStyle = foil(g, 0, 0, W, H);
  for (const [x, y] of [[W / 2, o], [W / 2, H - o]]) {
    g.beginPath(); g.moveTo(x, y - 7); g.lineTo(x + 7, y); g.lineTo(x, y + 7); g.lineTo(x - 7, y); g.closePath(); g.fill();
  }
  g.restore();
}

/** Brand line (logo + spaced name) and a tag on the right. Returns the y below it. */
export async function luxBrand(g: G, W: number, M: number, top: number, tag: string): Promise<number> {
  const logo = await img("/brand/logo-192.png");
  const s = 60;
  if (logo) {
    g.save(); g.shadowColor = "rgba(240,185,11,0.5)"; g.shadowBlur = 24;
    g.beginPath(); g.roundRect(M, top, s, s, 14); g.fillStyle = "#000"; g.fill(); g.restore();
    g.save(); g.beginPath(); g.roundRect(M, top, s, s, 14); g.clip(); g.drawImage(logo, M, top, s, s); g.restore();
  }
  txt(g, "CRYPTO INTELLIGENCE AI", M + s + 22, top + 26, { f: sora, w: 700, px: 20, track: 4, color: L.text });
  txt(g, SITE_HOST, M + s + 22, top + 52, { w: 500, px: 17, color: L.soft, track: 1 });
  g.save();
  g.font = sora(700, 15); spaced(g, 3);
  const tw = g.measureText(tag).width + 40;
  g.strokeStyle = foil(g, W - M - tw, top, W - M, top + 40); g.lineWidth = 1.5;
  g.beginPath(); g.roundRect(W - M - tw, top + 10, tw, 38, 19); g.stroke();
  g.restore();
  txt(g, tag, W - M - tw / 2, top + 35, { f: sora, w: 700, px: 15, track: 3, color: L.gold, align: "center" });
  return top + s;
}

/** A big figure: metallic gold when it is good news, plain red when it is not (losses are never dressed up). */
export function figure(g: G, t: string, x: number, y: number, px: number, good: boolean, o: { align?: CanvasTextAlign; maxW?: number } = {}) {
  g.save();
  g.font = sora(800, px);
  let size = px;
  while (o.maxW && size > 24 && g.measureText(t).width > o.maxW) { size -= 4; g.font = sora(800, size); }
  const w = g.measureText(t).width;
  const x0 = o.align === "center" ? x - w / 2 : o.align === "right" ? x - w : x;
  g.textAlign = "left"; g.textBaseline = "alphabetic";
  g.shadowColor = good ? "rgba(240,185,11,0.45)" : "rgba(246,70,93,0.45)"; g.shadowBlur = size * 0.35;
  g.fillStyle = good ? foil(g, x0, y - size, x0 + w, y) : L.bear;
  g.fillText(t, x0, y);
  g.restore();
  return { w, px: size };
}

/** Running-total line with a gold area under it and a glowing end point; dashed zero line. */
export function curveChart(g: G, x: number, y: number, w: number, h: number, pts: number[], good: boolean) {
  if (pts.length < 2) return;
  const lo = Math.min(0, ...pts), hi = Math.max(0, ...pts), span = hi - lo || 1;
  const X = (i: number) => x + (i / (pts.length - 1)) * w, Y = (v: number) => y + h - ((v - lo) / span) * h;
  const col = good ? "240,185,11" : "246,70,93";
  g.save();
  g.setLineDash([4, 8]); g.strokeStyle = L.hair; g.lineWidth = 1.5;
  g.beginPath(); g.moveTo(x, Y(0)); g.lineTo(x + w, Y(0)); g.stroke(); g.setLineDash([]);
  const area = g.createLinearGradient(0, y, 0, y + h);
  area.addColorStop(0, `rgba(${col},0.30)`); area.addColorStop(1, `rgba(${col},0)`);
  g.beginPath(); g.moveTo(X(0), Y(0)); pts.forEach((v, i) => g.lineTo(X(i), Y(v))); g.lineTo(X(pts.length - 1), Y(0)); g.closePath();
  g.fillStyle = area; g.fill();
  g.beginPath(); pts.forEach((v, i) => (i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v))));
  g.strokeStyle = good ? foil(g, x, 0, x + w, 0) : L.bear; g.lineWidth = 4; g.lineJoin = "round";
  g.shadowColor = `rgba(${col},0.7)`; g.shadowBlur = 16; g.stroke();
  const ex = X(pts.length - 1), ey = Y(pts[pts.length - 1]);
  g.fillStyle = good ? "#fff1c4" : L.bear; g.shadowBlur = 24;
  g.beginPath(); g.arc(ex, ey, 7, 0, Math.PI * 2); g.fill();
  g.strokeStyle = `rgba(${col},0.5)`; g.lineWidth = 2; g.shadowBlur = 0;
  g.beginPath(); g.arc(ex, ey, 14, 0, Math.PI * 2); g.stroke();
  g.restore();
}

/** Stats in a row, separated by thin gold hairlines (no boxes). */
export function statRow(g: G, x: number, y: number, w: number, items: [string, string, string?][], px = 52) {
  const cw = w / items.length;
  items.forEach(([k, v, c], i) => {
    const cx = x + i * cw;
    if (i) { g.fillStyle = L.line; g.fillRect(cx, y - px - 6, 1.5, px + 40); }
    const pad = i ? 32 : 0;
    txt(g, v, cx + pad, y, { f: sora, w: 700, px, color: c ?? L.text, maxW: cw - pad - 16 });
    txt(g, k, cx + pad, y + 34, { w: 500, px: 19, color: L.mute, maxW: cw - pad - 16 });
  });
}

/** Footer: a gold hairline, a call to action in foil, small print. */
export function luxFooter(g: G, W: number, M: number, top: number, cta: string, small: string[]) {
  g.fillStyle = L.line; g.fillRect(M, top, W - 2 * M, 1.5);
  g.fillStyle = foil(g, M, 0, M + 180, 0); g.fillRect(M, top - 1, 180, 3);
  txt(g, cta, M, top + 46, { f: sora, w: 700, px: 26, color: foil(g, M, top, M + 600, top + 40), maxW: W - 2 * M });
  small.forEach((s, k) => txt(g, s, M, top + 80 + k * 24, { w: 500, px: 16, color: L.dim, maxW: W - 2 * M }));
}

/** Word-wrap in the given font to maxW, at most n lines (last one ellipsised). */
export function wrapLines(g: G, t: string, font: string, maxW: number, n = 2): string[] {
  g.font = font;
  const out: string[] = [];
  let cur = "";
  for (const w of t.split(/\s+/)) {
    const tryL = cur ? `${cur} ${w}` : w;
    if (cur && g.measureText(tryL).width > maxW) { out.push(cur); cur = w; } else cur = tryL;
  }
  if (cur) out.push(cur);
  if (out.length > n) { out.length = n; out[n - 1] = out[n - 1].replace(/\s+\S*$/, "") + "…"; }
  return out;
}
