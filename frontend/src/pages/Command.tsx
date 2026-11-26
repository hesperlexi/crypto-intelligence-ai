// v2.45 Command Centre (owner, 16 Nov 2026: the approved "Command Centre concept", gold-black theme). An extra page:
// nothing else changes. Real data only, from documents the app already reads:
//   views/dashboard_4h (coins, regime, AI lean, RSI / ADX, 24h change + volume), the six views/futures_<tf> boards (the
//   Signals page's calls), views/track_record (open calls), views/market_context + context (alt strength, Fear & Greed),
//   views/health (mission control; already open in the header), the coin's analysis view for the scan (1 read per coin
//   picked). Correlations from public Binance 1h candles in the browser (no Firebase).
import { lazy, ReactNode, Suspense, useEffect, useId, useMemo, useRef, useState } from "react";
import { BeadDefs, CoinBead, leanOf } from "../components/Instruments";
import { Link } from "react-router-dom";
import { Segmented } from "../components/kit";
import { CoinAvatar } from "../components/Polish";
import { ErrorBox, Loading } from "../components/ui";
import { useApi } from "../lib/api";
import { isAdmin } from "../lib/session";
import { useKlines } from "../lib/klines";
import LazyMount from "../components/LazyMount";
import { CoinCompare } from "../components/CommandPlus";
const MarketGlobe = lazy(() => import("../components/MarketGlobe"));
import { useLive, useTicker, useTickerThrottled } from "../lib/live";
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

/** Market map = "Opportunity quadrant" (owner's pick, 24 Nov 2026; replaces the galaxy). Across = 24h move (live
 *  ticker), up / down = the AI's lean on the chosen timeframe (P(up) − P(down) from that timeframe's futures board; the
 *  trend when the board has none), dot size = 24h volume, colour = the AI's lean. Coins where the price and the AI agree
 *  sit in the green (top right) and red (bottom left) corners. Gold dashed ring = a call running on this timeframe. */
