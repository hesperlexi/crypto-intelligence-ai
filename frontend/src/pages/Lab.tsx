// v2.25 Performance Lab (admin): what works and what does not, from the live record (net R after fees).
// Data: views/perf_lab (backend services/perf_lab.py, every 2 h, admin only in the rules). Display only.
// Look: an "observatory" - every closed call is a glowing body orbiting on its timeframe's ring, the equity curve is a
// pulse on an oscilloscope grid, the R distribution a spectrum, weekday x session a hex hive. Colours from theme tokens.
import { PnlGradients } from "../components/PnlGradients";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, PageHeader, Segmented, Tile } from "../components/kit";
import { Empty, ErrorBox } from "../components/ui";
import { useApi } from "../lib/api";
import { ago, isNum } from "../lib/format";
import { FastStrategyCard, MarketRegimeCard, MlShadowCard, OpportunityCheckCard, PortfolioCard, RegimeCard } from "../components/LabRisk";

type St = { n: number; win_rate?: number; avg_r?: number; total_r?: number; profit_factor?: number | null; max_dd_r?: number; best_r?: number; worst_r?: number };
type Grp = St & { key: string };
type Dot = { t: number; tf: string; side: string; r: number; coin: string; g: string; a: number };

const TFS = ["15m", "1h", "4h", "12h", "1d", "3d"];
const r2 = (v: unknown, d = 2) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}R` : "—");
const pc = (v: unknown) => (isNum(v) ? `${Math.round(v * 100)}%` : "—");
const tn = (v: unknown) => (isNum(v) ? (v > 0.0001 ? "text-bull" : v < -0.0001 ? "text-bear" : "") : "text-mute");
const col = (v: number, a = 1) => `rgb(var(${v >= 0 ? "--bull" : "--bear"}) / ${a})`;

export default function Lab() {
  const q = useApi<any>("/perf-lab");
  const v = q.data;
  return (
    <div className="xeno space-y-4">
      <PageHeader title="Performance Lab" sub={v ? `Net R after fees · since ${v.since ? new Date(v.since).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "the restart"} · updated ${ago(v.generated_at)}` : undefined} />
      {q.error && !v && <ErrorBox error={q.error} retry={q.reload} />}
      {!v && !q.error && <div className="skeleton h-96 rounded-xl" />}
      {v && (!v.overall?.n ? <Empty>No closed calls yet.</Empty> : <LabBody v={v} />)}
    </div>
  );
}

function LabBody({ v }: { v: any }) {
  const o: St = v.overall;
  return (
    <>
      <section className="xeno-panel grid gap-4 p-4 lg:grid-cols-[minmax(0,420px)_1fr] lg:items-center">
        <ResultStrip dots={v.dots ?? []} total={o.total_r} />
        <div className="space-y-3">
          <div className="metric-strip">
            <Tile variant="strip" label="Closed calls" value={String(o.n)} sub={`${v.open} running · ${v.missed} not filled`} />
            <Tile variant="strip" label="Win rate" value={pc(o.win_rate)} sub={`avg ${r2(o.avg_r, 3)}`} />
            <Tile variant="strip" label="Profit factor" value={isNum(o.profit_factor) ? o.profit_factor.toFixed(2) : "—"} sub={`best ${r2(o.best_r)} · worst ${r2(o.worst_r)}`} />
            <Tile variant="strip" label="Max drawdown" value={r2(-(o.max_dd_r ?? 0))} valueClass="text-bear" sub={`streaks: ${v.streaks?.wins ?? 0} wins · ${v.streaks?.losses ?? 0} losses`} />
          </div>
          <AdminEffect v={v} />
          <p className="text-xs text-mute">Each dot is one closed call at its result in R (after costs), one row per timeframe; an outlined dot was changed by the admin.</p>
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="xeno-panel p-4"><h2 className="label mb-2">Equity in R</h2><Pulse curve={v.curve ?? []} /></section>
        <section className="xeno-panel p-4"><h2 className="label mb-2">Result spread · per call</h2><Spectrum bins={v.histogram ?? []} /></section>
      </div>

      <Splits v={v} />

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="xeno-panel p-4"><h2 className="label mb-2">Weekday heat · weekday × session (UTC)</h2><HeatGrid heat={v.heat ?? []} /></section>
        <section className="xeno-panel space-y-3 p-4">
          <h2 className="label">Notable calls</h2>
          <Specimen k="Losers that were in profit first" v={`${v.losers?.reached_profit?.["0.5"] ?? 0} of ${v.losers?.n ?? 0} reached +0.5R · ${v.losers?.reached_profit?.["1.0"] ?? 0} reached +1R`} />
          <Specimen k="Hold time" v={isNum(v.hold_h?.median) ? `median ${v.hold_h.median} h · longest ${v.hold_h.max} h` : "—"} />
          <Specimen k="How calls ended" v={Object.entries(v.exits ?? {}).map(([k, n]) => `${k === "None" ? "other" : k.replace(/_/g, " ")} ${n}`).join(" · ") || "—"} />
          {v.proof?.rejected && (
            <Specimen k="Filters' blocked calls" v={<>{v.proof.rejected.n ?? 0} blocked · would have made <span className={tn(v.proof.rejected.total_r)}>{r2(v.proof.rejected.total_r)}</span>{v.proof.rejected.verdict ? ` · ${v.proof.rejected.verdict}` : ""} · <Link to="/guardian" className="text-accent hover:underline">details</Link></>} />
          )}
          {(v.proof?.calibration?.warnings ?? []).map((w: string) => <p key={w} className="text-sm text-bear">{w}</p>)}
        </section>
      </div>

      {/* V3.3 Stage 2: portfolio risk, results by market regime, AI filters in shadow */}
      <div className="grid gap-4 lg:grid-cols-2">
        <PortfolioCard p={v.portfolio} />
        <RegimeCard rows={v.by_regime ?? []} />
      </div>
      <MlShadowCard m={v.ml_shadow} />
      {/* V3.4 Stage 3 / 4: market regime split, setup checklist check, the isolated fast strategy */}
      <div className="grid gap-4 lg:grid-cols-2">
        <MarketRegimeCard rows={v.by_market_regime ?? []} />
        <OpportunityCheckCard c={v.opportunity_check} />
      </div>
      <FastStrategyCard f={v.fast_strategy} />
    </>
  );
}

function Specimen({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="border-l-2 border-ai/50 pl-3"><div className="text-xs text-mute">{k}</div><div className="text-sm">{v}</div></div>;
}

function AdminEffect({ v }: { v: any }) {
  const a = v.no_admin as St, s = v.overall as St;
  if (!v.admin?.touched) return <p className="text-xs text-mute">No admin changes to any call: the record is exactly the engine's rules.</p>;
  return (
    <div className="rounded-xl border border-ai/30 bg-ai/[0.06] px-3 py-2 text-sm">
      <span className="text-mute">Admin decisions touched {v.admin.touched} calls. </span>
      As stored <span className={`num font-semibold ${tn(s.total_r)}`}>{r2(s.total_r)}</span> · engine rules only{" "}
      <span className={`num font-semibold ${tn(a.total_r)}`}>{r2(a.total_r)}</span>
      <span className="text-mute"> ({a.n} closed)</span>
    </div>
  );
}

/* ---------------------------------------------------------------- orbit */
function Orbit({ dots, total, win }: { dots: Dot[]; total?: number; win?: number }) {
  const [hover, setHover] = useState<Dot | null>(null);
  const rings = TFS.filter((t) => dots.some((d) => d.tf === t));
  const R0 = 72, R1 = 170;
  const ringR = (tf: string) => (rings.length <= 1 ? (R0 + R1) / 2 : R0 + ((R1 - R0) * rings.indexOf(tf)) / (rings.length - 1));
  const pts = useMemo(() => dots.map((d, i) => {
    const ang = -Math.PI / 2 + (2 * Math.PI * (i + 0.5)) / Math.max(1, dots.length);
    const rr = ringR(d.tf) + Math.max(-1.5, Math.min(3, d.r)) * 5;
    return { d, x: 200 + rr * Math.cos(ang), y: 200 + rr * Math.sin(ang), s: 2.2 + Math.min(3, Math.abs(d.r)) * 1.6 };
  }), [dots, rings.join(",")]);
  return (
    <figure className="relative mx-auto w-full max-w-[420px]">
      <svg viewBox="0 0 400 400" className="w-full" role="img" aria-label={`Calls map of ${dots.length} closed calls, total ${r2(total)}`}>
        <defs>
          <filter id="xglow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.4" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
          <radialGradient id="xcore"><stop offset="0%" stopColor="rgb(var(--ai) / 0.35)" /><stop offset="60%" stopColor="rgb(var(--ai) / 0.08)" /><stop offset="100%" stopColor="rgb(var(--ai) / 0)" /></radialGradient>
          <linearGradient id="xsweep" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stopColor="rgb(var(--ai) / 0)" /><stop offset="100%" stopColor="rgb(var(--ai) / 0.28)" /></linearGradient>
        </defs>
        <circle cx="200" cy="200" r="190" fill="url(#xcore)" />
        {rings.map((t, i) => (
          <g key={t}>
            <circle cx="200" cy="200" r={ringR(t)} fill="none" stroke="rgb(var(--ai) / 0.22)" strokeDasharray={i % 2 ? "2 5" : "1 3"} />
            <text x="200" y={200 - ringR(t) - 4} textAnchor="middle" className="fill-mute" fontSize="9" letterSpacing="1">{t.toUpperCase()}</text>
          </g>
        ))}
        <g className="xeno-sweep" style={{ transformOrigin: "200px 200px" }}>
          <path d="M200 200 L390 200 A190 190 0 0 0 383 150 Z" fill="url(#xsweep)" />
          <line x1="200" y1="200" x2="390" y2="200" stroke="rgb(var(--ai) / 0.55)" strokeWidth="1" />
        </g>
        <g filter="url(#xglow)">
          {pts.map(({ d, x, y, s }, i) => (
            <circle key={i} cx={x} cy={y} r={s} fill={col(d.r, 0.9)} stroke={d.a ? "rgb(var(--warn))" : "none"} strokeWidth={d.a ? 1.2 : 0}
              onMouseEnter={() => setHover(d)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(d)} onBlur={() => setHover(null)} tabIndex={0}>
              <title>{`${d.coin} ${d.tf} ${d.side === "L" ? "long" : "short"} ${r2(d.r)}`}</title>
            </circle>
          ))}
        </g>
        <circle cx="200" cy="200" r="44" fill="rgb(var(--panel) / 0.85)" stroke="rgb(var(--ai) / 0.45)" />
        <text x="200" y="198" textAnchor="middle" fontSize="22" fontWeight="700" fill={isNum(total) ? col(total) : "currentColor"} className="num">{r2(total, 1)}</text>
        <text x="200" y="216" textAnchor="middle" fontSize="10" className="fill-mute">{pc(win)} wins</text>
      </svg>
      <figcaption className="h-5 text-center text-xs text-mute">
        {hover ? <span><span className="font-semibold text-text">{hover.coin}</span> {hover.tf.toUpperCase()} {hover.side === "L" ? "long" : "short"} · grade {hover.g} · <span className={tn(hover.r)}>{r2(hover.r)}</span>{hover.a ? " · admin changed" : ""}</span> : "Point at a dot"}
      </figcaption>
    </figure>
  );
}

/* ---------------------------------------------------------------- pulse */
function Pulse({ curve }: { curve: { t: number; r: number; dd: number }[] }) {
  if (curve.length < 2) return <p className="text-sm text-mute">Needs two closed calls.</p>;
  const W = 600, H = 220, P = 8;
  const ys = curve.map((c) => c.r);
  const lo = Math.min(0, ...ys), hi = Math.max(0, ...ys);
  const span = hi - lo || 1;
  const x = (i: number) => P + ((W - 2 * P) * i) / (curve.length - 1);
  const y = (r: number) => P + (H - 2 * P) * (1 - (r - lo) / span);
  const line = curve.map((c, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(c.r).toFixed(1)}`).join(" ");
  const last = curve[curve.length - 1].r;
  const maxDd = Math.max(...curve.map((c) => c.dd)) || 1;
  return (
    <svg viewBox={`0 0 ${W} ${H + 40}`} className="fp-live w-full" role="img" aria-label={`Equity ${r2(last)}`}>
      <defs>
        <PnlGradients id="pl" y0={y(0)} top={P} bottom={H - P} />
        <pattern id="pgrid" width="30" height="22" patternUnits="userSpaceOnUse"><path d="M30 0H0V22" fill="none" stroke="rgb(var(--ai) / 0.10)" /></pattern>
      </defs>
      <rect x="0" y="0" width={W} height={H} fill="url(#pgrid)" rx="8" />
      <line x1={P} x2={W - P} y1={y(0)} y2={y(0)} stroke="rgb(var(--mute) / 0.5)" strokeDasharray="3 4" />
      <path d={`${line} L${x(curve.length - 1)} ${y(0)} L${x(0)} ${y(0)} Z`} fill="url(#pl-f)" />
      <path d={line} className="fp-line" pathLength={1} fill="none" stroke="url(#pl-s)" strokeWidth="2.4" strokeLinejoin="round" />
      <circle cx={x(curve.length - 1)} cy={y(last)} r="8" fill={col(last, 0.22)} />
      <circle cx={x(curve.length - 1)} cy={y(last)} r="4" fill={col(last)} className="xeno-blink" />
      {curve.map((c, i) => c.dd > 0 && <rect key={i} x={x(i) - 1} width="2" y={H + 8} height={(c.dd / maxDd) * 28} fill="rgb(var(--bear) / 0.55)" />)}
      <text x={W - P} y={H + 36} textAnchor="end" fontSize="10" className="fill-mute">drawdown below · deepest {r2(-maxDd)}</text>
    </svg>
  );
}

