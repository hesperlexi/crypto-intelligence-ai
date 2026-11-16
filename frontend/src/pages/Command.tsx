// v2.45 Command Centre (owner, 16 Nov 2026: the approved "Command Centre concept", gold-black theme). An extra page:
// nothing else changes. Real data only, from documents the app already reads:
//   views/dashboard_4h (coins, regime, AI lean, RSI / ADX, 24h change + volume), the six views/futures_<tf> boards (the
//   Signals page's calls), views/track_record (open calls), views/market_context + context (alt strength, Fear & Greed),
//   views/health (mission control; already open in the header), the coin's analysis view for the scan (1 read per coin
//   picked). Correlations from public Binance 1h candles in the browser (no Firebase).
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader, Segmented } from "../components/kit";
import { CoinAvatar } from "../components/Polish";
import { ErrorBox, Loading } from "../components/ui";
import { useApi } from "../lib/api";
import { useKlines } from "../lib/klines";
import LazyMount from "../components/LazyMount";
import { CoinCompare, HeatGlobe, SignalJourneys } from "../components/CommandPlus";
import { useLive, useTicker } from "../lib/live";
import { ago, base, fmtCompact, fmtPrice, isNum, slug } from "../lib/format";

const TFS = ["15m", "1h", "4h", "12h", "1d", "3d"] as const;
const UP = "rgb(var(--bull))", DN = "rgb(var(--bear))", GOLD = "rgb(var(--accent))", MUTE = "rgb(var(--mute))";
const name = (s: string) => (base(s) === "PAXG" ? "GOLD" : base(s));
const pct = (v: number | null | undefined, d = 1) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "—");
const callOf = (r: any): 1 | -1 | 0 => (r?.side && r?.plan?.valid ? (r.side > 0 ? 1 : -1) : 0);

function Defs() {
  return (
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
      <defs>
        <radialGradient id="cc-up" cx="35%" cy="30%"><stop offset="0%" stopColor="#b9f5da" /><stop offset="45%" stopColor="rgb(var(--bull))" /><stop offset="100%" stopColor="#06503a" /></radialGradient>
        <radialGradient id="cc-dn" cx="35%" cy="30%"><stop offset="0%" stopColor="#ffc2ca" /><stop offset="45%" stopColor="rgb(var(--bear))" /><stop offset="100%" stopColor="#5e1420" /></radialGradient>
        <radialGradient id="cc-gold" cx="35%" cy="30%"><stop offset="0%" stopColor="#fff1c4" /><stop offset="45%" stopColor="#f0b90b" /><stop offset="100%" stopColor="#6b4c06" /></radialGradient>
        <radialGradient id="cc-glow"><stop offset="0%" stopColor="rgb(var(--accent) / 0.5)" /><stop offset="60%" stopColor="rgb(var(--accent) / 0.08)" /><stop offset="100%" stopColor="rgb(var(--accent) / 0)" /></radialGradient>
        <linearGradient id="cc-sweep" x1="0" x2="1"><stop offset="0%" stopColor="rgb(var(--accent) / 0)" /><stop offset="100%" stopColor="rgb(var(--accent) / 0.32)" /></linearGradient>
      </defs>
    </svg>
  );
}

/* ---------------------------------------------------------------- galaxy */
function useNarrow() {
  const q = "(max-width: 640px)";
  const [n, setN] = useState(() => typeof window !== "undefined" && window.matchMedia(q).matches);
  useEffect(() => { const m = window.matchMedia(q); const on = () => setN(m.matches); m.addEventListener("change", on); return () => m.removeEventListener("change", on); }, []);
  return n;
}

