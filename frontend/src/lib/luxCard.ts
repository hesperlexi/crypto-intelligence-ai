// v2.37 premium share images (restyled v2.77, see L below) (owner, 14 Nov 2026: "a premium look that attracts users"): weekly report, achievements,
// Hesper Challenge. Private-bank black and gold: warm black with a diagonal gold light, fine gold grain, the round logo
// artwork as a faint watermark, a gold-foil frame, Sora display figures filled with a metallic gold gradient (losses stay
// red), an editorial left-aligned layout with hairline dividers instead of boxes. Numbers are exactly the page's.
import { SITE_HOST } from "./brand";

// v2.77 "Midnight & gold" (owner brief, 22 Nov 2026): the same family as the Telegram cards (backend services/cards.py) -
// midnight-navy background with a cool light top right and a faint warm light bottom left, one thin gold orbit arc, a hairline
// frame with gold corner marks, controlled gold only for brand marks and key labels, green gains / red losses, silver text.
export const L = {
  gold: "#d9b45f", soft: "#d9b45f", light: "#f2dfa6", text: "#f4f6fb", mute: "#9ca6ba", dim: "#6e788e", bull: "#34c98b", bear: "#e8616a",
  line: "rgba(38,50,78,1)", hair: "rgba(156,166,186,0.16)", panel: "#0f1626",
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
export const inter = (w: number, px: number) => `${w} ${px}px "DM Sans Variable", "DM Sans", Inter, system-ui, -apple-system, "Segoe UI", sans-serif`;

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
  gr.addColorStop(0, "#a8873f"); gr.addColorStop(0.35, "#d9b45f"); gr.addColorStop(0.55, "#f2dfa6");
  gr.addColorStop(0.75, "#d0aa55"); gr.addColorStop(1, "#9a7a38");
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

/** Background (midnight navy, cool / warm lights, the orbit, faint stars) and the hairline frame with gold corner marks. */
export async function luxBackground(g: G, W: number, H: number) {
  const bg = g.createLinearGradient(0, 0, 0, H);
  bg.addColorStop(0, "#0c1222"); bg.addColorStop(1, "#05080f");
  g.fillStyle = bg; g.fillRect(0, 0, W, H);
  const cool = g.createRadialGradient(W * 0.92, H * 0.05, 0, W * 0.92, H * 0.05, W * 0.95);
  cool.addColorStop(0, "rgba(26,44,82,0.85)"); cool.addColorStop(1, "rgba(26,44,82,0)");
  g.fillStyle = cool; g.fillRect(0, 0, W, H);
  const warm = g.createRadialGradient(0, H, 0, 0, H, W * 0.85);
  warm.addColorStop(0, "rgba(60,44,14,0.45)"); warm.addColorStop(1, "rgba(60,44,14,0)");
  g.fillStyle = warm; g.fillRect(0, 0, W, H);
  const v = g.createRadialGradient(W / 2, H / 2, W * 0.45, W / 2, H / 2, Math.max(W, H) * 0.85);
  v.addColorStop(0, "rgba(0,0,0,0)"); v.addColorStop(1, "rgba(0,0,0,0.45)");
  g.fillStyle = v; g.fillRect(0, 0, W, H);
  // the orbit: one thin gold ellipse off the right edge and a fainter cool one inside it
  g.save();
  g.strokeStyle = "rgba(217,180,95,0.10)"; g.lineWidth = 2;
  g.beginPath(); g.ellipse(W * 1.02, H * 0.40, W * 0.62, W * 0.36, 0, 0, Math.PI * 2); g.stroke();
  g.strokeStyle = "rgba(120,150,210,0.08)"; g.lineWidth = 1;
  g.beginPath(); g.ellipse(W * 1.02, H * 0.40, W * 0.48, W * 0.28, 0, 0, Math.PI * 2); g.stroke();
  let seed = 11;
  const r = () => ((seed = (seed * 9301 + 49297) % 233280) / 233280);
  for (let i = 0; i < 70; i++) {
    g.globalAlpha = 0.1 + r() * 0.22; g.fillStyle = "#c8d2eb";
    g.beginPath(); g.arc(r() * W, r() * H, 0.6 + r() * 1.1, 0, Math.PI * 2); g.fill();
  }
  g.restore();
  // frame: hairline, gold marks hugging the top-left and bottom-right corners
  const o = 26, rad = 28, len = 40 * (W / 1080);
  g.save();
  g.strokeStyle = "rgba(34,45,72,1)"; g.lineWidth = 1;
  g.beginPath(); g.roundRect(o, o, W - 2 * o, H - 2 * o, rad); g.stroke();
  g.strokeStyle = L.gold; g.lineWidth = 2;
  g.beginPath(); g.moveTo(o, o + rad + len); g.lineTo(o, o + rad); g.arc(o + rad, o + rad, rad, Math.PI, Math.PI * 1.5); g.lineTo(o + rad + len, o); g.stroke();
  const x1 = W - o, y1 = H - o;
  g.beginPath(); g.moveTo(x1, y1 - rad - len); g.lineTo(x1, y1 - rad); g.arc(x1 - rad, y1 - rad, rad, 0, Math.PI * 0.5); g.lineTo(x1 - rad - len, y1); g.stroke();
  g.restore();
}

/** Brand line (logo + spaced name) and a tag on the right. Returns the y below it. */
export async function luxBrand(g: G, W: number, M: number, top: number, tag: string): Promise<number> {
  const logo = await img("/brand/logo-192.png");
  const s = 64;
  if (logo) {
    g.save(); g.shadowColor = "rgba(217,180,95,0.45)"; g.shadowBlur = 20;
    g.beginPath(); g.arc(M + s / 2, top + s / 2, s / 2, 0, Math.PI * 2); g.fillStyle = "#000"; g.fill(); g.restore();
    g.save(); g.beginPath(); g.arc(M + s / 2, top + s / 2, s / 2, 0, Math.PI * 2); g.clip(); g.drawImage(logo, M, top, s, s); g.restore();
    g.save(); g.strokeStyle = "rgba(120,98,52,1)"; g.lineWidth = 1; g.beginPath(); g.arc(M + s / 2, top + s / 2, s / 2, 0, Math.PI * 2); g.stroke(); g.restore();
  }
  txt(g, "CRYPTO INTELLIGENCE AI", M + s + 20, top + 28, { f: sora, w: 700, px: 19, track: 4.2, color: L.text });
  txt(g, SITE_HOST, M + s + 20, top + 56, { w: 500, px: 18, color: L.mute });
  g.save();
  g.font = sora(700, 14); spaced(g, 2.6);
  const tw = g.measureText(tag).width + 40;
  g.fillStyle = "#161618"; g.strokeStyle = "rgba(120,98,52,1)"; g.lineWidth = 1;
  g.beginPath(); g.roundRect(W - M - tw, top + 12, tw, 38, 19); g.fill(); g.stroke();
  g.restore();
  txt(g, tag, W - M - tw / 2, top + 36, { f: sora, w: 700, px: 14, track: 2.6, color: L.gold, align: "center" });
  // hairline under the header: gold fading into navy
  const hl = g.createLinearGradient(M, 0, W - M, 0);
  hl.addColorStop(0, "rgba(217,180,95,0.9)"); hl.addColorStop(0.7, "rgba(38,50,78,1)"); hl.addColorStop(1, "rgba(38,50,78,1)");
  g.fillStyle = hl; g.fillRect(M, top + s + 18, W - 2 * M, 1);
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
  const [top, bot, glow] = o.gold ? ["#f2dfa6", "#d9b45f", "rgba(217,180,95,0.35)"]
    : good ? ["#9be6c6", "#34c98b", "rgba(52,201,139,0.35)"] : ["#f3b0b5", "#e8616a", "rgba(232,97,106,0.25)"];
  const gr = g.createLinearGradient(0, y - size * 0.75, 0, y);
  gr.addColorStop(0, top); gr.addColorStop(1, bot);
  g.shadowColor = glow; g.shadowBlur = size * 0.22;
  g.fillStyle = gr;
  g.fillText(t, x0, y);
  g.restore();
  return { w, px: size };
}

/** Running-total line with a gold area under it and a glowing end point; dashed zero line. */
export function curveChart(g: G, x: number, y: number, w: number, h: number, pts: number[], good: boolean) {
  if (pts.length < 2) return;
  const lo = Math.min(0, ...pts), hi = Math.max(0, ...pts), span = hi - lo || 1;
  const X = (i: number) => x + (i / (pts.length - 1)) * w, Y = (v: number) => y + h - ((v - lo) / span) * h;
  const col = good ? "52,201,139" : "232,97,106";
  g.save();
  g.setLineDash([4, 8]); g.strokeStyle = L.hair; g.lineWidth = 1.5;
  g.beginPath(); g.moveTo(x, Y(0)); g.lineTo(x + w, Y(0)); g.stroke(); g.setLineDash([]);
  const area = g.createLinearGradient(0, y, 0, y + h);
  area.addColorStop(0, `rgba(${col},0.30)`); area.addColorStop(1, `rgba(${col},0)`);
  g.beginPath(); g.moveTo(X(0), Y(0)); pts.forEach((v, i) => g.lineTo(X(i), Y(v))); g.lineTo(X(pts.length - 1), Y(0)); g.closePath();
  g.fillStyle = area; g.fill();
  g.beginPath(); pts.forEach((v, i) => (i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v))));
  g.strokeStyle = good ? L.bull : L.bear; g.lineWidth = 4; g.lineJoin = "round";
  g.shadowColor = `rgba(${col},0.5)`; g.shadowBlur = 10; g.stroke();
  const ex = X(pts.length - 1), ey = Y(pts[pts.length - 1]);
  g.fillStyle = good ? L.bull : L.bear; g.shadowBlur = 12;
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

/** Footer: hairline with a short gold segment, the call to action in white, small print. */
export function luxFooter(g: G, W: number, M: number, top: number, cta: string, small: string[]) {
  g.fillStyle = L.line; g.fillRect(M, top, W - 2 * M, 1);
  g.fillStyle = L.gold; g.fillRect(M, top - 0.5, 120, 2);
  txt(g, cta, M, top + 48, { f: sora, w: 700, px: 26, color: L.text, maxW: W - 2 * M });
  small.forEach((s, k) => txt(g, s, M, top + 82 + k * 24, { w: 500, px: 16, color: L.dim, maxW: W - 2 * M }));
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
