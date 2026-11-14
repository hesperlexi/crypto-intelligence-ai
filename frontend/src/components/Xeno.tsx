// "Observatory" visuals (owner, 14 Nov 2026): a quiet cosmic backdrop for every page, an AI market radar for the
// Overview and a holographic orbit for the welcome page. Decoration only: no data reads beyond what the page has,
// colours from theme tokens, all motion off under prefers-reduced-motion (index.css).
import { memo, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { base, slug } from "../lib/format";

/* deterministic pseudo-random so the sky does not jump between renders */
function rng(seed: number) {
  let s = seed;
  return () => ((s = (s * 9301 + 49297) % 233280) / 233280);
}

/** Fixed behind the app: faint stars, two nebula glows, one slow orbit arc. */
export const CosmicBackdrop = memo(function CosmicBackdrop() {
  const stars = useMemo(() => {
    const r = rng(11);
    return Array.from({ length: 110 }, (_, i) => ({ x: r() * 1600, y: r() * 1000, s: r() < 0.08 ? 1.6 : r() < 0.4 ? 1 : 0.6, tw: i % 9 === 0, d: (r() * 6).toFixed(2) }));
  }, []);
  return (
    <div className="cosmos" aria-hidden="true">
      <svg viewBox="0 0 1600 1000" preserveAspectRatio="xMidYMid slice" className="h-full w-full">
        <defs>
          <radialGradient id="neb1" cx="80%" cy="18%" r="45%"><stop offset="0%" stopColor="rgb(var(--ai) / 0.16)" /><stop offset="100%" stopColor="rgb(var(--ai) / 0)" /></radialGradient>
          <radialGradient id="neb2" cx="8%" cy="92%" r="40%"><stop offset="0%" stopColor="rgb(var(--accent) / 0.10)" /><stop offset="100%" stopColor="rgb(var(--accent) / 0)" /></radialGradient>
        </defs>
        <rect width="1600" height="1000" fill="url(#neb1)" />
        <rect width="1600" height="1000" fill="url(#neb2)" />
        <g className="cosmos-orbit" style={{ transformOrigin: "1320px 140px" }}>
          <ellipse cx="1320" cy="140" rx="520" ry="170" fill="none" stroke="rgb(var(--ai) / 0.10)" strokeDasharray="2 10" />
          <circle cx="1840" cy="140" r="2.6" fill="rgb(var(--ai) / 0.7)" />
        </g>
        {stars.map((st, i) => (
          <circle key={i} cx={st.x} cy={st.y} r={st.s} fill="rgb(var(--text) / 0.55)" className={st.tw ? "cosmos-twinkle" : undefined}
            style={st.tw ? { animationDelay: `${st.d}s` } : undefined} opacity={st.s > 1 ? 0.8 : 0.35} />
        ))}
      </svg>
    </div>
  );
});

type RadarRow = { symbol: string; signal?: string; score?: number; change_24h_pct?: number };
const dirOf = (s?: string) => (!s ? 0 : s.includes("BUY") ? 1 : s.includes("SELL") ? -1 : 0);

/** The watchlist as blips on a radar: angle = coin, distance from the centre = signal strength, colour = direction. */
export function MarketRadar({ rows, size = 260 }: { rows?: RadarRow[]; size?: number }) {
  const [hover, setHover] = useState<RadarRow | null>(null);
  const list = (rows ?? []).filter((r) => r.symbol).slice(0, 24);
  const C = 130, R = 112;
  const pts = list.map((r, i) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(1, list.length);
    const strength = Math.max(0.12, Math.min(1, (r.score ?? 50) / 100));
    const d = dirOf(r.signal);
    const rr = 18 + (R - 18) * (d === 0 ? 0.25 : strength);
    return { r, d, x: C + rr * Math.cos(a), y: C + rr * Math.sin(a) };
  });
  const bull = pts.filter((p) => p.d > 0).length, bear = pts.filter((p) => p.d < 0).length;
  const col = (d: number) => (d > 0 ? "rgb(var(--bull))" : d < 0 ? "rgb(var(--bear))" : "rgb(var(--mute))");
  return (
    <figure className="mx-auto w-full" style={{ maxWidth: size }}>
      <svg viewBox="0 0 260 260" className="w-full" role="img" aria-label={`AI radar: ${bull} coins leaning up, ${bear} leaning down`}>
        <defs>
          <radialGradient id="rdr-bg"><stop offset="0%" stopColor="rgb(var(--ai) / 0.22)" /><stop offset="70%" stopColor="rgb(var(--ai) / 0.05)" /><stop offset="100%" stopColor="rgb(var(--ai) / 0)" /></radialGradient>
          <linearGradient id="rdr-sw" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stopColor="rgb(var(--ai) / 0)" /><stop offset="100%" stopColor="rgb(var(--ai) / 0.32)" /></linearGradient>
          <filter id="rdr-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.2" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
        </defs>
        <circle cx={C} cy={C} r={R + 12} fill="url(#rdr-bg)" />
        {[0.33, 0.66, 1].map((k) => <circle key={k} cx={C} cy={C} r={18 + (R - 18) * k} fill="none" stroke="rgb(var(--ai) / 0.22)" strokeDasharray={k === 1 ? "" : "2 4"} />)}
        <line x1={C - R} x2={C + R} y1={C} y2={C} stroke="rgb(var(--ai) / 0.12)" />
        <line y1={C - R} y2={C + R} x1={C} x2={C} stroke="rgb(var(--ai) / 0.12)" />
        <g className="xeno-sweep" style={{ transformOrigin: `${C}px ${C}px` }}>
          <path d={`M${C} ${C} L${C + R} ${C} A${R} ${R} 0 0 0 ${C + R * Math.cos(-0.5)} ${C + R * Math.sin(-0.5)} Z`} fill="url(#rdr-sw)" />
          <line x1={C} y1={C} x2={C + R} y2={C} stroke="rgb(var(--ai) / 0.6)" />
        </g>
        <g filter="url(#rdr-glow)">
          {pts.map((p) => (
            <Link key={p.r.symbol} to={`/asset/${slug(p.r.symbol)}`} onMouseEnter={() => setHover(p.r)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(p.r)} onBlur={() => setHover(null)}>
              <circle cx={p.x} cy={p.y} r={p.d ? 4.2 : 3} fill={col(p.d)} className="xeno-blip" />
              <text x={p.x} y={p.y - 7} textAnchor="middle" fontSize="8" fill="rgb(var(--text) / 0.75)">{base(p.r.symbol)}</text>
            </Link>
          ))}
        </g>
        <circle cx={C} cy={C} r="13" fill="rgb(var(--panel) / 0.9)" stroke="rgb(var(--ai) / 0.5)" />
        <text x={C} y={C + 3.5} textAnchor="middle" fontSize="9" fontWeight="700" fill="rgb(var(--ai))">AI</text>
      </svg>
      <figcaption className="mt-1 text-center text-xs text-mute">
        {hover ? <><span className="font-semibold text-text">{base(hover.symbol)}</span> · {hover.signal ?? "—"}{typeof hover.score === "number" ? ` · ${hover.score}/100` : ""}</>
          : <><span className="text-bull">{bull} up</span> · <span className="text-bear">{bear} down</span> · {pts.length - bull - bear} neutral</>}
      </figcaption>
    </figure>
  );
}