function Galaxy({ rows, open, sel, onSel, onHover, board }: { rows: any[]; open: Set<string>; sel: string; onSel: (s: string) => void; onHover: (s: string | null) => void; board?: any[] }) {
  const { tickers } = useLive();
  const narrow = useNarrow();
  const W = narrow ? 400 : 960, H = narrow ? 420 : 560, P = { l: narrow ? 14 : 22, r: narrow ? 14 : 22, t: 30, b: 34 };
  const maxV = Math.max(1, ...rows.map((r) => r.quote_volume_24h ?? 0));
  const pts = rows.map((r) => {
    const f = (board ?? []).find((x: any) => x.symbol === r.symbol);
    const lean = isNum(f?.p_up) && isNum(f?.p_down) ? f.p_up - f.p_down : leanOf(r) * 0.3;
    const chg = tickers[r.symbol]?.change_pct ?? r.change_24h_pct ?? 0;
    return { r, lean, chg: isNum(chg) ? chg : 0, size: (narrow ? 4 : 6) + (narrow ? 9 : 16) * Math.sqrt((r.quote_volume_24h ?? 0) / maxV) };
  });
  const sortedAbs = pts.map((p) => Math.abs(p.chg)).sort((a, b) => a - b);
  const xMax = Math.max(1, sortedAbs[Math.floor(sortedAbs.length * 0.92)] ?? 1) * 1.15;
  const yMax = Math.max(0.2, ...pts.map((p) => Math.abs(p.lean))) * 1.15;
  const cx = (P.l + W - P.r) / 2, cy = (P.t + H - P.b) / 2, hw = (W - P.l - P.r) / 2, hh = (H - P.t - P.b) / 2;
  const X = (v: number) => cx + Math.max(-1, Math.min(1, v / xMax)) * hw * 0.94;
  const Y = (v: number) => cy - Math.max(-1, Math.min(1, v / yMax)) * hh * 0.9;
  const tone = (l: number) => (l > 0.02 ? "rgb(var(--bull))" : l < -0.02 ? "rgb(var(--bear))" : "rgb(var(--mute))");
  // labels: biggest first, skipped where they would sit on top of another label
  const placed: { x: number; y: number; w: number }[] = [];
  const labelled = new Set<string>(), leftSide = new Set<string>();
  [...pts].sort((a, b) => b.size - a.size).forEach((p) => {
    const w = name(p.r.symbol).length * (narrow ? 6.6 : 7.4) + 6;
    const left = X(p.chg) + p.size + 4 + w > W - P.r;
    const x = left ? X(p.chg) - p.size - 4 - w : X(p.chg) + p.size + 4, y = Y(p.lean) + 4;
    const hit = placed.some((q) => Math.abs(q.y - y) < 13 && x < q.x + q.w && x + w > q.x)
      || pts.some((o) => o !== p && X(o.chg) + o.size > x && X(o.chg) - o.size < x + w && Y(o.lean) + o.size > y - 11 && Y(o.lean) - o.size < y + 3);
    if (!hit || p.r.symbol === sel) { placed.push({ x, y, w }); labelled.add(p.r.symbol); if (left) leftSide.add(p.r.symbol); }
  });
  const corner = (x: number, y: number, a: "start" | "end", t: string, c: string) => <text x={x} y={y} fontSize={narrow ? 10.5 : 12} fontWeight="600" fill={c} textAnchor={a}>{t}</text>;
  return (
    <div className="cc-galaxy">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="group" aria-label="Market map: 24h move across, the AI's lean up and down">
        <rect x={cx} y={P.t} width={hw} height={hh} fill="rgb(var(--bull) / 0.05)" />
        <rect x={P.l} y={cy} width={hw} height={hh} fill="rgb(var(--bear) / 0.05)" />
        {[0.25, 0.5, 0.75].flatMap((k) => [cx - hw * k, cx + hw * k]).map((x) => <line key={`v${x}`} x1={x} x2={x} y1={P.t} y2={H - P.b} stroke="rgb(var(--glass) / 0.035)" />)}
        {[0.33, 0.66].flatMap((k) => [cy - hh * k, cy + hh * k]).map((y) => <line key={`h${y}`} x1={P.l} x2={W - P.r} y1={y} y2={y} stroke="rgb(var(--glass) / 0.035)" />)}
        <line x1={P.l} x2={W - P.r} y1={cy} y2={cy} stroke="rgb(var(--glass) / 0.16)" />
        <line x1={cx} x2={cx} y1={P.t} y2={H - P.b} stroke="rgb(var(--glass) / 0.16)" />
        {corner(W - P.r - 8, P.t + 16, "end", "Rising · AI agrees", "rgb(var(--bull))")}
        {corner(P.l + 8, P.t + 16, "start", "Falling · AI sees up", "rgb(var(--mute))")}
        {corner(P.l + 8, H - P.b - 8, "start", "Falling · AI agrees", "rgb(var(--bear))")}
        {corner(W - P.r - 8, H - P.b - 8, "end", "Rising · AI sees down", "rgb(var(--mute))")}
        <text x={cx} y={H - 10} fontSize="11" fill="rgb(var(--mute))" textAnchor="middle">24h move → · {`±${xMax.toFixed(1)}%`}</text>
        <text transform={`translate(${P.l - 4} ${cy}) rotate(-90)`} fontSize="11" fill="rgb(var(--mute))" textAnchor="middle" dy="-2">AI lean ↑</text>
        {[...pts].sort((a, b) => b.size - a.size).map((p) => {
          const on = p.r.symbol === sel, x = X(p.chg), y = Y(p.lean);
          return (
            <g key={p.r.symbol} className="cc-planet" tabIndex={0} role="button"
              aria-label={`${name(p.r.symbol)} ${pct(p.chg)} in 24 hours, AI ${p.lean > 0.02 ? "leans up" : p.lean < -0.02 ? "leans down" : "neutral"}${open.has(p.r.symbol) ? ", signal running" : ""}`}
              onMouseEnter={() => onHover(p.r.symbol)} onMouseLeave={() => onHover(null)} onFocus={() => onHover(p.r.symbol)} onBlur={() => onHover(null)}
              onClick={() => onSel(p.r.symbol)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSel(p.r.symbol); } }}>
              {on && <circle cx={x} cy={y} r={p.size + 8} fill="none" stroke="rgb(var(--text) / 0.8)" strokeWidth="1.5" />}
              {open.has(p.r.symbol) && <circle cx={x} cy={y} r={p.size + 4} fill="none" stroke={GOLD} strokeWidth="1.6" strokeDasharray="3 3" />}
              <circle cx={x} cy={y} r={p.size} fill={tone(p.lean)} fillOpacity={0.78} stroke="rgb(var(--ink))" strokeWidth="1" />
            </g>
          );
        })}
        {pts.filter((p) => labelled.has(p.r.symbol)).map((p) => {
          const x = X(p.chg), y = Y(p.lean), l = leftSide.has(p.r.symbol);
          return <text key={`l${p.r.symbol}`} x={l ? x - p.size - 4 : x + p.size + 4} y={y + 4} fontSize={narrow ? 10.5 : 12} fontWeight="600" fill="rgb(var(--text))" textAnchor={l ? "end" : "start"} pointerEvents="none"
            stroke="rgb(var(--panel))" strokeWidth={3} paintOrder="stroke">{name(p.r.symbol)}</text>;
        })}
      </svg>
    </div>
  );
}

