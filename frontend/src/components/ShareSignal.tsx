// v2.44 one-tap share image of a signal (1080 x 1350, story-friendly), drawn in the browser with the premium kit.
// A teaser: coin, side, timeframe, grade and how the call is doing now - never the entry / stop / targets, so the paid
// plan stays in the app. Shared through the phone's share sheet when it supports images, else downloaded.
import { useState } from "react";
import { base, isNum } from "../lib/format";
import { useLive } from "../lib/live";
import { figure, L, luxBackground, luxBrand, luxFooter, luxReady, sora, txt } from "../lib/luxCard";

function pill(g: CanvasRenderingContext2D, x: number, y: number, t: string, color: string, fill: string, edge: string): number {
  g.save(); g.font = sora(700, 17); try { (g as any).letterSpacing = "2px"; } catch { /* old browsers */ }
  const w = g.measureText(t).width + 38;
  g.fillStyle = fill; g.strokeStyle = edge; g.lineWidth = 1;
  g.beginPath(); g.roundRect(x, y, w, 42, 21); g.fill(); g.stroke(); g.restore();
  txt(g, t, x + w / 2, y + 28, { f: sora, w: 700, px: 17, track: 2, color, align: "center" });
  return x + w;
}

/** v2.77 same family as the Telegram result cards: header, pills, coin, live move, the trade rail (no prices), how it is managed. */
async function draw(r: any, plan: any, label: string, px: number | null): Promise<Blob | null> {
  const W = 1080, H = 1350, M = 72;
  const cv = document.createElement("canvas");
  cv.width = W; cv.height = H;
  const g = cv.getContext("2d")!;
  await luxReady();
  await luxBackground(g, W, H);
  await luxBrand(g, W, M, 66, "LIVE SIGNAL");
  const coin = base(r.symbol) === "PAXG" ? "GOLD" : base(r.symbol) === "XAG" ? "SILVER" : base(r.symbol);
  const long = (plan?.side ?? (r.side > 0 ? "LONG" : "SHORT")) === "LONG";
  const sc = long ? L.bull : L.bear;
  let x = pill(g, M, 214, long ? "LONG" : "SHORT", sc, long ? "rgba(52,201,139,0.14)" : "rgba(232,97,106,0.14)", sc);
  x = pill(g, x + 12, 214, String(r.timeframe ?? "").toUpperCase(), L.mute, "#151e32", L.line);
  pill(g, x + 12, 214, r.grade ? `GRADE ${r.grade}` : label.toUpperCase(), L.gold, "#1e1b14", "rgba(120,98,52,1)");
  const cw = txt(g, coin, M, 388, { f: sora, w: 800, px: 118, color: L.text, maxW: W - 2 * M - 170 });
  if (coin !== "GOLD" && coin !== "SILVER") txt(g, "/ USDT", M + cw + 16, 388, { f: sora, w: 600, px: 30, color: L.mute });
  // how it is doing now, in R and price move (no levels)
  const risk = plan && isNum(plan.entry) && isNum(plan.stop) ? Math.abs(plan.entry - plan.stop) : null;
  const s = long ? 1 : -1;
  const rNow = risk && isNum(px) ? (s * (px - plan.entry)) / risk : null;
  const mv = plan && isNum(px) && isNum(plan.entry) ? s * (px / plan.entry - 1) * 100 : null;
  txt(g, "SINCE ENTRY", M, 474, { w: 600, px: 16, track: 2.2, color: L.gold });
  if (rNow != null && mv != null) {
    figure(g, `${mv >= 0 ? "+" : ""}${mv.toFixed(2)}%`, M - 4, 636, 168, mv >= 0, { maxW: W - 2 * M });
    txt(g, `${rNow >= 0 ? "+" : ""}${rNow.toFixed(2)}R  ·  price move, no leverage`, M, 690, { w: 500, px: 24, color: L.mute });
  } else {
    txt(g, "New call", M, 620, { f: sora, w: 800, px: 120, color: L.text });
  }
  // the trade rail without prices: stop -> entry -> TP1-3, the live price as a dot
  const bx = M, by = 736, bw = W - 2 * M;
  g.fillStyle = L.panel; g.strokeStyle = L.line; g.lineWidth = 1;
  g.beginPath(); g.roundRect(bx, by, bw, 164, 22); g.fill(); g.stroke();
  const pos = [0, 0.3, 0.55, 0.75, 1], names = ["STOP", "ENTRY", "TP1", "TP2", "TP3"];
  const X = (p: number) => bx + 50 + p * (bw - 100), ly = by + 92;
  g.fillStyle = "rgba(38,50,78,1)"; g.fillRect(X(0), ly - 2, X(1) - X(0), 4);
  g.fillStyle = "rgba(232,97,106,0.45)"; g.fillRect(X(0), ly - 2, X(0.3) - X(0), 4);
  names.forEach((n, i) => {
    const cx = X(pos[i]), col = i === 0 ? L.bear : i === 1 ? L.gold : L.mute;
    if (i === 1) { g.fillStyle = L.gold; g.beginPath(); g.moveTo(cx, ly - 13); g.lineTo(cx + 13, ly); g.lineTo(cx, ly + 13); g.lineTo(cx - 13, ly); g.closePath(); g.fill(); }
    else { g.fillStyle = "#060911"; g.strokeStyle = col; g.lineWidth = 3; g.beginPath(); g.arc(cx, ly, 9, 0, Math.PI * 2); g.fill(); g.stroke(); }
    txt(g, n, cx, ly - 30, { w: 700, px: 14, track: 1.6, color: col, align: "center" });
  });
  if (rNow != null) {         // R mapped onto the rail: -1R = stop, 0 = entry, ~3R = last target
    const p = rNow < 0 ? 0.3 + Math.max(-1, rNow) * 0.3 : 0.3 + Math.min(3, rNow) / 3 * 0.7;
    g.save(); g.shadowColor = rNow >= 0 ? "rgba(52,201,139,0.7)" : "rgba(232,97,106,0.7)"; g.shadowBlur = 16;
    g.fillStyle = rNow >= 0 ? L.bull : L.bear; g.beginPath(); g.arc(X(p), ly, 11, 0, Math.PI * 2); g.fill(); g.restore();
    txt(g, "now", X(p), ly + 42, { w: 600, px: 16, color: L.text, align: "center" });
  }
  txt(g, "Prices for members in the app", bx + bw - 30, by + 150, { w: 500, px: 15, color: L.dim, align: "right" });
  // how the trade is managed (the same rules for every call)
  const runner = !!(plan?.runner?.on ?? plan?.runner ?? r?.runner);      // "let it run" calls close nothing before the final target
  const cells: [string, string][] = runner
    ? [["TP1", "Nothing closes, stop to break-even"], ["TP2", "Stop moves up to TP1"], ["1:4", "The whole position closes"]]
    : [["TP1", "Half closes, stop to break-even"], ["TP2", "A quarter closes, stop to TP1"], ["TP3", "The last quarter closes"]];
  const top = 924, ch = 236, cw3 = (W - 2 * M) / 3;
  g.fillStyle = L.panel; g.strokeStyle = L.line; g.beginPath(); g.roundRect(M, top, W - 2 * M, ch, 22); g.fill(); g.stroke();
  txt(g, "HOW IT IS MANAGED", M + 28, top + 44, { w: 600, px: 14, track: 2.2, color: L.gold });
  cells.forEach(([k, v], i) => {
    const cx = M + i * cw3;
    if (i) { g.fillStyle = L.line; g.fillRect(cx, top + 70, 1, ch - 100); }
    txt(g, k, cx + 28, top + 120, { f: sora, w: 700, px: 34, color: L.bull });
    const words = v.split(" "); const half = Math.ceil(words.length / 2);
    txt(g, words.slice(0, half).join(" "), cx + 28, top + 162, { w: 500, px: 20, color: L.mute, maxW: cw3 - 44 });
    txt(g, words.slice(half).join(" "), cx + 28, top + 190, { w: 500, px: 20, color: L.mute, maxW: cw3 - 44 });
  });
  luxFooter(g, W, M, H - 150, "Get the full plan in the app", [
    "AI analysis and demo trading. Every result shown, losses included. Not financial advice.",
  ]);
  return new Promise((res) => cv.toBlob((b) => res(b), "image/png"));
}

export default function ShareSignal({ r, market, plan, label }: { r: any; market: string; plan: any; label: string }) {
  const { tickers } = useLive();
  const [busy, setBusy] = useState(false);
  if (!plan || market !== "futures") return null;
  const go = async () => {
    setBusy(true);
    try {
      const blob = await draw(r, plan, label, tickers[r.symbol]?.last ?? r.price ?? null);
      if (!blob) return;
      const name = `${base(r.symbol)}-${String(r.timeframe)}-signal.png`;
      const file = new File([blob], name, { type: "image/png" });
      const nav: any = navigator;
      if (nav.canShare?.({ files: [file] })) {
        await nav.share({ files: [file], title: `${base(r.symbol)} signal` }).catch(() => undefined);
      } else {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob); a.download = name; a.click();
        window.setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      }
    } finally { setBusy(false); }
  };
  return (
    <button className="btn px-3" onClick={go} disabled={busy} aria-label="Share this signal as an image" title="Share as an image (no prices)">
      {busy ? "…" : (
        <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" /><path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4" /></svg>
      )}
    </button>
  );
}
