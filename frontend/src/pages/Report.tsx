// Weekly report for marketing: the week's best signals up front, the complete totals (wins and losses) on the same
// image, a link to the public track record, and a ready caption. Download as a post (1080x1080) or story (1080x1920).
import { useEffect, useMemo, useRef, useState } from "react";
import { ErrorBox, Loading } from "../components/ui";
import { useApi } from "../lib/api";
import { base, fmtPrice, isNum } from "../lib/format";
import { SITE_HOST } from "../lib/brand";

const SITE = SITE_HOST;
const dfmt = (ms: number) => new Date(ms).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
const range = (r: any) => `${dfmt(r.week_start)} – ${dfmt(r.week_end - 1)}`;
const sp = (v: unknown, d = 1) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "—");

function loadImg(src: string): Promise<HTMLImageElement | null> {
  return new Promise((res) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => res(null); i.src = src; });
}

async function draw(cv: HTMLCanvasElement, r: any, story: boolean) {
  const W = 1080, H = story ? 1920 : 1080;
  cv.width = W; cv.height = H;
  const g = cv.getContext("2d")!;
  const gold = "#f0b90b", bull = "#0ecb81", bear = "#f6465d", text = "#eaecef", mute = "#848e9c";
  const bg = g.createLinearGradient(0, 0, W, H);
  bg.addColorStop(0, "#0b0e11"); bg.addColorStop(1, "#181a20");
  g.fillStyle = bg; g.fillRect(0, 0, W, H);
  const glow = g.createRadialGradient(W * 0.85, 120, 10, W * 0.85, 120, 520);
  glow.addColorStop(0, "rgba(240,185,11,0.22)"); glow.addColorStop(1, "rgba(240,185,11,0)");
  g.fillStyle = glow; g.fillRect(0, 0, W, H);
  g.strokeStyle = "rgba(240,185,11,0.35)"; g.lineWidth = 4; g.strokeRect(24, 24, W - 48, H - 48);
  const font = (w: number, px: number, mono = false) => `${w} ${px}px ${mono ? "ui-monospace, Menlo, monospace" : "Inter, system-ui, sans-serif"}`;
  const logo = await loadImg("/icons/icon-192.png");
  let y = story ? 150 : 72;
  if (logo) g.drawImage(logo, 70, y - 10, 86, 86);
  g.fillStyle = text; g.font = font(800, 40); g.fillText("Crypto Intelligence", 176, y + 30);
  g.fillStyle = gold; g.fillText(" AI", 176 + g.measureText("Crypto Intelligence").width, y + 30);
  g.fillStyle = mute; g.font = font(500, 26); g.fillText(`WEEKLY RESULTS · ${range(r)}`.toUpperCase(), 176, y + 70);
  y += story ? 230 : 150;

  g.fillStyle = mute; g.font = font(600, 28); g.fillText("Total result of all closed signals", 70, y);
  g.fillStyle = (r.total_return_pct ?? 0) >= 0 ? bull : bear; g.font = font(800, story ? 150 : 112, true);
  g.fillText(sp(r.total_return_pct), 64, y + (story ? 150 : 108));
  y += story ? 220 : 160;
  const kp = [["Win rate", isNum(r.win_rate) ? `${Math.round(r.win_rate * 100)}%` : "—"], ["Wins / losses", `${r.wins} / ${r.losses}`], ["Signals", String(r.issued ?? r.closed)]];
  const kh = story ? 120 : 106;
  kp.forEach(([k, v], i) => {
    const x = 70 + i * 320;
    g.fillStyle = "rgba(255,255,255,0.05)"; g.fillRect(x, y, 290, kh);
    g.fillStyle = mute; g.font = font(600, 24); g.fillText(k, x + 22, y + 38);
    g.fillStyle = text; g.font = font(800, story ? 46 : 42, true); g.fillText(v, x + 22, y + kh - 22);
  });
  y += story ? 200 : 150;

  g.fillStyle = gold; g.font = font(700, 30); g.fillText("TOP SIGNALS THIS WEEK", 70, y);
  y += story ? 24 : 20;
  const bot = (r.scorecard_bots ?? []).find((b: any) => isNum(b.week_return_pct));
  const fy = H - (story ? 175 : 128);                   // the footer band starts here
  const rowH = story ? 100 : 84;
  // square post: only as many rows as fit above the scorecard line and the footer (nothing may overlap)
  const room = Math.floor((fy - 16 - (bot ? 46 : 0) - y) / rowH);
  const best = (r.best ?? []).filter((t: any) => t.return_pct > 0).slice(0, story ? 5 : Math.max(1, Math.min(3, room)));
  if (!best.length) { g.fillStyle = mute; g.font = font(500, 28); g.fillText("No winning signals closed this week.", 70, y + 50); y += 80; }
  for (const t of best) {
    const bh = rowH - 14, mid = y + bh / 2 + 12;
    g.fillStyle = "rgba(255,255,255,0.04)"; g.fillRect(70, y, W - 140, bh);
    g.fillStyle = text; g.font = font(800, 34); g.fillText(base(t.symbol), 96, mid);
    const w0 = g.measureText(base(t.symbol)).width;
    g.fillStyle = t.side === "LONG" ? bull : bear; g.font = font(800, 24); g.fillText(t.side, 112 + w0, mid - 2);
    const w1 = g.measureText(t.side).width;
    g.fillStyle = mute; g.font = font(500, 22, true);
    g.fillText(`${String(t.timeframe).toUpperCase()} · entry ${fmtPrice(t.entry)} · ${t.status === "TP3" ? "all targets" : t.status === "TP2" ? "target 2" : "target 1"}`, 136 + w0 + w1, mid - 2);
    g.fillStyle = bull; g.font = font(800, 38, true); g.textAlign = "right"; g.fillText(sp(t.return_pct), W - 96, mid + 2); g.textAlign = "left";
    y += rowH;
  }
  if (bot || r.radar_best) {
    y += 10;
    g.fillStyle = mute; g.font = font(500, 26);
    if (bot) { g.fillText(`Scorecard bot (all app signals, virtual money): `, 70, y + 30); g.fillStyle = bot.week_return_pct >= 0 ? bull : bear; g.font = font(800, 28, true); g.fillText(sp(bot.week_return_pct), 650, y + 30); y += 46; }
    if (r.radar_best && story) { g.fillStyle = mute; g.font = font(500, 26); g.fillText(`Radar pick ${base(r.radar_best.symbol)}: ${sp(r.radar_best.ret_7d_pct)} in 7 days`, 70, y + 30); y += 46; }
  }
  g.fillStyle = "rgba(240,185,11,0.12)"; g.fillRect(48, fy - 10, W - 96, story ? 130 : 100);
  g.fillStyle = text; g.font = font(700, 28); g.fillText(`AI crypto signals · join at ${SITE}`, 70, fy + 32);
  g.fillStyle = mute; g.font = font(500, 20);
  const disc = "Results of the app's published signals, equal size, before fees. Not financial advice; past results don't guarantee future ones.";
  wrap(g, disc, W - 150).forEach((ln, k) => g.fillText(ln, 70, fy + (story ? 72 : 58) + k * 24));
  if (story) {
    // call to action in the free space of the story format
    const cy = Math.max(y + 20, fy - 420);
    g.fillStyle = "rgba(240,185,11,0.10)"; g.fillRect(70, cy, W - 140, 380);
    g.strokeStyle = "rgba(240,185,11,0.5)"; g.lineWidth = 2; g.strokeRect(70, cy, W - 140, 380);
    g.fillStyle = gold; g.font = font(800, 44); g.fillText("Get the next signals", 110, cy + 80);
    g.fillStyle = text; g.font = font(500, 30);
    ["AI long / short calls with entry, stop-loss & targets", "Alerts on your phone · demo trading · weekly reports", "Full results, losses included, for members"].forEach((t, k) => {
      g.fillStyle = gold; g.fillText("✓", 110, cy + 150 + k * 56); g.fillStyle = text; g.fillText(t, 150, cy + 150 + k * 56);
    });
    g.fillStyle = gold; g.font = font(800, 34); g.fillText(`${SITE} · from 15 USDT/month`, 110, cy + 345);
  }
}

