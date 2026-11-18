// v2.61 member AI chat (owner, 18 Nov 2026). Talks to the Cloudflare Worker in chat-worker/ (VITE_CHAT_URL). The
// question goes with the figures of the page the member is on (read once when the question is sent, from documents the
// page already listens to), so the assistant explains what is on screen and nothing else. Free plan: 0 extra Firestore
// writes; the worker checks membership with the member's own sign-in and keeps a daily cap.
import { auth } from "./firebase";
import { getOnce } from "./api";
import { BUILD_ID } from "./version";

export const CHAT_URL = (import.meta.env.VITE_CHAT_URL as string | undefined)?.replace(/\/$/, "") ?? "";
export const PREVIEW = BUILD_ID === "preview";
export const chatReady = () => !!CHAT_URL || PREVIEW;

export interface Turn { role: "user" | "model"; text: string }

const TFS = ["15m", "1h", "4h", "12h", "1d", "3d"];
const tfOf = (q: URLSearchParams, d = "4h") => { const t = q.get("timeframe") ?? q.get("tf"); return t && TFS.includes(t) ? t : d; };

/** Keeps the useful parts of a view: drops long series, rounds numbers, caps list lengths. */
function slim(v: any, depth = 0): any {
  if (v == null || depth > 6) return v ?? null;
  if (typeof v === "number") return Number.isInteger(v) ? v : Number(v.toPrecision(6));
  if (typeof v === "string") return v.length > 400 ? `${v.slice(0, 400)}…` : v;
  if (Array.isArray(v)) return v.slice(0, 25).map((x) => slim(x, depth + 1));
  if (typeof v === "object") {
    const out: Record<string, any> = {};
    for (const [k, x] of Object.entries(v)) {
      if (/^(candles|curve|curves|equity|series|history_curve|points|dots|heat|histogram|overlays|events|sparkline|proof|payload_raw)$/i.test(k)) continue;
      out[k] = slim(x, depth + 1);
    }
    return out;
  }
  return v;
}

const pick = (o: any, keys: string[]) => Object.fromEntries(keys.filter((k) => o?.[k] !== undefined).map((k) => [k, o[k]]));
const safe = async (path: string) => { try { return await getOnce(path); } catch { return null; } };

