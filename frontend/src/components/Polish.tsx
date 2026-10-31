// Visual building blocks shared by the dashboard and the shell: coin icons, the live ticker tape, the
// dashboard hero and skeleton placeholders.
import { useState } from "react";
import { Link } from "react-router-dom";
import { base, fmtCompact, fmtPctRaw, fmtPrice, slug } from "../lib/format";
import { useLive } from "../lib/live";
import { useSession } from "../lib/session";

const ICONS = "https://cdn.jsdelivr.net/gh/spothq/cryptocurrency-icons@0.18.1/svg/color";

function hue(s: string) {
  let h = 0;
  for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
}

/** The coin's logo when a public icon exists, otherwise a coloured monogram. */
export function CoinAvatar({ symbol, size = 34 }: { symbol: string; size?: number }) {
  const b = base(symbol);
  const [failed, setFailed] = useState(false);
  const h = hue(b);
  if (b === "GOLD") {
    return (
      <span aria-hidden="true" className="flex shrink-0 items-center justify-center rounded-full font-bold ring-1 ring-[#f0b90b]/40"
        style={{ width: size, height: size, fontSize: size * 0.38, color: "#3b2a00", background: "radial-gradient(circle at 35% 30%, #fff1b8, #f0b90b 55%, #b8860b)" }}>Au</span>
    );
  }
  if (!failed) {
    return <img src={`${ICONS}/${b.toLowerCase()}.svg`} alt="" width={size} height={size} loading="lazy" onError={() => setFailed(true)}
      className="shrink-0 rounded-full bg-glass/[0.04] ring-1 ring-glass/10" style={{ width: size, height: size }} />;
  }
  return (
    <span aria-hidden="true" className="flex shrink-0 items-center justify-center rounded-full font-semibold text-white ring-1 ring-glass/15"
      style={{ width: size, height: size, fontSize: size * 0.36, background: `linear-gradient(135deg, hsl(${h} 70% 48%), hsl(${(h + 40) % 360} 75% 34%))` }}>
      {b.slice(0, 3)}
    </span>
  );
}

/** Exchange-style scrolling price strip under the header. Pauses on hover; still for reduced motion. */
export function TickerTape() {
  const { tickers, symbols } = useLive();
  const items = symbols.filter((s) => tickers[s]?.last != null);
  if (items.length < 2) return null;
  const row = (k: string) => items.map((s) => {
    const t = tickers[s];
    const c = t.change_pct ?? 0;
    return (
      <Link key={k + s} to={`/asset/${slug(s)}`} className="flex shrink-0 items-center gap-1.5 px-3.5 text-[11px] text-mute transition-colors hover:text-text" tabIndex={k === "b" ? -1 : 0} aria-hidden={k === "b" ? true : undefined}>
        <span className="font-semibold text-text/80">{base(s)}</span>
        <span className="num text-text/70">{fmtPrice(t.last)}</span>
        <span className={`num ${c >= 0 ? "text-bull/85" : "text-bear/85"}`}>{fmtPctRaw(c)}</span>
      </Link>
    );
  });
  // enough copies to fill wide screens, then the same again so the loop is seamless
  const reps = Math.max(1, Math.ceil(12 / items.length));
  const seq = (k: string) => Array.from({ length: reps }, (_, i) => row(`${k}${i}`));
  return (
    <div className="ticker-tape border-b border-glass/[0.06]" aria-label="Live prices">
      <div className="ticker-track" style={{ animationDuration: `${Math.max(25, items.length * reps * 4)}s` }}>
        <div className="flex">{seq("a")}</div>
        <div className="flex">{seq("b")}</div>
      </div>
    </div>
  );
}

