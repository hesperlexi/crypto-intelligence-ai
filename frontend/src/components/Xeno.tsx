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
export function HoloOrbit({ className = "", label = true }: { className?: string; label?: boolean }) {
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
      {label && <text x={C} y={C + 6} textAnchor="middle" fontSize="22" fontWeight="700" letterSpacing="3" fill="rgb(var(--text) / 0.9)">AI</text>}
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

/** A small orbiting glyph beside page titles: a core with one satellite. */
export function AiGlyph({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className="ai-glyph" aria-hidden="true">
      <circle cx="12" cy="12" r="10" fill="none" stroke="rgb(var(--ai) / 0.35)" strokeDasharray="1.5 2.5" />
      <circle cx="12" cy="12" r="3.4" fill="rgb(var(--ai) / 0.9)" className="ai-glyph-core" />
      <g className="ai-glyph-orbit" style={{ transformOrigin: "12px 12px" }}><circle cx="22" cy="12" r="1.8" fill="rgb(var(--accent))" /></g>
    </svg>
  );
}

/** Welcome page: the watchlist as a constellation the AI watches, with pulses running along the links. */
export function Constellation({ className = "" }: { className?: string }) {
  const nodes = useMemo(() => {
    const r = rng(23);
    const names = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "AVAX", "LINK", "ADA", "SUI", "LTC", "DOT", "NEAR", "AAVE"];
    return names.map((n, i) => ({ n, x: 40 + r() * 520, y: 30 + r() * 220, up: r() > 0.4, big: i < 4 }));
  }, []);
  const links = useMemo(() => {
    const out: [number, number][] = [];
    nodes.forEach((a, i) => {
      const near = nodes.map((b, j) => ({ j, d: Math.hypot(a.x - b.x, a.y - b.y) })).filter((x) => x.j !== i).sort((p, q) => p.d - q.d).slice(0, 2);
      near.forEach(({ j }) => { if (!out.some(([p, q]) => (p === j && q === i))) out.push([i, j]); });
    });
    return out;
  }, [nodes]);
  return (
    <svg viewBox="0 0 600 280" className={className} role="img" aria-label="The AI watches every coin and how they move together">
      <defs>
        <filter id="cn-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.4" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      </defs>
      {links.map(([i, j], k) => {
        const a = nodes[i], b = nodes[j];
        return (
          <g key={k}>
            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="rgb(var(--ai) / 0.22)" />
            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="rgb(var(--ai) / 0.9)" strokeWidth="1.4" strokeDasharray="6 400" className="cn-pulse" style={{ animationDelay: `${(k % 9) * 0.55}s` }} />
          </g>
        );
      })}
      <g filter="url(#cn-glow)">
        {nodes.map((p) => (
          <g key={p.n}>
            <circle cx={p.x} cy={p.y} r={p.big ? 6 : 4} fill={p.up ? "rgb(var(--bull))" : "rgb(var(--bear))"} className="xeno-blip" />
            <circle cx={p.x} cy={p.y} r={p.big ? 11 : 8} fill="none" stroke="rgb(var(--ai) / 0.35)" />
          </g>
        ))}
      </g>
      {nodes.map((p) => <text key={p.n} x={p.x} y={p.y - (p.big ? 15 : 12)} textAnchor="middle" fontSize="10" fill="rgb(var(--text) / 0.75)" letterSpacing="0.5">{p.n}</text>)}
    </svg>
  );
}

/** A thin "signal" divider: an oscilloscope wave with a travelling glint. */
export function SignalWave({ className = "" }: { className?: string }) {
  const d = useMemo(() => {
    let p = "M0 20";
    for (let x = 0; x <= 1200; x += 10) p += ` L${x} ${(20 + Math.sin(x / 38) * 7 * Math.sin(x / 260) + (x % 170 < 10 ? -9 : 0)).toFixed(1)}`;
    return p;
  }, []);
  return (
    <svg viewBox="0 0 1200 40" preserveAspectRatio="none" className={className} aria-hidden="true">
      <path d={d} fill="none" stroke="rgb(var(--ai) / 0.28)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      <path d={d} fill="none" stroke="rgb(var(--accent) / 0.9)" strokeWidth="1.6" vectorEffect="non-scaling-stroke" strokeDasharray="60 1400" className="wave-glint" />
    </svg>
  );
}

/* ---------------------------------------------------------------- bots: the fleet */
export type FleetBot = { id: string; name: string; tf: string; ret: number; open: number; enabled: boolean; futures: boolean };
const FLEET_TFS = ["15m", "1h", "4h", "12h", "1d", "3d"];

