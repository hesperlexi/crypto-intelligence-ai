// Weekly report for marketing: the week's best signals up front, the complete totals (wins and losses) on the same
// image, a link to the public track record, and a ready caption. Download as a post (1080x1080) or story (1080x1920).
import { useEffect, useMemo, useRef, useState } from "react";
import { PageHeader } from "../components/kit";
import { ErrorBox, Loading } from "../components/ui";
import { RoiFigure } from "../components/SignalExtras";
import { useApi } from "../lib/api";
import { base, isNum } from "../lib/format";
import { SITE_HOST } from "../lib/brand";
import { curveChart, figure, foil, inter, L, luxBackground, luxBrand, luxFooter, luxReady, sora, statRow, txt, wrapLines } from "../lib/luxCard";
import { roiOf } from "../lib/roi";
import AdminTabs from "../components/AdminTabs";
import TelegramButton from "../components/TelegramButton";

const SITE = SITE_HOST;
const dfmt = (ms: number) => new Date(ms).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
const range = (r: any) => `${dfmt(r.week_start)} – ${dfmt(r.week_end - 1)}`;
const sp = (v: unknown, d = 1) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "—");

const STATUS: Record<string, string> = { TP3: "All targets", TP2: "Target 2", TP1: "Target 1", STOPPED: "Stopped" };