/** Welcome page: a holographic planet with orbiting rings, scanning sweep and signal blips. */
export function HoloOrbit({ className = "" }: { className?: string }) {
  const blips = useMemo(() => { const r = rng(5); return Array.from({ length: 14 }, (_, i) => ({ a: (i / 14) * Math.PI * 2 + r() * 0.3, k: 0.45 + r() * 0.5, up: r() > 0.42 })); }, []);
  const C = 200;
  return (
    <svg viewBox="0 0 400 400" className={className} aria-hidden="true">
      <defs>
        <radialGradient id="ho-core" cx="40%" cy="35%"><stop offset="0%" stopColor="rgb(var(--ai) / 0.55)" /><stop offset="55%" stopColor="rgb(var(--ai) / 0.12)" /><stop offset="100%" stopColor="rgb(var(--ai) / 0)" /></radialGradient>
        <radialGradient id="ho-halo"><stop offset="60%" stopColor="rgb(var(--accent) / 0)" /><stop offset="85%" stopColor="rgb(var(--accent) / 0.10)" /><stop offset="100%" stopColor="rgb(var(--accent) / 0)" /></radialGradient>
        <linearGradient id="ho-sw" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stopColor="rgb(var(--ai) / 0)" /><stop offset="100%" stopColor="rgb(var(--ai) / 0.16)" /></linearGradient>
        <pattern id="ho-hex" width="14" height="24" patternUnits="userSpaceOnUse"><path d="M7 0 14 4v8L7 16 0 12V4Z M7 16v8" fill="none" stroke="rgb(var(--ai) / 0.12)" strokeWidth="0.6" /></pattern>
        <clipPath id="ho-clip"><circle cx={C} cy={C} r="78" /></clipPath>
        <filter id="ho-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.5" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      </defs>
      <circle cx={C} cy={C} r="190" fill="url(#ho-halo)" />
      {[120, 150, 182].map((r, i) => <circle key={r} cx={C} cy={C} r={r} fill="none" stroke="rgb(var(--ai) / 0.18)" strokeDasharray={i === 1 ? "1 6" : "3 5"} />)}
      <g className="holo-tilt" style={{ transformOrigin: `${C}px ${C}px` }}>
        <ellipse cx={C} cy={C} rx="170" ry="46" fill="none" stroke="rgb(var(--accent) / 0.35)" />
        <circle cx={C + 170} cy={C} r="4" fill="rgb(var(--accent))" filter="url(#ho-glow)" />
      </g>
      <g className="holo-tilt2" style={{ transformOrigin: `${C}px ${C}px` }}>
        <ellipse cx={C} cy={C} rx="140" ry="62" fill="none" stroke="rgb(var(--ai) / 0.35)" strokeDasharray="4 6" />
        <circle cx={C - 140} cy={C} r="3" fill="rgb(var(--ai))" filter="url(#ho-glow)" />
      </g>
      <g className="xeno-sweep" style={{ transformOrigin: `${C}px ${C}px`, animationDuration: "9s" }}>
        <path d={`M${C} ${C} L${C + 182} ${C} A182 182 0 0 0 ${C + 182 * Math.cos(-0.45)} ${C + 182 * Math.sin(-0.45)} Z`} fill="url(#ho-sw)" />
      </g>
      <circle cx={C} cy={C} r="80" fill="rgb(var(--ink) / 0.6)" />
      <circle cx={C} cy={C} r="80" fill="url(#ho-core)" />
      <rect x={C - 80} y={C - 80} width="160" height="160" fill="url(#ho-hex)" clipPath="url(#ho-clip)" />
      <circle cx={C} cy={C} r="80" fill="none" stroke="rgb(var(--ai) / 0.6)" filter="url(#ho-glow)" />
      <g filter="url(#ho-glow)">
        {blips.map((b, i) => (
          <circle key={i} cx={C + (95 + b.k * 85) * Math.cos(b.a)} cy={C + (95 + b.k * 85) * Math.sin(b.a)} r={2.2 + (i % 3)}
            fill={b.up ? "rgb(var(--bull))" : "rgb(var(--bear))"} className="xeno-blip" style={{ animationDelay: `${(i % 7) * 0.4}s` }} />
        ))}
      </g>
      <text x={C} y={C + 6} textAnchor="middle" fontSize="22" fontWeight="700" letterSpacing="3" fill="rgb(var(--text) / 0.9)">AI</text>
    </svg>
  );
}

