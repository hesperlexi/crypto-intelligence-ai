// v2.62 Money flow (owner, 20 Nov 2026, inspired by a live "money flow" site). Real data only, straight from Binance
// USDⓈ-M futures public streams in the browser - no Firestore reads or writes, nothing stored.
//   useFlowFeed   one socket: aggTrade (every trade, buyer- or seller-initiated), forceOrder (liquidations), markPrice
//                 (funding) for the FLOW coins. Keeps the last 5 minutes of trades and the liquidations since opening.
//   FlowRiver     canvas: per coin, buyers' money flows IN from the left (green), sellers' money flows OUT to the right
//                 (red), wiped-out bets burst amber at the coin; dot size = trade size. Paused when hidden / reduced motion.
//   FlowStats, WhaleWatch, FundingBars   tiles, big-trade list and funding thermometer from the same feed.
//   NetFlowSankey 24 h net taker flow per watched coin (1h futures klines: taker-buy quote volume vs total), net sellers
//                 on the left, net buyers on the right of a centre bar.
import { ReactNode, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { raceSocket } from "../lib/ws";
import { base, fmtCompact, fmtPctRaw, fmtPrice, isNum, slug } from "../lib/format";
import { useTickerThrottled } from "../lib/live";
import { CoinAvatar } from "./Polish";

export const FLOW: { sym: string; stream: string; label: string; whale: number; color: string }[] = [
  { sym: "BTC/USDT", stream: "btcusdt", label: "Bitcoin", whale: 250_000, color: "247 147 26" },
  { sym: "ETH/USDT", stream: "ethusdt", label: "Ether", whale: 150_000, color: "98 126 234" },
  { sym: "SOL/USDT", stream: "solusdt", label: "Solana", whale: 50_000, color: "153 69 255" },
  { sym: "PAXG/USDT", stream: "paxgusdt", label: "Gold", whale: 50_000, color: "212 175 55" },
];
const BY_STREAM = Object.fromEntries(FLOW.map((f) => [f.stream.toUpperCase(), f]));

export interface Trade { s: string; usd: number; buy: boolean; t: number; p: number }
export interface Liq { s: string; usd: number; longWiped: boolean; t: number; p: number }
interface Feed {
  trades: Trade[];                       // last 5 min
  liqs: Liq[];                           // since the page opened (max 300)
  funding: Record<string, { rate: number; next: number }>;
  live: boolean;
  since: number;
  sub: (fn: (t: Trade | null, l: Liq | null) => void) => () => void;
}

/** One shared live feed while a component that needs it is on screen. */
export function useFlowFeed(): Feed {
  const ref = useRef<Feed | null>(null);
  const [, bump] = useState(0);
  if (!ref.current) {
    const subs = new Set<(t: Trade | null, l: Liq | null) => void>();
    ref.current = { trades: [], liqs: [], funding: {}, live: false, since: Date.now(), sub: (fn) => { subs.add(fn); return () => subs.delete(fn); } };
    (ref.current as any)._subs = subs;
  }
  useEffect(() => {
    const f = ref.current!;
    const subs: Set<(t: Trade | null, l: Liq | null) => void> = (f as any)._subs;
    let race: ReturnType<typeof raceSocket> | null = null, closed = false, retry = 0, timer = 0;
    const streams = FLOW.flatMap((x) => [`${x.stream}@aggTrade`, `${x.stream}@forceOrder`, `${x.stream}@markPrice@1s`]).join("/");
    const connect = () => {
      if (closed) return;
      race = raceSocket([`wss://fstream.binance.com/market/stream?streams=${streams}`], (m) => {
        const d = m?.data;
        if (!d) return;
        if (!f.live) { f.live = true; retry = 0; }
        if (d.e === "aggTrade") {
          const p = +d.p, usd = p * +d.q, coin = BY_STREAM[d.s];
          if (!coin || !Number.isFinite(usd)) return;
          const t: Trade = { s: coin.sym, usd, buy: !d.m, t: d.T, p };
          f.trades.push(t);
          subs.forEach((fn) => fn(t, null));
        } else if (d.e === "forceOrder") {
          const o = d.o, coin = BY_STREAM[o?.s];
          if (!coin) return;
          const p = +(o.ap || o.p), usd = p * +(o.z || o.q);
          // a SELL order closes a long: someone who bet on a rise was wiped out
          const l: Liq = { s: coin.sym, usd, longWiped: o.S === "SELL", t: o.T ?? d.E, p };
          f.liqs.unshift(l); if (f.liqs.length > 300) f.liqs.pop();
          subs.forEach((fn) => fn(null, l));
        } else if (d.e === "markPriceUpdate") {
          const coin = BY_STREAM[d.s];
          if (coin) f.funding[coin.sym] = { rate: +d.r, next: +d.T };
        }
      }, () => {
        f.live = false;
        if (closed) return;
        timer = window.setTimeout(connect, Math.min(30_000, 1000 * 2 ** retry++));
      });
    };
    connect();
    // prune to 5 minutes and refresh the numbers 2x a second
    const iv = window.setInterval(() => {
      const cut = Date.now() - 5 * 60_000;
      let i = 0; while (i < f.trades.length && f.trades[i].t < cut) i++;
      if (i) f.trades.splice(0, i);
      bump((n) => n + 1);
    }, 500);
    return () => { closed = true; race?.close(); window.clearTimeout(timer); window.clearInterval(iv); };
  }, []);
  return ref.current;
}

const reduced = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

interface Dot { row: number; buy: boolean; liq?: boolean; r: number; born: number; dur: number; lane: number }

/** The river: one lane per coin, buyers' money in from the left, sellers' money out to the right. */
export function FlowRiver({ feed, paused }: { feed: Feed; paused: boolean }) {
  const wrap = useRef<HTMLDivElement>(null);
  const cvs = useRef<HTMLCanvasElement>(null);
  const dots = useRef<Dot[]>([]);
  const pend = useRef<Record<string, { buy: number; sell: number }>>({});
  const [w, setW] = useState(800);
  useEffect(() => {
    const el = wrap.current; if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el); setW(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  // trades are pooled for 200 ms per coin and side, so a busy market draws a steady stream, not thousands of specks
  useEffect(() => feed.sub((t, l) => {
    if (t) { const k = pend.current[t.s] ?? (pend.current[t.s] = { buy: 0, sell: 0 }); if (t.buy) k.buy += t.usd; else k.sell += t.usd; }
    if (l) {
      const row = FLOW.findIndex((f) => f.sym === l.s);
      if (row >= 0) dots.current.push({ row, buy: false, liq: true, r: Math.min(26, 6 + Math.sqrt(l.usd) / 40), born: performance.now(), dur: 1600, lane: 0 });
    }
  }), [feed]);
  useEffect(() => {
    const c = cvs.current; if (!c) return;
    const ctx = c.getContext("2d")!;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const rowH = w < 640 ? 96 : 92;
    const yc = (i: number) => rowH * i + (w < 640 ? rowH * 0.66 : rowH / 2);   // phones: labels on top, flow below
    const H = rowH * FLOW.length;
    c.width = Math.round(w * dpr); c.height = Math.round(H * dpr); c.style.height = `${H}px`;
    const css = (v: string) => getComputedStyle(document.documentElement).getPropertyValue(v).trim() || "128 128 128";
    const bull = css("--bull"), bear = css("--bear"), warn = css("--warn"), glass = css("--glass");
    const left = w < 640 ? 8 : 150, right = w < 640 ? 8 : 120;
    const cx = left + (w - left - right) / 2;
    let raf = 0, last = 0;
    const flush = (now: number) => {
      for (const [s, k] of Object.entries(pend.current)) {
        const row = FLOW.findIndex((f) => f.sym === s); if (row < 0) continue;
        for (const [buy, usd] of [[true, k.buy], [false, k.sell]] as const) {
          if (usd < 500) continue;
          dots.current.push({ row, buy, r: Math.max(1.5, Math.min(12, Math.sqrt(usd) / 26)), born: now, dur: 2600 + Math.random() * 900, lane: (Math.random() - 0.5) * rowH * (w < 640 ? 0.3 : 0.42) });
        }
      }
      pend.current = {};
      if (dots.current.length > 700) dots.current.splice(0, dots.current.length - 700);
    };
    const draw = (now: number) => {
      raf = requestAnimationFrame(draw);
      if (paused || document.hidden) return;
      if (now - last > 200) { flush(now); last = now; }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, H);
      FLOW.forEach((f, i) => {
        const y = yc(i);
        const gl = ctx.createLinearGradient(left, 0, cx, 0); gl.addColorStop(0, `rgb(${bull} / 0)`); gl.addColorStop(1, `rgb(${bull} / .35)`);
        const gr = ctx.createLinearGradient(cx, 0, w - right, 0); gr.addColorStop(0, `rgb(${bear} / .35)`); gr.addColorStop(1, `rgb(${bear} / 0)`);
        ctx.fillStyle = gl; ctx.fillRect(left, y - 0.75, cx - left, 1.5);
        ctx.fillStyle = gr; ctx.fillRect(cx, y - 0.75, w - right - cx, 1.5);
        const halo = ctx.createRadialGradient(cx, y, 2, cx, y, rowH * (w < 640 ? 0.3 : 0.42));
        halo.addColorStop(0, `rgb(${f.color} / .55)`); halo.addColorStop(1, `rgb(${f.color} / 0)`);
        ctx.fillStyle = halo; ctx.beginPath(); ctx.arc(cx, y, rowH * (w < 640 ? 0.3 : 0.42), 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = `rgb(${f.color})`; ctx.beginPath(); ctx.arc(cx, y, w < 640 ? 11 : 14, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = `rgb(${glass} / .95)`; ctx.font = `600 ${w < 640 ? 10 : 12}px "DM Sans Variable", "DM Sans", system-ui, sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillText(f.label === "Gold" ? "Au" : base(f.sym).slice(0, 3), cx, y + 0.5);
      });
      const keep: Dot[] = [];
      for (const d of dots.current) {
        const k = (now - d.born) / d.dur;
        if (k >= 1) continue;
        keep.push(d);
        const y0 = yc(d.row);
        if (d.liq) {
          const rr = d.r * (0.6 + k * 1.6);
          ctx.strokeStyle = `rgb(${warn} / ${0.85 * (1 - k)})`; ctx.lineWidth = 2;
          ctx.beginPath(); ctx.arc(cx, y0, rr, 0, Math.PI * 2); ctx.stroke();
          ctx.fillStyle = `rgb(${warn} / ${0.35 * (1 - k)})`; ctx.beginPath(); ctx.arc(cx, y0, rr * 0.6, 0, Math.PI * 2); ctx.fill();
          continue;
        }
        const e = 1 - (1 - k) * (1 - k);                       // ease out
        const x = d.buy ? left + (cx - left) * e : cx + (w - right - cx) * e;
        const y = y0 + d.lane * (d.buy ? 1 - e : e);           // lanes converge into the coin, spread when leaving
        const a = d.buy ? Math.min(1, k * 4) * (1 - Math.max(0, k - 0.85) / 0.15) : (1 - k) * Math.min(1, k * 8);
        const col = d.buy ? bull : bear;
        ctx.fillStyle = `rgb(${col} / ${0.22 * a})`;            // soft trail
        ctx.beginPath(); ctx.ellipse(x + (d.buy ? -d.r * 1.6 : d.r * 1.6), y, d.r * 2.2, d.r * 0.8, 0, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = `rgb(${col} / ${0.9 * a})`;
        ctx.beginPath(); ctx.arc(x, y, d.r, 0, Math.PI * 2); ctx.fill();
      }
      dots.current = keep;
    };
    if (reduced()) { draw(performance.now()); cancelAnimationFrame(raf); return; }
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [w, paused]);

  const minute = tallies(feed.trades, 60_000);     // the page re-renders twice a second with the feed
  const rowH = w < 640 ? 96 : 92;
  return (
    <div ref={wrap} className="mf-river relative">
      <canvas ref={cvs} className="block w-full" aria-hidden="true" />
      {FLOW.map((f, i) => (
        <div key={f.sym} className="mf-row" style={{ top: rowH * i, height: rowH }}>
          <RowLabel f={f} />
          <div className="mf-tally">
            <span className="text-bull">in ${fmtCompact(minute[f.sym]?.buy ?? 0)}</span>
            <span className="text-bear">out ${fmtCompact(minute[f.sym]?.sell ?? 0)}</span>
          </div>
        </div>
      ))}
      <p className="sr-only">Live money flow for Bitcoin, Ether, Solana and gold over the last minute: {FLOW.map((f) => `${f.label} in ${fmtCompact(minute[f.sym]?.buy ?? 0)} dollars, out ${fmtCompact(minute[f.sym]?.sell ?? 0)} dollars`).join("; ")}.</p>
    </div>
  );
}

function RowLabel({ f }: { f: (typeof FLOW)[number] }) {
  const t = useTickerThrottled(f.sym, 1000);
  const ch = t?.change_pct;
  return (
    <Link to={`/asset/${slug(f.sym)}`} className="mf-label">
      <b>{f.label}</b>
      <span className="num">{isNum(t?.last) ? `$${fmtPrice(t!.last)}` : "–"} <span className={!isNum(ch) ? "text-mute" : ch >= 0 ? "text-bull" : "text-bear"}>{isNum(ch) ? `${ch >= 0 ? "▲" : "▼"} ${fmtPctRaw(Math.abs(ch))}` : ""}</span></span>
    </Link>
  );
}

export function tallies(trades: Trade[], ms: number) {
  const cut = Date.now() - ms, out: Record<string, { buy: number; sell: number }> = {};
  for (let i = trades.length - 1; i >= 0 && trades[i].t >= cut; i--) {
    const t = trades[i], k = out[t.s] ?? (out[t.s] = { buy: 0, sell: 0 });
    if (t.buy) k.buy += t.usd; else k.sell += t.usd;
  }
  return out;
}

const ago = (t: number) => { const s = Math.max(0, Math.round((Date.now() - t) / 1000)); return s < 60 ? `${s}s ago` : `${Math.round(s / 60)} min ago`; };
const timeOf = (t: number) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export function FlowStats({ feed }: { feed: Feed }) {
  const m = tallies(feed.trades, 60_000);
  const tot = Object.values(m).reduce((a, k) => a + k.buy + k.sell, 0);
  const net = Object.values(m).reduce((a, k) => a + k.buy - k.sell, 0);
  const big = feed.trades.reduce<Trade | null>((b, t) => (!b || t.usd > b.usd ? t : b), null);
  const lw = feed.liqs.filter((l) => l.longWiped).reduce((a, l) => a + l.usd, 0);
  const sw = feed.liqs.filter((l) => !l.longWiped).reduce((a, l) => a + l.usd, 0);
  const mins = Math.max(1, Math.round((Date.now() - feed.since) / 60_000));
  return (
    <div className="mf-stats">
      <div><span className="mf-k">Traded in the last minute</span><b className="num">${fmtCompact(tot)}</b>
        <span className="mf-s">{FLOW.map((f) => `${f.label === "Gold" ? "gold" : base(f.sym)} $${fmtCompact((m[f.sym]?.buy ?? 0) + (m[f.sym]?.sell ?? 0))}`).join(" · ")}</span></div>
      <div><span className="mf-k">Buyers minus sellers, last minute</span><b className={`num ${net >= 0 ? "text-bull" : "text-bear"}`}>{net >= 0 ? "+" : "−"}${fmtCompact(Math.abs(net))}</b>
        <span className="mf-s">{net >= 0 ? "more money buying than selling" : "more money selling than buying"}</span></div>
      <div><span className="mf-k">Bets wiped out, last {mins < 60 ? `${mins} min` : `${Math.round(mins / 60)} h`}</span><b className="num">${fmtCompact(lw + sw)}</b>
        <span className="mf-s">rise-bets ${fmtCompact(lw)} · fall-bets ${fmtCompact(sw)}</span></div>
      <div><span className="mf-k">Biggest single trade, last 5 min</span><b className="num">{big ? `$${fmtCompact(big.usd)}` : "–"}</b>
        <span className="mf-s">{big ? `${big.buy ? "bought" : "sold"} ${FLOW.find((f) => f.sym === big.s)?.label} at ${timeOf(big.t)}` : "waiting for trades"}</span></div>
    </div>
  );
}

// v2.62 (owner: "too fast, hard to track"): the two lists are calm. Trades of the same coin and side close together are
// merged into one row, new rows arrive at most once every RELEASE_MS, and nothing moves while the pointer / finger is
// on the list or it is paused - new rows wait behind a "Show N new" button instead.
const RELEASE_MS = 4000;
interface Row { id: number; s: string; buy: boolean; usd: number; n: number; p: number; t: number; liq?: boolean }
let rowId = 0;

function useCalmList(merge_ms: number) {
  const [rows, setRows] = useState<Row[]>([]);
  const [held, setHeld] = useState(false);
  const [waiting, setWaiting] = useState(0);
  const pending = useRef<Row[]>([]);
  const heldRef = useRef(false);
  heldRef.current = held;
  const add = (r: Omit<Row, "id" | "n">) => {
    const q = pending.current, last = q[0];
    if (last && last.s === r.s && last.buy === r.buy && last.liq === r.liq && r.t - last.t <= merge_ms) {
      last.usd += r.usd; last.n += 1; last.t = r.t; last.p = r.p;
    } else q.unshift({ ...r, id: ++rowId, n: 1 });
    if (q.length > 20) q.length = 20;
  };
  const release = () => {
    const q = pending.current; if (!q.length) return;
    pending.current = [];
    setRows((cur) => {
      const top = cur[0], next = [...q];
      const tail = next[next.length - 1];
      // the oldest new row continues the current top row when it is the same coin / side and close in time
      if (top && tail && top.s === tail.s && top.buy === tail.buy && top.liq === tail.liq && tail.t - top.t <= merge_ms) {
        next[next.length - 1] = { ...tail, usd: tail.usd + top.usd, n: tail.n + top.n, id: top.id };
        return [...next, ...cur.slice(1)].slice(0, 8);
      }
      return [...next, ...cur].slice(0, 8);
    });
    setWaiting(0);
  };
  useEffect(() => {
    const iv = window.setInterval(() => { if (heldRef.current) setWaiting(pending.current.length); else release(); }, RELEASE_MS);
    return () => window.clearInterval(iv);
  }, []);
  return { rows, add, held, setHeld, waiting, release };
}

function CalmList({ list, empty, render }: { list: ReturnType<typeof useCalmList>; empty: string; render: (r: Row) => ReactNode }) {
  const [paused, setPaused] = useState(false);
  const hover = useRef(false);
  const sync = () => list.setHeld(paused || hover.current);
  useEffect(sync, [paused]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="mf-list" onPointerEnter={() => { hover.current = true; sync(); }} onPointerLeave={() => { hover.current = false; sync(); }}>
      <div className="flex items-center justify-between gap-2 text-xs text-mute">
        <span>{list.held ? (list.waiting ? `${list.waiting} new waiting` : "Paused") : "Updates every few seconds"}</span>
        <span className="flex items-center gap-1.5">
          {list.held && list.waiting > 0 && <button type="button" className="btn px-2 py-0.5 text-xs" onClick={list.release}>Show new</button>}
          <button type="button" className="btn px-2 py-0.5 text-xs" aria-pressed={paused} onClick={() => setPaused((p) => !p)}>{paused ? "Resume" : "Pause"}</button>
        </span>
      </div>
      {list.rows.length === 0 && <p className="text-sm text-mute">{empty}</p>}
      {list.rows.map((r) => <div key={r.id} className={`mf-item ${r.liq ? "is-liq" : r.buy ? "is-buy" : "is-sell"}`}>{render(r)}</div>)}
    </div>
  );
}

export function WhaleWatch({ feed }: { feed: Feed }) {
  const list = useCalmList(8000);
  useEffect(() => feed.sub((t) => {
    if (!t) return;
    const f = FLOW.find((x) => x.sym === t.s);
    if (f && t.usd >= f.whale) list.add({ s: t.s, buy: t.buy, usd: t.usd, p: t.p, t: t.t });
  }), [feed]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <CalmList list={list} empty="Waiting for a big trade: $250K+ Bitcoin, $150K+ Ether, $50K+ Solana or gold."
      render={(r) => (<>
        <CoinAvatar symbol={r.s} size={20} />
        <span className="min-w-0 flex-1 truncate"><b>{r.buy ? "Bought" : "Sold"}</b> {FLOW.find((f) => f.sym === r.s)?.label} at ${fmtPrice(r.p)}{r.n > 1 ? <span className="text-mute"> · {r.n} trades</span> : null}</span>
        <b className={`num ${r.buy ? "text-bull" : "text-bear"}`}>${fmtCompact(r.usd)}</b>
        <span className="num w-16 text-right text-xs text-mute">{ago(r.t)}</span>
      </>)} />
  );
}

export function WipeOuts({ feed }: { feed: Feed }) {
  const list = useCalmList(15000);
  useEffect(() => feed.sub((_, l) => {
    if (l) list.add({ s: l.s, buy: !l.longWiped, usd: l.usd, p: l.p, t: l.t, liq: true });
  }), [feed]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <CalmList list={list} empty="No forced closes yet since you opened this page. They appear here as the exchange reports them."
      render={(r) => (<>
        <CoinAvatar symbol={r.s} size={20} />
        <span className="min-w-0 flex-1 truncate"><b>{r.buy ? "Fall-bets" : "Rise-bets"}</b> wiped out · {FLOW.find((f) => f.sym === r.s)?.label}{r.n > 1 ? <span className="text-mute"> · {r.n} closes</span> : null}</span>
        <b className="num text-warn">${fmtCompact(r.usd)}</b>
        <span className="num w-16 text-right text-xs text-mute">{ago(r.t)}</span>
      </>)} />
  );
}

/** Funding: positive = rise-bets pay fall-bets every 8 h (the crowd leans up), negative = the other way. */
export function FundingBars({ feed }: { feed: Feed }) {
  return (
    <div className="space-y-3">
      {FLOW.map((f) => {
        const r = feed.funding[f.sym]?.rate;
        const pct = isNum(r) ? r * 100 : null;
        const pos = Math.max(-1, Math.min(1, (pct ?? 0) / 0.05));    // ±0.05 % per 8 h = full bar
        return (
          <div key={f.sym} className="mf-fund">
            <span className="w-16 text-sm font-medium">{f.label}</span>
            <div className="mf-fund-track" aria-hidden="true">
              <span className="mf-fund-mid" />
              <span className={`mf-fund-bar ${pos >= 0 ? "is-pos" : "is-neg"}`} style={pos >= 0 ? { left: "50%", width: `${pos * 50}%` } : { right: "50%", width: `${-pos * 50}%` }} />
            </div>
            <span className={`num w-24 text-right text-sm ${pct == null ? "text-mute" : pct >= 0 ? "text-bull" : "text-bear"}`}>{pct == null ? "–" : `${pct >= 0 ? "+" : ""}${pct.toFixed(4)}%`}</span>
          </div>
        );
      })}
      <p className="text-xs text-mute">Every 8 hours. Plus = buyers with leverage pay sellers (the crowd leans up). Minus = the other way.</p>
    </div>
  );
}

// ---- 24 h net flow per coin -------------------------------------------------------------------------------------
interface Net { sym: string; net: number; vol: number }

async function netFlow(sym: string): Promise<Net | null> {
  const b = sym.replace("/", "");
  for (const url of [`https://fapi.binance.com/fapi/v1/klines?symbol=${b}&interval=1h&limit=24`, `https://api.binance.com/api/v3/klines?symbol=${b}&interval=1h&limit=24`]) {
    try {
      const r = await fetch(url); if (!r.ok) continue;
      const rows: any[] = await r.json();
      let vol = 0, buy = 0;
      for (const k of rows) { vol += +k[7]; buy += +k[10]; }      // quote volume, taker-buy quote volume
      return { sym, net: buy - (vol - buy), vol };
    } catch { /* next */ }
  }
  return null;
}

export function NetFlowSankey({ symbols }: { symbols: string[] }) {
  const [rows, setRows] = useState<Net[] | null>(null);
  const [w, setW] = useState(0);
  const wrap = useRef<HTMLDivElement>(null);
  const key = symbols.join(",");
  useEffect(() => {
    const el = wrap.current; if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth)); ro.observe(el); setW(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    let alive = true;
    const load = async () => {
      if (document.hidden) return;
      const out = (await Promise.all(symbols.slice(0, 16).map(netFlow))).filter(Boolean) as Net[];
      if (alive) setRows(out);
    };
    load();
    const iv = window.setInterval(load, 5 * 60_000);
    return () => { alive = false; window.clearInterval(iv); };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!rows || !w) return <div ref={wrap} className="min-w-0 overflow-hidden"><div className="skeleton h-72 rounded-xl" /></div>;
  const out = rows.filter((r) => r.net < 0).sort((a, b) => a.net - b.net);
  const inn = rows.filter((r) => r.net >= 0).sort((a, b) => b.net - a.net);
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.net)));
  const narrow = w < 640;
  const n = Math.max(out.length, inn.length, 1);
  const T = 30;                                        // room for the "Net" label above the bar
  const rowH = narrow ? 30 : 34, H = T + n * rowH + 10, cx = w / 2, barW = 8;
  const labW = narrow ? 112 : 150;
  const thick = (v: number) => Math.max(3, (Math.abs(v) / max) * (rowH - 6));
  const sideY = (i: number) => T + i * rowH + rowH / 2;
  // ribbons meet the centre bar stacked in order
  const stack = (list: Net[]) => { let y = 8; const tot = list.reduce((a, r) => a + thick(r.net), 0); const top = (T + H - 10) / 2 - tot / 2; y = top; return list.map((r) => { const h = thick(r.net); const m = y + h / 2; y += h; return m; }); };
  const mo = stack(out), mi = stack(inn);
  const ribbon = (x0: number, y0: number, x1: number, y1: number, h: number) =>
    `M${x0} ${y0 - h / 2} C${(x0 + x1) / 2} ${y0 - h / 2} ${(x0 + x1) / 2} ${y1 - h / 2} ${x1} ${y1 - h / 2} L${x1} ${y1 + h / 2} C${(x0 + x1) / 2} ${y1 + h / 2} ${(x0 + x1) / 2} ${y0 + h / 2} ${x0} ${y0 + h / 2} Z`;
  const spine = (x0: number, y0: number, x1: number, y1: number) => `M${x0} ${y0} C${(x0 + x1) / 2} ${y0} ${(x0 + x1) / 2} ${y1} ${x1} ${y1}`;
  const motion = !reduced();
  // money moving along each ribbon: more dots on thicker ribbons (left: leaving the coin, right: arriving)
  const particles = (key: string, d: string, h: number, color: string) => {
    if (!motion) return null;
    const count = Math.max(2, Math.min(8, Math.round(h / 3.5)));
    return Array.from({ length: count }, (_, j) => {
    const dur = 4 + (key.charCodeAt(0) % 5) * 0.4;
    const off = ((j * 0.37) % 1 - 0.5) * Math.max(0, h - 4);
    return (
      <circle key={`${key}-${j}`} r={1.6 + ((j * 7) % 3) * 0.7} cy={off} fill={color} opacity=".85">
        <animateMotion dur={`${dur}s`} begin={`${(-dur * j) / count}s`} repeatCount="indefinite" path={d} />
      </circle>
    );
    });
  };
  const net = rows.reduce((a, r) => a + r.net, 0);
  return (
    <div ref={wrap} className="min-w-0 overflow-hidden">
      <svg width="100%" height={H} style={{ display: "block" }} viewBox={`0 0 ${w} ${H}`} role="img" aria-label={`Net money flow over 24 hours: ${inn.length} coins with more buying, ${out.length} with more selling`}>
        <defs>
          <linearGradient id="nf-out" x1="0" x2="1"><stop offset="0" stopColor="rgb(var(--bear))" stopOpacity=".55" /><stop offset="1" stopColor="rgb(var(--bear))" stopOpacity=".12" /></linearGradient>
          <linearGradient id="nf-in" x1="0" x2="1"><stop offset="0" stopColor="rgb(var(--bull))" stopOpacity=".12" /><stop offset="1" stopColor="rgb(var(--bull))" stopOpacity=".55" /></linearGradient>
        </defs>
        {out.map((r, i) => <path key={r.sym} d={ribbon(labW, sideY(i), cx - barW / 2, mo[i], thick(r.net))} fill="url(#nf-out)" className="nf-ribbon" />)}
        {inn.map((r, i) => <path key={r.sym} d={ribbon(cx + barW / 2, mi[i], w - labW, sideY(i), thick(r.net))} fill="url(#nf-in)" className="nf-ribbon" />)}
        {out.map((r, i) => <g key={`p${r.sym}`}>{particles(r.sym, spine(labW, sideY(i), cx - barW / 2, mo[i]), thick(r.net), "rgb(var(--bear))")}</g>)}
        {inn.map((r, i) => <g key={`p${r.sym}`}>{particles(r.sym, spine(cx + barW / 2, mi[i], w - labW, sideY(i)), thick(r.net), "rgb(var(--bull))")}</g>)}
        <rect x={cx - barW / 2} y={T - 4} width={barW} height={H - T - 4} rx={4} fill="rgb(var(--ai))" opacity=".85" />
        <text x={cx} y={14} textAnchor="middle" className="nf-text"><tspan fill="rgb(var(--mute))">Net </tspan><tspan className="nf-num" fill={net >= 0 ? "rgb(var(--bull))" : "rgb(var(--bear))"}>{net >= 0 ? "+" : "−"}${fmtCompact(Math.abs(net))}</tspan></text>
        {out.map((r, i) => (
          <g key={r.sym}>
            <circle cx={labW - 4} cy={sideY(i)} r={3.5} fill="rgb(var(--bear))" />
            <text x={labW - 12} y={sideY(i)} textAnchor="end" dominantBaseline="middle" className="nf-text">{base(r.sym)} <tspan className="nf-num" fill="rgb(var(--bear))">−${fmtCompact(-r.net)}</tspan></text>
          </g>
        ))}
        {inn.map((r, i) => (
          <g key={r.sym}>
            <circle cx={w - labW + 4} cy={sideY(i)} r={3.5} fill="rgb(var(--bull))" />
            <text x={w - labW + 12} y={sideY(i)} dominantBaseline="middle" className="nf-text">{base(r.sym)} <tspan className="nf-num" fill="rgb(var(--bull))">+${fmtCompact(r.net)}</tspan></text>
          </g>
        ))}
      </svg>
    </div>
  );
}

// ---- whale direction: who placed the big trades -----------------------------------------------------------------
/** Big trades (whale size per coin) over the last 5 minutes: money that bought vs money that sold. */
export function WhaleBalance({ feed }: { feed: Feed }) {
  let buy = 0, sell = 0, nb = 0, ns = 0;
  const cut = Date.now() - 5 * 60_000;
  for (const t of feed.trades) {
    if (t.t < cut) continue;
    const f = FLOW.find((x) => x.sym === t.s);
    if (!f || t.usd < f.whale) continue;
    if (t.buy) { buy += t.usd; nb++; } else { sell += t.usd; ns++; }
  }
  const tot = buy + sell;
  const pb = tot ? (buy / tot) * 100 : 50;
  return (
    <div className="mf-whalebar">
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span><b className="num text-bull">${fmtCompact(buy)}</b> <span className="text-mute">bought · {nb}</span></span>
        <span className="text-xs text-mute">big trades, last 5 min</span>
        <span><span className="text-mute">{ns} · sold</span> <b className="num text-bear">${fmtCompact(sell)}</b></span>
      </div>
      <div className="mf-split" role="img" aria-label={`Big trades last 5 minutes: ${fmtCompact(buy)} dollars bought, ${fmtCompact(sell)} dollars sold`}>
        <span className="is-buy" style={{ width: `${pb}%` }} /><span className="is-sell" style={{ width: `${100 - pb}%` }} />
      </div>
      <p className="text-xs text-mute">{!tot ? "No big trades in the last 5 minutes." : pb >= 60 ? "Big money is mostly buying." : pb <= 40 ? "Big money is mostly selling." : "Big money is split between buying and selling."}</p>
    </div>
  );
}

// ---- liquidity map: where the resting orders sit --------------------------------------------------------------------
interface Book { mid: number; bins: { lo: number; hi: number; bid: number; ask: number }[] }

async function loadBook(sym: string, span: number): Promise<Book | null> {
  const b = sym.replace("/", "");
  try {
    const r = await fetch(`https://fapi.binance.com/fapi/v1/depth?symbol=${b}&limit=1000`);
    if (!r.ok) return null;
    const d: any = await r.json();
    const bids: [number, number][] = (d.bids ?? []).map((x: any) => [+x[0], +x[1]]);
    const asks: [number, number][] = (d.asks ?? []).map((x: any) => [+x[0], +x[1]]);
    if (!bids.length || !asks.length) return null;
    const mid = (bids[0][0] + asks[0][0]) / 2;
    const N = 40, lo = mid * (1 - span), step = (mid * 2 * span) / N;
    const bins = Array.from({ length: N }, (_, i) => ({ lo: lo + i * step, hi: lo + (i + 1) * step, bid: 0, ask: 0 }));
    for (const [p, q] of bids) { const i = Math.floor((p - lo) / step); if (i >= 0 && i < N) bins[i].bid += p * q; }
    for (const [p, q] of asks) { const i = Math.floor((p - lo) / step); if (i >= 0 && i < N) bins[i].ask += p * q; }
    return { mid, bins };
  } catch { return null; }
}

/** Resting buy orders (support walls, green) below the price and sell orders (resistance walls, red) above it,
 *  from the futures order book, in 40 price bands. Refreshed every 30 s while on screen. Forced closes since the page
 *  opened are marked on the ladder. */
export function LiquidityMap({ feed }: { feed: Feed }) {
  const [sym, setSym] = useState(FLOW[0].sym);
  const [book, setBook] = useState<Book | null>(null);
  const [at, setAt] = useState(0);
  const span = sym === "PAXG/USDT" ? 0.01 : sym === "BTC/USDT" ? 0.015 : 0.025;   // ± range around the price
  useEffect(() => {
    let alive = true;
    setBook(null);
    const load = async () => { if (document.hidden) return; const b = await loadBook(sym, span); if (alive && b) { setBook(b); setAt(Date.now()); } };
    load();
    const iv = window.setInterval(load, 30_000);
    return () => { alive = false; window.clearInterval(iv); };
  }, [sym, span]);
  const max = book ? Math.max(1, ...book.bins.map((b) => Math.max(b.bid, b.ask))) : 1;
  const walls = book ? [...book.bins].sort((a, b) => Math.max(b.bid, b.ask) - Math.max(a.bid, a.ask)).slice(0, 3) : [];
  const liqs = feed.liqs.filter((l) => l.s === sym);
  const rows = book ? [...book.bins].reverse() : [];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="seg" role="group" aria-label="Coin">
          {FLOW.map((f) => <button key={f.sym} type="button" aria-pressed={sym === f.sym} onClick={() => setSym(f.sym)}>{f.label}</button>)}
        </div>
        <span className="text-xs text-mute">{book ? `±${(span * 100).toFixed(1)}% around $${fmtPrice(book.mid)} · updated ${Math.max(0, Math.round((Date.now() - at) / 1000))}s ago` : "loading the order book…"}</span>
      </div>
      {!book ? <div className="skeleton h-80 rounded-xl" /> : (
        <div className="lq-map" role="img" aria-label={`Order book for ${sym}: biggest walls at ${walls.map((w) => `$${fmtPrice((w.lo + w.hi) / 2)}`).join(", ")}`}>
          {rows.map((b, i) => {
            const midRow = b.lo <= book.mid && b.hi > book.mid;
            const wall = walls.includes(b) && Math.max(b.bid, b.ask) > 0;
            const liq = liqs.find((l) => l.p >= b.lo && l.p < b.hi);
            const v = Math.max(b.bid, b.ask), ask = b.ask >= b.bid;
            return (
              <div key={i} className={`lq-row ${midRow ? "is-mid" : ""}`}>
                <span className="lq-price num">{fmtPrice((b.lo + b.hi) / 2)}</span>
                <span className="lq-bar-wrap">
                  {v > 0 && <span className={`lq-bar ${ask ? "is-ask" : "is-bid"} ${wall ? "is-wall" : ""}`} style={{ width: `${Math.max(1.5, (v / max) * 100)}%`, opacity: 0.35 + 0.65 * (v / max) }} />}
                </span>
                <span className="lq-val num">{v > 0 ? `$${fmtCompact(v)}` : ""}{wall && <b className={ask ? "text-bear" : "text-bull"}> {ask ? "sell wall" : "buy wall"}</b>}{liq && <b className="text-warn"> ⚡</b>}</span>
              </div>
            );
          })}
        </div>
      )}
      <p className="text-xs text-mute">Green = waiting buy orders below the price (support), red = waiting sell orders above it (resistance). Big walls can be pulled at any time. ⚡ = a forced close at that price since you opened the page.</p>
    </div>
  );
}