async function draw(cv: HTMLCanvasElement, r: any, story: boolean) {
  // v2.37 premium layout (lib/luxCard.ts): editorial, left-aligned, metallic gold figures, hairlines instead of boxes
  const W = 1080, H = story ? 1920 : 1080, M = 84;
  cv.width = W; cv.height = H;
  const g = cv.getContext("2d")!;
  await luxReady();
  await luxBackground(g, W, H);
  let y = await luxBrand(g, W, M, story ? 110 : 72, "WEEKLY REPORT");
  const roiTot = isNum(r.total_roi_pct);
  const head = roiTot ? r.total_roi_pct : r.total_return_pct;
  const good = (head ?? 0) >= 0;

  y += story ? 120 : 64;
  txt(g, `Week of ${range(r)}`, M, y, { f: sora, w: 600, px: story ? 34 : 26, color: L.soft });
  y += story ? 56 : 36;
  txt(g, roiTot ? "Total ROI on margin, every closed signal" : "Total price move, every closed signal", M, y, { w: 500, px: story ? 26 : 21, color: L.mute });
  y += story ? 176 : 120;
  figure(g, sp(head, 2), M - 6, y, story ? 190 : 128, good, { maxW: W - 2 * M });
  y += story ? 64 : 42;
  txt(g, `${roiTot ? `price ${sp(r.total_return_pct, 2)}  ·  ` : ""}${r.closed} closed, wins and losses  ·  equal margin, before fees`, M, y,
    { w: 500, px: story ? 24 : 19, color: L.mute, maxW: W - 2 * M });

  // the week's running total, trade by trade
  if (Array.isArray(r.curve) && r.curve.length > 1) {
    y += story ? 48 : 22;
    const ch = story ? 200 : 100;
    curveChart(g, M, y, W - 2 * M, ch, r.curve, (r.curve[r.curve.length - 1] ?? 0) >= 0);
    y += ch;
  }

  y += story ? 130 : 76;
  statRow(g, M, y, W - 2 * M, [
    [`win rate`, isNum(r.win_rate) ? `${Math.round(r.win_rate * 100)}%` : "—"],
    [`wins · losses`, `${r.wins} · ${r.losses}`],
    [`signals issued`, String(r.issued ?? r.closed)],
  ], story ? 64 : 44);
  y += story ? 110 : 92;

  // top signals: a ledger with hairlines
  const fy = H - (story ? 190 : 150);
  const rowH = story ? 84 : 56;
  const cta = story ? 440 : 0;          // CTA block (300) + its gap + the bot line
  const room = Math.floor((fy - 20 - cta - y - 20) / rowH);
  const best = (r.best ?? []).filter((t: any) => t.return_pct > 0).slice(0, Math.max(0, Math.min(story ? 5 : 3, room)));
  if (best.length) {
    txt(g, "Top signals", M, y, { f: sora, w: 700, px: story ? 30 : 24, color: L.text });
    y += 18;
    best.forEach((t: any, k: number) => {
      const top = y + k * rowH, mid = top + rowH / 2 + 8;
      g.fillStyle = L.hair; g.fillRect(M, top, W - 2 * M, 1);
      txt(g, `0${k + 1}`, M, mid, { f: sora, w: 700, px: story ? 24 : 20, color: L.soft });
      txt(g, base(t.symbol), M + 60, mid, { f: sora, w: 700, px: story ? 34 : 28, color: L.text, maxW: 170 });
      txt(g, `${t.side} · ${String(t.timeframe).toUpperCase()} · ${t.status === "EXPIRED" ? (t.return_pct > 0 ? "Win at market" : "Loss at market") : STATUS[t.status] ?? t.status}`, M + 250, mid,
        { w: 600, px: story ? 21 : 18, color: t.side === "LONG" ? L.bull : L.bear, maxW: 330 });
      const ro = roiOf(t)!;
      figure(g, sp(ro.value, 1), W - M, mid, story ? 36 : 30, true, { align: "right" });
      if (ro.onMargin) txt(g, `${ro.leverage}x · price ${sp(ro.price, 2)}`, W - M - (story ? 160 : 136), mid, { w: 500, px: story ? 18 : 15, color: L.mute, align: "right" });
    });
    y += best.length * rowH;
  } else {
    txt(g, "No winning signals closed this week. Every loss is still counted above.", M, y, { w: 500, px: 22, color: L.mute, maxW: W - 2 * M });
    y += rowH;
  }

  if (story) {
    const bot = (r.scorecard_bots ?? []).find((b: any) => isNum(b.week_return_pct));
    const cy = fy - 50 - 300;
    if (bot) txt(g, `Scorecard bot (all app signals, virtual money) this week: ${sp(bot.week_return_pct)}`, M, cy - 40, { w: 500, px: 22, color: L.mute, maxW: W - 2 * M });
    g.save();
    g.strokeStyle = foil(g, M, cy, W - M, cy + 300); g.lineWidth = 2;
    g.beginPath(); g.roundRect(M, cy, W - 2 * M, 300, 28); g.stroke();
    g.fillStyle = "rgba(217,180,95,0.05)"; g.fill();
    g.restore();
    txt(g, "Get the next signals live", M + 44, cy + 78, { f: sora, w: 800, px: 44, color: foil(g, M, cy, W - M, cy + 80) });
    ["Long and short calls with entry, stop and three targets", "Phone alerts, demo trading, weekly reports", "Every result public, losses included"].forEach((t, k) =>
      txt(g, `—  ${t}`, M + 44, cy + 140 + k * 46, { w: 500, px: 26, color: L.text, maxW: W - 2 * M - 88 }));
  }

  luxFooter(g, W, M, fy, `${SITE}  ·  from 15 USDT a month`, wrapLines(g,
    "ROI on margin = price move × the leverage each signal card suggested; losses grow the same way. Equal margin per signal, before fees. Not financial advice; past results don't guarantee future results.",
    inter(500, 16), W - 2 * M, 2));
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
  if (!r) return <p className="text-sm text-mute">No weekly report yet.</p>;
  const download = () => {
    const a = document.createElement("a");
    a.download = `crypto-intelligence-weekly-${new Date(r.week_start).toISOString().slice(0, 10)}${story ? "-story" : ""}.png`;
    a.href = cv.current!.toDataURL("image/png");
    a.click();
  };
  const copy = async () => { try { await navigator.clipboard.writeText(cap); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* ignore */ } };

  return (
    <div className="space-y-4">
      <AdminTabs family="share" />
      <PageHeader title="Weekly report" />
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
        <TelegramButton canvas={async () => cv.current} caption={cap} kind="weekly-report" />
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,560px)_minmax(0,1fr)]">
        <canvas ref={cv} className="mx-auto w-full max-w-[560px] self-start rounded-xl border border-glass/10" style={{ aspectRatio: story ? "9 / 16" : "1 / 1" }} aria-label="Weekly report image" />
        <div className="ov-stack flex min-w-0 flex-col gap-3">
          <section className="panel panel-hero p-4">
            <h2 className="label mb-2">Caption</h2>
            <pre className="whitespace-pre-wrap font-sans text-sm text-text/90">{cap}</pre>
          </section>
          <section className="panel p-4 text-sm">
            <h2 className="label mb-2">All signals closed this week ({r.closed})</h2>
            {r.closed ? (
              <ul className="space-y-1">
                {(r.best ?? []).concat(r.closed > 5 && r.worst ? [r.worst] : []).map((t: any, k: number) => (
                  <li key={k} className="flex items-center justify-between gap-3 border-b border-glass/[0.05] py-1.5 last:border-0"><span className="flex min-w-0 flex-wrap items-center gap-x-1.5"><span className="font-semibold">{base(t.symbol)}</span> <span className={`text-xs font-bold ${t.side === "LONG" ? "text-bull" : "text-bear"}`}>{t.side}</span> <span className="text-xs text-mute">{String(t.timeframe).toUpperCase()}</span></span><RoiFigure x={t} size="sm" /></li>
                ))}
              </ul>
            ) : <p className="text-mute">No signals closed in this week yet.</p>}
            <p className="mt-2 text-xs text-mute">{r.basis}</p>
          </section>
        </div>
      </div>
    </div>
  );
}