/** What the assistant may look at on this page. */
export async function pageContext(pathname: string, search: string): Promise<{ page: string; data: any }> {
  const q = new URLSearchParams(search);
  const seg = pathname.split("/").filter(Boolean);
  const briefing = async () => (await safe("/market-context"))?.briefing ?? null;
  switch (seg[0] ?? "") {
    case "": {
      const [d, tr, b] = await Promise.all([safe("/dashboard?timeframe=4h"), safe("/track-record"), briefing()]);
      return { page: "Home / Overview", data: { market_4h: pick(d, ["market_status", "rows", "opportunities", "risks"]), briefing: b, record: pick(tr?.live, ["summary", "signals"]), last_7d: tr?.last_7d } };
    }
    case "signals": {
      const tf = q.get("timeframe") === "all" ? "4h" : tfOf(q);
      const f = await safe(`/futures?timeframe=${tf}`);
      const sym = q.get("symbol");
      const rows = (f?.rows ?? []).filter((r: any) => !sym || r.symbol === sym || r.side);
      return { page: `Signals (${tf.toUpperCase()}${sym ? `, ${sym}` : ""})`, data: { timeframe: tf, selected: sym, rows } };
    }
    case "asset": {
      const s = seg[1] ?? "btc-usdt";
      const tf = tfOf(q);
      const sym = s.replace("-", "/").toUpperCase();
      const [a, rep, f] = await Promise.all([safe(`/analysis/${s}?timeframe=${tf}`), safe(`/coin-reports/${s}`), safe(`/futures?timeframe=${TFS.includes(tf) ? tf : "4h"}`)]);
      return { page: `Coin page ${sym} (${tf.toUpperCase()})`, data: {
        analysis: pick(a, ["status", "decision", "decision_reason", "grade", "signal", "regime", "volatility", "levels", "setup", "flags", "price", "horizons", "mtf", "commentary"]),
        ai_report: rep, call: (f?.rows ?? []).find((r: any) => r.symbol === sym) ?? null } };
    }
    case "results": case "history": {
      const tr = await safe("/track-record");
      return { page: "Results / track record", data: pick(tr, ["live", "last_7d", "restart", "withdrawn", "excluded_tests", "method", "by_timeframe", "summary"]) };
    }
    case "news": {
      const n = await safe("/news");
      return { page: "News & calendar", data: { headlines: (n?.headlines ?? n?.items ?? []).slice(0, 15).map((h: any) => pick(h, ["title", "source", "published", "coins", "sentiment"])), calendar: (n?.calendar ?? []).slice(0, 15), last_high: n?.last_high, risk_now: n?.risk_now, mood: n?.mood } };
    }
    case "radar": {
      const r = await safe("/radar");
      return { page: "Radar", data: pick(r, ["picks", "extended", "scorecard", "generated_at", "method"]) };
    }
    case "command": {
      const tf = (() => { try { return localStorage.getItem("cia-cc-tf") || "4h"; } catch { return "4h"; } })();
      const [d, b] = await Promise.all([safe(`/dashboard?timeframe=${tf}`), briefing()]);
      return { page: `Command Centre (${tf.toUpperCase()})`, data: { market: pick(d, ["market_status", "rows"]), briefing: b } };
    }
    case "paper": {
      const sym = q.get("symbol") ?? "BTC/USDT";
      const f = await safe("/futures?timeframe=4h");
      return { page: `Trade (practice, ${sym})`, data: { call_4h: (f?.rows ?? []).find((r: any) => r.symbol === sym) ?? null, note: "Practice account with virtual money; the app never places real orders." } };
    }
    default:
      return { page: pathname, data: { briefing: await briefing() } };
  }
}

const MOCK = "This is the preview, so here is a sample answer. On the live site the assistant reads the figures on this page and explains them in plain words. It never tells you to buy or sell.";

export async function askAI(question: string, history: Turn[], pathname: string, search: string): Promise<{ answer: string; left?: number }> {
  const ctx = await pageContext(pathname, search);
  if (!CHAT_URL) {
    if (PREVIEW) { await new Promise((r) => setTimeout(r, 700)); return { answer: MOCK, left: 19 }; }
    throw new Error("The assistant is not available yet.");
  }
  const token = await auth.currentUser?.getIdToken();
  if (!token) throw new Error("Please sign in again.");
  const r = await fetch(`${CHAT_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ question, page: ctx.page, context: JSON.stringify(slim(ctx.data)).slice(0, 14000), history: history.slice(-6) }),
  }).catch(() => null);
  if (!r) throw new Error("No connection to the assistant. Check your internet and try again.");
  const d: any = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(d.error ?? "The assistant could not answer just now."), { left: d.left });
  return { answer: String(d.answer ?? ""), left: d.left };
}

/** Starter questions per page. */
export function starters(pathname: string): string[] {
  const s = pathname.split("/")[1] ?? "";
  if (s === "signals") return ["Explain the selected signal in simple words", "What does grade A mean?", "Why is a coin on WAIT?"];
  if (s === "asset") return ["Summarise this coin's AI report", "What are the key levels here?", "What would cancel this view?"];
  if (s === "results" || s === "history") return ["How are the results calculated?", "Summarise the last 7 days", "What does ROI on margin mean?"];
  if (s === "news") return ["What's the next big release?", "Why are signals paused around news?", "Summarise today's headlines"];
  if (s === "paper") return ["How does practice trading work?", "What is liquidation price?", "Explain the AI call for this coin"];
  if (s === "radar") return ["What is the radar showing?", "Which coins are beating BTC?"];
  return ["What is the market mood right now?", "Explain today's briefing", "How many signals are open?"];
}