/* ---------------------------------------------------------------- spectrum */
function Spectrum({ bins }: { bins: { lo: number | null; hi: number | null; n: number }[] }) {
  const max = Math.max(1, ...bins.map((b) => b.n));
  const lab = (b: any) => (b.lo == null ? `<${b.hi}` : b.hi == null ? `≥${b.lo}` : `${b.lo}`);
  return (
    <div>
      <div className="flex h-44 items-end gap-1" role="img" aria-label="Results per call in R">
        {bins.map((b, i) => {
          const mid = b.lo == null ? -2 : b.hi == null ? 4 : (b.lo + b.hi) / 2;
          return (
            <div key={i} className="flex h-full flex-1 flex-col justify-end" title={`${lab(b)}R: ${b.n}`}>
              {b.n > 0 && <span className="num mb-0.5 text-center text-xs text-mute">{b.n}</span>}
              <div className="xeno-bar rounded-t-sm" style={{ height: `${(b.n / max) * 100}%`, background: `linear-gradient(to top, ${col(mid, 0.25)}, ${col(mid, 0.95)})`, boxShadow: b.n ? `0 0 12px ${col(mid, 0.5)}` : "none" }} />
            </div>
          );
        })}
      </div>
      <div className="mt-1 flex gap-1 text-xs text-mute">{bins.map((b, i) => <span key={i} className="num flex-1 text-center">{i % 2 ? "" : lab(b)}</span>)}</div>
    </div>
  );
}

