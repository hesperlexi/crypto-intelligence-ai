/* V3.0 Hesper Challenge journeys (owner picks, 24 Nov 2026; replace the space "Mission"):
   AscentJourney      main run  - concept A "Path to Superintelligence": seed -> 2x Learning -> 5x Reasoning ->
                      10x Superintelligence core; liquidation = the "Shutdown" grid below.
   SingularityJourney Last Stand - concept C "The Singularity": data lines converge on the 10x point; liquidation = the
                      "Null" void below.
   Progress is on a log scale (a $100 -> $30 drop and a $300 -> $900 climb at their true weight). Real balances only. */

const L = Math.log;
const money = (v: number) => `$${Math.round(v).toLocaleString()}`;

function prog(start: number, goal: number, balance: number | null) {
  return balance && balance > 0 ? Math.max(-0.35, Math.min(1.15, (L(balance) - L(start)) / (L(goal) - L(start)))) : 0;
}

/** fixed pseudo-random points (same picture every render) */
function rng(seed: number) { let s = seed; return () => { s = (s * 16807) % 2147483647; return s / 2147483647; }; }

function Craft({ x, y, label, bad }: { x: number; y: number; label: string; bad?: boolean }) {
  return (
    <g transform={`translate(${x} ${y})`}>
      <circle r="26" fill={`rgb(var(${bad ? "--bear" : "--accent"}) / 0.14)`} />
      <clipPath id="jr-clip"><circle r="15" /></clipPath>
      <image href="/brand/logo-art-192.webp" x="-15" y="-15" width="30" height="30" clipPath="url(#jr-clip)" />
      <circle r="15.5" fill="none" stroke={`rgb(var(${bad ? "--bear" : "--accent"}))`} strokeWidth="1.6" />
      <text y="-34" textAnchor="middle" fontSize="14" fontWeight="600" className="num" fill="rgb(var(--text))">{label}</text>
    </g>
  );
}

