// Visual building blocks shared by the dashboard and the shell: coin icons, the live ticker tape, the
// dashboard hero and skeleton placeholders.
import { useState } from "react";
import { Link } from "react-router-dom";
import { base, fmtPctRaw, fmtPrice, slug } from "../lib/format";
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
      <Link key={k + s} to={`/asset/${slug(s)}`} className="flex shrink-0 items-center gap-2 px-4 text-xs hover:text-accent" tabIndex={k === "b" ? -1 : 0} aria-hidden={k === "b" ? true : undefined}>
        <CoinAvatar symbol={s} size={16} />
        <span className="font-semibold">{base(s)}</span>
        <span className="num text-text/90">{fmtPrice(t.last)}</span>
        <span className={`num ${c >= 0 ? "text-bull" : "text-bear"}`}>{c >= 0 ? "▲" : "▼"} {fmtPctRaw(Math.abs(c))}</span>
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

/** Top of the dashboard: greeting, market mood and the numbers that matter at a glance. */
export function DashboardHero({ rows, status, tf }: { rows?: any[]; status?: any; tf: string }) {
  const s = useSession();
  const { tickers } = useLive();
  const first = (s?.name || s?.email || "").split(/[ @]/)[0];
  const r = rows ?? [];
  const buys = r.filter((x) => x.signal?.includes("BUY")).length;
  const sells = r.filter((x) => x.signal?.includes("SELL")).length;
  const best = [...r].filter((x) => x.signal && !x.signal.includes("HOLD")).sort((a, b) => (b.score ?? 0) - (a.score ?? 0))[0];
  const mood = status?.status ?? null;
  const moodText = mood === "BULL" ? "leaning bullish" : mood === "BEAR" ? "leaning bearish" : mood === "NEUTRAL" ? "mixed" : "warming up";
  const kpis = ["BTC/USDT", "ETH/USDT"].map((sym) => ({ sym, t: tickers[sym], row: r.find((x) => x.symbol === sym) }));
  return (
    <section className="hero relative overflow-hidden rounded-2xl p-4 sm:p-6">
      <svg aria-hidden="true" className="hero-line pointer-events-none absolute inset-x-0 bottom-0 h-28 w-full" viewBox="0 0 1200 120" preserveAspectRatio="none">
        <defs>
          <linearGradient id="hl" x1="0" x2="1"><stop offset="0" stopColor="rgb(var(--accent))" stopOpacity="0" /><stop offset="0.5" stopColor="rgb(var(--accent))" stopOpacity="0.55" /><stop offset="1" stopColor="rgb(var(--accent-2))" stopOpacity="0.9" /></linearGradient>
          <linearGradient id="hf" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="rgb(var(--accent))" stopOpacity="0.16" /><stop offset="1" stopColor="rgb(var(--accent))" stopOpacity="0" /></linearGradient>
        </defs>
        <path d="M0 96 C 90 92, 150 104, 240 88 S 380 70, 470 78 S 620 52, 720 58 S 880 30, 980 36 S 1120 14, 1200 10 V 120 H 0 Z" fill="url(#hf)" />
        <path d="M0 96 C 90 92, 150 104, 240 88 S 380 70, 470 78 S 620 52, 720 58 S 880 30, 980 36 S 1120 14, 1200 10" fill="none" stroke="url(#hl)" strokeWidth="2.5" />
      </svg>
      <div className="relative grid gap-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:items-center">
        <div>
          <p className="text-sm text-mute">{greeting()}{first ? `, ${first}` : ""}</p>
          <h1 className="font-display mt-1 text-2xl font-bold leading-tight tracking-tight sm:text-[34px]">
            The market is <span className="text-gradient">{moodText}</span> on the {tf.toUpperCase()} chart.
          </h1>
          <p className="mt-2 text-sm text-mute">
            {r.length ? <><span className="text-bull">{buys} buy</span> · <span className="text-bear">{sells} sell</span> signals across {r.length} coins{best ? <> · strongest: <Link to={`/asset/${slug(best.symbol)}`} className="font-medium text-text hover:text-accent">{base(best.symbol)} {best.signal}</Link></> : null}</> : "Signals appear after the next engine run."}
          </p>
          <div className="mt-4 grid grid-cols-3 gap-2 sm:flex sm:flex-wrap">
            <Link to="/futures" className="btn btn-primary px-2 text-xs sm:px-4 sm:text-sm"><span className="sm:hidden">Signals</span><span className="hidden sm:inline">Futures signals</span></Link>
            <Link to="/alerts" className="btn px-2 text-xs sm:px-4 sm:text-sm">Set an alert</Link>
            <Link to="/paper" className="btn px-2 text-xs sm:px-4 sm:text-sm">Paper trade</Link>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2.5">
          {kpis.map(({ sym, t, row }) => {
            const ch = t?.change_pct ?? row?.change_24h_pct;
            return (
              <Link key={sym} to={`/asset/${slug(sym)}`} className="kpi p-3 sm:p-4">
                <div className="flex items-center gap-2"><CoinAvatar symbol={sym} size={26} /><span className="font-semibold">{base(sym)}</span>
                  <span className={`num ml-auto text-xs ${ch == null ? "text-mute" : ch >= 0 ? "text-bull" : "text-bear"}`}>{fmtPctRaw(ch)}</span></div>
                <div className="num mt-2 truncate text-xl font-semibold sm:text-2xl">{fmtPrice(t?.last ?? row?.price)}</div>
                <div className="mt-1 truncate text-[11px] text-mute">{row?.signal ? `${row.signal} · ${row.regime ?? ""}` : "live price"}</div>
              </Link>
            );
          })}
          <div className="kpi col-span-2 flex items-center justify-between gap-3 p-3 sm:p-4">
            <div>
              <div className="label">Market mood</div>
              <div className="mt-1 flex items-center gap-2 text-sm"><span className={`h-2 w-2 rounded-full ${mood === "BULL" ? "bg-bull" : mood === "BEAR" ? "bg-bear" : "bg-warn"}`} />{status ? `${status.bull} bull · ${status.neutral} neutral · ${status.bear} bear` : "—"}</div>
            </div>
            <div className="flex h-2 w-24 shrink-0 overflow-hidden rounded-full bg-glass/[0.06] sm:w-32" aria-hidden="true">
              {status && <><div className="bg-bull" style={{ flex: status.bull || 0 }} /><div className="bg-warn/70" style={{ flex: status.neutral || 0 }} /><div className="bg-bear" style={{ flex: status.bear || 0 }} /></>}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/** Shimmering placeholder blocks while data loads. */
export function Skeleton({ lines = 3, className = "" }: { lines?: number; className?: string }) {
  return (
    <div className={`space-y-2.5 py-2 ${className}`} aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => <div key={i} className="skeleton h-3.5 rounded-md" style={{ width: `${92 - ((i * 23) % 40)}%` }} />)}
    </div>
  );
}