/* ---------------------------------------------------------------- splits */
const SPLITS = [["by_tf", "Timeframe"], ["by_side", "Side"], ["by_grade", "Grade"], ["by_session", "Session"], ["by_coin", "Coin"], ["by_entry", "Entry"], ["by_runner", "Let it run"]] as const;

function Splits({ v }: { v: any }) {
  const [k, setK] = useState<string>("by_tf");
  const rows: Grp[] = v[k] ?? [];
  const max = Math.max(0.5, ...rows.map((r) => Math.abs(r.total_r ?? 0)));
  return (
    <section className="xeno-panel space-y-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="label">Where it works</h2>
        <Segmented label="Split by" value={k} onChange={setK} options={SPLITS.map(([a, b]) => [a, b]) as any} />
      </div>
      <ul className="space-y-2">
        {rows.map((r) => (
          <li key={r.key} className="grid grid-cols-[5.5rem_1fr_auto] items-center gap-3 text-sm sm:grid-cols-[7rem_1fr_15rem]">
            <span className="truncate font-medium">{r.key === "?" ? "unknown" : r.key}</span>
            <span className="relative h-3 rounded-full bg-glass/[0.05]">
              <span className="absolute inset-y-0 left-1/2 w-px bg-mute/40" />
              <span className="absolute inset-y-0 rounded-full" style={{
                left: (r.total_r ?? 0) >= 0 ? "50%" : `${50 - (Math.abs(r.total_r ?? 0) / max) * 50}%`,
                width: `${(Math.abs(r.total_r ?? 0) / max) * 50}%`, background: col(r.total_r ?? 0, 0.85), boxShadow: `0 0 10px ${col(r.total_r ?? 0, 0.55)}` }} />
            </span>
            <span className="num text-right text-xs sm:text-sm">
              <span className={`font-semibold ${tn(r.total_r)}`}>{r2(r.total_r)}</span>
              <span className="text-mute"> · {r.n} · {pc(r.win_rate)}</span>
              <span className="hidden text-mute sm:inline"> · avg {r2(r.avg_r)}</span>
            </span>
          </li>
        ))}
      </ul>
      {rows.some((r) => r.n < 10) && <p className="text-xs text-mute"><Badge tone="mute">small sample</Badge> fewer than 10 calls: too early to judge.</p>}
    </section>
  );
}