/** Welcome page background: a planet's rim rising over a perspective grid that fades into space. */
export function CyberHorizon({ className = "" }: { className?: string }) {
  const W = 1200, H = 600, vy = 140;
  const verticals = Array.from({ length: 25 }, (_, i) => -600 + i * 100);
  const rows = Array.from({ length: 9 }, (_, i) => vy + Math.pow(i / 8, 1.8) * (H - vy));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid slice" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="hz-fade" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#fff" stopOpacity="0" /><stop offset="35%" stopColor="#fff" stopOpacity="0.9" /><stop offset="100%" stopColor="#fff" stopOpacity="0" /></linearGradient>
        <mask id="hz-mask"><rect x="0" y={vy} width={W} height={H - vy} fill="url(#hz-fade)" /></mask>
        <radialGradient id="hz-planet" cx="50%" cy="100%" r="60%"><stop offset="80%" stopColor="rgb(var(--ai) / 0.0)" /><stop offset="96%" stopColor="rgb(var(--ai) / 0.22)" /><stop offset="100%" stopColor="rgb(var(--ai) / 0)" /></radialGradient>
      </defs>
      <ellipse cx={W / 2} cy={vy + 700} rx="900" ry="700" fill="url(#hz-planet)" />
      <ellipse cx={W / 2} cy={vy + 700} rx="900" ry="700" fill="none" stroke="rgb(var(--ai) / 0.35)" strokeWidth="1.2" />
      <g mask="url(#hz-mask)" stroke="rgb(var(--ai) / 0.30)" strokeWidth="0.8">
        {verticals.map((x) => <line key={x} x1={W / 2 + (x + 600 - W / 2) * 0.25} y1={vy} x2={x + 600} y2={H} />)}
        {rows.map((y) => <line key={y} x1="0" x2={W} y1={y} y2={y} />)}
      </g>
      <line className="hz-scan" x1="0" x2={W} y1={vy} y2={vy} stroke="rgb(var(--accent) / 0.5)" strokeWidth="1" />
    </svg>
  );
}
