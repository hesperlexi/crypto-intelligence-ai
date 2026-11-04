// v2.20 Home "Overview" (owner request 4 Nov 2026, layout after the owner's mockups, our brand and ONLY real data).
// Data sources (no new sockets; Firestore: +1 read per open for views/track_record, +1 for the admin's views/guardian):
//   BTC card / volatility / chart  Binance public klines (lib/klines: cached, ≤ 1 request per 5 min) + the live ticker
//   Total market cap               views/market_context.pulse (CoinGecko), else views/context.market
//   Market sentiment               views/dashboard_4h.market_status (4H mood) + views/context.sentiment (Fear & Greed)
//   AI market intelligence         views/market_context.briefing (v2.16 briefing)
//   Global market status           live tickers, market_context.pulse / altseason, context.sentiment
//   Active signals                 views/track_record.live.signals (status OPEN) + live tickers
//   Recent activity                track_record (opened / closed calls), views/alerts_u_<uid> events, briefing time
//   Performance overview           track_record.live.summary / curve / last_7d (after fees)
//   Trade Guardian (admin only)    views/guardian when it exists, otherwise nothing is rendered
// Components are defined at the top level (never inside a render) and the price-driven parts subscribe on their own,
// so a price tick re-renders a table row, not the page.
import { lazy, memo, ReactNode, Suspense, useId, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/api";
import { ago, base, DASH, fmtCompact, fmtDate, fmtPctRaw, fmtPrice, isNum, slug } from "../lib/format";
import { realisedVol, useKlines } from "../lib/klines";
import { useLive, useTickerThrottled } from "../lib/live";
import type { Candle } from "../lib/ta";
import { Ico } from "./AppNav";
import { Badge, Segmented, Tone } from "./kit";
import { CoinAvatar } from "./Polish";
import { isPending, liveOf, RecordSheet } from "./RecordDetails";
import { AiTag, Empty, Info } from "./ui";

const CandleChart = lazy(() => import("./CandleChart"));
const BTC = "BTC/USDT";
const H1_LIMIT = 200;                 // 1h candles: sparkline (24), rolling volatility (7 days) and the 1H chart, one request

const toneText = (v: number | null | undefined) => (!isNum(v) ? "text-mute" : v >= 0 ? "text-bull" : "text-bear");
const arrow = (v: number | null | undefined) => (!isNum(v) ? "" : v >= 0 ? "▲ " : "▼ ");

/* ---- small building blocks ------------------------------------------------------------------------------------ */
/** A tiny area line (SVG): no axes, colour from a theme token. */
export const Sparkline = memo(function Sparkline({ values, tone = "--accent", className = "h-10 w-full", label }: { values: number[]; tone?: string; className?: string; label?: string }) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const v = values.filter(isNum);
  if (v.length < 2) return <div className={className} aria-hidden="true" />;
  const min = Math.min(...v), max = Math.max(...v), span = max - min || 1;
  const pts = v.map((y, i) => `${((i / (v.length - 1)) * 100).toFixed(2)} ${(30 - ((y - min) / span) * 27).toFixed(2)}`);
  const line = `M${pts.join(" L")}`;
  return (
    <svg viewBox="0 0 100 32" preserveAspectRatio="none" className={className} role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      <defs><linearGradient id={`sg${id}`} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor={`rgb(var(${tone}))`} stopOpacity="0.26" /><stop offset="1" stopColor={`rgb(var(${tone}))`} stopOpacity="0" /></linearGradient></defs>
      <path d={`${line} L100 32 L0 32 Z`} fill={`url(#sg${id})`} />
      <path d={line} fill="none" stroke={`rgb(var(${tone}))`} strokeWidth="1.7" vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
});

/** Semicircle gauge 0-100 (Fear & Greed): fear zone red, neutral amber, greed green, needle at the value. */
export function Gauge({ value, size = 96, label }: { value: number | null; size?: number; label?: string }) {
  const pt = (v: number, r = 40) => { const a = Math.PI * (1 - v / 100); return [50 + r * Math.cos(a), 50 - r * Math.sin(a)]; };
  const arc = (a: number, b: number) => { const [x1, y1] = pt(a), [x2, y2] = pt(b); return `M${x1.toFixed(2)} ${y1.toFixed(2)} A40 40 0 0 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`; };
  const v = isNum(value) ? Math.max(0, Math.min(100, value)) : null;
  const tip = v == null ? null : pt(v, 31);
  return (
    <svg viewBox="0 0 100 56" width={size} height={size * 0.56} role="img" aria-label={label ?? (v == null ? "No reading" : `${v} of 100`)} className="shrink-0">
      <path d={arc(0, 44)} stroke="rgb(var(--bear) / 0.75)" strokeWidth="8" fill="none" />
      <path d={arc(45.5, 54.5)} stroke="rgb(var(--warn) / 0.75)" strokeWidth="8" fill="none" />
      <path d={arc(56, 100)} stroke="rgb(var(--bull) / 0.75)" strokeWidth="8" fill="none" />
      {tip && <><line x1="50" y1="50" x2={tip[0]} y2={tip[1]} stroke="rgb(var(--text))" strokeWidth="2.4" strokeLinecap="round" /><circle cx="50" cy="50" r="3.6" fill="rgb(var(--text))" /></>}
    </svg>
  );
}

function CardHead({ icon, title, right, ai = false }: { icon?: ReactNode; title: ReactNode; right?: ReactNode; ai?: boolean }) {
  return (
    <div className="mb-3 flex min-w-0 flex-wrap items-center justify-between gap-2">
      <h2 className="flex min-w-0 items-center gap-2 text-sm font-semibold text-text">{ai && <AiTag />}{icon && <span className="text-accent">{icon}</span>}<span className="truncate">{title}</span></h2>
      {right}
    </div>
  );
}

const ViewAll = ({ to, label = "View all" }: { to: string; label?: string }) => (
  <Link to={to} className="tap-h inline-flex items-center text-xs font-medium text-accent hover:underline">{label} →</Link>
);

/** Row 1 card: label, big figure, change line, sparkline. */
function StatCard({ icon, label, value, sub, spark, sparkLabel, info, to }: {
  icon: ReactNode; label: string; value: ReactNode; sub?: ReactNode; spark?: ReactNode; sparkLabel?: ReactNode; info?: ReactNode; to?: string;
}) {
  const body = (
    <>
      <div className="flex items-center gap-2.5">
        {icon}
        <span className="min-w-0 flex-1 text-xs font-semibold uppercase leading-tight tracking-[0.06em] text-mute sm:truncate">{label}</span>
        {info}
      </div>
      <div className="num mt-2.5 truncate text-xl font-semibold leading-tight tracking-tight sm:text-2xl">{value}</div>
      {sub != null && <div className="num mt-1 text-xs leading-snug">{sub}</div>}
      {spark && <div className="mt-auto pt-2">{spark}{sparkLabel && <div className="mt-0.5 truncate text-xs text-mute">{sparkLabel}</div>}</div>}
    </>
  );
  const cls = "panel ov-card flex min-w-0 flex-col p-3.5 sm:p-4";
  return to ? <Link to={to} className={`${cls} transition-colors hover:border-accent/40`}>{body}</Link> : <section className={cls}>{body}</section>;
}

const IconDisc = ({ name }: { name: string }) => (
  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-accent/25 bg-accent/[0.08] text-accent"><Ico name={name} size={16} /></span>
);

/* ---- row 1 ------------------------------------------------------------------------------------------------------ */
export function BtcCard() {
  const t = useTickerThrottled(BTC, 1000);
  const h1 = useKlines(BTC, "1h", H1_LIMIT, 300_000).data;
  const closes = useMemo(() => (h1 ?? []).slice(-25).map((c) => c[4]), [h1]);
  const ch = t?.change_pct;
  const abs = isNum(t?.last) && isNum(ch) ? t!.last! - t!.last! / (1 + ch / 100) : null;
  return (
    <StatCard to={`/asset/${slug(BTC)}`} icon={<CoinAvatar symbol={BTC} size={32} />} label="BTC price" value={isNum(t?.last) ? `$${fmtPrice(t!.last)}` : DASH}
      sub={<span className={toneText(ch)}>{arrow(ch)}{fmtPctRaw(ch)}{isNum(abs) ? <span className="hidden sm:inline"> ({abs >= 0 ? "+" : "−"}${fmtPrice(Math.abs(abs))})</span> : ""}<span className="text-mute"> · 24h</span></span>}
      spark={<Sparkline values={closes} tone={isNum(ch) && ch < 0 ? "--bear" : "--bull"} label="BTC price, last 24 hours" />} sparkLabel="Last 24 h, hourly closes" />
  );
}

export function MarketCapCard({ mc, ctx }: { mc: any; ctx: any }) {
  const pulse = mc?.pulse, m = ctx?.market;
  const cap = pulse?.total_market_cap_usd ?? m?.total_market_cap_usd;
  const ch = isNum(pulse?.market_cap_change_24h_pct) ? pulse.market_cap_change_24h_pct : m?.market_cap_change_24h_pct;
  const dom = mc?.dominance;
  // no market-cap history is stored, so the line shows what is: Bitcoin's share over the last 7 days (4-hour points)
  const series: number[] = useMemo(() => ((dom?.series ?? []) as any[]).slice(-43).map((p) => p[1]), [dom]);
  return (
    <StatCard icon={<IconDisc name="/results" />} label="Total market cap" value={isNum(cap) ? `$${fmtCompact(cap)}` : DASH}
      sub={<span className={toneText(ch)}>{arrow(ch)}{fmtPctRaw(ch)}<span className="text-mute"> · 24h · CoinGecko</span></span>}
      spark={series.length > 1 ? <Sparkline values={series} tone="--accent" label="Bitcoin dominance, 7 days" /> : undefined}
      sparkLabel={series.length > 1 ? <>BTC dominance 7d · <span className="num text-text/80">{isNum(dom?.btc) ? `${dom.btc.toFixed(1)}%` : DASH}</span></> : undefined} />
  );
}

export function VolatilityCard() {
  const h1 = useKlines(BTC, "1h", H1_LIMIT, 300_000).data;
  const v = useMemo(() => {
    if (!h1 || h1.length < 30) return null;
    const c = h1.map((x) => x[4]);
    const now = realisedVol(c.slice(-25));
    const prev = c.length >= 49 ? realisedVol(c.slice(-49, -24)) : null;
    const last = h1.slice(-24);
    const range = (Math.max(...last.map((x) => x[2])) - Math.min(...last.map((x) => x[3]))) / c[c.length - 1] * 100;
    const roll: number[] = [];
    for (let i = Math.max(24, c.length - 168); i < c.length; i += 2) { const r = realisedVol(c.slice(i - 24, i + 1)); if (isNum(r)) roll.push(r); }
    return { now, prev, range, roll };
  }, [h1]);
  const d = v && isNum(v.now) && isNum(v.prev) ? v.now - v.prev : null;
  return (
    <StatCard icon={<IconDisc name="/health" />} label="BTC 24h volatility" value={v && isNum(v.now) ? `${v.now.toFixed(1)}%` : DASH}
      info={<Info label="What this volatility is">Realised volatility of Bitcoin: the spread of its hourly returns over the last 24 hours, annualised (× √8,760). The range is the gap between the 24-hour high and low. Binance prices.</Info>}
      sub={<>{isNum(d) ? <span className={d > 0 ? "text-warn" : "text-mute"}>{d > 0 ? "▲ +" : "▼ "}{d.toFixed(1)} pts</span> : <span className="text-mute">{DASH}</span>}<span className="text-mute"> vs day before · annualised</span></>}
      spark={<Sparkline values={v?.roll ?? []} tone="--warn" label="BTC 24-hour realised volatility, last 7 days" />}
      sparkLabel={<>7 days · 24h range <span className="num text-text/80">{v ? `${v.range.toFixed(2)}%` : DASH}</span></>} />
  );
}

export function SentimentCard({ status, sentiment }: { status: any; sentiment: any }) {
  const mood = status?.status;
  const word = mood === "BULL" ? "Bullish" : mood === "BEAR" ? "Bearish" : mood === "NEUTRAL" ? "Mixed" : "Warming up";
  const cls = mood === "BULL" ? "text-bull" : mood === "BEAR" ? "text-bear" : "text-warn";
  const fg = isNum(sentiment?.value) ? sentiment.value : null;
  return (
    <section className="panel ov-card flex min-w-0 flex-col p-3.5 sm:p-4">
      <div className="flex items-center gap-2.5">
        <IconDisc name="/radar" />
        <span className="min-w-0 flex-1 text-xs font-semibold uppercase leading-tight tracking-[0.06em] text-mute sm:truncate">Market sentiment</span>
        <Info label="How the sentiment is read">Mood = share of the watchlist in a bullish or bearish 4H regime (60% needed), from the engine. Gauge = the Fear &amp; Greed index (alternative.me).</Info>
      </div>
      <div className="mt-2 flex min-w-0 flex-wrap items-end justify-between gap-x-2 gap-y-1">
        <div className="min-w-0">
          <div className={`font-display text-xl font-semibold leading-tight sm:text-2xl ${cls}`}>{word}</div>
          <div className="num mt-1 text-xs text-mute">{status ? <>4H · <span className="text-bull">{status.bull} bull</span> · <span className="text-bear">{status.bear} bear</span></> : "4H mood not published yet"}</div>
        </div>
        <div className="flex flex-col items-center">
          <Gauge value={fg} size={84} label={fg == null ? "Fear and Greed unavailable" : `Fear and Greed ${fg}, ${sentiment.label}`} />
          <div className="num -mt-0.5 text-xs text-mute">F&amp;G <span className="font-semibold text-text">{fg ?? DASH}</span>{sentiment?.label ? ` · ${sentiment.label}` : ""}</div>
        </div>
      </div>
    </section>
  );
}

/* ---- row 2 ------------------------------------------------------------------------------------------------------ */
const CHART_TF: Record<string, [string, number, number]> = { "1H": ["1h", H1_LIMIT, 300_000], "4H": ["4h", 180, 600_000], "1D": ["1d", 180, 1_800_000], "1W": ["1w", 150, 1_800_000] };

export function BtcChartCard() {
  const [tf, setTf] = useState<keyof typeof CHART_TF>(() => { try { return (localStorage.getItem("cia-home-chart-tf") as any) in CHART_TF ? localStorage.getItem("cia-home-chart-tf") as any : "4H"; } catch { return "4H"; } });
  const [itf, limit, age] = CHART_TF[tf];
  const k = useKlines(BTC, itf, limit, age);
  const t = useTickerThrottled(BTC, 1000);
  const height = typeof window !== "undefined" && window.innerWidth < 640 ? 230 : 320;
  const pick = (v: keyof typeof CHART_TF) => { setTf(v); try { localStorage.setItem("cia-home-chart-tf", v); } catch { /* ignore */ } };
  return (
    <section className="panel min-w-0 p-3.5 sm:p-4">
      <CardHead icon={<Ico name="/results" size={16} />} title={<>BTC market chart <span className="font-normal text-mute">· perpetual</span></>}
        right={<Segmented value={tf} options={Object.keys(CHART_TF) as (keyof typeof CHART_TF)[]} onChange={pick} label="Chart timeframe" />} />
      <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="num text-lg font-semibold">{isNum(t?.last) ? `$${fmtPrice(t!.last)}` : DASH}</span>
        <span className={`num text-sm ${toneText(t?.change_pct)}`}>{fmtPctRaw(t?.change_pct)} <span className="text-mute">24h</span></span>
        <Link to={`/asset/${slug(BTC)}`} className="tap-h ml-auto inline-flex items-center text-xs font-medium text-accent hover:underline">Full chart &amp; AI view →</Link>
      </div>
      <div style={{ height }} className="min-w-0">
        {k.data?.length ? (
          <Suspense fallback={<div className="skeleton h-full rounded-lg" />}>
            <ChartBox candles={k.data} live={t?.last ?? null} height={height} viewKey={`home-btc-${itf}`} />
          </Suspense>
        ) : k.error ? <Empty>Chart data could not be loaded ({k.error}).</Empty> : <div className="skeleton h-full rounded-lg" />}
      </div>
    </section>
  );
}
const ChartBox = memo(function ChartBox({ candles, live, height, viewKey }: { candles: Candle[]; live: number | null; height: number; viewKey: string }) {
  return <CandleChart candles={candles} livePrice={live} height={height} viewKey={viewKey} />;
});

/** First one or two sentences of the briefing (≤ ~220 characters) for the headline. */
function headline(text: string): string {
  // split only where a sentence ends (". " before a capital), never inside a number such as "+1.8%"
  const parts = text.replace(/([.!?])\s+(?=[A-Z"'(])/g, "$1\u0001").split("\u0001");
  let out = parts[0].trim();
  if (parts[1] && out.length + parts[1].length < 220) out += " " + parts[1].trim();
  return out;
}

export function AiBriefCard({ b, loading }: { b: any; loading: boolean }) {
  const [open, setOpen] = useState(false);
  const mood = b?.mood;
  const tone: Tone = mood === "BULL" ? "bull" : mood === "BEAR" ? "bear" : "warn";
  const bullets: string[] = b?.bullets ?? [];
  return (
    <section className="panel ai-card flex min-w-0 flex-col p-3.5 sm:p-4">
      <CardHead ai title="Market intelligence" right={b?.text ? (
        <button type="button" className="tap-h inline-flex items-center text-xs font-medium text-accent hover:underline" aria-expanded={open} aria-controls="ov-brief-more" onClick={() => setOpen((v) => !v)}>
          {open ? "Hide details" : "View details →"}
        </button>) : undefined} />
      {!b?.text ? (loading ? <div className="space-y-2"><div className="skeleton h-4 w-2/3 rounded" /><div className="skeleton h-4 w-full rounded" /><div className="skeleton h-4 w-5/6 rounded" /></div>
        : <Empty>The market briefing appears after the next hourly analysis.</Empty>) : (
        <>
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone={tone} caps>{mood === "BULL" ? "Bullish" : mood === "BEAR" ? "Bearish" : "Mixed"} mood · 4H</Badge>
            <span className="text-xs text-mute">{b.source === "ai" ? "AI briefing" : "Briefing"} · {ago(b.at)}</span>
          </div>
          <p className="mt-2.5 text-base font-semibold leading-snug text-text">{headline(b.text)}</p>
          <ul className="mb-3 mt-3 space-y-2">
            {bullets.slice(0, 3).map((x) => (
              <li key={x} className="flex gap-2 text-sm text-text/85"><span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-bull/15 text-bull" aria-hidden="true">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg></span><span className="min-w-0">{x}</span></li>
            ))}
          </ul>
          {!open && bullets.length > 3 && <ul className="mb-3 flex flex-wrap gap-1.5">{bullets.slice(3).map((x) => <li key={x} className="fact-pill">{x}</li>)}</ul>}
          {open && (
            <div id="ov-brief-more" className="mt-3 rounded-lg border border-glass/[0.08] bg-ink/40 p-3">
              <p className="text-sm leading-relaxed text-text/90">{b.text}</p>
            </div>
          )}
          <p className="mt-auto border-t border-glass/[0.06] pt-3 text-xs text-mute">{b.note ?? "From the engine's own numbers. Context, not advice."}</p>
        </>
      )}
    </section>
  );
}

/* ---- row 3 ------------------------------------------------------------------------------------------------------ */
function MiniTile({ children, to, className = "" }: { children: ReactNode; to?: string; className?: string }) {
  const cls = `tile min-w-0 p-2.5 sm:p-3 ${className}`;
  return to ? <Link to={to} className={`${cls} block transition-colors hover:border-accent/40`}>{children}</Link> : <div className={cls}>{children}</div>;
}

function CoinMini({ sym }: { sym: string }) {
  const t = useTickerThrottled(sym, 1000);
  return (
    <MiniTile to={`/asset/${slug(sym)}`}>
      <div className="flex items-center gap-1.5 text-xs font-semibold text-mute"><CoinAvatar symbol={sym} size={16} />{base(sym)}</div>
      <div className="num mt-1 truncate text-sm font-semibold sm:text-base">{isNum(t?.last) ? `$${fmtPrice(t!.last)}` : DASH}</div>
      <div className={`num text-xs ${toneText(t?.change_pct)}`}>{arrow(t?.change_pct)}{fmtPctRaw(t?.change_pct)}</div>
    </MiniTile>
  );
}

export function GlobalStatusCard({ mc, ctx }: { mc: any; ctx: any }) {
  const pulse = mc?.pulse, m = ctx?.market, s = ctx?.sentiment, alt = mc?.altseason;
  const cap = pulse?.total_market_cap_usd ?? m?.total_market_cap_usd;
  const ch = isNum(pulse?.market_cap_change_24h_pct) ? pulse.market_cap_change_24h_pct : m?.market_cap_change_24h_pct;
  const fg = isNum(s?.value) ? s.value : null;
  return (
    <section className="panel min-w-0 p-3.5 sm:p-4">
      <CardHead icon={<Ico name="/radar" size={16} />} title="Global market status" right={<ViewAll to="/news" label="Market news" />} />
      <div className="grid grid-cols-1 gap-2 min-[360px]:grid-cols-2 sm:grid-cols-3">
        <CoinMini sym="BTC/USDT" />
        <CoinMini sym="ETH/USDT" />
        <MiniTile>
          <div className="text-xs font-semibold text-mute">Total cap</div>
          <div className="num mt-1 truncate text-sm font-semibold sm:text-base">{isNum(cap) ? `$${fmtCompact(cap)}` : DASH}</div>
          <div className={`num text-xs ${toneText(ch)}`}>{arrow(ch)}{fmtPctRaw(ch)}</div>
        </MiniTile>
        <MiniTile>
          <div className="truncate text-xs font-semibold text-mute" title="Fear & Greed index">Fear &amp; Greed</div>
          <div className="mt-1 flex items-center gap-2">
            <Gauge value={fg} size={48} label={fg == null ? "Fear and Greed unavailable" : `Fear and Greed ${fg}`} />
            <div className="min-w-0"><div className="num text-sm font-semibold sm:text-base">{fg ?? DASH}</div><div className="truncate text-xs text-mute">{s?.label ?? ""}</div></div>
          </div>
        </MiniTile>
        <MiniTile className="min-[360px]:col-span-2" to="/radar">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-semibold text-mute">Altcoin strength</span>
            <Info label="What altcoin strength is">Altcoin season index: share of the top coins that beat Bitcoin over {alt?.window_days ?? 90} days (75+ = altcoin season, 25 or less = Bitcoin season). {alt?.source ?? ""}</Info>
          </div>
          <div className="num mt-1 text-sm font-semibold">{isNum(alt?.value) ? <>{alt.value}<span className="text-mute">/100</span></> : DASH} <span className="font-normal text-mute">{alt?.label ?? ""}</span></div>
          {isNum(alt?.value) && <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-glass/[0.08]"><div className="h-full rounded-full bg-accent" style={{ width: `${alt.value}%` }} /></div>}
          {isNum(alt?.n_beat) && <div className="num mt-1 text-xs text-mute">{alt.n_beat} of {alt.n_total} beat BTC</div>}
        </MiniTile>
      </div>
    </section>
  );
}

/** Health of an open call (v2.20 rule): where the live price sits between the stop now in force (0) and the next
 *  target (1). Healthy ≥ 0.5 (at or beyond the midpoint: for a fresh 1R target that is the entry), Watch 0.25-0.5,
 *  At risk < 0.25 or beyond the stop. All targets hit → Healthy. Waiting pullback entries → Waiting. */
export function healthOf(x: any, px: number | undefined): [string, Tone, number | null] {
  if (isPending(x)) return ["Waiting", "mute", null];
  if (!isNum(px)) return [DASH, "mute", null];
  const L = liveOf(x, px);
  if (!L.next) return ["Healthy", "bull", 1];
  const toStop = isNum(L.toStop) ? -L.toStop : null;       // + = price still on the safe side of the stop
  const toNext = L.toNext;                                  // + = target not reached yet
  if (!isNum(toStop) || !isNum(toNext)) return [DASH, "mute", null];
  if (toStop <= 0) return ["At risk", "bear", 0];
  const p = toNext <= 0 ? 1 : toStop / (toStop + toNext);
  return p >= 0.5 ? ["Healthy", "bull", p] : p >= 0.25 ? ["Watch", "warn", p] : ["At risk", "bear", p];
}

const SignalRow = memo(function SignalRow({ x, px, onOpen }: { x: any; px: number | undefined; onOpen: (x: any) => void }) {
  const pend = isPending(x);
  const L = !pend && isNum(px) ? liveOf(x, px) : null;
  const [label, tone] = healthOf(x, px);
  const long = x.side !== "SHORT";
  return (
    <tr className="cursor-pointer hover:bg-glass/[0.04]" tabIndex={0} onClick={() => onOpen(x)} onKeyDown={(e) => { if (e.key === "Enter") onOpen(x); }}>
      <td><span className="flex items-center gap-2 font-medium"><CoinAvatar symbol={x.symbol} size={18} />{base(x.symbol)}<span className="text-xs uppercase text-mute">{x.timeframe}</span></span></td>
      <td><span className={`text-xs font-bold ${long ? "text-bull" : "text-bear"}`}>{long ? "▲ LONG" : "▼ SHORT"}</span></td>
      <td className="num text-right">{fmtPrice(x.entry)}</td>
      <td className="num text-right">{fmtPrice(px)}</td>
      <td className={`num text-right ${pend ? "text-mute" : toneText(L?.move)}`}>{pend ? "waiting" : fmtPctRaw(L?.move)}</td>
      <td className="text-right"><Badge tone={tone}>{label}</Badge></td>
    </tr>
  );
});

const SignalItem = memo(function SignalItem({ x, px, onOpen }: { x: any; px: number | undefined; onOpen: (x: any) => void }) {
  const pend = isPending(x);
  const L = !pend && isNum(px) ? liveOf(x, px) : null;
  const [label, tone] = healthOf(x, px);
  const long = x.side !== "SHORT";
  return (
    <li>
      <button type="button" onClick={() => onOpen(x)} className="flex min-h-[44px] w-full flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-lg px-2 py-2 text-left text-sm hover:bg-glass/[0.04]">
        <span className="flex min-w-0 items-center gap-2 font-medium"><CoinAvatar symbol={x.symbol} size={18} />{base(x.symbol)}<span className="text-xs uppercase text-mute">{x.timeframe}</span><span className={`text-xs font-bold ${long ? "text-bull" : "text-bear"}`}>{long ? "LONG" : "SHORT"}</span></span>
        <span className="flex items-center gap-2"><span className={`num ${pend ? "text-xs text-mute" : toneText(L?.move)}`}>{pend ? "waiting for entry" : fmtPctRaw(L?.move)}</span><Badge tone={tone}>{label}</Badge></span>
      </button>
    </li>
  );
});

export function ActiveSignalsCard({ track, loading }: { track: any; loading: boolean }) {
  const { tickers } = useLive();
  const [open, setOpen] = useState<any>(null);
  const rows: any[] = useMemo(() => ((track?.live?.signals ?? []) as any[]).filter((x) => x.status === "OPEN")
    .sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0)), [track]);
  const shown = rows.slice(0, 6);
  return (
    <section className="panel min-w-0 p-3.5 sm:p-4">
      <CardHead icon={<Ico name="/signals" size={16} />} title={<>Active signals <span className="num font-normal text-mute">· {rows.length}</span></>}
        right={<span className="flex items-center gap-2"><Info label="How live % and status are worked out">Live % = price move since the recorded entry, no leverage, before fees (after a target, the part already closed counts at its target). Status = where the price sits between the stop now in force and the next target: Healthy from halfway, Watch 25–50%, At risk under 25%.</Info><ViewAll to="/results?tab=track" /></span>} />
      {!track && loading ? <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-8 rounded" />)}</div>
        : !shown.length ? <Empty>No open calls right now. Waiting for a setup that passes every check is normal.</Empty> : (
        <>
          <div className="hidden overflow-x-auto sm:block">
            <table className="grid-table ov-table w-full whitespace-nowrap text-sm">
              <thead><tr><th>Coin</th><th>Side</th><th className="text-right">Entry</th><th className="text-right">Live</th><th className="text-right">Live %</th><th className="text-right">Status</th></tr></thead>
              <tbody>{shown.map((x) => <SignalRow key={x.id} x={x} px={tickers[x.symbol]?.last ?? undefined} onOpen={setOpen} />)}</tbody>
            </table>
          </div>
          <ul className="space-y-0.5 sm:hidden">{shown.map((x) => <SignalItem key={x.id} x={x} px={tickers[x.symbol]?.last ?? undefined} onOpen={setOpen} />)}</ul>
          {rows.length > shown.length && <p className="mt-2 text-xs text-mute">+{rows.length - shown.length} more on Results.</p>}
        </>
      )}
      {open && <RecordSheet x={open} onClose={() => setOpen(null)} />}
    </section>
  );
}

/** Admin only: the Trade Guardian summary when views/guardian exists; nothing at all otherwise. */
export function GuardianCard() {
  const g = useApi<any>("/guardian");
  const v = g.data;
  if (!v) return null;
  const live: any[] = v.live ?? [];
  const sb = v.scoreboard ?? {};
  return (
    <section className="panel min-w-0 p-3.5 sm:p-4">
      <CardHead icon={<Ico name="/guardian" size={16} />} title={<>Trade Guardian <Badge tone="mute">Admin</Badge></>} right={<ViewAll to="/guardian" />} />
      <div className="flex items-center gap-3">
        <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full border-2 ${live.length ? "border-warn text-warn" : "border-bull/60 text-bull"}`} aria-hidden="true">
          <span className="num text-lg font-bold">{live.length}</span>
        </span>
        <div className="min-w-0">
          <div className="text-sm font-semibold">{live.length ? `${live.length} recommendation${live.length > 1 ? "s" : ""} waiting` : "Nothing to review"}</div>
          <div className="text-xs text-mute">{v.enabled === false ? "Guardian is switched off" : `Last check ${ago(v.status?.last_check)}`}</div>
        </div>
      </div>
      {live.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {live.slice(0, 3).map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-2 text-sm">
              <span className="min-w-0 truncate">{base(r.symbol)} <span className="text-xs uppercase text-mute">{r.timeframe}</span> <span className={`text-xs font-bold ${r.side > 0 || r.side === "LONG" ? "text-bull" : "text-bear"}`}>{r.side > 0 || r.side === "LONG" ? "LONG" : "SHORT"}</span></span>
              <Badge tone={String(r.level).toUpperCase().includes("CLOSE") ? "bear" : "warn"} caps>{r.level}</Badge>
            </li>
          ))}
        </ul>
      )}
      {isNum(sb.n) && sb.n > 0 && <p className="num mt-3 text-xs text-mute">Shadow results: {sb.net_r >= 0 ? "+" : ""}{sb.net_r}R over {sb.n} checked · helped {sb.helped}, hurt {sb.hurt}</p>}
      <Link to="/guardian" className="btn btn-primary mt-3 w-full justify-center">Review</Link>
    </section>
  );
}

/* ---- row 4 ------------------------------------------------------------------------------------------------------ */
type Act = { ts: number; text: ReactNode; tag: string; tone: Tone; key: string };
const RESULT: Record<string, string> = { TP1: "target 1", TP2: "target 2", TP3: "all targets", STOPPED: "stopped", EXPIRED: "time limit", NOT_FILLED: "entry missed", VOID: "void" };

export function RecentActivityCard({ track, briefing }: { track: any; briefing: any }) {
  const ev = useApi<any>("/alert-events");
  const items: Act[] = useMemo(() => {
    const out: Act[] = [];
    for (const x of (track?.live?.signals ?? []) as any[]) {
      const name = `${base(x.symbol)} ${String(x.timeframe).toUpperCase()} ${x.side}`;
      if (isNum(x.created_at)) out.push({ key: `o${x.id}`, ts: x.created_at, tag: "Opened", tone: "accent", text: <>Signal published: <span className="font-medium">{name}</span></> });
      if (isNum(x.closed_at) && x.status !== "OPEN") {
        const r = x.return_pct;
        out.push({ key: `c${x.id}`, ts: x.closed_at, tag: isNum(r) ? (r > 0 ? "Win" : "Loss") : "Closed", tone: isNum(r) ? (r > 0 ? "bull" : "bear") : "mute",
          text: <>Signal closed: <span className="font-medium">{name}</span> · {RESULT[x.status] ?? String(x.status).toLowerCase()}{isNum(r) ? <span className={`num ${toneText(r)}`}> {fmtPctRaw(r)}</span> : null}</> });
      }
    }
    for (const e of (ev.data?.events ?? []) as any[]) out.push({ key: `a${e.id}`, ts: e.created_at, tag: "Alert", tone: "warn", text: <span className="min-w-0">{e.message}</span> });
    if (isNum(briefing?.at)) out.push({ key: "brief", ts: briefing.at, tag: "AI", tone: "ai", text: <>Market briefing updated</> });
    return out.filter((a) => isNum(a.ts)).sort((a, b) => b.ts - a.ts).slice(0, 7);
  }, [track, ev.data, briefing]);
  return (
    <section className="panel min-w-0 p-3.5 sm:p-4">
      <CardHead icon={<Ico name="/alerts" size={16} />} title="Recent activity" right={<ViewAll to="/alerts" label="Your alerts" />} />
      {items.length ? (
        <ul className="divide-y divide-glass/[0.06]">
          {items.map((a) => (
            <li key={a.key} className="flex items-start gap-2.5 py-2 text-sm">
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${a.tone === "bull" ? "bg-bull" : a.tone === "bear" ? "bg-bear" : a.tone === "warn" ? "bg-warn" : a.tone === "ai" ? "bg-ai" : a.tone === "accent" ? "bg-accent" : "bg-mute"}`} aria-hidden="true" />
              <span className="min-w-0 flex-1 break-words text-text/90">{a.text}</span>
              <span className="flex shrink-0 flex-col items-end gap-1 min-[400px]:flex-row min-[400px]:items-center min-[400px]:gap-2">
                <Badge tone={a.tone}>{a.tag}</Badge>
                <span className="num text-xs text-mute" title={new Date(a.ts).toLocaleString()}>{ago(a.ts)}</span>
              </span>
            </li>
          ))}
        </ul>
      ) : <Empty>Nothing yet since the restart.</Empty>}
    </section>
  );
}

