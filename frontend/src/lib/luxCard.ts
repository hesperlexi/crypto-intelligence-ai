// v2.37 premium share images (restyled v2.77, see L below) (owner, 14 Nov 2026: "a premium look that attracts users"): weekly report, achievements,
// Hesper Challenge. Private-bank black and gold: warm black with a diagonal gold light, fine gold grain, the round logo
// artwork as a faint watermark, a gold-foil frame, Sora display figures filled with a metallic gold gradient (losses stay
// red), an editorial left-aligned layout with hairline dividers instead of boxes. Numbers are exactly the page's.
import { SITE_HOST } from "./brand";

// v2.77 "Midnight & gold" (owner brief, 22 Nov 2026): the same family as the Telegram cards (backend services/cards.py) -
// midnight-navy background with a cool light top right and a faint warm light bottom left, one thin gold orbit arc, a hairline
// frame with gold corner marks, controlled gold only for brand marks and key labels, green gains / red losses, silver text.
export const L = {
  // V3.0 (24 Nov 2026): graphite + the logo's gold (#E8B637) and cyan, no space
  // V3.1 (owner, 24 Nov 2026: "rework all the shareable cards"): Binance-style greys / greens / reds, IBM Plex Sans only
  gold: "#e8b637", soft: "#e8b637", light: "#f6e37a", text: "#eaecef", mute: "#848e9c", dim: "#5e6673", bull: "#0ecb81", bear: "#f6465d",
  line: "rgba(48,50,58,1)", hair: "rgba(234,236,239,0.10)", panel: "#1c1d23", cyan: "#5df1dd",
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
export const sora = (w: number, px: number) => `${Math.min(w, 700)} ${px}px "IBM Plex Sans", Inter, system-ui, sans-serif`;   // V3.0: Binance-style single family
export const inter = (w: number, px: number) => `${Math.min(w, 700)} ${px}px "IBM Plex Sans", Inter, system-ui, -apple-system, "Segoe UI", sans-serif`;

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
  gr.addColorStop(0, "#e8b637"); gr.addColorStop(1, "#f0c75a");      // V3.1: flat gold, no metallic foil
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

/** V3.1 background: graphite (lighter at the top), the logo's neural mesh in the top-right corner (cyan links, green /
 *  red neurons). No frame: the footer band closes the card. */
export async function luxBackground(g: G, W: number, H: number) {
  const bg = g.createLinearGradient(0, 0, 0, H);
  bg.addColorStop(0, "#17181d"); bg.addColorStop(1, "#101114");
  g.fillStyle = bg; g.fillRect(0, 0, W, H);
  const warm = g.createRadialGradient(W * 0.92, 0, 0, W * 0.92, 0, W * 0.75);
  warm.addColorStop(0, "rgba(232,182,55,0.07)"); warm.addColorStop(1, "rgba(232,182,55,0)");
  g.fillStyle = warm; g.fillRect(0, 0, W, H);
  g.save();
  let seed = 13;
  const r = () => ((seed = (seed * 9301 + 49297) % 233280) / 233280);
  const k = W / 1080, pts: number[][] = [];
  while (pts.length < 22) {
    const x = W * (0.52 + r() * 0.5), y = 1350 * k * (r() * 0.13);
    if (!(x > W - 72 * k - 260 * k && y > 50 * k && y < 130 * k)) pts.push([x, y]);
  }
  g.lineWidth = 1;
  for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++) {
    const d = Math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]);
    if (d < W * 0.13) { g.strokeStyle = `rgba(93,241,221,${0.28 * (1 - d / (W * 0.13))})`; g.beginPath(); g.moveTo(pts[i][0], pts[i][1]); g.lineTo(pts[j][0], pts[j][1]); g.stroke(); }
  }
  pts.forEach(([x, y], i) => { g.fillStyle = i % 2 ? "rgba(246,70,93,0.6)" : "rgba(14,203,129,0.6)"; g.beginPath(); g.arc(x, y, 3 * k, 0, Math.PI * 2); g.fill(); });
  g.restore();
}