/** v2.74 Observatory (owner, 22 Nov 2026): the readout beside the galaxy - the planet under the pointer, else the one
 *  locked on. Never drawn over the galaxy. */
function Readout({ symbol, row, f, tf, onScan }: { symbol: string; row: any; f: any; tf: string; onScan: () => void }) {
  const t = useTickerThrottled(symbol, 1000);
  const px = t?.last ?? row?.price, chg = t?.change_pct ?? row?.change_24h_pct;
  const side = f?.side ?? 0, grade = f?.grade;
  const up = isNum(f?.p_up) ? Math.round(f.p_up * 100) : null, dn = isNum(f?.p_down) ? Math.round(f.p_down * 100) : null;
  return (
    <section className="cc-readout" aria-live="polite" aria-label={`Readout: ${name(symbol)}`}>
      <div className="flex items-center gap-3"><CoinAvatar symbol={symbol} size={44} />
        <div className="min-w-0"><div className="font-display text-[22px] font-semibold leading-tight">{name(symbol)}</div><div className="text-sm text-mute">Selected · tap a coin</div></div></div>
      <div><span className="font-display num text-[34px] font-semibold tracking-tight">{isNum(px) ? fmtPrice(px) : "—"}</span> <span className={`num font-semibold ${(chg ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{pct(chg)}</span></div>
      <span className={`cc-ro-call ${side > 0 ? "is-long" : side < 0 ? "is-short" : ""}`}>{side > 0 ? "▲ Long call" : side < 0 ? "▼ Short call" : "No call now"} · {tf.toUpperCase()}{side && grade ? ` · grade ${grade}` : ""}</span>
      <dl className="cc-ro-grid">
        <div><dt>Trend</dt><dd>{row?.trend_label ?? regimeWord(row?.regime)}</dd></div>
        <div><dt>RSI 14</dt><dd className="num">{isNum(row?.rsi) ? row.rsi.toFixed(0) : "—"}</dd></div>
        <div><dt>Volume 24h</dt><dd className="num">{isNum(row?.quote_volume_24h) ? fmtCompact(row.quote_volume_24h) : "—"}</dd></div>
        <div><dt>AI lean</dt><dd className={up != null && dn != null ? (up > dn ? "text-bull" : up < dn ? "text-bear" : "") : ""}>{up != null && dn != null ? (up >= dn ? `${up}% up` : `${dn}% down`) : "—"}</dd></div>
      </dl>
      {(f?.ai?.rationale || f?.decision_basis || f?.decision_reason) && <p className="cc-ro-note">{f?.ai?.rationale ?? f?.decision_basis ?? f?.decision_reason}</p>}
      <button type="button" className="btn btn-primary mt-auto w-full" onClick={onScan}>Coin deep dive</button>
    </section>
  );
}

const regimeWord = (r?: string) => (!r ? "—" : r.charAt(0) + r.slice(1).toLowerCase());

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

function beta(a: number[], b: number[]) {
  const n = Math.min(a.length, b.length);
  if (n < 20) return null;
  const x = a.slice(-n), y = b.slice(-n);
  const mx = x.reduce((s, v) => s + v, 0) / n, my = y.reduce((s, v) => s + v, 0) / n;
  let cxy = 0, vx = 0;
  for (let i = 0; i < n; i++) { cxy += (x[i] - mx) * (y[i] - my); vx += (x[i] - mx) ** 2; }
  return vx ? cxy / vx : null;
}

/** BTC link map = "Racing BTC" (owner's pick, 24 Nov 2026; replaces the v2.66 solar system). Seven days of hourly closes
 *  of BTC and the five biggest coins, all rebased to 0 % at the start: gold = BTC, a coin in green finished ahead of BTC,
 *  grey behind it. Under it per coin: how closely it followed BTC (hourly-return correlation) and how big its moves were
 *  next to BTC's (beta). Same public Binance klines as before; no Firestore reads. */
function Universe({ peers, status, mc, onSel, tf }: { peers: string[]; status: any; mc: any; onSel: (s: string) => void; tf: string }) {
  const btc = useKlines("BTC/USDT", "1h", 168, 900_000);
  const k = [useKlines(peers[0] ?? "ETH/USDT", "1h", 168, 900_000), useKlines(peers[1] ?? "SOL/USDT", "1h", 168, 900_000), useKlines(peers[2] ?? "BNB/USDT", "1h", 168, 900_000),
    useKlines(peers[3] ?? "XRP/USDT", "1h", 168, 900_000), useKlines(peers[4] ?? "DOGE/USDT", "1h", 168, 900_000)];
  const rb = rets(btc.data);
  const rebase = (c: any[] | null) => (c && c.length > 1 ? c.map((x) => (x[4] / c[0][4] - 1) * 100) : null);
  const series = [{ s: "BTC/USDT", v: rebase(btc.data), btc: true, c: 1, b: 1 },
    ...peers.slice(0, 5).map((s, i) => ({ s, v: rebase(k[i].data), btc: false, c: corr(rb, rets(k[i].data)), b: beta(rb, rets(k[i].data)) }))]
    .filter((x) => x.v && x.v.length > 1) as { s: string; v: number[]; btc: boolean; c: number | null; b: number | null }[];
  const bw = week(btc.data);
  const alt = mc?.altseason?.value;
  const W = 640, H = 280, x0 = 8, x1 = W - 128, top = 12, bot = H - 24;
  const all = series.flatMap((x) => x.v);
  const mn = Math.min(0, ...all) - 0.5, mx = Math.max(0, ...all) + 0.5;
  const Y = (v: number) => top + ((mx - v) / (mx - mn)) * (bot - top);
  const n = Math.max(2, ...series.map((x) => x.v.length));
  const X = (i: number, len: number) => x0 + ((i + (n - len)) / (n - 1)) * (x1 - x0);
  const end = (x: { v: number[] }) => x.v[x.v.length - 1];
  const colOf = (x: { btc: boolean; v: number[] }) => (x.btc ? "rgb(var(--accent))" : isNum(bw) && end(x) >= bw ? "rgb(var(--bull))" : "rgb(var(--text) / 0.5)");
  const step = (mx - mn) > 24 ? 10 : (mx - mn) > 10 ? 5 : 2;
  const grid: number[] = [];
  for (let g = Math.ceil(mn / step) * step; g <= mx; g += step) grid.push(g);
  // labels at the right end, pushed apart so they never overlap
  const labels = series.map((x) => ({ x, y: Y(end(x)) })).sort((a, b) => a.y - b.y);
  for (let i = 1; i < labels.length; i++) labels[i].y = Math.max(labels[i].y, labels[i - 1].y + 17);
  const over = labels.length ? labels[labels.length - 1].y - (H - 8) : 0;
  if (over > 0) labels.forEach((l) => { l.y -= over; });
  const days = btc.data && btc.data.length > 1 ? Array.from({ length: 7 }, (_, d) => {
    const i = Math.round(((d + 0.5) / 7) * (btc.data!.length - 1));
    return { x: X(i, btc.data!.length), t: new Date(btc.data![i][0]).toLocaleDateString(undefined, { weekday: "short" }) };
  }) : [];
  return (
    <div className="flex flex-1 flex-col gap-3">
      {series.length < 2 ? <div className="skeleton h-[260px] rounded-xl" /> : (
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Seven days of Bitcoin and the five biggest coins, rebased to 0%. Bitcoin ${pct(bw)}.`}>
          {grid.map((g) => (
            <g key={g}>
              <line x1={x0} x2={x1} y1={Y(g)} y2={Y(g)} stroke={`rgb(var(--glass) / ${g === 0 ? 0.16 : 0.05})`} />
              <text x={x1 + 6} y={Y(g) + 3.5} fontSize="9.5" fill="rgb(var(--mute) / 0.8)">{g > 0 ? "+" : ""}{g}%</text>
            </g>
          ))}
          {days.map((d, i) => <text key={i} x={d.x} y={H - 6} fontSize="10" fill="rgb(var(--mute))" textAnchor="middle">{d.t}</text>)}
          {series.filter((x) => !x.btc).map((x) => (
            <polyline key={x.s} points={x.v.map((v, i) => `${X(i, x.v.length).toFixed(1)},${Y(v).toFixed(1)}`).join(" ")} fill="none" stroke={colOf(x)} strokeWidth={1.5} strokeLinejoin="round" />
          ))}
          {series.filter((x) => x.btc).map((x) => (
            <polyline key={x.s} points={x.v.map((v, i) => `${X(i, x.v.length).toFixed(1)},${Y(v).toFixed(1)}`).join(" ")} fill="none" stroke={colOf(x)} strokeWidth={2.8} strokeLinejoin="round" />
          ))}
          {labels.map(({ x, y }) => (
            <g key={x.s} className="cc-planet" tabIndex={x.btc ? -1 : 0} role={x.btc ? undefined : "button"} onClick={() => !x.btc && onSel(x.s)} onKeyDown={(e) => { if (e.key === "Enter" && !x.btc) onSel(x.s); }}>
              <line x1={x1} y1={Y(end(x))} x2={x1 + 30} y2={y} stroke={colOf(x)} strokeOpacity={0.35} />
              <text x={x1 + 34} y={y + 3.5} fontSize="11" fontWeight="600" fill="rgb(var(--text))">{name(x.s)} <tspan fill={x.btc ? "rgb(var(--accent))" : end(x) >= 0 ? "rgb(var(--bull))" : "rgb(var(--bear))"}>{pct(end(x))}</tspan></text>
            </g>
          ))}
        </svg>
      )}
      <div className="rb-chips">
        {series.filter((x) => !x.btc).map((x) => (
          <button key={x.s} type="button" className="rb-chip" onClick={() => onSel(x.s)}>
            <CoinAvatar symbol={x.s} size={16} /><span>{name(x.s)} follows BTC <b>{isNum(x.c) ? `${Math.round(x.c * 100)}%` : "—"}</b></span>
            <span className="text-mute">· moves <b className="text-accent">{isNum(x.b) ? `${x.b.toFixed(1)}×` : "—"}</b></span>
          </button>
        ))}
      </div>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div className="cc-cell"><div className="text-mute">Breadth · {tf.toUpperCase()}</div><div className="text-sm font-semibold"><span className="text-bull">{status?.bull ?? "—"} ▲</span> <span className="text-bear">{status?.bear ?? "—"} ▼</span></div></div>
        <div className="cc-cell"><div className="text-mute">Alt strength</div><div className="text-sm font-semibold">{isNum(alt) ? `${Math.round(alt)} / 100` : "—"}</div></div>
        <div className="cc-cell"><div className="text-mute">BTC · 7 days</div><div className={`text-sm font-semibold ${(bw ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{pct(bw)}</div></div>
      </div>
      <p className="text-xs text-mute">All lines start at 0% seven days ago. Gold = Bitcoin; green = finished ahead of Bitcoin. "Moves 1.6×" = its swings are 1.6 times Bitcoin's.</p>
    </div>
  );
}

function Mission({ health, connected }: { health: any; connected: boolean }) {
  const e = health?.engine ?? {};
  const last = e.last_tick_finished;
  const age = isNum(last) ? (Date.now() - last) / 60_000 : null;
  const models: any[] = health?.models ?? [];
  const active = health?.models_summary?.active ?? models.filter((m) => m.version).length;
  const newest = health?.models_summary?.newest ?? Math.max(0, ...models.map((m) => m.trained_at ?? 0));
  const admin = isAdmin();                                   // v2.68: plan budget and errors are for the owner only
  const writes = e.firestore_writes_today, budget = isNum(e.firestore_free_limit) ? e.firestore_free_limit : 20000;
  const errs = health?.recent_errors_count ?? 0;
  const ok = "rgb(var(--bull))", warn = "rgb(var(--warn))", bad = "rgb(var(--bear))";
  const rows: [string, string, string, string][] = [
    ["Live prices", connected ? "Streaming from Binance" : "Reconnecting…", connected ? "Live" : "Waiting", connected ? ok : warn],
    ["Signal engine", isNum(last) ? `Last cycle ${ago(last)} · every 4 min` : "No cycle seen yet", age == null ? "Unknown" : age < 15 ? "Running" : age < 75 ? "Late" : "Stopped", age == null ? warn : age < 15 ? ok : age < 75 ? warn : bad],
    ["AI models", `${active} active${newest ? ` · newest ${ago(newest)}` : ""}`, active ? "Ready" : "Training", active ? ok : warn],
    ["Market data", health?.market_data?.status ? `Feed ${String(health.market_data.status).toLowerCase()}${isNum(health.market_data.quality_pct) ? ` · ${health.market_data.quality_pct}% complete` : ""}` : "—", health?.status ?? "—", health?.status === "LIVE" ? ok : health?.status === "DOWN" ? bad : warn],
    ...(!admin ? [] : [["Free-plan budget", isNum(writes) ? `${writes.toLocaleString()} of ${Number(budget).toLocaleString()} writes today` : "—", isNum(writes) ? `${Math.round((writes / budget) * 100)}%` : "—", isNum(writes) && writes / budget > 0.9 ? warn : ok],
    ["Errors · recent", errs ? `${errs} logged by the engine` : "None logged", String(errs), errs ? warn : ok]] as [string, string, string, string][]),
  ];
  return (
    <ul className="grid h-full auto-rows-fr gap-2">
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
/** Coin deep dive = "Trading card" (owner's pick, 24 Nov 2026; replaces the planet). A premium card for the coin (logo,
 *  rank by 24h volume, live price, today's change, 60 hourly closes) beside the eight facts, the call on the chosen
 *  timeframe and the engine's note, with the nearest support / resistance under the line. */
function Scan({ symbol, row, f4, tf, rank }: { symbol: string; row: any; f4: any; tf: string; rank?: number }) {
  const T = tf.toUpperCase();
  const tk = useTicker(symbol);
  const an = useApi<any>(`/analysis/${slug(symbol)}?timeframe=${tf}`);
  const a = an.data?.status === "OK" ? an.data : null;
  const kl = useKlines(symbol, "1h", 60, 900_000);
  const px = tk?.last ?? a?.price ?? row?.price;
  const sup = (a?.levels?.zones?.support ?? []).map((z: any) => z.mid).filter((p: number) => isNum(p) && isNum(px) && p < px).sort((x: number, y: number) => y - x)[0];
  const res = (a?.levels?.zones?.resistance ?? []).map((z: any) => z.mid).filter((p: number) => isNum(p) && isNum(px) && p > px).sort((x: number, y: number) => x - y)[0];
  const side = callOf(f4);
  const chg = tk?.change_pct ?? row?.change_24h_pct;
  const abs = isNum(px) && isNum(chg) ? px - px / (1 + chg / 100) : null;
  const closes: number[] = (kl.data ?? []).map((k: any) => k[4]);
  const mn = Math.min(...closes), mx = Math.max(...closes);
  const line = closes.length > 1 ? closes.map((c, i) => `${((i / (closes.length - 1)) * 380).toFixed(1)},${(56 - ((c - mn) / (mx - mn || 1)) * 50).toFixed(1)}`).join(" ") : "";
  const up = closes.length > 1 ? closes[closes.length - 1] >= closes[0] : (chg ?? 0) >= 0;
  const trend = row?.trend_label;
  const inds: [string, string, string?][] = [
    [`Trend ${T}`, trend ?? "—", trend === "Up" ? "text-bull" : trend === "Down" ? "text-bear" : ""],
    ["RSI 14", isNum(row?.rsi) ? `${row.rsi.toFixed(0)} · ${row.rsi >= 70 ? "overbought" : row.rsi <= 30 ? "oversold" : "neutral"}` : "—"],
    ["ADX", isNum(row?.adx) ? `${row.adx.toFixed(0)} · ${row.adx >= 25 ? "trending" : "no clear trend"}` : "—"],
    ["Volatility", row?.volatility ? String(row.volatility).toLowerCase().replace(/^./, (c: string) => c.toUpperCase()) : "—"],
    ["Volume 24h", isNum(tk?.quote_volume ?? row?.quote_volume_24h) ? `${fmtCompact(tk?.quote_volume ?? row?.quote_volume_24h)} USDT` : "—"],
    ["Liquidity", isNum(tk?.spread_bps) ? `spread ${tk!.spread_bps!.toFixed(1)} bps` : "—"],
    ["Signal score", isNum(row?.score) ? `${Math.round(row.score)} / 100` : "—", "text-accent"],
    ["News", f4?.news_risk?.title ? `${f4.news_risk.title}` : "No major release near", f4?.news_risk ? "text-warn" : ""],
  ];
  const note = a?.ai?.rationale || (side ? f4?.decision_basis : f4?.decision_reason ? `No trade: ${f4.decision_reason}.` : null) || "The engine has no note for this coin yet.";
  return (
    <div className="tc-wrap">
      <div className="tc-card">
        <div className="tc-glow" aria-hidden="true" />
        <div className="tc-head">
          <CoinAvatar symbol={symbol} size={44} />
          <div className="min-w-0"><div className="tc-name">{name(symbol)}</div><div className="text-xs text-mute">{base(symbol)}/USDT{rank ? ` · #${rank}` : ""}</div></div>
          <span className={`tc-call ${side > 0 ? "is-long" : side < 0 ? "is-short" : ""}`}>{side > 0 ? "▲ LONG" : side < 0 ? "▼ SHORT" : "WAIT"}{side && f4?.grade ? ` · ${f4.grade}` : ""} · {T}</span>
        </div>
        <div className="tc-price num">{fmtPrice(px)}</div>
        <div className={`num text-sm font-semibold ${(chg ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{pct(chg)}{isNum(abs) ? ` · ${abs >= 0 ? "+" : ""}${fmtPrice(abs)} today` : ""}</div>
        {line ? (
          <svg viewBox="0 0 380 60" className="tc-spark" aria-label="Last 60 hours">
            <defs><linearGradient id="tc-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor={up ? "rgb(var(--bull))" : "rgb(var(--bear))"} stopOpacity="0.3" /><stop offset="1" stopColor={up ? "rgb(var(--bull))" : "rgb(var(--bear))"} stopOpacity="0" /></linearGradient></defs>
            <polygon points={`0,60 ${line} 380,60`} fill="url(#tc-fill)" />
            <polyline points={line} fill="none" stroke={up ? "rgb(var(--bull))" : "rgb(var(--bear))"} strokeWidth="2" strokeLinejoin="round" />
          </svg>
        ) : <div className="skeleton tc-spark h-[60px]" />}
        <div className="tc-levels num"><span className="text-bull">Support {isNum(sup) ? fmtPrice(sup) : "—"}</span><span className="text-bear">Resistance {isNum(res) ? fmtPrice(res) : "—"}</span></div>
      </div>
      <div className="tc-side">
        <h2 className="font-display text-lg font-semibold">Coin deep dive · {T}</h2>
        <div className="tc-facts">
          {inds.map(([k, v, c]) => <div key={k} className="tc-fact"><div className="text-xs text-mute">{k}</div><div className={`truncate font-semibold ${c ?? ""}`}>{v}</div></div>)}
        </div>
        <div className="tc-note"><b className="text-ai">AI note</b> {note}</div>
        <Link to={`/asset/${slug(symbol)}?tf=${tf}`} className="btn btn-primary w-full sm:w-auto sm:self-start">Open full analysis</Link>
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
    <section className="cc-mission" aria-label="System status">
      <div className="min-w-0">
        <h1 className="page-title">AI Intelligence</h1>
        <p className="mt-1 flex items-center gap-2 text-sm text-mute"><span className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-bull live-dot" : "bg-warn"}`} />Live market intelligence · real data only</p>
      </div>
      <dl className="cc-readouts">
        {read.map(([k, v, c]) => <div key={k}><dt>{k}</dt><dd className={c ?? ""}>{v}</dd></div>)}
      </dl>
      <div className="cc-mission-tf">
        <Segmented value={tf} onChange={setTf} options={TFS.map((t) => [t, t.toUpperCase()] as [string, string])} label="Timeframe the map, AI core and deep dive follow" />
      </div>
    </section>
  );
}

