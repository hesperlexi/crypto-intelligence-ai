// Weekly report for marketing: the week's best signals up front, the complete totals (wins and losses) on the same
// image, a link to the public track record, and a ready caption. Download as a post (1080x1080) or story (1080x1920).
import { useEffect, useMemo, useRef, useState } from "react";
import { ErrorBox, Loading } from "../components/ui";
import { RoiFigure } from "../components/SignalExtras";
import { useApi } from "../lib/api";
import { base, isNum } from "../lib/format";
import { SITE_HOST } from "../lib/brand";
import { backdrop, C, cap, chip, fontsReady, footer, glowText, header, M, panel, sidePill, text, wrap, font } from "../lib/cardCanvas";
import { roiOf } from "../lib/roi";

const SITE = SITE_HOST;
const dfmt = (ms: number) => new Date(ms).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
const range = (r: any) => `${dfmt(r.week_start)} – ${dfmt(r.week_end - 1)}`;
const sp = (v: unknown, d = 1) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "—");

const STATUS: Record<string, string> = { TP3: "All targets", TP2: "Target 2", TP1: "Target 1", STOPPED: "Stopped", EXPIRED: "Time limit" };

async function draw(cv: HTMLCanvasElement, r: any, story: boolean) {
  const W = 1080, H = story ? 1920 : 1080;
  cv.width = W; cv.height = H;
  const g = cv.getContext("2d")!;
  await fontsReady();
  backdrop(g, W, H);
  let y = await header(g, `Weekly results · ${range(r)}`, story ? 120 : 64) + (story ? 72 : 40);
  const roiTot = isNum(r.total_roi_pct);
  const head = roiTot ? r.total_roi_pct : r.total_return_pct;
  const col = (head ?? 0) >= 0 ? C.bull : C.bear;

  // hero: total ROI on margin (else the price move, labelled)
  const hh = story ? 320 : 224;
  panel(g, M, y, W - 2 * M, hh, { r: 32, stroke: (head ?? 0) >= 0 ? "rgba(14,203,129,0.45)" : "rgba(246,70,93,0.45)", fill: (head ?? 0) >= 0 ? "rgba(14,203,129,0.06)" : "rgba(246,70,93,0.06)" });
  text(g, roiTot ? "TOTAL ROI ON MARGIN · ALL CLOSED SIGNALS" : "TOTAL PRICE MOVE · ALL CLOSED SIGNALS", W / 2, y + (story ? 64 : 48), { weight: 800, px: 22, color: C.gold, align: "center" });
  glowText(g, sp(head, 2), W / 2, y + (story ? 216 : 160), col, { weight: 800, px: story ? 150 : 120, align: "center", maxW: W - 2 * M - 64, blur: 44 });
  text(g, `${roiTot ? `price ${sp(r.total_return_pct, 2)} · ` : ""}${r.closed} closed signals, wins and losses, equal margin, before fees`,
    W / 2, y + hh - 32, { weight: 500, px: 20, color: C.mute, align: "center", maxW: W - 2 * M - 48 });
  y += hh + 24;

  // three KPI tiles, values centred on one baseline
  const kp: [string, string, string][] = [["WIN RATE", isNum(r.win_rate) ? `${Math.round(r.win_rate * 100)}%` : "—", C.text],
    ["WINS · LOSSES", `${r.wins} · ${r.losses}`, C.text], ["SIGNALS ISSUED", String(r.issued ?? r.closed), C.text]];
  const kw = (W - 2 * M - 2 * 24) / 3, kh = story ? 152 : 112;
  kp.forEach(([k, v, c], i) => {
    const x = M + i * (kw + 24);
    panel(g, x, y, kw, kh, { r: 24 });
    text(g, k, x + kw / 2, y + (story ? 48 : 40), { weight: 700, px: 17, color: C.mute, align: "center", maxW: kw - 32 });
    text(g, v, x + kw / 2, y + kh - (story ? 36 : 24), { weight: 800, px: story ? 56 : 44, color: c, align: "center", maxW: kw - 40 });
  });
  y += kh + (story ? 64 : 40);

  const fy = H - (story ? 200 : 152);                                   // footer hairline
  const bot = (r.scorecard_bots ?? []).find((b: any) => isNum(b.week_return_pct));
  const tail = (bot ? 48 : 0) + (story && r.radar_best ? 48 : 0);
  const cta = story ? 400 : 0;
  const rowH = story ? 88 : 80;
  text(g, "TOP SIGNALS THIS WEEK", M, y, { weight: 800, px: 20, color: C.gold });
  y += 20;
  const room = Math.floor((fy - 24 - tail - cta - y) / rowH);
  const best = (r.best ?? []).filter((t: any) => t.return_pct > 0).slice(0, Math.max(0, Math.min(story ? 5 : 3, room)));
  if (!best.length) { text(g, "No winning signals closed this week.", M, y + 48, { weight: 500, px: 24, color: C.mute }); y += rowH; }
  const xr = W - M - 28;                                                 // right edge inside the rows
  for (const [k, t] of best.entries()) {
    const top = y + k * rowH, mid = top + (rowH - 10) / 2;
    panel(g, M, top, W - 2 * M, rowH - 10, { r: 18, fill: k % 2 ? "rgba(255,255,255,0.02)" : C.panel });
    g.font = font(800, 32);
    text(g, base(t.symbol), M + 28, mid + cap(g) / 2, { weight: 800, px: 32, maxW: 180 });
    sidePill(g, M + 220, mid - 16, t.side, { h: 32, px: 15, minW: 92 });
    chip(g, M + 324, mid - 16, String(t.timeframe).toUpperCase(), { h: 32, px: 15, minW: 68 });
    g.font = font(500, 19);
    text(g, STATUS[t.status] ?? t.status, M + 408, mid + cap(g) / 2, { weight: 500, px: 19, color: C.mute });
    const ro = roiOf(t)!;
    if (ro.leverage) chip(g, xr, mid - 15, `${ro.leverage}x`, { h: 30, px: 14, minW: 56, align: "right" });
    g.font = font(800, 34);
    const vy = mid + cap(g) / 2 - (ro.onMargin ? 8 : 0);
    text(g, sp(ro.value, 2), xr - 72, vy, { weight: 800, px: 34, color: C.bull, align: "right" });
    if (ro.onMargin) text(g, `price ${sp(ro.price, 2)}`, xr - 72, vy + 24, { weight: 500, px: 15, color: C.mute, align: "right" });
    else text(g, "price move", xr - 72, vy + 22, { weight: 500, px: 15, color: C.mute, align: "right" });
  }
  y += Math.max(1, best.length) * rowH + 8;
  if (bot) {
    y += 32;
    const w0 = text(g, "Scorecard bot (all app signals, virtual money) this week:", M, y, { weight: 500, px: 21, color: C.mute });
    text(g, sp(bot.week_return_pct), M + w0 + 12, y, { weight: 800, px: 22, color: bot.week_return_pct >= 0 ? C.bull : C.bear });
    y += 16;
  }
  if (story && r.radar_best) {
    y += 32;
    text(g, `Radar pick ${base(r.radar_best.symbol)}: ${sp(r.radar_best.ret_7d_pct)} in 7 days`, M, y, { weight: 500, px: 21, color: C.mute });
    y += 16;
  }
  if (story) {
    const cy = fy - 48 - 360;
    panel(g, M, cy, W - 2 * M, 360, { r: 28, fill: "rgba(240,185,11,0.07)", stroke: "rgba(240,185,11,0.5)" });
    text(g, "Get the next signals", M + 40, cy + 76, { weight: 800, px: 44, color: C.gold });
    ["AI long / short calls with entry, stop-loss & targets", "Alerts on your phone · demo trading · weekly reports", "Full results, losses included, for members"].forEach((t, k) => {
      text(g, "✓", M + 40, cy + 148 + k * 56, { weight: 800, px: 28, color: C.gold });
      text(g, t, M + 84, cy + 148 + k * 56, { weight: 500, px: 28, maxW: W - 2 * M - 124 });
    });
    text(g, `${SITE} · from 15 USDT/month`, M + 40, cy + 324, { weight: 800, px: 32, color: C.gold });
  }
  g.font = font(500, 17);
  footer(g, W, fy, "Past results don't guarantee future results",
    wrap(g, `ROI on margin = price move × the leverage each signal card suggested; losses grow the same way. Equal margin per signal, before fees. Analysis only, not financial advice.`, W - 2 * M, 2));
}

