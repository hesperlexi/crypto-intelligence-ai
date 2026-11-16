// v2.47 (owner, 16 Nov 2026: "make the Radar page like a real radar"): a gold-phosphor radar scope of the scan's
// contacts (views/radar picks + extended; no extra data). Bitcoin sits in the centre; the further out a coin, the more it
// beat Bitcoin over 7 days; bearing is fixed per coin; blip size = volume surge. A rotating sweep with an afterglow
// lights each blip as it passes (CSS only: one rotating layer + one keyframe per blip, delay = its bearing).
import { useMemo, useState } from "react";
import { base, isNum } from "../lib/format";

const T = 6;                                    // seconds per sweep
const RINGS = [0.05, 0.15, 0.3, 0.5];           // outperformance vs BTC (7 days) at each range ring
const bearingOf = (s: string) => { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h % 360; };
const rangeOf = (rs: number) => Math.min(1, Math.sqrt(Math.max(0, rs) / 0.5));
const pct = (v: number) => `${v > 0 ? "+" : ""}${Math.round(v * 100)}%`;

type Contact = { symbol: string; rs: number; rs30: number | null; vol: number | null; ext: boolean; rank: number; brg: number; rng: number };

export default function RadarScope({ picks, extended, updated, onPick }: { picks: any[]; extended: any[]; updated?: number | null; onPick?: (s: string) => void }) {
  const [hover, setHover] = useState<string | null>(null);
  const contacts = useMemo<Contact[]>(() => [...picks.map((p) => ({ p, ext: false })), ...extended.map((p) => ({ p, ext: true }))]
    .filter(({ p }) => isNum(p.rs_7d))
    .map(({ p, ext }) => ({ symbol: p.symbol, rs: p.rs_7d, rs30: isNum(p.rs_30d) ? p.rs_30d : null, vol: isNum(p.vol_surge) ? p.vol_surge : null, ext, rank: p.rank ?? 99,
      brg: bearingOf(p.symbol), rng: rangeOf(p.rs_7d) })), [picks, extended]);
  const S = 400, C = S / 2, R = 160;
  const xy = (brg: number, rng: number) => { const a = (brg * Math.PI) / 180, r = 22 + rng * (R - 30); return [C + r * Math.sin(a), C - r * Math.cos(a)]; };
  return (
    <section className="panel panel-hero scope-panel p-4 sm:p-5" aria-label="Radar scope">
      <div className="grid items-center gap-5 lg:grid-cols-[minmax(0,440px)_minmax(0,1fr)]">
        <div className="scope" style={{ ["--sweep" as any]: `${T}s` }}>
          <div className="scope-sweep" aria-hidden="true" />
          <svg viewBox={`0 0 ${S} ${S}`} className="relative w-full" role="img" aria-label={`Radar: ${contacts.length} coins beating Bitcoin; further out = beat it by more over 7 days`}>
            <defs>
              <radialGradient id="sc-bg"><stop offset="0%" stopColor="rgb(var(--accent) / 0.10)" /><stop offset="100%" stopColor="rgb(var(--accent) / 0.02)" /></radialGradient>
            </defs>
            <circle cx={C} cy={C} r={R} fill="url(#sc-bg)" stroke="rgb(var(--accent) / 0.55)" strokeWidth="1.5" />
            {Array.from({ length: 120 }, (_, i) => {
              const a = (i * 3 * Math.PI) / 180, major = i % 10 === 0, mid = i % 5 === 0;
              const r1 = R + 2, r2 = R + (major ? 12 : mid ? 8 : 5);
              return <line key={i} x1={C + r1 * Math.sin(a)} y1={C - r1 * Math.cos(a)} x2={C + r2 * Math.sin(a)} y2={C - r2 * Math.cos(a)} stroke={`rgb(var(--accent) / ${major ? 0.7 : 0.3})`} />;
            })}
            {[0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330].map((d) => {
              const a = (d * Math.PI) / 180;
              return <text key={d} x={C + (R + 22) * Math.sin(a)} y={C - (R + 22) * Math.cos(a) + 4} textAnchor="middle" fontSize="11" fill="rgb(var(--accent) / 0.75)" className="num">{String(d).padStart(3, "0")}</text>;
            })}
            {RINGS.map((v) => {
              const r = 22 + rangeOf(v) * (R - 30);
              return (
                <g key={v}>
                  <circle cx={C} cy={C} r={r} fill="none" stroke="rgb(var(--accent) / 0.22)" strokeDasharray="2 5" />
                  <text x={C + 4} y={C - r - 3} fontSize="11" fill="rgb(var(--accent) / 0.8)">{pct(v)}</text>
                </g>
              );
            })}
            <line x1={C - R} y1={C} x2={C + R} y2={C} stroke="rgb(var(--accent) / 0.14)" />
            <line x1={C} y1={C - R} x2={C} y2={C + R} stroke="rgb(var(--accent) / 0.14)" />
            <circle cx={C} cy={C} r="9" fill="url(#cc-gold-scope)" />
            <defs><radialGradient id="cc-gold-scope" cx="35%" cy="30%"><stop offset="0%" stopColor="#fff1c4" /><stop offset="50%" stopColor="#f0b90b" /><stop offset="100%" stopColor="#6b4c06" /></radialGradient></defs>
            <text x={C} y={C + 24} textAnchor="middle" fontSize="11" fontWeight="700" fill="rgb(var(--accent))">BTC</text>
            {contacts.map((c) => {
              const [x, y] = xy(c.brg, c.rng);
              const size = 4 + Math.min(5, (c.vol ?? 1) * 1.2);
              const on = hover === c.symbol;
              return (
                <g key={c.symbol} className="scope-blip" style={{ animationDelay: `${(c.brg / 360) * T}s` }} tabIndex={0} role="button"
                  aria-label={`${base(c.symbol)}: ${pct(c.rs)} vs Bitcoin over 7 days${c.ext ? ", already extended" : ""}`}
                  onMouseEnter={() => setHover(c.symbol)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(c.symbol)} onBlur={() => setHover(null)}
                  onClick={() => onPick?.(c.symbol)} onKeyDown={(e) => { if (e.key === "Enter") onPick?.(c.symbol); }}>
                  <circle cx={x} cy={y} r={size + 7} fill={c.ext ? "rgb(var(--warn) / 0.2)" : "rgb(var(--accent) / 0.22)"} />
                  <circle cx={x} cy={y} r={size} fill={c.ext ? "rgb(var(--warn))" : "#ffd65c"} />
                  {on && <circle cx={x} cy={y} r={size + 12} fill="none" stroke="#fff1c4" strokeWidth="1.5" />}
                  <text x={x + size + 6} y={y + 4} fontSize="12" fontWeight="700" fill="rgb(var(--text))" className="rd-label">{base(c.symbol)}</text>
                </g>
              );
            })}
            {!contacts.length && <text x={C} y={C + 52} textAnchor="middle" fontSize="13" fill="rgb(var(--mute))">No contacts on this scan</text>}
          </svg>
        </div>
        <div className="min-w-0 space-y-3">
          <div className="scope-readout">
            <div><span className="text-mute">CONTACTS</span><b className="num">{contacts.length}</b></div>
            <div><span className="text-mute">SWEEP</span><b className="num">{T}s</b></div>
            <div><span className="text-mute">LAST SCAN</span><b className="num">{updated ? new Date(updated).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : "—"}</b></div>
          </div>
          <ul className="space-y-1.5">
            {[...contacts].sort((a, b) => b.rs - a.rs).slice(0, 8).map((c) => (
              <li key={c.symbol}>
                <button type="button" className={`scope-row ${hover === c.symbol ? "is-on" : ""}`} onMouseEnter={() => setHover(c.symbol)} onMouseLeave={() => setHover(null)} onClick={() => onPick?.(c.symbol)}>
                  <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${c.ext ? "bg-warn" : "bg-accent"}`} />
                  <b className="w-16 text-left">{base(c.symbol)}</b>
                  <span className="num flex-1 text-left text-xs text-mute">BRG {String(c.brg).padStart(3, "0")}° · VOL {c.vol ? `${c.vol.toFixed(1)}x` : "—"}{c.rs30 != null ? ` · 30d ${pct(c.rs30)}` : ""}</span>
                  <span className="num text-sm font-semibold text-bull">{pct(c.rs)}</span>
                </button>
              </li>
            ))}
          </ul>
          <p className="text-xs text-mute">Centre = Bitcoin. Further out = beat Bitcoin by more over 7 days. Gold = new pick, amber = already extended (wait for a pullback). Bigger dot = volume surge.</p>
        </div>
      </div>
    </section>
  );
}