function greeting() {
  const h = new Date().getHours();
  return h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

/** One cell of the Home overview strip. */
function HeroMetric({ k, v, sub, to, children }: { k: string; v: React.ReactNode; sub?: React.ReactNode; to?: string; children?: React.ReactNode }) {
  const body = (
    <>
      <div className="flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-mute">{children}{k}</div>
      <div className="num mt-1.5 truncate text-[22px] font-semibold leading-none tracking-tight sm:text-2xl">{v}</div>
      {sub != null && <div className="num mt-1.5 truncate text-[11px] text-mute">{sub}</div>}
    </>
  );
  return to ? <Link to={to} className="hero-metric">{body}</Link> : <div className="hero-metric">{body}</div>;
}

/** Top of the dashboard: market-mood headline, then one strip of the numbers that matter at a glance
 *  (BTC, ETH, Fear & Greed, BTC dominance, total market, active calls). */
export function DashboardHero({ rows, status, tf, sentiment, market, basket }: { rows?: any[]; status?: any; tf: string; sentiment?: any; market?: any; basket?: any }) {
  const s = useSession();
  const { tickers } = useLive();
  const first = (s?.name || s?.email || "").split(/[ @]/)[0];
  const r = rows ?? [];
  const buys = r.filter((x) => x.signal?.includes("BUY")).length;
  const sells = r.filter((x) => x.signal?.includes("SELL")).length;
  const best = [...r].filter((x) => x.signal && !x.signal.includes("HOLD")).sort((a, b) => (b.score ?? 0) - (a.score ?? 0))[0];
  const mood = status?.status ?? null;
  const moodText = mood === "BULL" ? "leaning bullish" : mood === "BEAR" ? "leaning bearish" : mood === "NEUTRAL" ? "mixed" : "warming up";
  const moodCls = mood === "BULL" ? "text-bull" : mood === "BEAR" ? "text-bear" : "text-accent";
  const kpis = ["BTC/USDT", "ETH/USDT"].map((sym) => ({ sym, t: tickers[sym], row: r.find((x) => x.symbol === sym) }));
  const fg = isNumber(sentiment?.value) ? sentiment.value : null;
  const fgCls = fg == null ? "" : fg >= 55 ? "text-bull" : fg <= 45 ? "text-bear" : "text-warn";
  const chg = (v: number | null | undefined) => <span className={v == null ? "text-mute" : v >= 0 ? "text-bull" : "text-bear"}>{fmtPctRaw(v)}</span>;
  return (
    <section className="hero relative overflow-hidden">
      <svg aria-hidden="true" className="hero-line pointer-events-none absolute inset-x-0 top-0 h-40 w-full" viewBox="0 0 1200 160" preserveAspectRatio="none">
        <defs>
          <linearGradient id="hl" x1="0" x2="1"><stop offset="0" stopColor="rgb(var(--accent))" stopOpacity="0" /><stop offset="0.6" stopColor="rgb(var(--accent))" stopOpacity="0.45" /><stop offset="1" stopColor="rgb(var(--accent-2))" stopOpacity="0.8" /></linearGradient>
          <linearGradient id="hf" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="rgb(var(--accent))" stopOpacity="0.1" /><stop offset="1" stopColor="rgb(var(--accent))" stopOpacity="0" /></linearGradient>
        </defs>
        <path d="M0 136 C 90 132, 150 144, 240 128 S 380 110, 470 118 S 620 92, 720 98 S 880 70, 980 76 S 1120 54, 1200 40 V 160 H 0 Z" fill="url(#hf)" />
        <path d="M0 136 C 90 132, 150 144, 240 128 S 380 110, 470 118 S 620 92, 720 98 S 880 70, 980 76 S 1120 54, 1200 40" fill="none" stroke="url(#hl)" strokeWidth="2" />
      </svg>
      <div className="relative grid gap-5 p-5 sm:p-7 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] lg:items-end">
        <div>
          <p className="text-sm text-mute">{greeting()}{first ? `, ${first}` : ""} · {tf.toUpperCase()} chart</p>
          <h1 className="font-display mt-1.5 text-[26px] font-bold leading-[1.12] tracking-tight sm:text-[38px]">
            The market is <span className={moodCls}>{moodText}</span>.
          </h1>
          <p className="mt-2.5 text-sm text-mute">
            {r.length ? <><span className="font-medium text-bull">{buys} buy</span> · <span className="font-medium text-bear">{sells} sell</span> signals across {r.length} coins{best ? <> · strongest: <Link to={`/asset/${slug(best.symbol)}`} className="font-medium text-text hover:text-accent">{base(best.symbol)} {best.signal}</Link></> : null}</> : "Signals appear after the next engine run."}
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            <Link to="/futures" className="btn btn-primary px-4"><span className="sm:hidden">Signals</span><span className="hidden sm:inline">Futures signals</span></Link>
            <Link to="/alerts" className="btn px-4">Set an alert</Link>
            <Link to="/paper" className="btn px-4">Paper trade</Link>
          </div>
        </div>
        <div className="rounded-xl border border-glass/[0.08] bg-ink/40 p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="label">Market mood</div>
            <span className={`text-xs font-semibold ${moodCls}`}>{mood ?? "—"}</span>
          </div>
          <div className="mt-2.5 flex h-2 overflow-hidden rounded-full bg-glass/[0.06]" aria-hidden="true">
            {status && <><div className="bg-bull" style={{ flex: status.bull || 0 }} /><div className="bg-warn/70" style={{ flex: status.neutral || 0 }} /><div className="bg-bear" style={{ flex: status.bear || 0 }} /></>}
          </div>
          <div className="num mt-2 text-sm">{status ? <><span className="text-bull">{status.bull} bull</span> · <span className="text-mute">{status.neutral} neutral</span> · <span className="text-bear">{status.bear} bear</span></> : "—"}</div>
          {status?.basis && <p className="mt-1.5 text-[11px] leading-snug text-mute">{status.basis}</p>}
        </div>
      </div>
      {/* the overview strip */}
      <div className="hero-strip relative">
        {kpis.map(({ sym, t, row }) => {
          const ch = t?.change_pct ?? row?.change_24h_pct;
          return (
            <HeroMetric key={sym} k={base(sym)} to={`/asset/${slug(sym)}`} v={fmtPrice(t?.last ?? row?.price)}
              sub={<>{chg(ch)} 24h{row?.signal ? ` · ${row.signal}` : ""}</>}>
              <CoinAvatar symbol={sym} size={14} />
            </HeroMetric>
          );
        })}
        <HeroMetric k="Fear & Greed" v={<span className={fgCls}>{fg ?? "—"}</span>} sub={sentiment ? `${sentiment.label}${isNumber(sentiment.change_7d) ? ` · ${sentiment.change_7d > 0 ? "+" : ""}${sentiment.change_7d} in 7d` : ""}` : "unavailable"} />
        <HeroMetric k="BTC dominance" v={isNumber(market?.btc_dominance) ? `${market.btc_dominance.toFixed(1)}%` : "—"} sub="share of total crypto market" />
        {market
          ? <HeroMetric k="Total market" v={`$${fmtCompact(market.total_market_cap_usd)}`} sub={<>{chg(market.market_cap_change_24h_pct)} 24h · CoinGecko</>} />
          : <HeroMetric k="Basket, 20d" v={basket ? <span className={basket.return >= 0 ? "text-bull" : "text-bear"}>{fmtPctRaw(basket.return * 100)}</span> : "—"} sub="equal-weight proxy, not total market cap" />}
        <HeroMetric k={`Active calls · ${tf.toUpperCase()}`} to="/signals" v={<><span className="text-bull">{buys}</span><span className="text-mute/60"> / </span><span className="text-bear">{sells}</span></>} sub={`buy / sell of ${r.length} coins`} />
      </div>
    </section>
  );
}

const isNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** Shimmering placeholder blocks while data loads. */
export function Skeleton({ lines = 3, className = "" }: { lines?: number; className?: string }) {
  return (
    <div className={`space-y-2.5 py-2 ${className}`} aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => <div key={i} className="skeleton h-3.5 rounded-md" style={{ width: `${92 - ((i * 23) % 40)}%` }} />)}
    </div>
  );
}
