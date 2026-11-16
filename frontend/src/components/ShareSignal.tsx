// v2.44 one-tap share image of a signal (1080 x 1350, story-friendly), drawn in the browser with the premium kit.
// A teaser: coin, side, timeframe, grade and how the call is doing now - never the entry / stop / targets, so the paid
// plan stays in the app. Shared through the phone's share sheet when it supports images, else downloaded.
import { useState } from "react";
import { base, isNum } from "../lib/format";
import { useLive } from "../lib/live";
import { figure, foil, L, luxBackground, luxBrand, luxFooter, luxReady, sora, txt } from "../lib/luxCard";

async function draw(r: any, plan: any, label: string, px: number | null): Promise<Blob | null> {
  const W = 1080, H = 1350, M = 84;
  const cv = document.createElement("canvas");
  cv.width = W; cv.height = H;
  const g = cv.getContext("2d")!;
  await luxReady();
  await luxBackground(g, W, H);
  let y = await luxBrand(g, W, M, 72, "LIVE SIGNAL");
  const coin = base(r.symbol) === "PAXG" ? "GOLD" : base(r.symbol);
  const long = (plan?.side ?? (r.side > 0 ? "LONG" : "SHORT")) === "LONG";
  y += 150;
  txt(g, coin, M, y, { f: sora, w: 800, px: 132, color: foil(g, M, y - 130, M + 600, y) });
  y += 64;
  txt(g, `${long ? "▲ LONG" : "▼ SHORT"}  ·  ${String(r.timeframe ?? "").toUpperCase()}  ·  ${r.grade ? `GRADE ${r.grade}` : label}`, M, y,
    { f: sora, w: 700, px: 32, track: 2, color: long ? L.bull : L.bear });
  // how it is doing now, in R and price move (no levels)
  const risk = plan && isNum(plan.entry) && isNum(plan.stop) ? Math.abs(plan.entry - plan.stop) : null;
  const s = long ? 1 : -1;
  const rNow = risk && isNum(px) ? (s * (px - plan.entry)) / risk : null;
  const mv = plan && isNum(px) && isNum(plan.entry) ? s * (px / plan.entry - 1) * 100 : null;
  y += 200;
  if (rNow != null && mv != null) {
    txt(g, "Since entry", M, y - 120, { w: 600, px: 24, color: L.mute });
    figure(g, `${mv >= 0 ? "+" : ""}${mv.toFixed(2)}%`, M - 6, y, 150, mv >= 0, { maxW: W - 2 * M });
    txt(g, `${rNow >= 0 ? "+" : ""}${rNow.toFixed(2)}R  ·  price move, no leverage`, M, y + 54, { w: 500, px: 24, color: L.soft });
  } else {
    txt(g, "New call", M, y - 40, { f: sora, w: 800, px: 96, color: foil(g, M, y - 130, M + 600, y) });
  }
  y += 140;
  // the plan's shape as a teaser: stop -> entry -> three targets, without prices
  const bx = M, bw = W - 2 * M;
  g.fillStyle = "rgba(245,241,230,0.08)"; g.beginPath(); g.roundRect(bx, y, bw, 12, 6); g.fill();
  const marks = [0, 0.25, 0.5, 0.69, 1];
  marks.forEach((m, i) => {
    g.fillStyle = i === 0 ? L.bear : i === 1 ? L.gold : L.bull;
    g.beginPath(); g.roundRect(bx + bw * m - 2, y - 8, 4, 28, 2); g.fill();
  });
  ["STOP", "ENTRY", "TP1", "TP2", "TP3"].forEach((t, i) => txt(g, t, bx + bw * marks[i], y + 58, { w: 700, px: 18, track: 2, color: i === 0 ? L.bear : i === 1 ? L.gold : L.bull, align: i === 0 ? "left" : i === 4 ? "right" : "center" }));
  txt(g, "Entry, stop-loss and 3 targets for members in the app", M, y + 110, { w: 500, px: 22, color: L.mute });
  luxFooter(g, W, M, H - 160, "Get the full plan in the app", [
    "AI analysis and demo trading. Every result shown, losses included.",
    "Not financial advice. Leverage magnifies losses.",
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