export default function Command() {
  // v2.47 (owner): every timeframe - the galaxy, AI core, breadth and the scan follow the chosen one (remembered)
  const [tf, setTfRaw] = useState<string>(() => { try { const t = localStorage.getItem("cia-cc-tf"); return t && (TFS as readonly string[]).includes(t) ? t : "4h"; } catch { return "4h"; } });
  const setTf = (t: string) => { setTfRaw(t); try { localStorage.setItem("cia-cc-tf", t); } catch { /* ignore */ } };
  const dash = useApi<any>(`/dashboard?timeframe=${tf}`, 60000);
  // v2.75: only the chosen timeframe's board loads at once; the other five wait until "Signals in flight" is near
  const flightRef = useRef<HTMLElement | null>(null);
  const [flightSeen, setFlightSeen] = useState(false);
  useEffect(() => {
    const el = flightRef.current;
    if (flightSeen || !el || typeof IntersectionObserver === "undefined") { if (!flightSeen && typeof IntersectionObserver === "undefined") setFlightSeen(true); return; }
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { setFlightSeen(true); io.disconnect(); } }, { rootMargin: "400px" });
    io.observe(el);
    return () => io.disconnect();
  });
  const boards = TFS.map((t) => useApi<any>(t === tf || flightSeen ? `/futures?timeframe=${t}` : null)); // fixed list: stable hooks
  const track = useApi<any>("/track-record");
  const mc = useApi<any>("/market-context");
  const health = useApi<any>(isAdmin() ? "/system/admin" : "/system/health");
  const news = useApi<any>("/news", 300_000);
  const { connected } = useLive();
  const rows: any[] = (dash.data?.rows ?? []).filter((r: any) => r.status === "OK");
  const open = useMemo(() => new Set<string>((track.data?.live?.signals ?? []).filter((x: any) => x.status === "OPEN" && x.timeframe === tf).map((x: any) => x.symbol)), [track.data, tf]);
  const [sel, setSel] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const scan = () => window.setTimeout(() => document.getElementById("cc-scan")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  const pick = (s: string) => { setSel(s); scan(); };
  const focus = sel ?? [...open][0] ?? rows[0]?.symbol ?? "BTC/USDT";
  const row = rows.find((r) => r.symbol === focus);
  const shown = hover ?? focus;
  const f4 = (boards[TFS.indexOf(tf as any)]?.data?.rows ?? []).find((r: any) => r.symbol === focus);
  const peers = rows.map((r) => r.symbol).filter((s) => s !== "BTC/USDT" && base(s) !== "PAXG")
    .sort((a, b) => (rows.find((r) => r.symbol === b)?.quote_volume_24h ?? 0) - (rows.find((r) => r.symbol === a)?.quote_volume_24h ?? 0)).slice(0, 5);
  if (dash.loading && !dash.data && !rows.length) return <Loading />;
  if (dash.error) return <ErrorBox error={dash.error} retry={dash.reload} />;
  return (
    <div className="cc-page space-y-4">
      <Defs />
      <MissionStrip tf={tf} setTf={setTf} status={dash.data?.market_status} open={track.data} health={health.data} connected={connected} />
      {/* v2.74 Observatory (owner's pick, 22 Nov 2026): galaxy beside its readout */}
      <div className="cc-row1">
        <section className="cc-panel flex flex-col p-4 sm:p-5" aria-label="Market map">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div><h2 className="font-display text-xl font-semibold">Market map</h2><p className="text-sm text-mute">Across = 24h move, up / down = the AI's lean. Tap a coin to read it.</p></div>
            <div className="flex flex-wrap gap-3 text-xs text-mute"><span className="text-bull">● AI leans up</span><span className="text-bear">● AI leans down</span><span className="text-accent">◌ {tf.toUpperCase()} signal running</span><span>size = 24h volume</span></div>
          </div>
          <div className="flex flex-1 items-center [&>*]:w-full"><Galaxy rows={rows} open={open} sel={focus} onSel={setSel} onHover={setHover} board={boards[TFS.indexOf(tf as any)]?.data?.rows} /></div>
        </section>
        <Readout symbol={shown} row={rows.find((r) => r.symbol === shown)} f={(boards[TFS.indexOf(tf as any)]?.data?.rows ?? []).find((r: any) => r.symbol === shown)} tf={tf}
          onScan={() => { setSel(shown); scan(); }} />
      </div>
      {/* V3.4 Stage 5: live signals live in one place, Opportunities → Signals (no repeat here) */}
      <Link to="/signals" className="cc-panel flex items-center justify-between gap-3 p-4 text-sm hover:border-accent/40">
        <span><b className="font-semibold">Live signals</b><span className="ml-2 text-mute">running calls with stop, entry, targets and price now</span></span>
        <span className="text-accent">Open Signals →</span>
      </Link>
      {/* market forces: universe beside mission control, then the globe full width */}
      <div className="cc-forces">
        <section className="cc-panel flex flex-col p-4 sm:p-5" aria-label="Racing BTC">
          <div className="flex items-baseline justify-between"><h2 className="font-display text-lg font-semibold">Racing BTC</h2><span className="text-xs text-mute">7 days · rebased to 0%</span></div>
          <Universe peers={peers} status={dash.data?.market_status} mc={mc.data} onSel={pick} tf={tf} />
        </section>
        <section className="cc-panel flex flex-col p-4 sm:p-5" aria-label="System status">
          <div className="flex items-baseline justify-between"><h2 className="font-display text-lg font-semibold">System status</h2><span className="text-xs text-mute">live status</span></div>
          <div className="mt-3 flex-1"><Mission health={health.data} connected={connected} /></div>
        </section>
      </div>
      <section className="cc-panel p-4 sm:p-5" aria-label="Market heat globe">
        <div className="flex items-baseline justify-between"><h2 className="font-display text-lg font-semibold">Market heat</h2><span className="text-xs text-mute">sessions · volume · next release</span></div>
        <div className="mt-3 flex-1"><LazyMount height={380}><Suspense fallback={<div className="skeleton h-[360px] rounded-xl" />}><MarketGlobe news={news.data} /></Suspense></LazyMount></div>
      </section>
      <section id="cc-scan" className="cc-panel cc-scan scroll-mt-20 p-4 sm:p-6" aria-label={`Coin deep dive: ${name(focus)}`}>
        <Scan symbol={focus} row={row} f4={f4} tf={tf} rank={[...rows].sort((a, b) => (b.quote_volume_24h ?? 0) - (a.quote_volume_24h ?? 0)).findIndex((r) => r.symbol === focus) + 1 || undefined} />
      </section>
      <section className="cc-panel p-4 sm:p-5" aria-label="Coin versus coin">
        <div className="flex items-baseline justify-between"><h2 className="font-display text-lg font-semibold">Coin vs coin</h2><span className="text-xs text-mute">pick up to 3</span></div>
        <div className="mt-3"><LazyMount height={320}><CoinCompare rows={rows} /></LazyMount></div>
      </section>
    </div>
  );
}