/** Header: logo tile, name, the site, a gold tag on the right, a divider. Returns the y of the logo's bottom. */
export async function luxBrand(g: G, W: number, M: number, top: number, tag: string): Promise<number> {
  const logo = await img("/brand/logo-192.png");
  const s = 76;
  if (logo) g.drawImage(logo, M, top, s, s);
  txt(g, "Crypto Intelligence AI", M + s + 20, top + 34, { w: 600, px: 30, color: L.text });
  txt(g, SITE_HOST, M + s + 20, top + 66, { w: 400, px: 21, color: L.mute });
  g.save();
  g.font = inter(600, 17); spaced(g, 0.6);
  const tw = g.measureText(tag).width + 32;
  g.fillStyle = "#2c2512";
  g.beginPath(); g.roundRect(W - M - tw, top + 18, tw, 40, 8); g.fill();
  g.restore();
  txt(g, tag, W - M - tw / 2, top + 44, { w: 600, px: 17, track: 0.6, color: L.gold, align: "center" });
  g.fillStyle = L.line; g.fillRect(M, top + s + 32, W - 2 * M, 1);
  return top + s;
}

/** A big figure: green for a gain, red for a loss (never dressed up), soft glow, light-to-full gradient. */
export function figure(g: G, t: string, x: number, y: number, px: number, good: boolean, o: { align?: CanvasTextAlign; maxW?: number; gold?: boolean } = {}) {
  g.save();
  g.font = sora(800, px);
  let size = px;
  while (o.maxW && size > 24 && g.measureText(t).width > o.maxW) { size -= 4; g.font = sora(800, size); }
  const w = g.measureText(t).width;
  const x0 = o.align === "center" ? x - w / 2 : o.align === "right" ? x - w : x;
  g.textAlign = "left"; g.textBaseline = "alphabetic";
  g.fillStyle = o.gold ? L.gold : good ? L.bull : L.bear;      // V3.1: flat colour, no glow
  g.fillText(t, x0, y);
  g.restore();
  return { w, px: size };
}

/** Running-total line with a gold area under it and a glowing end point; dashed zero line. */
export function curveChart(g: G, x: number, y: number, w: number, h: number, pts: number[], good: boolean) {
  if (pts.length < 2) return;
  const lo = Math.min(0, ...pts), hi = Math.max(0, ...pts), span = hi - lo || 1;
  const X = (i: number) => x + (i / (pts.length - 1)) * w, Y = (v: number) => y + h - ((v - lo) / span) * h;
  const col = good ? "14,203,129" : "246,70,93";
  g.save();
  g.setLineDash([4, 8]); g.strokeStyle = L.hair; g.lineWidth = 1.5;
  g.beginPath(); g.moveTo(x, Y(0)); g.lineTo(x + w, Y(0)); g.stroke(); g.setLineDash([]);
  const area = g.createLinearGradient(0, y, 0, y + h);
  area.addColorStop(0, `rgba(${col},0.30)`); area.addColorStop(1, `rgba(${col},0)`);
  g.beginPath(); g.moveTo(X(0), Y(0)); pts.forEach((v, i) => g.lineTo(X(i), Y(v))); g.lineTo(X(pts.length - 1), Y(0)); g.closePath();
  g.fillStyle = area; g.fill();
  g.beginPath(); pts.forEach((v, i) => (i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v))));
  g.strokeStyle = good ? L.bull : L.bear; g.lineWidth = 4; g.lineJoin = "round";
  g.stroke();
  const ex = X(pts.length - 1), ey = Y(pts[pts.length - 1]);
  g.fillStyle = good ? L.bull : L.bear;
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

/** V3.1 footer: a solid band from `top` to the bottom with a gold rule, the call to action in gold, small print. */
export function luxFooter(g: G, W: number, M: number, top: number, cta: string, small: string[]) {
  const H = g.canvas.height, y0 = top - 26;
  g.fillStyle = "#0d0e11"; g.fillRect(0, y0, W, H - y0);
  g.fillStyle = L.gold; g.fillRect(0, y0, W, 2);
  txt(g, cta, M, top + 38, { w: 600, px: 27, color: L.gold, maxW: W - 2 * M });
  small.forEach((s, k) => txt(g, s, M, top + 74 + k * 24, { w: 400, px: 16, color: L.dim, maxW: W - 2 * M }));
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