export function AscentJourney({ start, goal, balance, reached }: { start: number; goal: number; balance: number | null; reached?: boolean }) {
  const W = 1000, H = 300;
  const p = prog(start, goal, balance);
  const t = Math.max(0, Math.min(1, p));
  const P = (u: number): [number, number] => {
    const x0 = 80, y0 = 220, cx = 470, cy = -10, x1 = 880, y1 = 95;
    return [(1 - u) ** 2 * x0 + 2 * (1 - u) * u * cx + u * u * x1, (1 - u) ** 2 * y0 + 2 * (1 - u) * u * cy + u * u * y1];
  };
  const r = rng(7);
  const pts = Array.from({ length: 34 }, () => [r() * W, r() * 250]);
  const links: [number[], number[]][] = [];
  pts.forEach((a, i) => pts.forEach((b, j) => { if (j > i && Math.hypot(a[0] - b[0], a[1] - b[1]) < 110) links.push([a, b]); }));
  const mult = balance && start ? balance / start : null;
  const [cx, cy] = p < 0 ? [80 + (-p / 0.35) * 110, 220 + (-p / 0.35) * 60] : P(t);
  const stages: [number, string][] = [[2, "Learning"], [5, "Reasoning"]];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Run progress: ${mult ? mult.toFixed(2) : "?"}x of ${(goal / start).toFixed(0)}x`}>
      <defs>
        <linearGradient id="ja-path" x1="0" x2="1"><stop offset="0" stopColor="#9C7417" /><stop offset="1" stopColor="#F6E37A" /></linearGradient>
        <radialGradient id="ja-core"><stop offset="0" stopColor="#FFF6CC" /><stop offset=".3" stopColor="#F6E37A" /><stop offset=".65" stopColor="rgb(232 182 55 / .35)" /><stop offset="1" stopColor="rgb(232 182 55 / 0)" /></radialGradient>
        <radialGradient id="ja-seed"><stop offset="0" stopColor="rgb(var(--ai) / .9)" /><stop offset="1" stopColor="rgb(var(--ai) / 0)" /></radialGradient>
      </defs>
      {links.map(([a, b], i) => <line key={i} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="rgb(var(--ai) / 0.07)" />)}
      <path d="M80 220 Q470 -10 880 95" fill="none" stroke="rgb(var(--mute) / 0.35)" strokeDasharray="2 7" strokeWidth="1.5" />
      <path d="M80 220 Q470 -10 880 95" fill="none" stroke="url(#ja-path)" strokeWidth="3" pathLength={1} strokeDasharray={`${t} 1`} />
      {/* shutdown grid = liquidation */}
      {[0, 1, 2, 3, 4, 5].map((k) => <ellipse key={k} cx="220" cy="284" rx={90 - k * 14} ry={14 - k * 2} fill="none" stroke={`rgb(var(--bear) / ${0.08 + k * 0.07})`} />)}
      {[-4, -3, -2, -1, 0, 1, 2, 3, 4].map((k) => <line key={k} x1={220 + k * 22} y1={271 + Math.abs(k) * 1.5} x2={220 + k * 3} y2={286} stroke="rgb(var(--bear) / 0.25)" />)}
      <ellipse cx="220" cy="285" rx="16" ry="4" fill="rgb(var(--ink))" />
      <text x="330" y="289" fontSize="13" fill="rgb(var(--bear))">Shutdown · liquidation</text>
      <circle cx="80" cy="220" r="24" fill="url(#ja-seed)" /><circle cx="80" cy="220" r="7" fill="rgb(var(--ai))" />
      <text x="80" y="258" textAnchor="middle" fontSize="13" fill="rgb(var(--mute))">Seed · {money(start)}</text>
      {stages.map(([m, n]) => {
        const u = L(m) / L(goal / start);
        if (u >= 1) return null;
        const [x, y] = P(u);
        const done = u <= t;
        return (
          <g key={m}>
            <polygon points={`${x},${y - 9} ${x + 9},${y} ${x},${y + 9} ${x - 9},${y}`} fill={done ? "rgb(var(--accent))" : "rgb(var(--raised))"} stroke={done ? "#F6E37A" : "rgb(var(--ai))"} strokeWidth="1.4" />
            <text x={x} y={y + 30} textAnchor="middle" fontSize="13" className="num" fill="rgb(var(--text))">{m}x</text>
            <text x={x} y={y + 46} textAnchor="middle" fontSize="12" fill="rgb(var(--mute))">{n}</text>
          </g>
        );
      })}
      {Array.from({ length: 16 }, (_, k) => {
        const a = (k / 16) * Math.PI * 2, r2 = 54 + (k % 2) * 14;
        return <line key={k} x1={880 + Math.cos(a) * 28} y1={95 + Math.sin(a) * 28} x2={880 + Math.cos(a) * r2} y2={95 + Math.sin(a) * r2} stroke="rgb(246 227 122 / .35)" />;
      })}
      <circle cx="880" cy="95" r="66" fill="url(#ja-core)" className={reached ? "xeno-blink" : ""} />
      <polygon points="880,72 900,86 893,113 867,113 860,86" fill="#F6E37A" stroke="#FFF6CC" strokeWidth="1.2" />
      <text x="880" y="186" textAnchor="middle" fontSize="15" fontWeight="600" fill="rgb(var(--accent))">Superintelligence · {money(goal)} · {(goal / start).toFixed(0)}x</text>
      <Craft x={cx} y={cy} label={mult ? `${balance ? money(balance) : ""} · ${mult.toFixed(2)}x` : ""} bad={p < 0} />
    </svg>
  );
}

export function SingularityJourney({ start, goal, balance }: { start: number; goal: number; balance: number | null }) {
  const W = 1000, H = 300;
  const p = prog(start, goal, balance);
  const t = Math.max(0, Math.min(1, p));
  const r = rng(11);
  const cx = 860, cy = 115;
  const lines = Array.from({ length: 24 }, (_, k) => [20 + r() * 180, 10 + k * 12, 0.05 + r() * 0.12]);
  // the run's curve: (80,210) -> (840,115), cubic, sampled for marker placement
  const B = (u: number): [number, number] => {
    const p0 = [80, 210], p1 = [380, 210], p2 = [600, 115], p3 = [840, 115];
    const m = 1 - u;
    return [m ** 3 * p0[0] + 3 * m * m * u * p1[0] + 3 * m * u * u * p2[0] + u ** 3 * p3[0], m ** 3 * p0[1] + 3 * m * m * u * p1[1] + 3 * m * u * u * p2[1] + u ** 3 * p3[1]];
  };
  const mult = balance && start ? balance / start : null;
  const [x, y] = p < 0 ? [80 + (-p / 0.35) * 160, 210 + (-p / 0.35) * 60] : B(t);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Last Stand: ${mult ? mult.toFixed(2) : "?"}x of the start`}>
      <defs>
        <radialGradient id="js-core"><stop offset="0" stopColor="#FFF6CC" /><stop offset=".3" stopColor="#F6E37A" /><stop offset=".65" stopColor="rgb(232 182 55 / .35)" /><stop offset="1" stopColor="rgb(232 182 55 / 0)" /></radialGradient>
        <radialGradient id="js-void"><stop offset="0" stopColor="rgb(var(--ink))" /><stop offset=".55" stopColor="rgb(var(--ink))" /><stop offset=".78" stopColor="rgb(var(--bear) / .35)" /><stop offset="1" stopColor="rgb(var(--bear) / 0)" /></radialGradient>
        <linearGradient id="js-path" x1="0" x2="1"><stop offset="0" stopColor="#9C7417" /><stop offset="1" stopColor="#F6E37A" /></linearGradient>
      </defs>
      {lines.map(([x0, y0, o], k) => <path key={k} d={`M${x0} ${y0} C 500 ${y0}, 700 ${cy + (y0 - cy) * 0.25}, ${cx} ${cy}`} fill="none" stroke={`rgb(var(--ai) / ${o})`} />)}
      {[0, 1, 2, 3, 4].map((k) => <circle key={k} cx={cx} cy={cy} r={40 + k * 26} fill="none" stroke={`rgb(232 182 55 / ${0.22 - k * 0.04})`} />)}
      <circle cx={cx} cy={cy} r="80" fill="url(#js-core)" /><circle cx={cx} cy={cy} r="9" fill="#FFF6CC" />
      <text x={cx} y={cy + 118} textAnchor="middle" fontSize="15" fontWeight="600" fill="rgb(var(--accent))">The Singularity · {money(goal)} · {(goal / start).toFixed(0)}x</text>
      <path d="M80 210 C 380 210, 600 115, 840 115" fill="none" stroke="rgb(var(--mute) / 0.35)" strokeDasharray="2 7" strokeWidth="1.5" />
      <path d="M80 210 C 380 210, 600 115, 840 115" fill="none" stroke="url(#js-path)" strokeWidth="3" pathLength={1} strokeDasharray={`${t} 1`} />
      <circle cx="80" cy="210" r="22" fill="rgb(var(--ai) / .25)" /><circle cx="80" cy="210" r="7" fill="rgb(var(--ai))" />
      <text x="80" y="248" textAnchor="middle" fontSize="13" fill="rgb(var(--mute))">{money(start)}</text>
      {[2, 5].map((m) => {
        const u = L(m) / L(goal / start);
        if (u >= 1) return null;
        const [mx, my] = B(u);
        return <g key={m}><circle cx={mx} cy={my} r="6" fill={u <= t ? "rgb(var(--accent))" : "rgb(var(--raised))"} stroke="rgb(var(--ai))" />
          <text x={mx} y={my + 26} textAnchor="middle" fontSize="13" className="num" fill="rgb(var(--mute))">{m}x</text></g>;
      })}
      <ellipse cx="300" cy="282" rx="110" ry="22" fill="url(#js-void)" />
      {[0, 1, 2].map((k) => <ellipse key={k} cx="300" cy="282" rx={80 - k * 22} ry={13 - k * 3.5} fill="none" stroke="rgb(var(--bear) / .4)" strokeDasharray="2 4" />)}
      <text x="430" y="287" fontSize="13" fill="rgb(var(--bear))">Null · liquidation</text>
      <Craft x={x} y={y} label={mult ? `${balance ? money(balance) : ""} · ${mult.toFixed(2)}x` : ""} bad={p < 0} />
    </svg>
  );
}