/* ---------------------------------------------------------------- hive */
function Hive({ heat }: { heat: { wd: string; cells: (St & { s: string })[] }[] }) {
  const S = ["Asia", "Europe", "US", "Late"];
  const r = 22, w = Math.sqrt(3) * r;
  const max = Math.max(0.25, ...heat.flatMap((d) => d.cells.map((c) => Math.abs(c.avg_r ?? 0))));
  const hex = (cx: number, cy: number) => Array.from({ length: 6 }, (_, i) => { const a = Math.PI / 6 + (i * Math.PI) / 3; return `${(cx + r * Math.cos(a)).toFixed(1)},${(cy + r * Math.sin(a)).toFixed(1)}`; }).join(" ");
  const W = 60 + w * S.length + w / 2, H = 40 + heat.length * r * 1.5 + r;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mx-auto w-full max-w-[380px]" role="img" aria-label="Average result by weekday and session">
      {S.map((s, j) => <text key={s} x={60 + w / 2 + j * w} y="14" textAnchor="middle" fontSize="10" className="fill-mute">{s}</text>)}
      {heat.map((d, i) => (
        <g key={d.wd}>
          <text x="4" y={40 + i * r * 1.5 + 4} fontSize="10" className="fill-mute">{d.wd}</text>
          {d.cells.map((c, j) => {
            const cx = 60 + w / 2 + j * w + (i % 2 ? w / 2 : 0), cy = 40 + i * r * 1.5;
            const a = c.n ? 0.15 + 0.75 * Math.min(1, Math.abs(c.avg_r ?? 0) / max) : 0;
            return (
              <g key={c.s}>
                <polygon points={hex(cx, cy)} fill={c.n ? col(c.avg_r ?? 0, a) : "rgb(var(--glass) / 0.04)"} stroke="rgb(var(--ai) / 0.25)" strokeWidth="1">
                  <title>{`${d.wd} ${c.s}: ${c.n ? `${c.n} calls · avg ${r2(c.avg_r)} · total ${r2(c.total_r)}` : "no calls"}`}</title>
                </polygon>
                {c.n > 0 && <text x={cx} y={cy + 3.5} textAnchor="middle" fontSize="10" className="num fill-text" pointerEvents="none">{c.n}</text>}
              </g>
            );
          })}
        </g>
      ))}
    </svg>
  );
}