function roiLine(t: any): string {
  const ro = roiOf(t);
  if (!ro) return "—";
  return ro.onMargin ? `${sp(ro.value, 2)} ROI · ${ro.leverage}x margin (price ${sp(ro.price, 2)})` : `${sp(ro.value, 2)} price move`;
}

function caption(r: any): string {
  const best = (r.best ?? []).filter((t: any) => t.return_pct > 0).slice(0, 3);
  const lines = [
    `📊 Crypto Intelligence AI · weekly results (${range(r)})`,
    "",
    `✅ ${r.wins} wins / ${r.losses} losses · win rate ${isNum(r.win_rate) ? Math.round(r.win_rate * 100) + "%" : "—"}`,
    isNum(r.total_roi_pct) ? `📈 Total ROI on margin of all closed signals: ${sp(r.total_roi_pct, 2)} (price ${sp(r.total_return_pct, 2)})` : `📈 Total price move of all closed signals: ${sp(r.total_return_pct, 2)}`,
    ...(best.length ? ["", "Top signals:", ...best.map((t: any) => `• ${base(t.symbol)} ${t.side} (${String(t.timeframe).toUpperCase()}): ${roiLine(t)}`)] : []),
    "",
    `Join and see every signal live: https://${SITE}`,
    "AI long/short signals with entry, stop-loss and targets · from 15 USDT/month.",
    "",
    "Not financial advice. Past results don't guarantee future results.",
    "#crypto #bitcoin #tradingsignals #cryptotrading #AItrading",
  ];
  return lines.join("\n");
}