function Galaxy({ rows, open, sel, onSel }: { rows: any[]; open: Set<string>; sel: string; onSel: (s: string) => void }) {
  const { tickers } = useLive();
  const narrow = useNarrow();                    // phones: a tighter drawing so labels stay readable
  const W = narrow ? 400 : 800, H = narrow ? 430 : 540;
  const C = { x: W / 2, y: H / 2 };
  const ranked = [...rows].sort((a, b) => (b.quote_volume_24h ?? 0) - (a.quote_volume_24h ?? 0));
  const maxV = Math.max(1, ...ranked.map((r) => r.quote_volume_24h ?? 0));
  const tiers = [ranked.slice(0, 2), ranked.slice(2, 6), ranked.slice(6)];
  const RAD = narrow ? [76, 122, 170] : [118, 180, 242];
  const planets = tiers.flatMap((t, ti) => t.map((r, i) => {
    const a = ((i / Math.max(1, t.length)) * 360 + ti * 37 - 90) * (Math.PI / 180);
    const chg = tickers[r.symbol]?.change_pct ?? r.change_24h_pct;
    const size = (narrow ? 7 : 9) + (narrow ? 9 : 15) * Math.sqrt((r.quote_volume_24h ?? 0) / maxV);
    return { r, x: C.x + RAD[ti] * Math.cos(a), y: C.y + RAD[ti] * Math.sin(a) * 0.92, size, chg, sig: open.has(r.symbol) };
  }));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="group" aria-label="Crypto galaxy: every coin you watch as a planet">
      <circle cx={C.x} cy={C.y} r={narrow ? 80 : 120} fill="url(#cc-glow)" />
      {RAD.map((r) => <ellipse key={r} cx={C.x} cy={C.y} rx={r} ry={r * 0.92} fill="none" stroke="rgb(var(--accent) / 0.22)" strokeDasharray="2 6" />)}
      <g className="cc-orbit" style={{ transformOrigin: `${C.x}px ${C.y}px` }}><circle cx={C.x + RAD[2]} cy={C.y} r="3" fill="#fff1c4" /></g>
      <circle cx={C.x} cy={C.y} r={narrow ? 22 : 32} fill="url(#cc-gold)" />
      <text x={C.x} y={C.y + 5} textAnchor="middle" fontSize="15" fontWeight="800" fill="#1a1408">AI</text>
      {planets.map((p) => {
        const on = p.r.symbol === sel;
        return (
          <g key={p.r.symbol} className="cc-planet" tabIndex={0} role="button" aria-label={`${name(p.r.symbol)} ${pct(p.chg)} in 24 hours${p.sig ? ", signal running" : ""}`}
            onClick={() => onSel(p.r.symbol)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSel(p.r.symbol); } }}>
            {on && <circle cx={p.x} cy={p.y} r={p.size + 13} fill="none" stroke="#fff1c4" strokeWidth="1.5" />}
            {p.sig && <circle cx={p.x} cy={p.y} r={p.size + 7} fill="none" stroke={GOLD} strokeWidth="2" strokeDasharray="4 3" />}
            <circle cx={p.x} cy={p.y} r={p.size} fill={name(p.r.symbol) === "GOLD" || p.r.symbol.startsWith("PAXG") ? "url(#cc-gold)" : (p.chg ?? 0) >= 0 ? "url(#cc-up)" : "url(#cc-dn)"} />
            <text x={p.x} y={p.y + p.size + 15} textAnchor="middle" fontSize="13" fontWeight="600" fill="rgb(var(--text))">{name(p.r.symbol)}</text>
            <text x={p.x} y={p.y + p.size + 29} textAnchor="middle" fontSize="12" fill={(p.chg ?? 0) >= 0 ? UP : DN}>{pct(p.chg)}</text>
          </g>
        );
      })}
    </svg>
  );
}

