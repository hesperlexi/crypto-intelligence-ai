// Market insights on Home (engine document views/market_context, written at most hourly):
// BTC / ETH dominance with our own stored history, the altcoin season index, a market pulse strip and the top
// high-impact headline. Context only: every line describes the number, none of it is advice.
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { useApi } from "../lib/api";
import { ago, fmtCompact, fmtPctRaw, isNum } from "../lib/format";
import { Card } from "./ui";

const TVChart = lazy(() => import("./TVChart"));
// cards in a row share the height; the "as of" line sits at the bottom of each
const STRETCH = "flex flex-col [&>.card-body]:flex [&>.card-body]:flex-1 [&>.card-body]:flex-col";
const COLLECTING = "Collecting data — first reading within the hour.";

const pts = (v: number | null | undefined, digits = 2) =>
  isNum(v) ? `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toFixed(digits)} pt` : "—";
const chipTone = (v: number | null | undefined) => (!isNum(v) || Math.abs(v) < 0.005 ? "text-mute" : v > 0 ? "text-bull" : "text-bear");
const when = (ms: unknown) => (isNum(ms) ? new Date(ms).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");

function AsOf({ ms, source }: { ms: unknown; source?: string }) {
  return <p className="mt-auto pt-3 text-[11px] text-mute" title={source}>As of {when(ms)}{isNum(ms) ? ` · ${ago(ms)}` : ""}{source ? ` · ${source}` : ""}</p>;
}

function Chip({ label, v }: { label: string; v: number | null | undefined }) {
  return (
    <span className="tile inline-flex items-baseline gap-1.5 px-2 py-1 text-xs">
      <span className="text-mute">{label}</span><span className={`num font-semibold ${chipTone(v)}`}>{pts(v)}</span>
    </span>
  );
}

/** Our own BTC-dominance line from the hourly snapshots, with a hover read-out. */
function DomChart({ series }: { series: [number, number, number | null][] }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 300, H = 84, P = 4;
  const vals = series.map((p) => p[1]);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = Math.max(0.05, (hi - lo) * 0.15);
  const y0 = lo - pad, y1 = hi + pad;
  const t0 = series[0][0], t1 = series[series.length - 1][0];
  const x = (t: number) => (t1 === t0 ? W / 2 : ((t - t0) / (t1 - t0)) * W);
  const y = (v: number) => P + (1 - (v - y0) / (y1 - y0)) * (H - 2 * P);
  const line = series.map((p) => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" ");
  const area = `M0 ${H} L${series.map((p) => `${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`).join(" L")} L${W} ${H} Z`;
  const h = hover != null ? series[hover] : null;
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const t = t0 + ((e.clientX - r.left) / r.width) * (t1 - t0);
    let best = 0;
    series.forEach((p, i) => { if (Math.abs(p[0] - t) < Math.abs(series[best][0] - t)) best = i; });
    setHover(best);
  };
  const last = series[series.length - 1];
  return (
    <div className="relative mt-3">
      <div className="mb-1 flex justify-between text-[11px] text-mute">
        <span>{when(t0)}</span>
        <span className="num">{h ? `${when(h[0])} · ${h[1].toFixed(2)}%` : `range ${lo.toFixed(2)}–${hi.toFixed(2)}%`}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-20 w-full touch-none overflow-visible"
        onPointerMove={onMove} onPointerLeave={() => setHover(null)} role="img" aria-label={`BTC dominance, ${series.length} stored readings from ${lo.toFixed(2)}% to ${hi.toFixed(2)}%`}>
        <defs>
          <linearGradient id="dom-area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="rgb(var(--accent))" stopOpacity="0.28" /><stop offset="1" stopColor="rgb(var(--accent))" stopOpacity="0" />
          </linearGradient>
        </defs>
        <line x1="0" x2={W} y1={y((lo + hi) / 2)} y2={y((lo + hi) / 2)} stroke="rgb(var(--glass) / 0.10)" strokeDasharray="3 4" vectorEffect="non-scaling-stroke" />
        <path d={area} fill="url(#dom-area)" />
        <polyline points={line} fill="none" stroke="rgb(var(--accent))" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        {h && <line x1={x(h[0])} x2={x(h[0])} y1="0" y2={H} stroke="rgb(var(--text) / 0.35)" vectorEffect="non-scaling-stroke" />}
      </svg>
      {/* round markers drawn in HTML so the stretched SVG does not turn them into ovals */}
      {[h ?? last].map((p) => (
        <span key="m" aria-hidden="true" className="pointer-events-none absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-ink bg-accent"
          style={{ left: `${(x(p[0]) / W) * 100}%`, top: `calc(1.25rem + ${(y(p[1]) / H) * 5}rem)` }} />
      ))}
    </div>
  );
}

function FullChart({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  // portal: the page wrapper animates with a transform, which would otherwise trap a fixed overlay inside it
  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-end justify-center bg-black/75 p-0 backdrop-blur-sm sm:items-center sm:p-4" onClick={onClose} role="dialog" aria-modal="true" aria-label="BTC dominance full chart">
      <div className="panel w-full max-w-5xl rounded-b-none sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between gap-2 border-b border-glass/[0.06] px-4 py-2.5">
          <h2 className="label">BTC dominance · full history</h2>
          <button className="btn btn-ghost px-3" onClick={onClose} aria-label="Close">Close</button>
        </div>
        <div className="p-2">
          <Suspense fallback={<div className="h-[60vh] animate-pulse rounded-lg bg-glass/[0.04]" />}>
            <TVChart symbol="BTC/USDT" tvSymbolOverride="CRYPTOCAP:BTC.D" tf="1d" height={Math.min(560, Math.round(window.innerHeight * 0.62))} />
          </Suspense>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function Dominance({ d }: { d: any }) {
  const [full, setFull] = useState(false);
  const button = <button className="btn px-3 text-xs" onClick={() => setFull(true)}>Full chart</button>;
  return (
    <Card title="BTC dominance" right={button} className={STRETCH}>
      {d ? (
        <>
          <div className="flex items-end justify-between gap-3">
            <div>
              <div className="num text-3xl font-bold tracking-tight text-accent">{d.btc.toFixed(2)}%</div>
              <div className="text-xs text-mute">Bitcoin's share of all crypto</div>
            </div>
            <div className="text-right">
              <div className="num text-lg font-semibold">{isNum(d.eth) ? `${d.eth.toFixed(2)}%` : "—"}</div>
              <div className="text-xs text-mute">ETH dominance</div>
              {isNum(d.eth_change_24h) && <div className="text-xs text-mute"><span className={`num ${chipTone(d.eth_change_24h)}`}>{pts(d.eth_change_24h)}</span> 24h</div>}
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5"><Chip label="24h" v={d.btc_change_24h} /><Chip label="7d" v={d.btc_change_7d} /></div>
          {(d.series ?? []).length >= 2
            ? <DomChart series={d.series} />
            : <p className="mt-3 rounded-lg bg-glass/[0.03] px-3 py-4 text-center text-xs text-mute">Our own chart starts after the second hourly reading. "Full chart" shows the complete history now.</p>}
          <p className="mt-3 text-sm text-text">{d.reading}</p>
          <AsOf ms={d.as_of} source="CoinGecko" />
        </>
      ) : <p className="py-6 text-center text-sm text-mute">{COLLECTING} "Full chart" shows the complete history now.</p>}
      {full && <FullChart onClose={() => setFull(false)} />}
    </Card>
  );
}

function AltSeason({ a }: { a: any }) {
  const v = isNum(a?.value) ? Math.max(0, Math.min(100, a.value)) : null;
  const color = v == null ? "rgb(var(--mute))" : v <= 25 ? "#f7931a" : v >= 75 ? "#8b7cf6" : "rgb(var(--accent))";
  return (
    <Card title="Altcoin season index" right={<span className="text-[11px] text-mute">0–100</span>} className={STRETCH}>
      {a && v != null ? (
        <>
          <div className="flex items-end justify-between gap-3">
            <div className="num text-3xl font-bold tracking-tight" style={{ color }}>{v}</div>
            <span className="rounded-full px-3 py-0.5 text-sm font-semibold" style={{ color, background: "rgb(var(--glass) / 0.05)", boxShadow: "inset 0 0 0 1px rgb(var(--glass) / 0.12)" }}>{a.label}</span>
          </div>
          <div className="relative mt-4">
            <div className="flex h-3 overflow-hidden rounded-full" aria-hidden="true">
              <div className="h-full bg-[#f7931a]/70" style={{ width: "25%" }} />
              <div className="h-full bg-glass/[0.10]" style={{ width: "50%", marginLeft: 2, marginRight: 2 }} />
              <div className="h-full bg-[#8b7cf6]/70" style={{ width: "25%" }} />
            </div>
            <span className="absolute top-1/2 h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] bg-ink shadow" style={{ left: `${v}%`, borderColor: color }}
              role="img" aria-label={`Index ${v} of 100`} />
          </div>
          <div className="mt-1.5 grid grid-cols-[1fr_2fr_1fr] text-[11px] text-mute">
            <span className="text-left">Bitcoin season</span>
            <span className="num text-center">25 · neither · 75</span>
            <span className="text-right">Altcoin season</span>
          </div>
          <p className="mt-3 text-sm text-text"><span className="num font-semibold">{a.n_beat} of {a.n_total}</span> top coins beat BTC over the last {a.window_days} days.</p>
          {(a.best ?? []).length > 0 && (
            <p className="mt-1 text-xs text-mute">Strongest vs BTC: {a.best.map((b: any) => `${b.coin} ${b.vs_btc > 0 ? "+" : ""}${(b.vs_btc * 100).toFixed(0)}%`).join(" · ")}</p>
          )}
          <p className="mt-2 text-xs text-mute">≤25 Bitcoin season, ≥75 Altcoin season. Stablecoins, wrapped, staked and leveraged tokens excluded.</p>
          <AsOf ms={a.as_of} source={a.universe} />
        </>
      ) : <p className="py-6 text-center text-sm text-mute">Collecting data — the first index is computed within six hours.</p>}
    </Card>
  );
}

function Pulse({ p, f }: { p: any; f: any }) {
  const readTone = f?.read && f.read !== "neutral" ? "text-warn" : "text-text";   // neutral colour: a read, not a direction
  const tiles = [
    { k: "Total market cap", v: p && isNum(p.total_market_cap_usd) ? `$${fmtCompact(p.total_market_cap_usd)}` : "—",
      sub: p && isNum(p.market_cap_change_24h_pct) ? <span className={chipTone(p.market_cap_change_24h_pct)}>{fmtPctRaw(p.market_cap_change_24h_pct)} 24h</span> : "24h change —" },
    { k: "Stablecoin share", v: p && isNum(p.stablecoin_share) ? `${p.stablecoin_share.toFixed(2)}%` : "—", sub: "cash on the sidelines" },
    { k: "Avg funding (8h)", v: f && isNum(f.avg_rate_8h) ? `${f.avg_rate_8h >= 0 ? "+" : "−"}${Math.abs(f.avg_rate_8h * 100).toFixed(4)}%` : "—",
      sub: f ? <span className={`font-semibold capitalize ${readTone}`}>{f.read}</span> : "no funding data" },
  ];
  return (
    <Card title="Market pulse" className={STRETCH}>
      {p || f ? (
        <>
          <div className="grid grid-cols-1 gap-2">
            {tiles.map((t) => (
              <div key={t.k} className="tile flex items-center justify-between gap-3 px-3 py-2.5">
                <div className="min-w-0"><div className="label">{t.k}</div><div className="mt-0.5 truncate text-xs text-mute">{t.sub}</div></div>
                <div className="num shrink-0 text-lg font-semibold">{t.v}</div>
              </div>
            ))}
          </div>
          {f && <p className="mt-3 text-xs text-mute">Funding averaged over {f.n} watchlist coins ({f.source}). ≥ +0.03% crowded long, ≤ −0.01% crowded short; the exchanges' default is +0.01%.</p>}
          <AsOf ms={p?.as_of ?? f?.as_of} source={p?.source} />
        </>
      ) : <p className="py-6 text-center text-sm text-mute">{COLLECTING}</p>}
    </Card>
  );
}

function Headline({ h }: { h: any }) {
  return (
    <div className="panel flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-4">
      <span className="label shrink-0 text-accent">Top headline</span>
      <a href={h.url} target="_blank" rel="noopener nofollow" className="min-w-0 flex-1 text-sm font-medium text-text hover:text-accent sm:truncate">{h.title}</a>
      <span className="flex shrink-0 items-center gap-3 text-xs text-mute">
        <span>{h.source}{isNum(h.ts) ? ` · ${ago(h.ts)}` : ""}</span>
        <Link to="/news" className="text-accent hover:underline">All news →</Link>
      </span>
    </div>
  );
}

export default function MarketInsights() {
  const v = useApi<any>("/market-context", 600_000);
  const d = v.data;
  const stale = useMemo(() => isNum(d?.generated_at) && Date.now() - d.generated_at > 3 * 3_600_000, [d?.generated_at]);
  return (
    <section aria-labelledby="mi-title" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2 border-b border-glass/[0.07] pb-3 pt-3">
        <h2 id="mi-title" className="section-title">Market insights</h2>
        <span className="text-xs text-mute">{d ? `Updated ${ago(d.generated_at)}${stale ? " (engine catching up)" : ""}` : "Context only, not advice"}</span>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Dominance d={d?.dominance} />
        <AltSeason a={d?.altseason} />
        <Pulse p={d?.pulse} f={d?.funding} />
      </div>
      {d?.headline?.url && <Headline h={d.headline} />}
    </section>
  );
}