/** V3.4 Stage 5 (owner: plain charts instead of the orbit): each closed call as a dot at its net R, one row per timeframe. */
function ResultStrip({ dots, total }: { dots: Dot[]; total?: number }) {
  const rows = TFS.filter((t) => dots.some((d) => d.tf === t));
  const lo = Math.min(-1.5, ...dots.map((d) => d.r ?? 0)), hi = Math.max(2, ...dots.map((d) => d.r ?? 0));
  const W = 400, X = (r: number) => 8 + ((r - lo) / (hi - lo)) * (W - 16);
  return (
    <div className="space-y-2" role="img" aria-label={`Closed calls by result in R, total ${r2(total)}`}>
      {rows.map((tf) => (
        <div key={tf} className="lab-strip">
          <span className="num text-xs text-mute">{tf.toUpperCase()}</span>
          <svg viewBox={`0 0 ${W} 26`} className="w-full" preserveAspectRatio="none">
            <line x1={X(0)} x2={X(0)} y1={2} y2={24} stroke="rgb(var(--glass) / 0.25)" />
            {dots.filter((d) => d.tf === tf && isNum(d.r)).map((d, i) => (
              <circle key={i} cx={X(d.r as number)} cy={13 + ((i % 5) - 2) * 3} r={3.2}
                fill={(d.r as number) > 0 ? "rgb(var(--bull) / 0.75)" : "rgb(var(--bear) / 0.75)"}
                stroke={d.a ? "rgb(var(--warn))" : "none"} strokeWidth={1.2}><title>{`${d.coin} ${d.side} · ${r2(d.r)}`}</title></circle>
            ))}
          </svg>
        </div>
      ))}
      <div className="lab-strip text-xs text-mute"><span /><span className="flex justify-between"><span>{r2(lo)}</span><span>0</span><span>{r2(hi)}</span></span></div>
      <p className="text-sm">Total <b className={tn(total)}>{r2(total)}</b> <span className="text-mute">· {dots.length} closed calls shown (latest 300)</span></p>
    </div>
  );
}