/** A small alien drone: a saucer with a glowing eye (green running / grey paused). */
export function BotDrone({ on = true, size = 26, tone = "ai" }: { on?: boolean; size?: number; tone?: "ai" | "bull" | "bear" }) {
  const c = `rgb(var(--${tone}))`;
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className={on ? "bot-drone" : ""}>
      <ellipse cx="16" cy="19" rx="13" ry="4.2" fill="rgb(var(--raised))" stroke={c} strokeOpacity="0.7" />
      <path d="M8 18.5c0-5 3.6-9 8-9s8 4 8 9" fill="rgb(var(--panel))" stroke={c} strokeOpacity="0.8" />
      <circle cx="16" cy="14.5" r="2.6" fill={on ? c : "rgb(var(--mute))"} className={on ? "xeno-blip" : ""} />
      {[8, 16, 24].map((x) => <circle key={x} cx={x} cy="19.4" r="1" fill={on ? "rgb(var(--accent))" : "rgb(var(--mute))"} />)}
      {on && <path d="M12 23.5 10 29M20 23.5 22 29" stroke={c} strokeOpacity="0.35" strokeWidth="2" strokeLinecap="round" />}
    </svg>
  );
}

/** Every bot as a craft orbiting the AI core: ring = timeframe, colour = return, satellites = open positions. */
export function FleetOrbit({ bots }: { bots: FleetBot[] }) {
  const [hover, setHover] = useState<FleetBot | null>(null);
  const rings = FLEET_TFS.filter((t) => bots.some((b) => b.tf === t));
  const C = 210, R0 = 62, R1 = 186;
  const ringR = (tf: string) => (rings.length <= 1 ? (R0 + R1) / 2 : R0 + ((R1 - R0) * rings.indexOf(tf)) / (rings.length - 1));
  const placed = bots.map((b) => {
    const same = bots.filter((x) => x.tf === b.tf);
    const k = same.indexOf(b);
    const a = -Math.PI / 2 + (rings.indexOf(b.tf) * 0.9) + (2 * Math.PI * k) / Math.max(1, same.length);
    return { b, a, r: ringR(b.tf) };
  });
  return (
    <figure className="mx-auto w-full max-w-[460px]">
      <svg viewBox="0 0 420 420" className="w-full" role="img" aria-label={`${bots.length} demo bots around the AI core`}>
        <defs>
          <radialGradient id="fl-core"><stop offset="0%" stopColor="rgb(var(--ai) / 0.65)" /><stop offset="45%" stopColor="rgb(var(--ai) / 0.15)" /><stop offset="100%" stopColor="rgb(var(--ai) / 0)" /></radialGradient>
          <linearGradient id="fl-sw" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stopColor="rgb(var(--ai) / 0)" /><stop offset="100%" stopColor="rgb(var(--ai) / 0.22)" /></linearGradient>
        </defs>
        <circle cx={C} cy={C} r="205" fill="url(#fl-core)" opacity="0.5" />
        {rings.map((t, i) => (
          <g key={t}>
            <circle cx={C} cy={C} r={ringR(t)} fill="none" stroke="rgb(var(--ai) / 0.22)" strokeDasharray={i % 2 ? "2 6" : "1 3"} />
            <text x={C} y={C - ringR(t) - 3} textAnchor="middle" fontSize="9" fill="rgb(var(--mute))">{t.toUpperCase()}</text>
          </g>
        ))}
        <g className="xeno-sweep" style={{ transformOrigin: `${C}px ${C}px`, animationDuration: "10s" }}>
          <path d={`M${C} ${C} L${C + 200} ${C} A200 200 0 0 0 ${C + 200 * Math.cos(-0.4)} ${C + 200 * Math.sin(-0.4)} Z`} fill="url(#fl-sw)" />
        </g>
        {placed.map(({ b, a, r }) => (
          <g key={b.id}>
            <line x1={C} y1={C} x2={C + r * Math.cos(a)} y2={C + r * Math.sin(a)} stroke={b.ret >= 0 ? "rgb(var(--bull) / 0.18)" : "rgb(var(--bear) / 0.18)"} strokeDasharray="2 4" />
            <g transform={`translate(${C + r * Math.cos(a) - 17} ${C + r * Math.sin(a) - 17})`} onMouseEnter={() => setHover(b)} onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(b)} onBlur={() => setHover(null)} tabIndex={0} style={{ cursor: "default" }}>
              <BotDrone on={b.enabled} size={34} tone={b.ret > 0 ? "bull" : b.ret < 0 ? "bear" : "ai"} />
              {Array.from({ length: Math.min(4, b.open) }, (_, k) => (
                <circle key={k} cx={17 + 22 * Math.cos(k * 1.6)} cy={17 + 22 * Math.sin(k * 1.6)} r="2.4" fill="rgb(var(--accent))" className="xeno-blip" />
              ))}
              <title>{`${b.name}: ${b.ret >= 0 ? "+" : ""}${b.ret.toFixed(2)}% · ${b.open} open`}</title>
            </g>
          </g>
        ))}
        <circle cx={C} cy={C} r="34" fill="rgb(var(--panel) / 0.9)" stroke="rgb(var(--ai) / 0.6)" />
        <text x={C} y={C - 2} textAnchor="middle" fontSize="13" fontWeight="700" fill="rgb(var(--ai))">AI</text>
        <text x={C} y={C + 12} textAnchor="middle" fontSize="8" fill="rgb(var(--mute))">core</text>
      </svg>
      <figcaption className="h-5 text-center text-xs text-mute">
        {hover ? <><span className="font-semibold text-text">{hover.name}</span> · <span className={hover.ret >= 0 ? "text-bull" : "text-bear"}>{hover.ret >= 0 ? "+" : ""}{hover.ret.toFixed(2)}%</span> · {hover.open} open{hover.enabled ? "" : " · paused"}</>
          : "Point at a bot"}
      </figcaption>
    </figure>
  );
}