function wrap(g: CanvasRenderingContext2D, t: string, max: number): string[] {
  const out: string[] = [];
  let line = "";
  for (const w of t.split(" ")) {
    const next = line ? `${line} ${w}` : w;
    if (g.measureText(next).width > max && line) { out.push(line); line = w; } else line = next;
  }
  if (line) out.push(line);
  return out;
}

function caption(r: any): string {
  const best = (r.best ?? []).filter((t: any) => t.return_pct > 0).slice(0, 3);
  const lines = [
    `📊 Crypto Intelligence AI · weekly results (${range(r)})`,
    "",
    `✅ ${r.wins} wins / ${r.losses} losses · win rate ${isNum(r.win_rate) ? Math.round(r.win_rate * 100) + "%" : "—"}`,
    `📈 Total result of all closed signals: ${sp(r.total_return_pct)}`,
    ...(best.length ? ["", "Top signals:", ...best.map((t: any) => `• ${base(t.symbol)} ${t.side} (${String(t.timeframe).toUpperCase()}): ${sp(t.return_pct)}`)] : []),
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
                  <li key={k} className="flex justify-between"><span>{base(t.symbol)} <span className={t.side === "LONG" ? "text-bull" : "text-bear"}>{t.side}</span> <span className="text-mute">{String(t.timeframe).toUpperCase()}</span></span><span className={`num ${t.return_pct > 0 ? "text-bull" : "text-bear"}`}>{sp(t.return_pct, 2)}</span></li>
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