/** V3.4 Stage 5: weekday × session as a plain grid (average net R; n in each cell). */
function HeatGrid({ heat }: { heat: { wd: string; cells: (St & { s: string })[] }[] }) {
  const S = ["Asia", "Europe", "US", "Late"];
  const max = Math.max(0.25, ...heat.flatMap((d) => d.cells.map((c) => Math.abs(c.avg_r ?? 0))));
  return (
    <div className="lab-heat">
      <span />{S.map((s) => <span key={s} className="text-center text-mute">{s}</span>)}
      {heat.map((d) => [
        <span key={d.wd} className="self-center text-mute">{d.wd}</span>,
        ...S.map((s) => {
          const c = d.cells.find((x) => x.s === s);
          const v = c?.avg_r, a = isNum(v) ? Math.min(1, Math.abs(v as number) / max) : 0;
          return (
            <div key={d.wd + s} title={c?.n ? `${c.n} calls · avg ${r2(v, 3)}` : "no calls"}
              style={{ background: c?.n ? `rgb(var(${(v ?? 0) >= 0 ? "--bull" : "--bear"}) / ${0.08 + a * 0.4})` : "rgb(var(--glass) / 0.03)" }}>
              <div className="num font-medium">{c?.n ? r2(v, 2) : "–"}</div><div className="text-mute">{c?.n ?? 0}</div>
            </div>
          );
        }),
      ])}
    </div>
  );
}