/** All bots' equity as % return, on one oscilloscope. */
export function FleetPulse({ curves }: { curves: { name: string; pts: { ts: number; v: number }[] }[] }) {
  const all = curves.flatMap((c) => c.pts);
  if (all.length < 2) return <p className="text-sm text-mute">Not enough history yet.</p>;
  const W = 600, H = 200, P = 8;
  const t0 = Math.min(...all.map((p) => p.ts)), t1 = Math.max(...all.map((p) => p.ts)) || t0 + 1;
  const lo = Math.min(0, ...all.map((p) => p.v)), hi = Math.max(0, ...all.map((p) => p.v)), span = hi - lo || 1;
  const x = (t: number) => P + ((W - 2 * P) * (t - t0)) / (t1 - t0 || 1);
  const y = (v: number) => P + (H - 2 * P) * (1 - (v - lo) / span);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Return of every bot over time">
      <defs>
        <pattern id="fp-grid" width="30" height="20" patternUnits="userSpaceOnUse"><path d="M30 0H0V20" fill="none" stroke="rgb(var(--ai) / 0.10)" /></pattern>
      </defs>
      <rect width={W} height={H} fill="url(#fp-grid)" rx="8" />
      <line x1={P} x2={W - P} y1={y(0)} y2={y(0)} stroke="rgb(var(--mute) / 0.5)" strokeDasharray="3 4" />
      <g>
        {curves.map((c) => {
          if (c.pts.length < 2) return null;
          const last = c.pts[c.pts.length - 1].v;
          const d = c.pts.map((p, i) => `${i ? "L" : "M"}${x(p.ts).toFixed(1)} ${y(p.v).toFixed(1)}`).join(" ");
          return <path key={c.name} d={d} fill="none" stroke={last >= 0 ? "rgb(var(--bull) / 0.85)" : "rgb(var(--bear) / 0.85)"} strokeWidth="1.6"><title>{`${c.name}: ${last >= 0 ? "+" : ""}${last.toFixed(2)}%`}</title></path>;
        })}
      </g>
      <text x={W - P} y={y(hi) + 10} textAnchor="end" fontSize="10" fill="rgb(var(--mute))">{`+${hi.toFixed(1)}%`}</text>
      <text x={W - P} y={y(lo) - 4} textAnchor="end" fontSize="10" fill="rgb(var(--mute))">{`${lo.toFixed(1)}%`}</text>
    </svg>
  );
}

/* ---------------------------------------------------------------- Hesper: the mission */
/** The run as a voyage: a craft travelling a curved route from the start to the 10x world, on a log scale; a black hole
 *  (liquidation) waits below. */
