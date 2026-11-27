// v2.66 premium instruments (owner, 21 Nov 2026: "make them look premium"). Same data as before, no extra reads.
//   CoinBead    a coin's real logo as a small sphere in SVG (gold for GOLD, initials when no logo exists)
//   OrbitDial   Home hero: every watched coin as a logo bead around a watch-style dial, grouped bull → neutral → bear,
//               ticker names printed radially; Fear & Greed arc inside; BTC live in the centre.
//   SonarScope  Market intelligence: coins leaning up in the upper half, leaning down in the lower half; distance from
//               the centre = signal strength; phosphor sweep; the strongest each side carry their logo and name.
import { memo, useId, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { base, DASH, fmtPctRaw, fmtPrice, isNum, slug } from "../lib/format";
import { useTickerThrottled } from "../lib/live";
import { TickFlash } from "./kit";
import { LookCycle } from "./TradeJourneys";

const ICONS = "/coins";   // v2.75: self-hosted (spothq/cryptocurrency-icons 0.18.1, CC0) - no third-party request per logo
const MISSING = new Set<string>();
const TAU = Math.PI * 2;
const BULL = "rgb(var(--bull))", BEAR = "rgb(var(--bear))", GLASS = "rgb(var(--glass) / 0.35)";
const hue = (s: string) => { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 360; return h; };
const arcPath = (cx: number, cy: number, r: number, a0: number, a1: number, sweep = 1) => {
  const p = (a: number) => `${(cx + r * Math.cos(a)).toFixed(2)} ${(cy + r * Math.sin(a)).toFixed(2)}`;
  return `M${p(a0)} A${r} ${r} 0 ${Math.abs(a1 - a0) > Math.PI ? 1 : 0} ${sweep} ${p(a1)}`;
};

/** +1 call up, +0.5 bullish regime, 0 neutral, -0.5 bearish regime, -1 call down. */
export const leanOf = (r: any) => {
  const s = String(r?.signal ?? r?.decision ?? "");
  if (/BUY|LONG/.test(s)) return 1;
  if (/SELL|SHORT/.test(s)) return -1;
  const g = String(r?.regime ?? "");
  return /BULL|UP/.test(g) ? 0.5 : /BEAR|DOWN/.test(g) ? -0.5 : 0;
};
const toneOf = (v: number) => (v > 0 ? BULL : v < 0 ? BEAR : GLASS);
const words = (v: number) => (v >= 1 ? "buy signal" : v > 0 ? "bullish trend" : v <= -1 ? "sell signal" : v < 0 ? "bearish trend" : "neutral");

/** One shared clip per SVG (objectBoundingBox: works for every bead size). */
export function BeadDefs({ id }: { id: string }) {
  return (
    <defs>
      <clipPath id={`${id}-round`} clipPathUnits="objectBoundingBox"><circle cx="0.5" cy="0.5" r="0.5" /></clipPath>
      <radialGradient id={`${id}-shade`} cx="35%" cy="30%" r="75%"><stop offset="0%" stopColor="#fff" stopOpacity="0.32" /><stop offset="45%" stopColor="#fff" stopOpacity="0" /><stop offset="100%" stopColor="#000" stopOpacity="0.55" /></radialGradient>
      <radialGradient id={`${id}-gold`} cx="35%" cy="30%"><stop offset="0%" stopColor="#fff1b8" /><stop offset="55%" stopColor="#f0b90b" /><stop offset="100%" stopColor="#8a6408" /></radialGradient>
      <radialGradient id={`${id}-silver`} cx="35%" cy="30%"><stop offset="0%" stopColor="#ffffff" /><stop offset="55%" stopColor="#b9c0c8" /><stop offset="100%" stopColor="#5d646d" /></radialGradient>
      <filter id={`${id}-glow`} x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="2.4" /></filter>
    </defs>
  );
}

export function CoinBead({ id, symbol, x, y, r, tone, ring = 1.4, shade = true }: { id: string; symbol: string; x: number; y: number; r: number; tone: string; ring?: number; shade?: boolean }) {
  const b = base(symbol);
  const [failed, setFailed] = useState(() => MISSING.has(b));
  const h = hue(b);
  return (
    <g>
      <circle cx={x} cy={y} r={r + 3.2} fill={tone} opacity={0.35} filter={`url(#${id}-glow)`} />
      {b === "GOLD" ? <>
        <circle cx={x} cy={y} r={r} fill={`url(#${id}-gold)`} />
        <text x={x} y={y + r * 0.34} textAnchor="middle" fontSize={r * 0.95} fontWeight="800" fill="#3b2a00">Au</text>
      </> : b === "SILVER" ? <>
        <circle cx={x} cy={y} r={r} fill={`url(#${id}-silver)`} />
        <text x={x} y={y + r * 0.34} textAnchor="middle" fontSize={r * 0.95} fontWeight="800" fill="#262b31">Ag</text>
      </> : failed ? <>
        <circle cx={x} cy={y} r={r} fill={`hsl(${h} 62% 42%)`} />
        <text x={x} y={y + r * 0.32} textAnchor="middle" fontSize={r * (b.length > 3 ? 0.62 : 0.8)} fontWeight="700" fill="#fff">{b.slice(0, 3)}</text>
      </> : <>
        <circle cx={x} cy={y} r={r} fill="#12151c" />
        <image href={`${ICONS}/${b.toLowerCase()}.svg`} x={x - r} y={y - r} width={r * 2} height={r * 2} clipPath={`url(#${id}-round)`}
          onError={() => { MISSING.add(b); setFailed(true); }} preserveAspectRatio="xMidYMid slice" />
      </>}
      {shade && <circle cx={x} cy={y} r={r} fill={`url(#${id}-shade)`} opacity={0.75} />}
      <circle cx={x} cy={y} r={r + 1.6} fill="none" stroke={tone} strokeWidth={ring} />
    </g>
  );
}

/* ================================================================== OrbitDial (Home hero) */
export const OrbitDial = memo(function OrbitDial({ rows, fg, fgLabel, status }: { rows?: any[]; fg?: number | null; fgLabel?: string; status?: any }) {
  const id = useId().replace(/:/g, "");
  const [hover, setHover] = useState<any>(null);
  const list = useMemo(() => (rows ?? []).filter((x) => x?.symbol)
    .map((x) => ({ x, v: leanOf(x) }))
    .sort((a, b) => b.v - a.v || (b.x.score ?? 0) - (a.x.score ?? 0)), [rows]);
  const n = Math.max(1, list.length);
  const C = 180, RB = 140;
  const step = TAU / n;
  const beadR = Math.max(6, Math.min(13, (RB * step) / 2 - 2.5));
  const start = -Math.PI / 2;
  const ang = (i: number) => start + (i + 0.5) * step;
  // background bands per group
  const groups: { v: number; i0: number; i1: number }[] = [];
  list.forEach((p, i) => { const g = p.v > 0 ? 1 : p.v < 0 ? -1 : 0; const last = groups[groups.length - 1]; if (last && last.v === g) last.i1 = i; else groups.push({ v: g, i0: i, i1: i }); });
  const f0 = Math.PI * 0.75, f1 = Math.PI * 2.25, RF = 106;
  const fv = isNum(fg) ? Math.max(0, Math.min(100, fg)) : null;
  const fa = fv == null ? null : f0 + (f1 - f0) * (fv / 100);
  const bull = status?.bull ?? list.filter((p) => p.v > 0).length;
  const bear = status?.bear ?? list.filter((p) => p.v < 0).length;
  return (
    <figure className="ins-dial">
      <svg viewBox="0 0 360 360" role="group" aria-label={`Market dial: ${bull} bullish and ${bear} bearish of ${list.length} coins; Fear and Greed ${fv ?? "unknown"}`}>
        <BeadDefs id={id} />
        <defs>
          <radialGradient id={`${id}-disc`}><stop offset="0%" stopColor="rgb(var(--accent) / 0.13)" /><stop offset="45%" stopColor="rgb(var(--panel) / 0.6)" /><stop offset="88%" stopColor="rgb(var(--ink) / 0.9)" /><stop offset="100%" stopColor="rgb(var(--ink) / 0)" /></radialGradient>
          <linearGradient id={`${id}-bezel`} x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="#fff1c4" stopOpacity="0.85" /><stop offset="35%" stopColor="#f0b90b" stopOpacity="0.55" /><stop offset="70%" stopColor="#6b4c06" stopOpacity="0.35" /><stop offset="100%" stopColor="#f0b90b" stopOpacity="0.6" /></linearGradient>
          <linearGradient id={`${id}-fg`} x1="0" x2="1"><stop offset="0%" stopColor="rgb(var(--bear))" /><stop offset="50%" stopColor="rgb(var(--accent))" /><stop offset="100%" stopColor="rgb(var(--bull))" /></linearGradient>
          <linearGradient id={`${id}-glint`} x1="0" x2="1"><stop offset="0%" stopColor="#fff" stopOpacity="0" /><stop offset="100%" stopColor="#fff1c4" stopOpacity="0.9" /></linearGradient>
        </defs>
        <circle cx={C} cy={C} r={170} fill={`url(#${id}-disc)`} />
        {/* group bands: the share of the ring is the market's breadth */}
        {groups.map((g) => {
          const a0 = start + g.i0 * step + 0.02, a1 = start + (g.i1 + 1) * step - 0.02;
          const col = g.v > 0 ? "rgb(var(--bull) / 0.16)" : g.v < 0 ? "rgb(var(--bear) / 0.14)" : "rgb(var(--glass) / 0.07)";
          return <path key={g.i0} d={arcPath(C, C, RB, a0, Math.max(a0 + 0.01, a1))} stroke={col} strokeWidth={beadR * 2 + 10} fill="none" strokeLinecap="round" />;
        })}
        {/* bezel + ticks */}
        <circle cx={C} cy={C} r={RB - beadR - 9} fill="none" stroke="rgb(var(--glass) / 0.08)" />
        <circle cx={C} cy={C} r={RB + beadR + 7} fill="none" stroke={`url(#${id}-bezel)`} strokeWidth={1.1} />
        {Array.from({ length: 72 }, (_, i) => {
          const a = (i / 72) * TAU, k = i % 6 === 0, r0 = RB + beadR + 9;
          return <line key={i} x1={C + r0 * Math.cos(a)} y1={C + r0 * Math.sin(a)} x2={C + (r0 + (k ? 4.5 : 2.2)) * Math.cos(a)} y2={C + (r0 + (k ? 4.5 : 2.2)) * Math.sin(a)} stroke={k ? "rgb(var(--accent) / 0.55)" : "rgb(var(--glass) / 0.2)"} strokeWidth={k ? 1 : 0.6} />;
        })}
        <g className="ins-glint" style={{ transformOrigin: `${C}px ${C}px` }}>
          <path d={arcPath(C, C, RB + beadR + 7, -0.9, 0)} stroke={`url(#${id}-glint)`} strokeWidth={1.8} fill="none" strokeLinecap="round" />
        </g>
        {/* fear & greed */}
        <path d={arcPath(C, C, RF, f0, f1)} stroke="rgb(var(--glass) / 0.08)" strokeWidth={4} fill="none" strokeLinecap="round" />
        {fa != null && <path d={arcPath(C, C, RF, f0, fa)} stroke={`url(#${id}-fg)`} strokeWidth={4} fill="none" strokeLinecap="round" />}
        {fa != null && <circle cx={C + RF * Math.cos(fa)} cy={C + RF * Math.sin(fa)} r={5} fill="rgb(var(--accent-2))" stroke="rgb(var(--ink))" strokeWidth={2} />}
        <text x={C} y={C + RF + 4} textAnchor="middle" fontSize="8.5" fill="rgb(var(--mute))" letterSpacing="0.5">Fear &amp; Greed</text>
        {/* coins */}
        {list.map((p, i) => {
          const a = ang(i), x = C + RB * Math.cos(a), y = C + RB * Math.sin(a);
          const b = base(p.x.symbol);
          const on = hover?.symbol === p.x.symbol;
          return (
            <Link key={p.x.symbol} to={`/asset/${slug(p.x.symbol)}`} className="ins-bead" aria-label={`${b}: ${words(p.v)}`}
              onMouseEnter={() => setHover(p.x)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(p.x)} onBlur={() => setHover(null)}>
              <CoinBead id={id} symbol={p.x.symbol} x={x} y={y} r={on ? beadR + 1.5 : beadR} tone={toneOf(p.v)} ring={Math.abs(p.v) >= 1 ? 1.8 : 1} />
              <title>{`${b} · ${words(p.v)}`}</title>
            </Link>
          );
        })}
      </svg>
      <DialCentre hover={hover} />
      <figcaption className="ins-cap">
        <span><b className="text-bull">{bull}</b> bullish · <b className="text-bear">{bear}</b> bearish <span className="text-mute">of {list.length} coins · 4H</span></span>
        <span className="text-mute">Fear &amp; Greed <b className="num text-text">{fv ?? DASH}</b>{fgLabel ? ` · ${fgLabel}` : ""}</span>
      </figcaption>
    </figure>
  );
});

/* ================================================================== ThinkingSpectrum (Overview mood card, V3.1)
   Owner's pick 24 Nov 2026 ("H"): a live "thinking" visualiser. Each watched coin is a bar around the AI core - colour =
   the AI's lean (call or trend), length = strength (a call > a trend > neutral, then the board score). The bars breathe,
   the core sends out cyan pulses, a thin gold ring carries Fear & Greed as an arc. BTC live in the centre; hover / focus a
   coin to see it there. Same data as the old dial, no extra reads. */
export const ThinkingSpectrum = memo(function ThinkingSpectrum({ rows, fg, fgLabel, status, tfLabel = "4H" }: { rows?: any[]; fg?: number | null; fgLabel?: string; status?: any; tfLabel?: string }) {
  const id = useId().replace(/:/g, "");
  const [hover, setHover] = useState<any>(null);
  const list = useMemo(() => (rows ?? []).filter((x) => x?.symbol)
    .map((x) => {
      const v = leanOf(x), sc = isNum(x.score) ? Math.max(0, Math.min(100, x.score)) / 100 : 0.5;
      return { x, v, k: Math.max(0.18, Math.min(1, 0.15 + 0.5 * Math.abs(v) + 0.35 * sc)) };
    })
    .sort((a, b) => b.v - a.v || b.k - a.k), [rows]);
  const n = Math.max(1, list.length);
  const C = 180, R0 = 66, LEN = 62, RING = 168;
  const step = TAU / n, start = -Math.PI / 2;
  const bw = Math.max(3, Math.min(9, (R0 * step) * 0.62));
  const beadR = Math.max(6, Math.min(9.5, ((R0 + LEN + 14) * step) / 2 - 1.5));
  const fv = isNum(fg) ? Math.max(0, Math.min(100, fg)) : null;
  const bull = status?.bull ?? list.filter((p) => p.v > 0).length;
  const bear = status?.bear ?? list.filter((p) => p.v < 0).length;
  const fgCol = fv == null ? "rgb(var(--mute))" : fv < 25 ? BEAR : fv < 45 ? "rgb(var(--warn))" : fv <= 55 ? "rgb(var(--mute))" : BULL;
  return (
    <figure className="ins-dial ts-dial">
      <svg viewBox="0 0 360 360" role="group" aria-label={`AI market spectrum: ${bull} bullish and ${bear} bearish of ${list.length} coins; Fear and Greed ${fv ?? "unknown"}`}>
        <BeadDefs id={id} />
        <circle cx={C} cy={C} r={RING} fill="none" stroke="rgb(var(--accent) / 0.35)" strokeWidth={1.2} />
        {fv != null && fv > 0 && <path d={arcPath(C, C, RING, start, start + Math.max(0.02, (fv / 100) * TAU))} fill="none" stroke={fgCol} strokeWidth={3.5} strokeLinecap="round" />}
        {list.map((p, i) => {
          const a = start + (i + 0.5) * step, r1 = R0 + LEN * p.k;
          const on = hover?.symbol === p.x.symbol;
          return (
            <line key={`b${p.x.symbol}`} x1={C + R0 * Math.cos(a)} y1={C + R0 * Math.sin(a)} x2={C + r1 * Math.cos(a)} y2={C + r1 * Math.sin(a)}
              stroke={toneOf(p.v)} strokeWidth={on ? bw + 2 : bw} strokeLinecap="round" className="ts-bar" style={{ animationDelay: `${((i * 0.37) % 2.4).toFixed(2)}s`, animationDuration: `${(2 + p.k * 2).toFixed(1)}s` }} />
          );
        })}
        <circle cx={C} cy={C} r={58} fill="rgb(var(--ink))" stroke="rgb(var(--accent))" strokeWidth={2.4} />
        {[0, 0.8, 1.6].map((d) => <circle key={d} cx={C} cy={C} r={58} fill="none" stroke="rgb(var(--ai))" strokeWidth={1.2} className="ts-pulse" style={{ animationDelay: `${d}s` }} />)}
        {list.map((p, i) => {
          const a = start + (i + 0.5) * step, rb = R0 + LEN * p.k + beadR + 5;
          const x = C + rb * Math.cos(a), y = C + rb * Math.sin(a), b = base(p.x.symbol);
          return (
            <Link key={p.x.symbol} to={`/asset/${slug(p.x.symbol)}`} className="ins-bead" aria-label={`${b}: ${words(p.v)}`}
              onMouseEnter={() => setHover(p.x)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(p.x)} onBlur={() => setHover(null)}>
              <CoinBead id={id} symbol={p.x.symbol} x={x} y={y} r={hover?.symbol === p.x.symbol ? beadR + 1.5 : beadR} tone={toneOf(p.v)} ring={1} shade={false} />
              <title>{`${b} · ${words(p.v)}`}</title>
            </Link>
          );
        })}
      </svg>
      <DialCentre hover={hover} />
      <figcaption className="ins-cap">
        <span><b className="text-bull">{bull}</b> bullish · <b className="text-bear">{bear}</b> bearish <span className="text-mute">of {list.length} coins · {tfLabel}</span></span>
        <span className="text-mute">Fear &amp; Greed <b className="num" style={{ color: fgCol }}>{fv ?? DASH}</b>{fgLabel ? ` · ${fgLabel}` : ""}</span>
      </figcaption>
    </figure>
  );
});

function DialCentre({ hover }: { hover: any }) {
  const sym = hover?.symbol ?? "BTC/USDT";
  const t = useTickerThrottled(sym, 1000);
  const ch = t?.change_pct ?? hover?.change_24h_pct;
  const v = hover ? leanOf(hover) : null;
  return (
    <div className="ins-dial-centre" aria-live="off">
      <span className="text-xs text-mute">{hover ? base(sym) : "Bitcoin"}</span>
      <TickFlash value={t?.last} className="num text-xl font-semibold tracking-tight">{isNum(t?.last) ? `$${fmtPrice(t!.last)}` : isNum(hover?.price) ? `$${fmtPrice(hover.price)}` : DASH}</TickFlash>
      <span className={`num text-xs font-medium ${!isNum(ch) ? "text-mute" : ch >= 0 ? "text-bull" : "text-bear"}`}>{isNum(ch) ? `${ch >= 0 ? "▲" : "▼"} ${fmtPctRaw(ch)}` : ""}</span>
      {v != null && <span className={`text-[11px] font-semibold ${v > 0 ? "text-bull" : v < 0 ? "text-bear" : "text-mute"}`}>{words(v)}</span>}
    </div>
  );
}

/* ================================================================== SonarScope (Market intelligence) */
type SonarRow = { symbol: string; signal?: string; score?: number; change_24h_pct?: number; regime?: string };
export function SonarScope({ rows, size = 300 }: { rows?: SonarRow[]; size?: number }) {
  const id = useId().replace(/:/g, "");
  const [hover, setHover] = useState<SonarRow | null>(null);
  const C = 150, R = 124, R0 = 24;
  const pts = useMemo(() => {
    const all = (rows ?? []).filter((r) => r.symbol).map((r) => ({ r, d: leanOf(r), s: Math.max(0.12, Math.min(1, (r.score ?? 50) / 100)) }));
    const place = (arr: typeof all, a0: number, a1: number) => {
      // even slots across the half; the strongest take slots spread far apart (middle, quarters, …) so labels never touch
      const k = arr.length, sorted = arr.sort((a, b) => b.s - a.s), used = new Set<number>();
      const vdc = (i: number) => { let x = 0, f = 0.5; for (let n = i + 1; n; n >>= 1, f /= 2) if (n & 1) x += f; return x; };
      return sorted.map((p, i) => {
        let slot = k > 1 ? Math.round(vdc(i) * (k - 1)) : 0;
        for (let d = 0; used.has(slot); d++) slot = (slot + (d % 2 ? -d : d) + k) % k;
        used.add(slot);
        const a = k > 1 ? a0 + ((slot + 0.5) / k) * (a1 - a0) : (a0 + a1) / 2;
        const rr = R0 + 10 + (R - R0 - 30) * p.s;
        return { ...p, a, x: C + rr * Math.cos(a), y: C + rr * Math.sin(a), rank: i };
      });
    };
    const up = place(all.filter((p) => p.d > 0), -Math.PI + 0.12, -0.12);
    const dn = place(all.filter((p) => p.d < 0), 0.12, Math.PI - 0.12);
    const ne = all.filter((p) => p.d === 0).map((p, i) => {
      const side = i % 2 ? Math.PI : 0, j = Math.floor(i / 2);
      const a = side + (j % 2 ? 1 : -1) * 0.05 * Math.ceil(j / 2);
      const rr = R0 + 18 + (j * 13) % (R - R0 - 26);
      return { ...p, a, x: C + rr * Math.cos(a), y: C + rr * Math.sin(a), rank: 99 };
    });
    return [...up, ...dn, ...ne];
  }, [rows]);
  const up = pts.filter((p) => p.d > 0), dn = pts.filter((p) => p.d < 0);
  const top = (arr: typeof pts) => arr.filter((p) => p.rank < 3);
  const labelled = new Set([...top(up), ...top(dn)].map((p) => p.r.symbol));
  const wedges = 14;
  return (
    <figure className="ins-sonar mx-auto w-full" style={{ maxWidth: size }}>
      <svg viewBox="0 0 300 300" role="group" aria-label={`AI sonar: ${up.length} coins leaning up, ${dn.length} leaning down`}>
        <BeadDefs id={id} />
        <defs>
          <radialGradient id={`${id}-bg`}><stop offset="0%" stopColor="rgb(var(--ai) / 0.16)" /><stop offset="75%" stopColor="rgb(var(--ink) / 0.55)" /><stop offset="100%" stopColor="rgb(var(--ink) / 0.9)" /></radialGradient>
          <linearGradient id={`${id}-up`} x1="0" y1="1" x2="0" y2="0"><stop offset="0%" stopColor="rgb(var(--bull) / 0)" /><stop offset="100%" stopColor="rgb(var(--bull) / 0.13)" /></linearGradient>
          <linearGradient id={`${id}-dn`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="rgb(var(--bear) / 0)" /><stop offset="100%" stopColor="rgb(var(--bear) / 0.13)" /></linearGradient>
          <radialGradient id={`${id}-core`} cx="40%" cy="35%"><stop offset="0%" stopColor="#d9ecff" /><stop offset="45%" stopColor="rgb(var(--ai))" /><stop offset="100%" stopColor="rgb(var(--ai) / 0.25)" /></radialGradient>
        </defs>
        <circle cx={C} cy={C} r={R + 10} fill={`url(#${id}-bg)`} />
        <path d={`M${C - R} ${C} A${R} ${R} 0 0 1 ${C + R} ${C} Z`} fill={`url(#${id}-up)`} />
        <path d={`M${C - R} ${C} A${R} ${R} 0 0 0 ${C + R} ${C} Z`} fill={`url(#${id}-dn)`} />
        {/* range rings + bearing ticks */}
        {[0.34, 0.67, 1].map((k) => <circle key={k} cx={C} cy={C} r={R0 + (R - R0) * k} fill="none" stroke="rgb(var(--ai) / 0.2)" strokeDasharray={k === 1 ? "" : "1.5 4"} />)}
        <circle cx={C} cy={C} r={R + 6} fill="none" stroke="rgb(var(--ai) / 0.35)" strokeWidth={0.8} />
        {Array.from({ length: 72 }, (_, i) => {
          const a = (i / 72) * TAU, k = i % 9 === 0;
          return <line key={i} x1={C + (R + 6) * Math.cos(a)} y1={C + (R + 6) * Math.sin(a)} x2={C + (R + (k ? 11 : 8.5)) * Math.cos(a)} y2={C + (R + (k ? 11 : 8.5)) * Math.sin(a)} stroke={k ? "rgb(var(--ai) / 0.6)" : "rgb(var(--ai) / 0.25)"} strokeWidth={0.7} />;
        })}
        <line x1={C - R - 6} x2={C + R + 6} y1={C} y2={C} stroke="rgb(var(--glass) / 0.25)" strokeWidth={0.8} />
        <text x={C + R0 + (R - R0) * 0.34 - 2} y={C - 3} textAnchor="end" fontSize="6.5" fill="rgb(var(--mute))">weak</text>
        <text x={C + R - 4} y={C - 3} textAnchor="end" fontSize="6.5" fill="rgb(var(--mute))">strong</text>
        {/* phosphor sweep: a fan of thin wedges fading behind the beam */}
        <g className="ins-sweep" style={{ transformOrigin: `${C}px ${C}px` }}>
          {Array.from({ length: wedges }, (_, i) => {
            const a1 = -i * 0.045, a0 = a1 - 0.05;
            return <path key={i} d={`M${C} ${C} L${C + R * Math.cos(a0)} ${C + R * Math.sin(a0)} A${R} ${R} 0 0 1 ${C + R * Math.cos(a1)} ${C + R * Math.sin(a1)} Z`} fill="rgb(var(--ai))" opacity={0.2 * (1 - i / wedges) ** 1.6} />;
          })}
          <line x1={C} y1={C} x2={C + R} y2={C} stroke="rgb(var(--ai) / 0.85)" strokeWidth={1.1} />
        </g>
        {/* blips */}
        {pts.map((p) => {
          const tone = toneOf(p.d), big = labelled.has(p.r.symbol), on = hover?.symbol === p.r.symbol;
          const b = base(p.r.symbol);
          const below = p.y < C; // label on the centre side, away from the rim
          return (
            <Link key={p.r.symbol} to={`/asset/${slug(p.r.symbol)}`} className="ins-blip" aria-label={`${b}: ${words(p.d)}, strength ${Math.round(p.s * 100)}`}
              onMouseEnter={() => setHover(p.r)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(p.r)} onBlur={() => setHover(null)}>
              {big || on ? <>
                <CoinBead id={id} symbol={p.r.symbol} x={p.x} y={p.y} r={7} tone={tone} ring={1.2} />
                <g>
                  <rect x={p.x - (b.length * 2.9 + 6)} y={below ? p.y + 10 : p.y - 21} width={b.length * 5.8 + 12} height={12} rx={6} fill="rgb(var(--ink) / 0.82)" stroke={tone} strokeOpacity={0.45} strokeWidth={0.6} />
                  <text x={p.x} y={below ? p.y + 18.6 : p.y - 12.4} textAnchor="middle" fontSize="8" fontWeight="700" fill="rgb(var(--text))">{b}</text>
                </g>
              </> : <>
                <circle cx={p.x} cy={p.y} r={6} fill={tone} opacity={0.18} className="xeno-blip" style={{ animationDelay: `${(p.a / TAU) * 2.4}s` }} />
                <circle cx={p.x} cy={p.y} r={2.6} fill={tone} filter={`url(#${id}-glow)`} />
                <circle cx={p.x} cy={p.y} r={2.2} fill={tone} />
                <circle cx={p.x} cy={p.y} r={9} fill="transparent" />
              </>}
            </Link>
          );
        })}
        {/* AI core */}
        <circle cx={C} cy={C} r={R0 - 6} fill="rgb(var(--ai) / 0.12)" className="ins-pulse" style={{ transformOrigin: `${C}px ${C}px` }} />
        <circle cx={C} cy={C} r={12} fill={`url(#${id}-core)`} stroke="rgb(var(--ai) / 0.7)" strokeWidth={0.8} />
        <text x={C} y={C + 3.2} textAnchor="middle" fontSize="8.5" fontWeight="800" fill="#06121f">AI</text>
      </svg>
      <figcaption className="mt-1 text-center text-xs text-mute" aria-live="polite">
        {hover ? <><span className="font-semibold text-text">{base(hover.symbol)}</span> · {words(leanOf(hover))}{typeof hover.score === "number" ? ` · strength ${hover.score}/100` : ""}{isNum(hover.change_24h_pct) ? <> · <span className={hover.change_24h_pct >= 0 ? "text-bull" : "text-bear"}>{fmtPctRaw(hover.change_24h_pct)} 24h</span></> : null}</>
          : <><span className="text-bull">▲ {up.length} leaning up</span> · <span className="text-bear">▼ {dn.length} leaning down</span> · farther out = stronger</>}
      </figcaption>
    </figure>
  );
}

/* ================================================================== Mood dial looks (V3.5, owner 27 Nov 2026)
   Same data as ThinkingSpectrum (the chosen timeframe's dashboard rows, Fear & Greed, BTC live); one button turns through
   Spectrum → Liquid orb → Chronograph → LED stadium (remembered on this device). */
type MoodProps = { rows?: any[]; fg?: number | null; fgLabel?: string; status?: any; tfLabel?: string };
const MOOD_LOOKS = [["spectrum", "Spectrum"], ["orb", "Liquid orb"], ["watch", "Chronograph"], ["led", "LED stadium"]] as const;
type MoodLook = (typeof MOOD_LOOKS)[number][0];
const MOOD_KEY = "cia-mood-look";

function useMoodData({ rows, fg, status }: MoodProps) {
  const list = useMemo(() => (rows ?? []).filter((x) => x?.symbol).map((x) => {
    const v = leanOf(x), sc = isNum(x.score) ? Math.max(0, Math.min(100, x.score)) / 100 : 0.5;
    return { x, v, k: Math.max(0.18, Math.min(1, 0.15 + 0.5 * Math.abs(v) + 0.35 * sc)) };
  }).sort((a, b) => a.v - b.v || b.k - a.k), [rows]);
  const n = list.length;
  const bull = status?.bull ?? list.filter((p) => p.v > 0).length;
  const bear = status?.bear ?? list.filter((p) => p.v < 0).length;
  const fv = isNum(fg) ? Math.max(0, Math.min(100, fg)) : null;
  const fgCol = fv == null ? "rgb(var(--mute))" : fv < 25 ? BEAR : fv < 45 ? "rgb(var(--warn))" : fv <= 55 ? "rgb(var(--mute))" : BULL;
  const net = n ? (bull - bear) / n : 0;
  const word = !n ? "Waiting" : net <= -0.5 ? "Bearish" : net < -0.15 ? "Leaning bearish" : net >= 0.5 ? "Bullish" : net > 0.15 ? "Leaning bullish" : "Mixed";
  const tone = net < -0.15 ? BEAR : net > 0.15 ? BULL : "rgb(var(--mute))";
  return { list, n, bull, bear, fv, fgCol, net, word, tone };
}

function MoodCap({ d, tfLabel, fgLabel }: { d: ReturnType<typeof useMoodData>; tfLabel: string; fgLabel?: string }) {
  return (
    <figcaption className="ins-cap">
      <span><b className="text-bull">{d.bull}</b> bullish · <b className="text-bear">{d.bear}</b> bearish <span className="text-mute">of {d.n} coins · {tfLabel}</span></span>
      <span className="text-mute">Fear &amp; Greed <b className="num" style={{ color: d.fgCol }}>{d.fv ?? DASH}</b>{fgLabel ? ` · ${fgLabel}` : ""}</span>
    </figcaption>
  );
}

function BtcLine({ y, size = 13 }: { y: number; size?: number }) {
  const t = useTickerThrottled("BTC/USDT", 1000);
  const ch = t?.change_pct;
  return (
    <>
      <text x="180" y={y} textAnchor="middle" fontSize={size + 5} fontWeight="700" fill="rgb(var(--text))" className="num">{isNum(t?.last) ? `$${fmtPrice(t.last)}` : "BTC"}</text>
      {isNum(ch) && <text x="180" y={y + size + 4} textAnchor="middle" fontSize={size - 2} fill={ch >= 0 ? BULL : BEAR}>BTC {ch >= 0 ? "▲" : "▼"} {fmtPctRaw(Math.abs(ch))}</text>}
    </>
  );
}

const MoodOrb = memo(function MoodOrb(p: MoodProps) {
  const id = useId().replace(/:/g, "");
  const d = useMoodData(p);
  const bearSide = d.bear >= d.bull;
  const share = d.n ? (bearSide ? d.bear : d.bull) / d.n : 0;
  const col = !d.n ? "rgb(var(--mute))" : bearSide ? BEAR : BULL;
  const top = 330 - share * 300;
  const wave = (yy: number, a: number) => `M-40 ${yy} q20 ${-a} 40 0 t40 0 t40 0 t40 0 t40 0 t40 0 t40 0 t40 0 t40 0 t40 0 t40 0 V400 H-40Z`;
  const floaters = (bearSide ? d.list.filter((q) => q.v < 0) : [...d.list].reverse().filter((q) => q.v > 0)).slice(0, 3);
  return (
    <figure className="ins-dial md-orb">
      <svg viewBox="0 0 360 360" role="img" aria-label={`Liquid orb: ${Math.round(share * 100)}% of coins ${bearSide ? "bearish" : "bullish"}`}>
        <BeadDefs id={id} />
        <defs>
          <clipPath id={`${id}-o`}><circle cx="180" cy="180" r="150" /></clipPath>
          <radialGradient id={`${id}-g`} cx="35%" cy="28%" r="80%"><stop offset="0" stopColor="#fff" stopOpacity=".22" /><stop offset=".45" stopColor="#fff" stopOpacity=".03" /><stop offset="1" stopColor="#000" stopOpacity=".35" /></radialGradient>
        </defs>
        <circle cx="180" cy="180" r="166" fill="none" stroke="rgb(var(--accent) / 0.45)" strokeWidth="1.5" />
        {d.fv != null && d.fv > 0 && <path d={arcPath(180, 180, 166, -Math.PI / 2, -Math.PI / 2 + Math.max(0.02, (d.fv / 100) * TAU))} fill="none" stroke={d.fgCol} strokeWidth="3.5" strokeLinecap="round" />}
        <circle cx="180" cy="180" r="150" fill="rgb(var(--ink))" />
        <g clipPath={`url(#${id}-o)`}>
          <path className="md-wave2" d={wave(top + 4, 7)} fill={col} opacity=".45" />
          <path className="md-wave" d={wave(top, 9)} fill={col} opacity=".9" />
          {floaters.map((q, i) => (
            <g key={q.x.symbol} className="md-float" style={{ animationDelay: `${i * 1.1}s` }}>
              <CoinBead id={id} symbol={q.x.symbol} x={120 + i * 62} y={Math.min(300, Math.max(top + 40, 250 - (i % 2) * 34))} r={15} tone="rgb(255 255 255 / 0.5)" ring={1} />
            </g>
          ))}
        </g>
        <circle cx="180" cy="180" r="150" fill={`url(#${id}-g)`} stroke="rgb(var(--glass) / 0.25)" />
        <ellipse cx="128" cy="92" rx="44" ry="20" fill="#fff" opacity=".13" transform="rotate(-30 128 92)" />
        <text x="180" y="150" textAnchor="middle" fontSize="50" fontWeight="700" fill="#fff" style={{ paintOrder: "stroke" }} stroke="rgb(0 0 0 / 0.35)" strokeWidth="3" className="num">{d.n ? `${Math.round(share * 100)}%` : DASH}</text>
        <text x="180" y="174" textAnchor="middle" fontSize="14" fill="#fff" opacity=".85">{d.n ? (bearSide ? "bearish" : "bullish") : "waiting for data"}</text>
        <BtcLine y={212} />
      </svg>
      <MoodCap d={d} tfLabel={p.tfLabel ?? "4H"} fgLabel={p.fgLabel} />
    </figure>
  );
});

const MoodWatch = memo(function MoodWatch(p: MoodProps) {
  const id = useId().replace(/:/g, "");
  const d = useMoodData(p);
  const ang = Math.max(-1, Math.min(1, d.net)) * 120;
  const ticks = Array.from({ length: 41 }, (_, i) => {
    const a = ((-120 + i * 6) * Math.PI) / 180, big = i % 5 === 0, r1 = 150, r2 = big ? 136 : 142;
    return { x1: 180 + r1 * Math.sin(a), y1: 180 - r1 * Math.cos(a), x2: 180 + r2 * Math.sin(a), y2: 180 - r2 * Math.cos(a), big };
  });
  return (
    <figure className="ins-dial md-watch">
      <svg viewBox="0 0 360 360" role="img" aria-label={`Chronograph: market mood ${d.word}; Fear and Greed ${d.fv ?? "unknown"}`}>
        <defs>
          <linearGradient id={`${id}-gold`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#F6E37A" /><stop offset=".5" stopColor="#E8B637" /><stop offset="1" stopColor="#9C7417" /></linearGradient>
          <radialGradient id={`${id}-face`} cx="50%" cy="40%" r="70%"><stop offset="0" stopColor="rgb(var(--raised))" /><stop offset="1" stopColor="rgb(var(--ink))" /></radialGradient>
          <linearGradient id={`${id}-arc`} x1="0" y1="0" x2="1" y2="0"><stop offset="0" stopColor="rgb(var(--bear))" /><stop offset=".5" stopColor="rgb(var(--mute))" /><stop offset="1" stopColor="rgb(var(--bull))" /></linearGradient>
        </defs>
        <circle cx="180" cy="180" r="174" fill={`url(#${id}-gold)`} />
        <circle cx="180" cy="180" r="163" fill={`url(#${id}-face)`} />
        <path d="M 73.8 241.3 A 122.6 122.6 0 1 1 286.2 241.3" fill="none" stroke={`url(#${id}-arc)`} strokeWidth="10" strokeLinecap="round" />
        {ticks.map((t, i) => <line key={i} x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2} stroke={t.big ? "#E8B637" : "rgb(var(--glass) / 0.35)"} strokeWidth={t.big ? 2 : 1} />)}
        <text x="64" y="280" fontSize="11" fill={BEAR} letterSpacing="1">BEAR</text>
        <text x="180" y="44" fontSize="11" fill="rgb(var(--mute))" textAnchor="middle" letterSpacing="1">NEUTRAL</text>
        <text x="296" y="280" fontSize="11" fill={BULL} textAnchor="end" letterSpacing="1">BULL</text>
        <circle cx="133" cy="226" r="29" fill="rgb(var(--ink))" stroke="rgb(var(--accent) / 0.35)" />
        <text x="133" y="228" fontSize="17" fontWeight="700" fill={d.fgCol} textAnchor="middle" className="num">{d.fv ?? DASH}</text>
        <text x="133" y="242" fontSize="7.5" fill="rgb(var(--mute))" textAnchor="middle">FEAR &amp; GREED</text>
        <circle cx="227" cy="226" r="29" fill="rgb(var(--ink))" stroke="rgb(var(--accent) / 0.35)" />
        <text x="227" y="228" fontSize="15" fontWeight="700" fill={d.tone} textAnchor="middle" className="num">{d.bull}/{d.bear}</text>
        <text x="227" y="242" fontSize="7.5" fill="rgb(var(--mute))" textAnchor="middle">BULL / BEAR</text>
        <g className="md-needle" style={{ transform: `rotate(${ang}deg)` }}>
          <path d="M176.5 180 L180 70 L183.5 180 Z" fill="rgb(var(--text))" />
          <path d="M178 180 L180 204 L182 180 Z" fill="#E8B637" />
        </g>
        <circle cx="180" cy="180" r="11" fill={`url(#${id}-gold)`} />
        <circle cx="180" cy="180" r="4" fill="rgb(var(--ink))" />
        <BtcLine y={300} size={12} />
      </svg>
      <MoodCap d={d} tfLabel={p.tfLabel ?? "4H"} fgLabel={p.fgLabel} />
    </figure>
  );
});

const MoodLed = memo(function MoodLed(p: MoodProps) {
  const d = useMoodData(p);
  const n = Math.max(1, d.n);
  return (
    <figure className="ins-dial md-led">
      <svg viewBox="0 0 360 360" role="img" aria-label={`LED stadium: ${d.bear} red bearish, ${d.bull} green bullish of ${d.n} coins`}>
        <circle cx="180" cy="180" r="160" fill="none" stroke="rgb(var(--glass) / 0.08)" strokeWidth="34" />
        {d.list.map((q, i) => (
          <Link key={q.x.symbol} to={`/asset/${slug(q.x.symbol)}`} aria-label={`${base(q.x.symbol)}: ${words(q.v)}`}>
            <rect className="md-seg" x="173" y="12" width="14" height="30" rx="6" fill={q.v > 0 ? BULL : q.v < 0 ? BEAR : "rgb(var(--mute))"}
              opacity={(0.35 + 0.65 * q.k).toFixed(2)} transform={`rotate(${((i + 0.5) * 360 / n).toFixed(1)} 180 180)`} style={{ animationDelay: `${(i * 0.08).toFixed(2)}s` }}>
              <title>{`${base(q.x.symbol)} · ${words(q.v)}`}</title>
            </rect>
          </Link>
        ))}
        <circle className="md-chase" cx="180" cy="180" r="136" fill="none" stroke="#E8B637" strokeWidth="2" strokeDasharray="44 811" strokeLinecap="round" />
        <circle cx="180" cy="180" r="122" fill="rgb(var(--ink))" stroke="rgb(var(--accent) / 0.35)" />
        <text x="180" y="146" fontSize="11" fill="rgb(var(--mute))" textAnchor="middle" letterSpacing="2">MOOD</text>
        <text x="180" y="182" fontSize={d.word.length > 9 ? 24 : 34} fontWeight="700" fill={d.tone} textAnchor="middle">{d.word}</text>
        <text x="180" y="206" fontSize="13" fill="rgb(var(--mute))" textAnchor="middle">{d.n ? `${Math.max(d.bull, d.bear)} of ${d.n} coins` : ""}</text>
        <BtcLine y={238} size={11} />
      </svg>
      <MoodCap d={d} tfLabel={p.tfLabel ?? "4H"} fgLabel={p.fgLabel} />
    </figure>
  );
});

/** The Overview mood dial with one button that turns through its looks. */
export function MoodDial(p: MoodProps) {
  const [look, setLook] = useState<MoodLook>(() => { try { const v = localStorage.getItem(MOOD_KEY); return (MOOD_LOOKS.find(([k]) => k === v)?.[0] ?? "spectrum") as MoodLook; } catch { return "spectrum"; } });
  const pick = (v: MoodLook) => { setLook(v); try { localStorage.setItem(MOOD_KEY, v); } catch { /* private mode */ } };
  return (
    <div className="md-wrap">
      {look === "orb" ? <MoodOrb {...p} /> : look === "watch" ? <MoodWatch {...p} /> : look === "led" ? <MoodLed {...p} /> : <ThinkingSpectrum {...p} />}
      <LookCycle looks={MOOD_LOOKS} value={look} onChange={pick} label="Mood dial look" />
    </div>
  );
}
