// v2.45 Command Centre (owner, 16 Nov 2026: the approved "Command Centre concept", gold-black theme). An extra page:
// nothing else changes. Real data only, from documents the app already reads:
//   views/dashboard_4h (coins, regime, AI lean, RSI / ADX, 24h change + volume), the six views/futures_<tf> boards (the
//   Signals page's calls), views/track_record (open calls), views/market_context + context (alt strength, Fear & Greed),
//   views/health (mission control; already open in the header), the coin's analysis view for the scan (1 read per coin
//   picked). Correlations from public Binance 1h candles in the browser (no Firebase).
import { lazy, ReactNode, Suspense, useEffect, useId, useMemo, useState } from "react";
import { BeadDefs, CoinBead } from "../components/Instruments";
import { Link } from "react-router-dom";
import { Segmented } from "../components/kit";
import { CoinAvatar } from "../components/Polish";
import { ErrorBox, Loading } from "../components/ui";
import { useApi } from "../lib/api";
import { useKlines } from "../lib/klines";
import LazyMount from "../components/LazyMount";
import { CoinCompare, SignalJourneys } from "../components/CommandPlus";
const MarketGlobe = lazy(() => import("../components/MarketGlobe"));
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

function Galaxy({ rows, open, sel, onSel, onScan, tf }: { rows: any[]; open: Set<string>; sel: string; onSel: (s: string) => void; onScan: () => void; tf: string }) {
  const { tickers } = useLive();
  const narrow = useNarrow();                    // phones: a tighter drawing so labels stay readable
  // v2.55 (owner): the galaxy has the whole first row on computers, so the orbits are stretched wide (KX)
  const W = narrow ? 400 : 1100, H = narrow ? 430 : 600, KX = narrow ? 1 : 1.75, KY = narrow ? 0.92 : 0.95;
  const C = { x: W / 2, y: H / 2 };
  const ranked = [...rows].sort((a, b) => (b.quote_volume_24h ?? 0) - (a.quote_volume_24h ?? 0));
  const maxV = Math.max(1, ...ranked.map((r) => r.quote_volume_24h ?? 0));
  const tiers = [ranked.slice(0, 2), ranked.slice(2, 6), ranked.slice(6)];
  const RAD = narrow ? [76, 122, 170] : [130, 200, 268];
  const planets = tiers.flatMap((t, ti) => t.map((r, i) => {
    const a = ((i / Math.max(1, t.length)) * 360 + ti * 37 - 90) * (Math.PI / 180);
    const chg = tickers[r.symbol]?.change_pct ?? r.change_24h_pct;
    const size = (narrow ? 7 : 9) + (narrow ? 9 : 15) * Math.sqrt((r.quote_volume_24h ?? 0) / maxV);
    const sig = String(r.signal ?? "");
    const dir = /BUY|LONG/.test(sig) ? 1 : /SELL|SHORT/.test(sig) ? -1 : 0;
    return { r, a, x: C.x + RAD[ti] * KX * Math.cos(a), y: C.y + RAD[ti] * Math.sin(a) * KY, size, chg, sig: open.has(r.symbol), dir };
  }));
  // v2.56 signal constellations: coins with a call in the same direction joined by a faint line (in orbit order)
  const chain = (d: 1 | -1) => planets.filter((p) => p.dir === d).sort((p, q) => p.a - q.a);
  const line = (ps: typeof planets) => ps.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
  const longs = chain(1), shorts = chain(-1);
  const [hover, setHover] = useState<string | null>(null);
  const shown = planets.find((p) => p.r.symbol === (hover ?? sel));
  return (
    <div className="cc-galaxy">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="group" aria-label="Crypto galaxy: every coin you watch as a planet">
        <ellipse cx={C.x} cy={C.y} rx={narrow ? 80 : 190} ry={narrow ? 80 : 130} fill="url(#cc-glow)" />
        {RAD.map((r, i) => (
          <g key={r}>
            <ellipse cx={C.x} cy={C.y} rx={r * KX} ry={r * KY} fill="none" stroke="rgb(var(--accent) / 0.2)" strokeDasharray="2 6" />
            {/* a light travelling along each orbit (stroke offset only: cheap) */}
            <ellipse cx={C.x} cy={C.y} rx={r * KX} ry={r * KY} fill="none" stroke="rgb(var(--accent-2) / 0.7)" strokeWidth={1.6} strokeLinecap="round"
              pathLength={1000} strokeDasharray="6 994" className="cc-trail" style={{ animationDuration: `${18 + i * 9}s` }} />
          </g>
        ))}
        {longs.length > 1 && <path d={line(longs)} fill="none" stroke="rgb(var(--bull) / 0.35)" strokeWidth={1} strokeDasharray="1 5" strokeLinecap="round" />}
        {shorts.length > 1 && <path d={line(shorts)} fill="none" stroke="rgb(var(--bear) / 0.4)" strokeWidth={1} strokeDasharray="1 5" strokeLinecap="round" />}
        <LogoPlanet x={C.x} y={C.y} r={narrow ? 30 : 48} />
        {planets.map((p) => {
          const on = p.r.symbol === sel;
          return (
            <g key={p.r.symbol} className="cc-planet" tabIndex={0} role="button" aria-label={`${name(p.r.symbol)} ${pct(p.chg)} in 24 hours${p.sig ? ", signal running" : ""}`}
              onMouseEnter={() => setHover(p.r.symbol)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(p.r.symbol)} onBlur={() => setHover(null)}
              onClick={() => onSel(p.r.symbol)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSel(p.r.symbol); } }}>
              {on && <circle cx={p.x} cy={p.y} r={p.size + 13} fill="none" stroke="#fff1c4" strokeWidth="1.5" className="cc-lock" />}
              {p.sig && <circle cx={p.x} cy={p.y} r={p.size + 7} fill="none" stroke={GOLD} strokeWidth="2" strokeDasharray="4 3" />}
              <circle cx={p.x} cy={p.y} r={p.size} fill={name(p.r.symbol) === "GOLD" || p.r.symbol.startsWith("PAXG") ? "url(#cc-gold)" : (p.chg ?? 0) >= 0 ? "url(#cc-up)" : "url(#cc-dn)"} />
              <text x={p.x} y={p.y + p.size + 15} textAnchor="middle" fontSize="13" fontWeight="600" fill="rgb(var(--text))">{name(p.r.symbol)}</text>
              <text x={p.x} y={p.y + p.size + 29} textAnchor="middle" fontSize="12" fill={(p.chg ?? 0) >= 0 ? UP : DN}>{pct(p.chg)}</text>
            </g>
          );
        })}
      </svg>
      {/* hologram readout of the planet under the pointer (or the one locked on) */}
      {shown && (
        <div className="cc-holo" aria-live="polite">
          <div className="flex items-center gap-2"><CoinAvatar symbol={shown.r.symbol} size={22} /><b className="font-display text-base">{name(shown.r.symbol)}</b>
            <span className={`ml-auto text-xs font-semibold ${shown.dir > 0 ? "text-bull" : shown.dir < 0 ? "text-bear" : "text-mute"}`}>{shown.dir > 0 ? "▲ Long call" : shown.dir < 0 ? "▼ Short call" : "No call"} · {tf.toUpperCase()}</span></div>
          <div className="num mt-1.5 text-xl font-semibold">{fmtPrice(tickers[shown.r.symbol]?.last ?? shown.r.price)} <span className={`text-sm ${(shown.chg ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{pct(shown.chg)}</span></div>
          <div className="mt-1.5 grid grid-cols-3 gap-2 text-xs">
            <span><span className="block text-mute">Trend</span>{shown.r.trend_label ?? "—"}</span>
            <span><span className="block text-mute">RSI</span><span className="num">{isNum(shown.r.rsi) ? shown.r.rsi.toFixed(0) : "—"}</span></span>
            <span><span className="block text-mute">Volume</span><span className="num">{isNum(shown.r.quote_volume_24h) ? fmtCompact(shown.r.quote_volume_24h) : "—"}</span></span>
          </div>
          <button type="button" className="btn btn-sm mt-2.5 w-full" onClick={() => { onSel(shown.r.symbol); onScan(); }}>Deep-space scan ↓</button>
        </div>
      )}
    </div>
  );
}

/** v2.58 (owner, 18 Nov 2026): the galaxy's centre is the brand itself - the round logo artwork as a planet: lit from
 *  the upper left, a gold atmosphere, a tilted ring that passes behind and in front of it, a small moon on the ring. */
function LogoPlanet({ x, y, r }: { x: number; y: number; r: number }) {
  const rx = r * 1.85, ry = r * 0.42, tilt = -16;
  const ring = (front: boolean) => (
    <path d={`M${x - rx} ${y} A${rx} ${ry} 0 0 ${front ? 0 : 1} ${x + rx} ${y}`} fill="none"
      stroke={front ? "url(#lp-ring)" : "rgb(var(--accent) / 0.35)"} strokeWidth={front ? 3 : 2} transform={`rotate(${tilt} ${x} ${y})`} />
  );
  return (
    <g aria-label="Crypto Intelligence AI" role="img">
      <defs>
        <clipPath id="lp-clip"><circle cx={x} cy={y} r={r} /></clipPath>
        <radialGradient id="lp-shade" cx="32%" cy="28%" r="80%">
          <stop offset="0%" stopColor="#fff6dc" stopOpacity="0.28" />
          <stop offset="38%" stopColor="#000" stopOpacity="0" />
          <stop offset="100%" stopColor="#000" stopOpacity="0.62" />
        </radialGradient>
        <radialGradient id="lp-atmo"><stop offset="70%" stopColor="rgb(var(--accent) / 0)" /><stop offset="82%" stopColor="rgb(var(--accent) / 0.45)" /><stop offset="100%" stopColor="rgb(var(--accent) / 0)" /></radialGradient>
        <linearGradient id="lp-ring" x1="0" x2="1"><stop offset="0%" stopColor="rgb(var(--accent) / 0.2)" /><stop offset="50%" stopColor="rgb(var(--accent-2))" /><stop offset="100%" stopColor="rgb(var(--accent) / 0.2)" /></linearGradient>
      </defs>
      <circle cx={x} cy={y} r={r * 1.3} fill="url(#lp-atmo)" className="lp-atmo" />
      {ring(false)}
      <circle cx={x} cy={y} r={r} fill="#0b0b0d" />
      <image href="/brand/logo-art-384.webp" x={x - r} y={y - r} width={r * 2} height={r * 2} clipPath="url(#lp-clip)" preserveAspectRatio="xMidYMid slice" />
      <circle cx={x} cy={y} r={r} fill="url(#lp-shade)" />
      <circle cx={x} cy={y} r={r} fill="none" stroke="rgb(var(--accent-2) / 0.7)" strokeWidth={1.2} />
      {ring(true)}
      {/* a small moon travelling along the ring (left out for people who reduce motion) */}
      {!(typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) && (
        <g transform={`rotate(${tilt} ${x} ${y})`}>
          <circle r={Math.max(2.5, r * 0.07)} fill="rgb(var(--ai))">
            <animateMotion dur="24s" repeatCount="indefinite" path={`M${x + rx} ${y} A${rx} ${ry} 0 1 1 ${x - rx} ${y} A${rx} ${ry} 0 1 1 ${x + rx} ${y}`} />
          </circle>
        </g>
      )}
    </g>
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
  // v2.66 (owner, 21 Nov 2026: "make it premium"): a tilted solar system. BTC = the sun (its own logo in a gold corona);
  // the five biggest coins as logo planets: the closer the orbit, the more it moved with Bitcoin over 7 days (hourly
  // correlation); planet size = size of the 7-day move; glow + label colour = up / down. Same data as v2.46.
  const id = useId().replace(/:/g, "");
  const btc = useKlines("BTC/USDT", "1h", 168, 900_000);
  const k = [useKlines(peers[0] ?? "ETH/USDT", "1h", 168, 900_000), useKlines(peers[1] ?? "SOL/USDT", "1h", 168, 900_000), useKlines(peers[2] ?? "BNB/USDT", "1h", 168, 900_000),
    useKlines(peers[3] ?? "XRP/USDT", "1h", 168, 900_000), useKlines(peers[4] ?? "DOGE/USDT", "1h", 168, 900_000)];
  const rb = rets(btc.data);
  const nodes = peers.slice(0, 5).map((s, i) => ({ s, c: corr(rb, rets(k[i].data)), w: week(k[i].data) }));
  const alt = mc?.altseason?.value;
  const bw = week(btc.data);
  const W = 520, H = 330, C = { x: 260, y: 150 }, TX = 1.75, TY = 0.42;
  const ORB = [62, 98, 134];
  const stars = useMemo(() => { let x = 7; const r = () => ((x = (x * 9301 + 49297) % 233280) / 233280); return Array.from({ length: 70 }, () => ({ x: r() * W, y: r() * H, s: 0.3 + r() * 1.1, d: r() * 4 })); }, []);
  const maxW = Math.max(1, ...nodes.map((n) => Math.abs(n.w ?? 0)));
  // fixed slots around the ellipse (degrees; 90 = front): back-left, back-right, front-left, front-right, front
  const SLOTS = [222, 318, 138, 42, 90];
  const placed = nodes.map((n, i) => {
    const c = isNum(n.c) ? Math.max(0, Math.min(1, n.c)) : 0.3;
    const orb = ORB[2] - c * (ORB[2] - ORB[0]);
    const a = (SLOTS[i] * Math.PI) / 180;
    const x = C.x + orb * TX * Math.cos(a), y = C.y + orb * TY * Math.sin(a) * 2.1;
    const depth = (Math.sin(a) + 1) / 2;                       // 0 back … 1 front
    const r = (12 + 7 * (Math.abs(n.w ?? 0) / maxW)) * (0.82 + 0.3 * depth);
    return { ...n, c, orb, x, y, r, depth, up: (n.w ?? 0) >= 0 };
  }).sort((a, b) => a.depth - b.depth);
  const ring = (r: number, half: "back" | "front") => {
    const rx = r * TX, ry = r * TY * 2.1;
    return half === "back" ? `M${C.x - rx} ${C.y} A${rx} ${ry} 0 0 1 ${C.x + rx} ${C.y}` : `M${C.x - rx} ${C.y} A${rx} ${ry} 0 0 0 ${C.x + rx} ${C.y}`;
  };
  return (
    <div className="flex flex-1 flex-col gap-3">
      <div className="uv-stage flex flex-1 items-center"><svg viewBox={`0 0 ${W} ${H}`} className="mx-auto w-full max-w-[560px]" role="group" aria-label="Bitcoin and the five biggest coins: a closer orbit means the coin moved more with Bitcoin over 7 days">
        <BeadDefs id={id} />
        <defs>
          <radialGradient id={`${id}-neb1`} cx="30%" cy="35%" r="60%"><stop offset="0%" stopColor="rgb(var(--ai) / 0.16)" /><stop offset="100%" stopColor="rgb(var(--ai) / 0)" /></radialGradient>
          <radialGradient id={`${id}-neb2`} cx="78%" cy="70%" r="55%"><stop offset="0%" stopColor="rgb(var(--accent) / 0.12)" /><stop offset="100%" stopColor="rgb(var(--accent) / 0)" /></radialGradient>
          <radialGradient id={`${id}-corona`}><stop offset="0%" stopColor="#fff1c4" stopOpacity="0.75" /><stop offset="22%" stopColor="#f0b90b" stopOpacity="0.45" /><stop offset="55%" stopColor="#f0b90b" stopOpacity="0.1" /><stop offset="100%" stopColor="#f0b90b" stopOpacity="0" /></radialGradient>
          <radialGradient id={`${id}-fade`} cx="50%" cy="48%" r="58%"><stop offset="55%" stopColor="#fff" /><stop offset="100%" stopColor="#000" /></radialGradient>
          <mask id={`${id}-mask`}><rect width={W} height={H} fill={`url(#${id}-fade)`} /></mask>
          <linearGradient id={`${id}-orb`} x1="0" x2="1"><stop offset="0%" stopColor="rgb(var(--accent) / 0.05)" /><stop offset="50%" stopColor="rgb(var(--accent) / 0.55)" /><stop offset="100%" stopColor="rgb(var(--accent) / 0.05)" /></linearGradient>
        </defs>
        <g mask={`url(#${id}-mask)`}>
          <rect width={W} height={H} fill={`url(#${id}-neb1)`} /><rect width={W} height={H} fill={`url(#${id}-neb2)`} />
          {stars.map((t, i) => <circle key={i} cx={t.x} cy={t.y} r={t.s} fill="#fff" opacity={0.5} className={i % 4 ? undefined : "cosmos-twinkle"} style={i % 4 ? undefined : { animationDelay: `${t.d}s` }} />)}
        </g>
        {/* back halves of the orbits, behind the sun */}
        {ORB.map((r) => <path key={`b${r}`} d={ring(r, "back")} fill="none" stroke="rgb(var(--accent) / 0.16)" strokeDasharray="1 5" />)}
        {/* the sun: corona, rotating rays, BTC */}
        <circle cx={C.x} cy={C.y} r={86} fill={`url(#${id}-corona)`} className="uv-float" style={{ transformOrigin: `${C.x}px ${C.y}px` }} />
        <g className="uv-spin" style={{ transformOrigin: `${C.x}px ${C.y}px` }}>
          <circle cx={C.x} cy={C.y} r={40} fill="none" stroke="#f0b90b" strokeOpacity={0.35} strokeWidth={7} strokeDasharray="1.2 6.5" />
        </g>
        <circle cx={C.x} cy={C.y} r={31} fill="url(#cc-gold)" />
        <CoinBead id={id} symbol="BTC/USDT" x={C.x} y={C.y} r={24} tone="#f0b90b" ring={1.2} />
        {/* front halves */}
        {ORB.map((r) => <path key={`f${r}`} d={ring(r, "front")} fill="none" stroke={`url(#${id}-orb)`} strokeWidth={1} />)}
        {/* beams + planets, back to front */}
        {placed.map((n) => (
          <g key={n.s} className="cc-planet" tabIndex={0} role="button" onClick={() => onSel(n.s)} onKeyDown={(e) => { if (e.key === "Enter") onSel(n.s); }}
            aria-label={`${name(n.s)}: ${pct(n.w)} in 7 days, moves with Bitcoin ${isNum(n.c) ? Math.round(n.c * 100) + "%" : "unknown"}`}>
            <line x1={C.x} y1={C.y} x2={n.x} y2={n.y} stroke={n.up ? "rgb(var(--bull) / 0.18)" : "rgb(var(--bear) / 0.18)"} strokeWidth={1} />
            <line x1={C.x} y1={C.y} x2={n.x} y2={n.y} stroke="rgb(var(--accent) / 0.85)" strokeWidth={0.8 + n.c * 2.2} strokeDasharray="2 12" strokeLinecap="round" className="un-flow" />
            <g className="uv-float" style={{ animationDelay: `${n.depth * 2}s`, transformOrigin: `${n.x}px ${n.y}px` }}>
              <CoinBead id={id} symbol={n.s} x={n.x} y={n.y} r={n.r} tone={n.up ? UP : DN} ring={1.6} />
            </g>
          </g>
        ))}
        {/* labels on top of everything, beside the planet on the outer side (below for the front one) */}
        {placed.map((n) => {
          let side = n.x < C.x - 20 ? -1 : n.x > C.x + 20 ? 1 : 0;
          if (side && (n.x + side * (n.r + 50) < 46 || n.x + side * (n.r + 50) > W - 46)) side = 0;   // no room beside: below
          const lx = side === 0 ? n.x : n.x + side * (n.r + 50), ly = side === 0 ? n.y + n.r + 9 : n.y - 15;
          return (
            <g key={`l${n.s}`} transform={`translate(${lx} ${ly})`} pointerEvents="none">
              <rect x={-44} y={0} width={88} height={30} rx={8} fill="rgb(var(--ink) / 0.92)" stroke={n.up ? "rgb(var(--bull) / 0.5)" : "rgb(var(--bear) / 0.5)"} strokeWidth={0.8} />
              <text x={0} y={12.5} textAnchor="middle" fontSize="10.5" fontWeight="700" fill="rgb(var(--text))">{name(n.s).length > 8 ? name(n.s).slice(0, 7) + "…" : name(n.s)} <tspan fill={n.up ? UP : DN}>{pct(n.w)}</tspan></text>
              <text x={0} y={24} textAnchor="middle" fontSize="8.5" fill="rgb(var(--text) / 0.7)">{isNum(n.c) ? `${Math.round(n.c * 100)}% with BTC` : "—"}</text>
            </g>
          );
        })}
        <g transform={`translate(${C.x} ${C.y - 58})`}>
          <rect x={-40} y={-11} width={80} height={20} rx={10} fill="rgb(var(--ink) / 0.8)" stroke="rgb(var(--accent) / 0.55)" strokeWidth={0.7} />
          <text x={0} y={3.5} textAnchor="middle" fontSize="10" fontWeight="700" fill="rgb(var(--accent))">BTC {pct(bw)}</text>
        </g>
      </svg></div>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div className="cc-cell"><div className="text-mute">Breadth · {tf.toUpperCase()}</div><div className="text-sm font-semibold"><span className="text-bull">{status?.bull ?? "—"} ▲</span> <span className="text-bear">{status?.bear ?? "—"} ▼</span></div></div>
        <div className="cc-cell"><div className="text-mute">Alt strength</div><div className="text-sm font-semibold">{isNum(alt) ? `${Math.round(alt)} / 100` : "—"}</div></div>
        <div className="cc-cell"><div className="text-mute">BTC · 7 days</div><div className={`text-sm font-semibold ${(bw ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{pct(bw)}</div></div>
      </div>
      <p className="text-xs text-mute">Closer orbit and brighter beam = moved more with Bitcoin (7 days). Bigger planet = bigger 7-day move.</p>
    </div>
  );
}

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
    <ul className="grid h-full auto-rows-fr gap-2 sm:grid-cols-2">
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

/* ---------------------------------------------------------------- mission strip (v2.56) */
/** The page's opening instrument: title, the readouts that matter right now, and the timeframe the instruments follow. */
function MissionStrip({ tf, setTf, status, open, health, connected }: { tf: string; setTf: (t: string) => void; status: any; open: any; health: any; connected: boolean }) {
  const btc = useTicker("BTC/USDT");
  const last = health?.engine?.last_tick_finished;
  const calls = ((open?.live?.signals ?? []) as any[]).filter((x) => x.status === "OPEN").length;
  const mood = status?.status;
  const read: [string, ReactNode, string?][] = [
    ["Market · " + tf.toUpperCase(), mood === "BULL" ? "Leaning bullish" : mood === "BEAR" ? "Leaning bearish" : mood ? "Mixed" : "—", mood === "BULL" ? "text-bull" : mood === "BEAR" ? "text-bear" : ""],
    ["Breadth", status ? <><span className="text-bull">{status.bull}▲</span> <span className="text-bear">{status.bear}▼</span> <span className="text-mute">/ {status.assets}</span></> : "—"],
    ["Bitcoin", <span className="num">{isNum(btc?.last) ? fmtPrice(btc!.last) : "—"} <span className={`text-sm ${(btc?.change_pct ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{pct(btc?.change_pct)}</span></span>],
    ["Live calls", <span className="num">{calls}</span>],
    ["Engine", <span className={isNum(last) && Date.now() - last < 15 * 60_000 ? "text-bull" : "text-warn"}>{isNum(last) ? ago(last) : "—"}</span>],
  ];
  return (
    <section className="cc-mission" aria-label="Mission status">
      <div className="min-w-0">
        <h1 className="page-title">Command Centre</h1>
        <p className="mt-1 flex items-center gap-2 text-sm text-mute"><span className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-bull live-dot" : "bg-warn"}`} />Live market intelligence · real data only</p>
      </div>
      <dl className="cc-readouts">
        {read.map(([k, v, c]) => <div key={k}><dt>{k}</dt><dd className={c ?? ""}>{v}</dd></div>)}
      </dl>
      <div className="cc-mission-tf">
        <Segmented value={tf} onChange={setTf} options={TFS.map((t) => [t, t.toUpperCase()] as [string, string])} label="Timeframe the galaxy, AI core and scan follow" />
      </div>
    </section>
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
  const scan = () => window.setTimeout(() => document.getElementById("cc-scan")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  const pick = (s: string) => { setSel(s); scan(); };
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
      <MissionStrip tf={tf} setTf={setTf} status={dash.data?.market_status} open={track.data} health={health.data} connected={connected} />
      {/* row 1 (owner, 18 Nov 2026): the galaxy on its own */}
      <section className="cc-panel p-4 sm:p-5" aria-label="Crypto galaxy">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div><h2 className="font-display text-xl font-semibold">Crypto galaxy</h2><p className="text-sm text-mute">Your coins around the AI core. Tap a planet to scan it.</p></div>
          <div className="flex flex-wrap gap-3 text-xs text-mute"><span className="text-bull">● up 24h</span><span className="text-bear">● down 24h</span><span className="text-accent">◌ {tf.toUpperCase()} signal running</span><span>size = 24h volume</span></div>
        </div>
        <Galaxy rows={rows} open={open} sel={focus} onSel={setSel} onScan={scan} tf={tf} />
      </section>
      {/* row 2: what the engine sees beside the system status, same height */}
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="cc-panel p-4 sm:p-5" aria-label="AI intelligence core">
          <Core row={row} f4={f4} status={dash.data?.market_status} ctx={ctx.data} health={health.data} tf={tf} />
        </section>
        <section className="cc-panel flex flex-col p-4 sm:p-5" aria-label="Mission control">
          <div className="flex items-baseline justify-between"><h2 className="font-display text-lg font-semibold">Mission control</h2><span className="text-xs text-mute">real system status</span></div>
          <div className="mt-3 flex-1"><Mission health={health.data} connected={connected} /></div>
        </section>
      </div>
      {/* row 3: radar beside the market universe; footers pinned so the bottoms line up */}
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="cc-panel flex flex-col p-4 sm:p-5" aria-label="Opportunity radar">
          <div className="flex items-baseline justify-between"><h2 className="font-display text-lg font-semibold">Opportunity radar</h2><span className="text-xs text-mute">closer = stronger</span></div>
          <div className="flex flex-1 flex-col justify-center"><Radar boards={boards.map((b) => b.data?.rows ?? [])} onSel={pick} tf={tf} /></div>
          <div className="mt-3 flex flex-wrap justify-center gap-3 text-xs text-mute"><span className="text-bull">● long</span><span className="text-bear">● short</span><span className="text-accent">◎ grade A</span><span>lit slice = live calls</span></div>
        </section>
        <section className="cc-panel flex flex-col p-4 sm:p-5" aria-label="Market universe">
          <div className="flex items-baseline justify-between"><h2 className="font-display text-lg font-semibold">Market universe</h2><span className="text-xs text-mute">7 days</span></div>
          <Universe peers={peers} status={dash.data?.market_status} mc={mc.data} onSel={pick} tf={tf} />
        </section>
      </div>
      {/* row 4: running signals beside coin vs coin; then the globe */}
      <div className="grid gap-4 xl:grid-cols-2">
        <section className="cc-panel flex flex-col p-4 sm:p-5" aria-label="Live signal journeys">
          <div className="flex items-baseline justify-between"><h2 className="font-display text-lg font-semibold">Live signal journeys</h2><span className="text-xs text-mute">stop → entry → targets</span></div>
          <div className="mt-3 flex-1"><SignalJourneys track={track.data} /></div>
        </section>
        <section className="cc-panel p-4 sm:p-5" aria-label="Coin versus coin">
          <div className="flex items-baseline justify-between"><h2 className="font-display text-lg font-semibold">Coin vs coin</h2><span className="text-xs text-mute">pick up to 3</span></div>
          <div className="mt-3"><LazyMount height={320}><CoinCompare rows={rows} /></LazyMount></div>
        </section>
      </div>
      <section className="cc-panel p-4 sm:p-5" aria-label="Market heat globe">
        <div className="flex items-baseline justify-between"><h2 className="font-display text-lg font-semibold">Market heat</h2><span className="text-xs text-mute">sessions · volume · next release</span></div>
        <div className="mt-3"><LazyMount height={380}><Suspense fallback={<div className="skeleton h-[360px] rounded-xl" />}><MarketGlobe news={news.data} /></Suspense></LazyMount></div>
      </section>
      <section id="cc-scan" className="cc-panel cc-scan scroll-mt-20 p-4 sm:p-6" aria-label={`Deep-space scan of ${name(focus)}`}>
        <Scan symbol={focus} row={row} f4={f4} tf={tf} />
      </section>
    </div>
  );
}