export default function Report() {
  const v = useApi<any>("/weekly-report");
  const reports: any[] = v.data?.reports ?? [];
  const [i, setI] = useState(-1);
  const [story, setStory] = useState(false);
  const [copied, setCopied] = useState(false);
  const cv = useRef<HTMLCanvasElement>(null);
  // default: the last complete week (index 1) when it exists, else this week so far
  const idx = i >= 0 ? i : reports.length > 1 ? 1 : 0;
  const r = reports[idx];
  useEffect(() => { if (r && cv.current) draw(cv.current, r, story); }, [r, story]);
  const cap = useMemo(() => (r ? caption(r) : ""), [r]);
  if (v.loading && !v.data) return <Loading />;
  if (v.error) return <ErrorBox error={v.error} retry={v.reload} />;
  if (!r) return <p className="text-sm text-mute">The first weekly report appears once signals have been published.</p>;
  const download = () => {
    const a = document.createElement("a");
    a.download = `crypto-intelligence-weekly-${new Date(r.week_start).toISOString().slice(0, 10)}${story ? "-story" : ""}.png`;
    a.href = cv.current!.toDataURL("image/png");
    a.click();
  };
  const copy = async () => { try { await navigator.clipboard.writeText(cap); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* ignore */ } };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="page-title">Weekly report</h1>
        <p className="text-sm text-mute">Ready to post: the week's best signals up front, with the full totals (wins and losses) and the app link. Showing the totals next to the best trades is what makes people trust the wins.</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <select className="input w-auto" value={idx} onChange={(e) => setI(Number(e.target.value))} aria-label="Week">
          {reports.map((x, k) => <option key={x.week_start} value={k}>{range(x)}{x.complete ? "" : " (so far)"}</option>)}
        </select>
        <span className="inline-flex rounded-xl border border-glass/10 p-1">
          <button className={`rounded-lg px-3 py-1 text-sm ${!story ? "bg-accent font-semibold text-ink" : "text-mute"}`} onClick={() => setStory(false)}>Post 1:1</button>
          <button className={`rounded-lg px-3 py-1 text-sm ${story ? "bg-accent font-semibold text-ink" : "text-mute"}`} onClick={() => setStory(true)}>Story 9:16</button>
        </span>
        <button className="btn btn-primary" onClick={download}>Download image</button>
        <button className="btn" onClick={copy}>{copied ? "Caption copied" : "Copy caption"}</button>
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)]">
        <canvas ref={cv} className="w-full max-w-[560px] rounded-xl border border-glass/10" style={{ aspectRatio: story ? "9 / 16" : "1 / 1" }} aria-label="Weekly report image" />
        <div className="space-y-3">
          <section className="panel p-4">
            <h2 className="label mb-2">Caption</h2>
            <pre className="whitespace-pre-wrap font-sans text-sm text-text/90">{cap}</pre>
          </section>
          <section className="panel p-4 text-sm">
            <h2 className="label mb-2">All signals closed this week ({r.closed})</h2>
            {r.closed ? (
              <ul className="space-y-1">
                {(r.best ?? []).concat(r.closed > 5 && r.worst ? [r.worst] : []).map((t: any, k: number) => (
                  <li key={k} className="flex items-center justify-between gap-3 border-b border-glass/[0.05] py-1.5 last:border-0"><span className="flex items-center gap-1.5"><span className="font-semibold">{base(t.symbol)}</span> <span className={`text-[11px] font-bold ${t.side === "LONG" ? "text-bull" : "text-bear"}`}>{t.side}</span> <span className="text-[11px] text-mute">{String(t.timeframe).toUpperCase()}</span></span><RoiFigure x={t} size="sm" /></li>
                ))}
              </ul>
            ) : <p className="text-mute">No signals closed in this week yet.</p>}
            <p className="mt-2 text-[11px] text-mute">{r.basis}</p>
          </section>
        </div>
      </div>
    </div>
  );
}