function maxDrawdown(cum: number[]): number {
  let peak = 0, dd = 0;
  for (const v of cum) { peak = Math.max(peak, v); dd = Math.max(dd, peak - v); }
  return dd;
}

export function PerformanceCard({ track, loading }: { track: any; loading: boolean }) {
  const [win, setWin] = useState<"all" | "7d">("all");
  const s = track?.live?.summary ?? {};
  const l7 = track?.last_7d;
  const curve: number[] = useMemo(() => [0, ...((track?.live?.curve ?? []) as any[]).map((c) => c.cum_return_pct).filter(isNum)], [track]);
  const since = track?.restart?.at ?? track?.record_since;
  const n = win === "all" ? s.closed ?? 0 : l7?.closed ?? 0;
  const wr = win === "all" ? s.win_rate : l7?.win_rate;
  const tot = win === "all" ? s.total_return_pct : l7?.total_return_pct;
  const dd = win === "all" && curve.length > 1 ? maxDrawdown(curve) : null;
  const pf = win === "all" ? s.profit_factor : null;
  const tile = (k: string, v: ReactNode, cls = "") => (
    <div className="min-w-0"><div className="text-xs text-mute">{k}</div><div className={`num mt-0.5 truncate text-lg font-semibold ${cls}`}>{v}</div></div>
  );
  return (
    <section className="panel min-w-0 p-3.5 sm:p-4">
      <CardHead icon={<Ico name="/achievements" size={16} />} title="Performance overview"
        right={<Segmented value={win} options={[["all", "Since restart"], ["7d", "7 days"]] as const} onChange={setWin} label="Period" />} />
      {!track && loading ? <div className="skeleton h-24 rounded" /> : (
        <>
          <div className="grid grid-cols-2 gap-x-3 gap-y-3 min-[480px]:grid-cols-4">
            {tile("Win rate", isNum(wr) && n ? `${(wr * 100).toFixed(0)}%` : DASH)}
            {tile("Total return", isNum(tot) && n ? fmtPctRaw(tot) : DASH, toneText(n ? tot : null))}
            {tile("Max drawdown", isNum(dd) && n ? `−${dd.toFixed(2)}%` : win === "7d" ? <span className="text-sm font-normal text-mute">all-time only</span> : DASH, isNum(dd) && dd > 0 ? "text-bear" : "")}
            {tile("Profit factor", isNum(pf) && n ? pf.toFixed(2) : win === "7d" ? <span className="text-sm font-normal text-mute">all-time only</span> : DASH)}
          </div>
          {win === "all" && curve.length > 2 && (
            <div className="mt-3"><Sparkline values={curve} tone={curve[curve.length - 1] >= 0 ? "--bull" : "--bear"} className="h-14 w-full" label="Cumulative net return of closed calls" />
              <div className="mt-0.5 text-xs text-mute">Cumulative net return, closed calls in order</div></div>
          )}
          <p className={`mt-3 text-xs ${n < 30 ? "text-warn" : "text-mute"}`}>
            {n < 30 ? <>Too early to judge: {n} closed {win === "all" ? <>since {fmtDate(since)}</> : "in the last 7 days"}{n ? "; short records swing a lot." : "."}</> : <>{n} closed {win === "all" ? <>since {fmtDate(since)}</> : "in 7 days"}.</>}
            {" "}<span className="text-mute">After fees, equal size, no leverage.</span> <Link to="/results" className="text-accent hover:underline">Results →</Link>
          </p>
        </>
      )}
    </section>
  );
}