/* ---------------------------------------------------------------- radar */
function Radar({ boards, onSel, tf }: { boards: any[][]; onSel: (s: string) => void; tf?: string }) {
  // v2.46 redesign (owner: "match the concept"): calls only, each with a halo, a label placed outside its dot, a lit
  // slice where a timeframe has calls, an instrument tick ring and the strongest calls listed underneath.
  const C = 180, R = 150;
  const calls = TFS.flatMap((tf, ti) => (boards[ti] ?? []).map((r: any) => {
    const side = callOf(r);
    const lean = isNum(r.p_up) && isNum(r.p_down) ? Math.abs(r.p_up - r.p_down) : 0;
    return { r, tf, ti, side, a: r.grade === "A", strength: (r.grade === "A" ? 0.62 : 0.42) + 0.3 * Math.min(1, lean) };
  }).filter((b) => b.side !== 0))
    .sort((a, b) => b.strength - a.strength);
  const per = new Map<number, number>();
  const placed = calls.map((b) => {
    const k = per.get(b.ti) ?? 0; per.set(b.ti, k + 1);
    if (k >= 3) return null;                                  // the 3 strongest per timeframe (all in the list below)
    const mid = b.ti * 60 - 60;                               // slice centre (deg)
    const ang = (mid + (k === 1 ? -14 : k === 2 ? 14 : 0)) * (Math.PI / 180);
    const d = Math.min(R - 22, R * (1 - b.strength) + 26 + k * 26);
    const x = C + d * Math.cos(ang), y = C + d * Math.sin(ang);
    const out = Math.cos(ang) >= 0.05 || (Math.abs(Math.cos(ang)) < 0.05 && k !== 1);
    return { ...b, x, y, lx: x + (out ? 12 : -12), anchor: out ? "start" : "end" };
  }).filter(Boolean) as any[];
  const lit = new Set(placed.map((b) => b.ti));
  const wedge = (i: number) => {
    const a0 = (i * 60 - 90) * (Math.PI / 180), a1 = a0 + Math.PI / 3;
    return `M${C} ${C} L${C + R * Math.cos(a0)} ${C + R * Math.sin(a0)} A${R} ${R} 0 0 1 ${C + R * Math.cos(a1)} ${C + R * Math.sin(a1)} Z`;
  };
  return (
    <div>
      <svg viewBox="-20 -20 400 400" className="mx-auto w-full max-w-[400px]" role="group" aria-label="Opportunity radar: live calls by timeframe; closer to the centre = stronger">
        <defs>
          <radialGradient id="rd-bg"><stop offset="0%" stopColor="rgb(var(--accent) / 0.16)" /><stop offset="70%" stopColor="rgb(var(--accent) / 0.04)" /><stop offset="100%" stopColor="rgb(var(--accent) / 0)" /></radialGradient>
        </defs>
        <circle cx={C} cy={C} r={R + 12} fill="url(#rd-bg)" />
        {Array.from({ length: 72 }, (_, i) => {
          const a = (i * 5) * (Math.PI / 180), long = i % 6 === 0;
          return <line key={i} x1={C + (R + 3) * Math.cos(a)} y1={C + (R + 3) * Math.sin(a)} x2={C + (R + (long ? 10 : 6)) * Math.cos(a)} y2={C + (R + (long ? 10 : 6)) * Math.sin(a)} stroke={`rgb(var(--accent) / ${long ? 0.55 : 0.22})`} />;
        })}
        {TFS.map((_, i) => lit.has(i) && <path key={`w${i}`} d={wedge(i)} fill="rgb(var(--accent) / 0.07)" />)}
        {tf && TFS.indexOf(tf as any) >= 0 && <path d={wedge(TFS.indexOf(tf as any))} fill="none" stroke="rgb(var(--accent) / 0.7)" strokeWidth="1.5" strokeDasharray="4 4" />}
        <circle cx={C} cy={C} r={R} fill="none" stroke="rgb(var(--accent) / 0.45)" />
        {[0.66, 0.33].map((f) => <circle key={f} cx={C} cy={C} r={R * f} fill="none" stroke="rgb(var(--accent) / 0.16)" strokeDasharray="2 5" />)}
        {TFS.map((tf, i) => {
          const a = (i * 60 - 90) * (Math.PI / 180), m = a + Math.PI / 6;
          return (
            <g key={tf}>
              <line x1={C} y1={C} x2={C + R * Math.cos(a)} y2={C + R * Math.sin(a)} stroke="rgb(var(--accent) / 0.16)" />
              <text x={C + (R + 24) * Math.cos(m)} y={C + (R + 24) * Math.sin(m) + 4} textAnchor="middle" fontSize="12" fontWeight="700" fill={lit.has(i) ? "rgb(var(--accent))" : "rgb(var(--mute))"}>{tf.toUpperCase()}</text>
            </g>
          );
        })}
        <g className="cc-sweep" style={{ transformOrigin: `${C}px ${C}px` }}><path d={`M${C} ${C} L${C + R} ${C} A${R} ${R} 0 0 0 ${C + R * Math.cos(-Math.PI / 4)} ${C + R * Math.sin(-Math.PI / 4)} Z`} fill="url(#cc-sweep)" /></g>
        <circle cx={C} cy={C} r="7" fill="url(#cc-gold)" />
        {placed.map((b) => {
          const col = b.side > 0 ? UP : DN;
          return (
            <g key={`${b.tf}${b.r.symbol}`} className="cc-planet" tabIndex={0} role="button" onClick={() => onSel(b.r.symbol)} onKeyDown={(e) => { if (e.key === "Enter") onSel(b.r.symbol); }}
              aria-label={`${name(b.r.symbol)} ${b.tf}: ${b.side > 0 ? "long" : "short"}${b.a ? ", grade A" : ""}`}>
              <circle cx={b.x} cy={b.y} r={b.a ? 13 : 10} fill={b.side > 0 ? "rgb(var(--bull) / 0.18)" : "rgb(var(--bear) / 0.18)"} />
              {b.a && <circle cx={b.x} cy={b.y} r="13" fill="none" stroke="rgb(var(--accent) / 0.8)" strokeWidth="1.5" />}
              <circle cx={b.x} cy={b.y} r="5.5" fill={col} />
              <text x={b.lx} y={b.y + 4} textAnchor={b.anchor} fontSize="12" fontWeight="600" fill="rgb(var(--text))" className="rd-label">{name(b.r.symbol)}</text>
            </g>
          );
        })}
        {!placed.length && <text x={C} y={C + 30} textAnchor="middle" fontSize="13" fill={MUTE}>No live calls right now</text>}
      </svg>
      {calls.length > 0 && (
        <ul className="mt-2 grid grid-cols-2 gap-1.5">
          {calls.slice(0, 4).map((b) => (
            <li key={`l${b.tf}${b.r.symbol}`}>
              <button type="button" onClick={() => onSel(b.r.symbol)} className="rd-chip">
                <span className={b.side > 0 ? "text-bull" : "text-bear"}>{b.side > 0 ? "▲" : "▼"}</span>
                <b>{name(b.r.symbol)}</b><span className="text-mute">{b.tf.toUpperCase()}</span>{b.a && <span className="text-accent">A</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- AI core */
function Core({ row, f4, status, ctx, health, tf }: { row: any; f4: any; status: any; ctx: any; health: any; tf: string }) {
  const T = tf.toUpperCase();
  const mood = status?.status;
  const moodWord = mood === "BULL" ? "Leaning bullish" : mood === "BEAR" ? "Leaning bearish" : "Mixed";
  const last = health?.engine?.last_tick_finished;
  const fresh = isNum(last) && Date.now() - last < 15 * 60_000;
  const side = callOf(f4);
  const flags: string[] = (row?.flags ?? []).slice(0, 3);
  const fg = ctx?.sentiment?.value;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-4">
        <svg viewBox="0 0 120 120" width="96" height="96" aria-hidden="true">
          <circle cx="60" cy="60" r="56" fill="url(#cc-glow)" />
          <g className="cc-ring" style={{ transformOrigin: "60px 60px" }}><circle cx="60" cy="60" r="48" fill="none" stroke="#f0b90b" strokeWidth="2" strokeDasharray="40 14 6 14" /></g>
          <circle cx="60" cy="60" r="26" fill="url(#cc-gold)" />
          <text x="60" y="66" textAnchor="middle" fontSize="16" fontWeight="800" fill="#1a1408">AI</text>
        </svg>
        <div className="min-w-0">
          <h2 className="font-display text-xl font-semibold">Intelligence core</h2>
          <p className="text-sm text-mute">What the engine sees for <b className="text-text">{row ? name(row.symbol) : "—"}</b></p>
          <p className={`mt-1 text-xs ${fresh ? "text-bull" : "text-warn"}`}>{isNum(last) ? `Engine data ${ago(last)}` : "Engine time unknown"}</p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="cc-cell"><div className="text-xs text-mute">Market · {T}</div><div className={`font-semibold ${mood === "BULL" ? "text-bull" : mood === "BEAR" ? "text-bear" : ""}`}>{moodWord}</div><div className="text-xs text-mute">{status ? `${status.bull} bull · ${status.bear} bear of ${status.assets}` : "—"}</div></div>
        <div className="cc-cell"><div className="text-xs text-mute">{row ? `${name(row.symbol)} trend · ${T}` : "Trend"}</div><div className="font-semibold">{row?.trend_label ?? "—"}</div><div className="text-xs text-mute">{row?.regime ? String(row.regime).replace(/_/g, " ").toLowerCase() : "—"}</div></div>
        <div className="cc-cell"><div className="text-xs text-mute">AI lean · up / down</div><div className="num font-semibold">{isNum(row?.p_up) ? <><span className="text-bull">{Math.round(row.p_up * 100)}%</span> / <span className="text-bear">{Math.round(row.p_down * 100)}%</span></> : "no model yet"}</div><div className="text-xs text-mute">{T}, calibrated</div></div>
        <div className="cc-cell"><div className="text-xs text-mute">Call · {T}</div><div className={`font-semibold ${side > 0 ? "text-bull" : side < 0 ? "text-bear" : "text-mute"}`}>{side > 0 ? "LONG" : side < 0 ? "SHORT" : "No trade"}{side && f4?.grade ? ` · grade ${f4.grade}` : ""}</div><div className="text-xs text-mute">{isNum(fg) ? `Fear & Greed ${fg}` : "—"}</div></div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div><div className="text-xs font-semibold tracking-wide text-bull">SUPPORTS</div><p className="mt-1 text-sm">{side && f4?.decision_basis ? f4.decision_basis : row?.mtf_alignment ? `Timeframes aligned: ${row.mtf_alignment}` : "Nothing strong right now."}</p></div>
        <div><div className="text-xs font-semibold tracking-wide text-bear">WEAKENS</div><p className="mt-1 text-sm">{[f4?.news_risk?.title ? `${f4.news_risk.title} ${f4.news_risk.when ?? ""}` : null, !side && f4?.decision_reason ? f4.decision_reason : null, ...flags].filter(Boolean).join(" · ") || "No warning flags."}</p></div>
      </div>
      <p className="border-t border-glass/[0.07] pt-2 text-xs text-mute">Engine numbers only. Members see the grade, not a confidence score.</p>
    </div>
  );
}

/* ---------------------------------------------------------------- universe */
function corr(a: number[], b: number[]) {
  const n = Math.min(a.length, b.length);
  if (n < 20) return null;
  const x = a.slice(-n), y = b.slice(-n);
  const mx = x.reduce((s, v) => s + v, 0) / n, my = y.reduce((s, v) => s + v, 0) / n;
  let sxy = 0, sx = 0, sy = 0;
  for (let i = 0; i < n; i++) { sxy += (x[i] - mx) * (y[i] - my); sx += (x[i] - mx) ** 2; sy += (y[i] - my) ** 2; }
  return sx && sy ? sxy / Math.sqrt(sx * sy) : null;
}
const rets = (c: any[] | null) => (c ?? []).map((k, i, a) => (i ? Math.log(k[4] / a[i - 1][4]) : 0)).slice(1);
const week = (c: any[] | null) => (c && c.length > 1 ? (c[c.length - 1][4] / c[0][4] - 1) * 100 : null);

function Universe({ peers, status, mc, onSel, tf }: { peers: string[]; status: any; mc: any; onSel: (s: string) => void; tf: string }) {
  // v2.46 redesign: a solar system - BTC as the gold sun, the five biggest coins as planets on their own orbits; the
  // closer a planet orbits, the more it moved with Bitcoin (7-day hourly correlation); a light beam flows along each
  // link; planet size = 7-day move size, colour = up / down.
  const btc = useKlines("BTC/USDT", "1h", 168, 900_000);
  const k = [useKlines(peers[0] ?? "ETH/USDT", "1h", 168, 900_000), useKlines(peers[1] ?? "SOL/USDT", "1h", 168, 900_000), useKlines(peers[2] ?? "BNB/USDT", "1h", 168, 900_000),
    useKlines(peers[3] ?? "XRP/USDT", "1h", 168, 900_000), useKlines(peers[4] ?? "DOGE/USDT", "1h", 168, 900_000)];
  const rb = rets(btc.data);
  const nodes = peers.slice(0, 5).map((s, i) => ({ s, c: corr(rb, rets(k[i].data)), w: week(k[i].data) }));
  const alt = mc?.altseason?.value;
  const bw = week(btc.data);
  const W = 360, H = 270, C = { x: 180, y: 132 };
  const maxW = Math.max(1, ...nodes.map((n) => Math.abs(n.w ?? 0)));
  return (
    <div className="space-y-3">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="group" aria-label="Bitcoin and the five biggest coins: a closer orbit means the coin moved more with Bitcoin over 7 days">
        <defs>
          <radialGradient id="un-sun"><stop offset="0%" stopColor="rgb(var(--accent) / 0.55)" /><stop offset="55%" stopColor="rgb(var(--accent) / 0.12)" /><stop offset="100%" stopColor="rgb(var(--accent) / 0)" /></radialGradient>
        </defs>
        <circle cx={C.x} cy={C.y} r="78" fill="url(#un-sun)" />
        {[58, 86, 114].map((r, i) => <ellipse key={r} cx={C.x} cy={C.y} rx={r * 1.35} ry={r * 0.82} fill="none" stroke={`rgb(var(--accent) / ${0.3 - i * 0.07})`} strokeDasharray="2 6" />)}
        {nodes.map((n, i) => {
          const c = isNum(n.c) ? Math.max(0, Math.min(1, n.c)) : 0.3;
          const r = 114 - c * 56;                          // stronger link = inner orbit
          const a = (i * 72 - 100) * (Math.PI / 180);
          const x = C.x + r * 1.35 * Math.cos(a), y = C.y + r * 0.82 * Math.sin(a);
          const size = 11 + 8 * (Math.abs(n.w ?? 0) / maxW);
          const up = (n.w ?? 0) >= 0;
          return (
            <g key={n.s} className="cc-planet" tabIndex={0} role="button" onClick={() => onSel(n.s)} onKeyDown={(e) => { if (e.key === "Enter") onSel(n.s); }}
              aria-label={`${name(n.s)}: ${pct(n.w)} in 7 days, moves with Bitcoin ${isNum(n.c) ? Math.round(n.c * 100) + "%" : "unknown"}`}>
              <line x1={C.x} y1={C.y} x2={x} y2={y} stroke="rgb(var(--accent) / 0.25)" strokeWidth="1" />
              <line x1={C.x} y1={C.y} x2={x} y2={y} stroke="rgb(var(--accent) / 0.85)" strokeWidth={1 + c * 2.5} strokeDasharray="3 14" className="un-flow" />
              <circle cx={x} cy={y} r={size + 5} fill={up ? "rgb(var(--bull) / 0.12)" : "rgb(var(--bear) / 0.12)"} />
              <circle cx={x} cy={y} r={size} fill={up ? "url(#cc-up)" : "url(#cc-dn)"} />
              <text x={x} y={y + size + 15} textAnchor="middle" fontSize="12" fontWeight="700" fill="rgb(var(--text))">{name(n.s)}</text>
              <text x={x} y={y + size + 29} textAnchor="middle" fontSize="12" fill={up ? UP : DN}>{pct(n.w)}{isNum(n.c) ? ` · ${Math.round(n.c * 100)}%` : ""}</text>
            </g>
          );
        })}
        <circle cx={C.x} cy={C.y} r="28" fill="url(#cc-gold)" />
        <text x={C.x} y={C.y + 1} textAnchor="middle" fontSize="13" fontWeight="800" fill="#1a1408">BTC</text>
        <text x={C.x} y={C.y + 15} textAnchor="middle" fontSize="11" fontWeight="700" fill="#3a2a05">{pct(bw)}</text>
      </svg>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div className="cc-cell"><div className="text-mute">Breadth · {tf.toUpperCase()}</div><div className="text-sm font-semibold"><span className="text-bull">{status?.bull ?? "—"} ▲</span> <span className="text-bear">{status?.bear ?? "—"} ▼</span></div></div>
        <div className="cc-cell"><div className="text-mute">Alt strength</div><div className="text-sm font-semibold">{isNum(alt) ? `${Math.round(alt)} / 100` : "—"}</div></div>
        <div className="cc-cell"><div className="text-mute">BTC · 7 days</div><div className={`text-sm font-semibold ${(bw ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{pct(bw)}</div></div>
      </div>
      <p className="text-xs text-mute">Closer orbit and thicker beam = moved more with Bitcoin (%, hourly, 7 days). Planet size = 7-day move.</p>
    </div>
  );
}

/* ---------------------------------------------------------------- mission control */
function Mission({ health, connected }: { health: any; connected: boolean }) {
  const e = health?.engine ?? {};
  const last = e.last_tick_finished;
  const age = isNum(last) ? (Date.now() - last) / 60_000 : null;
  const models: any[] = health?.models ?? [];
  const active = models.filter((m) => m.version).length;
  const newest = Math.max(0, ...models.map((m) => m.trained_at ?? 0));
  const writes = e.firestore_writes_today, budget = isNum(e.firestore_free_limit) ? e.firestore_free_limit : 20000;
  const errs = health?.recent_errors_count ?? 0;
  const ok = "rgb(var(--bull))", warn = "rgb(var(--warn))", bad = "rgb(var(--bear))";
  const rows: [string, string, string, string][] = [
    ["Live prices", connected ? "Streaming from Binance" : "Reconnecting…", connected ? "Live" : "Waiting", connected ? ok : warn],
    ["Signal engine", isNum(last) ? `Last cycle ${ago(last)} · every 5 min` : "No cycle seen yet", age == null ? "Unknown" : age < 15 ? "Running" : age < 75 ? "Late" : "Stopped", age == null ? warn : age < 15 ? ok : age < 75 ? warn : bad],
    ["AI models", `${active} active${newest ? ` · newest ${ago(newest)}` : ""}`, active ? "Ready" : "Training", active ? ok : warn],
    ["Market data", health?.market_data?.status ? `Feed ${String(health.market_data.status).toLowerCase()}${isNum(health.market_data.quality_pct) ? ` · ${health.market_data.quality_pct}% complete` : ""}` : "—", health?.status ?? "—", health?.status === "LIVE" ? ok : health?.status === "DOWN" ? bad : warn],
    ["Free-plan budget", isNum(writes) ? `${writes.toLocaleString()} of ${Number(budget).toLocaleString()} writes today` : "—", isNum(writes) ? `${Math.round((writes / budget) * 100)}%` : "—", isNum(writes) && writes / budget > 0.9 ? warn : ok],
    ["Errors · recent", errs ? `${errs} logged by the engine` : "None logged", String(errs), errs ? warn : ok],
  ];
  return (
    <ul className="space-y-2">
      {rows.map(([k, sub, st, c]) => (
        <li key={k} className="cc-row">
          <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: c, boxShadow: `0 0 0 4px color-mix(in srgb, ${c} 18%, transparent)` }} />
          <div className="min-w-0 flex-1"><div className="text-sm font-semibold">{k}</div><div className="truncate text-xs text-mute">{sub}</div></div>
          <span className="text-xs font-semibold" style={{ color: c }}>{st}</span>
        </li>
      ))}
    </ul>
  );
}

/* ---------------------------------------------------------------- deep-space scan */
function Scan({ symbol, row, f4, tf }: { symbol: string; row: any; f4: any; tf: string }) {
  const T = tf.toUpperCase();
  const tk = useTicker(symbol);
  const an = useApi<any>(`/analysis/${slug(symbol)}?timeframe=${tf}`);
  const a = an.data?.status === "OK" ? an.data : null;
  const px = tk?.last ?? a?.price ?? row?.price;
  const sup = (a?.levels?.zones?.support ?? []).map((z: any) => z.mid).filter((p: number) => isNum(p) && isNum(px) && p < px).sort((x: number, y: number) => y - x)[0];
  const res = (a?.levels?.zones?.resistance ?? []).map((z: any) => z.mid).filter((p: number) => isNum(p) && isNum(px) && p > px).sort((x: number, y: number) => x - y)[0];
  const pos = isNum(sup) && isNum(res) && isNum(px) ? Math.max(0, Math.min(1, (px - sup) / (res - sup))) : null;
  const side = callOf(f4);
  const chg = tk?.change_pct ?? row?.change_24h_pct;
  const inds: [string, string, string?][] = [
    [`Trend ${T}`, row?.trend_label ?? "—", row?.trend_label === "Up" ? "text-bull" : row?.trend_label === "Down" ? "text-bear" : ""],
    ["RSI 14", isNum(row?.rsi) ? row.rsi.toFixed(0) : "—"],
    ["ADX (trend strength)", isNum(row?.adx) ? row.adx.toFixed(0) : "—"],
    ["Volatility", row?.volatility ? String(row.volatility).toLowerCase() : "—"],
    ["Volume 24h", isNum(tk?.quote_volume ?? row?.quote_volume_24h) ? `${fmtCompact(tk?.quote_volume ?? row?.quote_volume_24h)} USDT` : "—"],
    ["Liquidity", isNum(tk?.spread_bps) ? `spread ${tk!.spread_bps!.toFixed(1)} bps` : "—"],
    ["Signal score", isNum(row?.score) ? `${Math.round(row.score)} / 100` : "—"],
    ["News", f4?.news_risk?.title ? `${f4.news_risk.title}` : "No major release near", f4?.news_risk ? "text-warn" : ""],
  ];
  return (
    <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)_320px] lg:items-start">
      <div className="flex flex-col items-center gap-2 text-center">
        <svg viewBox="0 0 170 150" width="170" height="150" aria-hidden="true">
          <ellipse cx="85" cy="75" rx="80" ry="20" fill="none" stroke="rgb(var(--accent) / 0.45)" strokeWidth="1.5" transform="rotate(-16 85 75)" />
          <circle cx="85" cy="75" r="46" fill={symbol.startsWith("PAXG") ? "url(#cc-gold)" : (chg ?? 0) >= 0 ? "url(#cc-up)" : "url(#cc-dn)"} />
          <path d="M5 75 A80 20 0 0 0 165 75" fill="none" stroke="#f0b90b" strokeWidth="2" transform="rotate(-16 85 75)" />
        </svg>
        <div className="flex items-center gap-2"><CoinAvatar symbol={symbol} size={24} /><span className="font-display text-2xl font-bold">{name(symbol)}</span></div>
        <div className="num text-xl font-semibold">{fmtPrice(px)} <span className={`text-sm ${(chg ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{pct(chg)}</span></div>
      </div>
      <div className="min-w-0 space-y-4">
        <h2 className="font-display text-lg font-semibold">Deep-space scan · {T}</h2>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {inds.map(([k, v, c]) => <div key={k} className="cc-cell"><div className="text-xs text-mute">{k}</div><div className={`truncate font-semibold ${c ?? ""}`}>{v}</div></div>)}
        </div>
        {pos != null && (
          <div>
            <div className="text-xs text-mute">Market structure · nearest support to resistance</div>
            <div className="cc-structure mt-2"><span style={{ left: `${pos * 100}%` }} /></div>
            <div className="num mt-1.5 flex justify-between text-xs"><span className="text-bull">Support {fmtPrice(sup)}</span><span className="text-accent">Price {fmtPrice(px)}</span><span className="text-bear">Resistance {fmtPrice(res)}</span></div>
          </div>
        )}
      </div>
      <div className="cc-cell space-y-3 p-4">
        <div className="flex items-center justify-between"><span className="text-xs text-mute">Signal · {T}</span>
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold ${side > 0 ? "bg-bull text-ink" : side < 0 ? "bg-bear text-white" : "bg-glass/15 text-text"}`}>{side > 0 ? "▲ LONG" : side < 0 ? "▼ SHORT" : "WAIT"}{side && f4?.grade ? ` · ${f4.grade}` : ""}</span></div>
        <p className="text-sm leading-relaxed">{a?.ai?.rationale || (side ? f4?.decision_basis : f4?.decision_reason ? `No trade: ${f4.decision_reason}.` : null) || "The engine has no note for this coin yet."}</p>
        <Link to={`/asset/${slug(symbol)}?tf=${tf}`} className="btn btn-primary w-full">Open full analysis</Link>
      </div>
    </div>
  );
}

export default function Command() {
  // v2.47 (owner): every timeframe - the galaxy, AI core, breadth and the scan follow the chosen one (remembered)
  const [tf, setTfRaw] = useState<string>(() => { try { const t = localStorage.getItem("cia-cc-tf"); return t && (TFS as readonly string[]).includes(t) ? t : "4h"; } catch { return "4h"; } });
  const setTf = (t: string) => { setTfRaw(t); try { localStorage.setItem("cia-cc-tf", t); } catch { /* ignore */ } };
  const dash = useApi<any>(`/dashboard?timeframe=${tf}`, 60000);
  const boards = TFS.map((t) => useApi<any>(`/futures?timeframe=${t}`)); // fixed list: stable hooks
  const track = useApi<any>("/track-record");
  const mc = useApi<any>("/market-context");
  const ctx = useApi<any>("/context", 600000);
  const health = useApi<any>("/system/health");
  const news = useApi<any>("/news", 300_000);
  const { connected } = useLive();
  const rows: any[] = (dash.data?.rows ?? []).filter((r: any) => r.status === "OK");
  const open = useMemo(() => new Set<string>((track.data?.live?.signals ?? []).filter((x: any) => x.status === "OPEN" && x.timeframe === tf).map((x: any) => x.symbol)), [track.data, tf]);
  const [sel, setSel] = useState<string | null>(null);
  const pick = (s: string) => { setSel(s); window.setTimeout(() => document.getElementById("cc-scan")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50); };
  const focus = sel ?? [...open][0] ?? rows[0]?.symbol ?? "BTC/USDT";
  const row = rows.find((r) => r.symbol === focus);
  const f4 = (boards[TFS.indexOf(tf as any)]?.data?.rows ?? []).find((r: any) => r.symbol === focus);
  const peers = rows.map((r) => r.symbol).filter((s) => s !== "BTC/USDT" && base(s) !== "PAXG")
    .sort((a, b) => (rows.find((r) => r.symbol === b)?.quote_volume_24h ?? 0) - (rows.find((r) => r.symbol === a)?.quote_volume_24h ?? 0)).slice(0, 5);
  if (dash.loading && !dash.data && !rows.length) return <Loading />;
  if (dash.error) return <ErrorBox error={dash.error} retry={dash.reload} />;
  return (
    <div className="cc-page space-y-4">
      <Defs />
      <PageHeader title="Command Centre" />
      <div className="cc-tfbar">
        <span className="text-xs text-mute">Timeframe</span>
        <Segmented value={tf} onChange={setTf} options={TFS.map((t) => [t, t.toUpperCase()] as [string, string])} label="Timeframe" />
        <span className="hidden text-xs text-mute sm:inline">Galaxy, AI core, breadth and the scan follow it. The radar always shows every timeframe.</span>
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <section className="cc-panel p-4 sm:p-5" aria-label="Crypto galaxy">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div><h2 className="font-display text-xl font-semibold">Crypto galaxy</h2><p className="text-sm text-mute">Your coins around the AI core. Tap a planet to scan it.</p></div>
            <div className="flex flex-wrap gap-3 text-xs text-mute"><span className="text-bull">● up 24h</span><span className="text-bear">● down 24h</span><span className="text-accent">◌ {tf.toUpperCase()} signal running</span><span>size = 24h volume</span></div>
          </div>
          <Galaxy rows={rows} open={open} sel={focus} onSel={pick} />
        </section>
        <section className="cc-panel p-4 sm:p-5" aria-label="AI intelligence core">
          <Core row={row} f4={f4} status={dash.data?.market_status} ctx={ctx.data} health={health.data} tf={tf} />
        </section>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <section className="cc-panel p-4" aria-label="Opportunity radar">
          <div className="flex items-baseline justify-between"><h2 className="font-display text-lg font-semibold">Opportunity radar</h2><span className="text-xs text-mute">closer = stronger</span></div>
          <Radar boards={boards.map((b) => b.data?.rows ?? [])} onSel={pick} tf={tf} />
          <div className="mt-1 flex flex-wrap justify-center gap-3 text-xs text-mute"><span className="text-bull">● long</span><span className="text-bear">● short</span><span className="text-accent">◎ grade A</span><span>lit slice = live calls</span></div>
        </section>
        <section className="cc-panel p-4" aria-label="Market universe">
          <div className="flex items-baseline justify-between"><h2 className="font-display text-lg font-semibold">Market universe</h2><span className="text-xs text-mute">7 days</span></div>
          <Universe peers={peers} status={dash.data?.market_status} mc={mc.data} onSel={pick} tf={tf} />
        </section>
        <section className="cc-panel p-4" aria-label="Mission control">
          <div className="flex items-baseline justify-between"><h2 className="font-display text-lg font-semibold">Mission control</h2><span className="text-xs text-mute">real system status</span></div>
          <div className="mt-3"><Mission health={health.data} connected={connected} /></div>
        </section>
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <section className="cc-panel p-4 sm:p-5" aria-label="Live signal journeys">
          <div className="flex items-baseline justify-between"><h2 className="font-display text-lg font-semibold">Live signal journeys</h2><span className="text-xs text-mute">stop → entry → targets</span></div>
          <div className="mt-3"><SignalJourneys track={track.data} /></div>
        </section>
        <section className="cc-panel flex flex-col p-4 sm:p-5" aria-label="Market heat globe">
          <div className="flex items-baseline justify-between"><h2 className="font-display text-lg font-semibold">Market heat</h2><span className="text-xs text-mute">sessions · volume · next release</span></div>
          <div className="mt-3 flex flex-1 flex-col justify-center"><HeatGlobe news={news.data} /></div>
        </section>
      </div>
      <section className="cc-panel p-4 sm:p-5" aria-label="Coin versus coin">
        <div className="flex items-baseline justify-between"><h2 className="font-display text-lg font-semibold">Coin vs coin</h2><span className="text-xs text-mute">pick up to 3</span></div>
        <div className="mt-3"><LazyMount height={320}><CoinCompare rows={rows} /></LazyMount></div>
      </section>
      <section id="cc-scan" className="cc-panel cc-scan scroll-mt-20 p-4 sm:p-6" aria-label={`Deep-space scan of ${name(focus)}`}>
        <Scan symbol={focus} row={row} f4={f4} tf={tf} />
      </section>
    </div>
  );
}