export function Mission({ start, goal, balance, reached }: { start: number; goal: number; balance: number | null; reached?: boolean }) {
  const W = 640, H = 230;
  const L = Math.log;
  const p = balance && balance > 0 ? Math.max(-0.35, Math.min(1.15, (L(balance) - L(start)) / (L(goal) - L(start)))) : 0;
  const bez = (t: number) => {          // quadratic curve from (60,170) via (320,10) to (580,80)
    const x0 = 60, y0 = 170, cx = 320, cy = 10, x1 = 580, y1 = 80;
    return [(1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1, (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1];
  };
  const tPos = Math.max(0, Math.min(1, p));
  const [sx, sy] = bez(tPos);
  const below = p < 0;
  const marks = [2, 5].map((m) => ({ m, t: L(m) / L(goal / start), xy: bez(L(m) / L(goal / start)) })).filter((x) => x.t < 1);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Run progress: ${balance ? (balance / start).toFixed(2) : "?"}x of ${(goal / start).toFixed(0)}x`}>
      <defs>
        <radialGradient id="ms-goal"><stop offset="0%" stopColor="rgb(var(--accent) / 0.95)" /><stop offset="55%" stopColor="rgb(var(--accent) / 0.35)" /><stop offset="100%" stopColor="rgb(var(--accent) / 0)" /></radialGradient>
        <radialGradient id="ms-home"><stop offset="0%" stopColor="rgb(var(--ai) / 0.9)" /><stop offset="60%" stopColor="rgb(var(--ai) / 0.25)" /><stop offset="100%" stopColor="rgb(var(--ai) / 0)" /></radialGradient>
        <radialGradient id="ms-hole"><stop offset="0%" stopColor="rgb(0 0 0 / 1)" /><stop offset="45%" stopColor="rgb(0 0 0 / 0.9)" /><stop offset="70%" stopColor="rgb(var(--bear) / 0.35)" /><stop offset="100%" stopColor="rgb(var(--bear) / 0)" /></radialGradient>
        <filter id="ms-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="3" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      </defs>
      <path d="M60 170 Q320 10 580 80" fill="none" stroke="rgb(var(--ai) / 0.25)" strokeDasharray="3 6" />
      <path d={`M60 170 Q320 10 580 80`} fill="none" stroke="rgb(var(--accent) / 0.85)" strokeWidth="2" filter="url(#ms-glow)"
        pathLength={1} strokeDasharray={`${tPos} 1`} />
      {/* black hole: liquidation */}
      <g className="ms-hole">
        <ellipse cx="120" cy="212" rx="60" ry="14" fill="url(#ms-hole)" />
        <ellipse cx="120" cy="212" rx="40" ry="8" fill="none" stroke="rgb(var(--bear) / 0.5)" strokeDasharray="2 4" />
      </g>
      <text x="120" y="229" textAnchor="middle" fontSize="9" fill="rgb(var(--bear) / 0.8)">liquidation</text>
      {/* home world */}
      <circle cx="60" cy="170" r="22" fill="url(#ms-home)" />
      <circle cx="60" cy="170" r="9" fill="rgb(var(--ai))" />
      <text x="60" y="203" textAnchor="middle" fontSize="10" fill="rgb(var(--mute))">{`$${Math.round(start).toLocaleString()}`}</text>
      {marks.map(({ m, xy }) => (
        <g key={m}><circle cx={xy[0]} cy={xy[1]} r="5" fill="rgb(var(--panel))" stroke="rgb(var(--ai) / 0.7)" /><text x={xy[0]} y={xy[1] - 10} textAnchor="middle" fontSize="10" fill="rgb(var(--mute))">{`${m}x`}</text></g>
      ))}
      {/* goal world */}
      <circle cx="580" cy="80" r="34" fill="url(#ms-goal)" className={reached ? "xeno-blink" : ""} />
      <circle cx="580" cy="80" r="14" fill="rgb(var(--accent))" />
      <ellipse cx="580" cy="80" rx="26" ry="6" fill="none" stroke="rgb(var(--accent) / 0.6)" transform="rotate(-18 580 80)" />
      <text x="580" y="128" textAnchor="middle" fontSize="11" fontWeight="600" fill="rgb(var(--accent))">{`$${Math.round(goal).toLocaleString()} · 10x`}</text>
      {/* the craft */}
      <g transform={`translate(${below ? 60 + (1 + p / 0.35) * 0 : sx} ${below ? 170 + (-p / 0.35) * 30 : sy})`} filter="url(#ms-glow)">
        <g className="ms-craft">
          <circle r="17" fill="none" stroke="rgb(var(--ai) / 0.7)" strokeDasharray="2 3" />
          <image href="/brand/logo-art-192.webp" x="-14" y="-14" width="28" height="28" />
          <circle r="14" fill="none" stroke={below ? "rgb(var(--bear))" : "rgb(var(--accent))"} strokeWidth="1.6" />
        </g>
      </g>
      <text x={W - 8} y="16" textAnchor="end" fontSize="11" fill="rgb(var(--mute))">{balance ? `${(balance / start).toFixed(2)}x of 10x` : ""}</text>
    </svg>
  );
}
