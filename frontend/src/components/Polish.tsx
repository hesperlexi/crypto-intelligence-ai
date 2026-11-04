// Visual building blocks shared by the dashboard and the shell: coin icons, the live ticker tape, the
// market briefing panel ("Know why") and skeleton placeholders. (The old Home hero was replaced by v2.20 Overview.)
import { useState } from "react";
import { Link } from "react-router-dom";
import { ago, base, fmtPctRaw, fmtPrice, slug } from "../lib/format";
import { Badge } from "./kit";
import { useLive } from "../lib/live";

const ICONS = "https://cdn.jsdelivr.net/gh/spothq/cryptocurrency-icons@0.18.1/svg/color";

function hue(s: string) {
  let h = 0;
  for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
}

/** The coin's logo when a public icon exists, otherwise a coloured monogram. */
// Coins without an icon file: remembered for the whole session, so a re-mounted avatar shows its letters at once
// instead of trying the missing image again (that try-then-fallback flashed on every refresh).
const MISSING_ICONS = new Set<string>();

export function CoinAvatar({ symbol, size = 34 }: { symbol: string; size?: number }) {
  const b = base(symbol);
  const [failed, setFailed] = useState(() => MISSING_ICONS.has(b));
  const h = hue(b);
  if (b === "GOLD") {
    return (
      <span aria-hidden="true" className="flex shrink-0 items-center justify-center rounded-full font-bold ring-1 ring-[#f0b90b]/40"
        style={{ width: size, height: size, fontSize: size * 0.38, color: "#3b2a00", background: "radial-gradient(circle at 35% 30%, #fff1b8, #f0b90b 55%, #b8860b)" }}>Au</span>
    );
  }
  if (!failed) {
    return <img src={`${ICONS}/${b.toLowerCase()}.svg`} alt="" width={size} height={size} loading="lazy" onError={() => { MISSING_ICONS.add(b); setFailed(true); }}
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
      <Link key={k + s} to={`/asset/${slug(s)}`} className="flex shrink-0 items-center gap-1.5 px-3.5 text-xs text-mute transition-colors hover:text-text" tabIndex={k === "b" ? -1 : 0} aria-hidden={k === "b" ? true : undefined}>
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

/** v2.16 market briefing (views/market_context.briefing): 3-5 sentences from the engine's own numbers + a few facts.
 *  Owner (4 Nov 2026): the hero keeps its original one-line summary; the briefing opens only from a small "Know why"
 *  button beside it. */
export function BriefingPanel({ b }: { b: any }) {
  return (
    <div id="market-why" className="mt-3 max-w-2xl rounded-xl border border-glass/[0.08] bg-ink/40 p-3.5">
      <p className="text-sm leading-relaxed text-text/90">{b.text}</p>
      {(b.bullets ?? []).length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {(b.bullets as string[]).slice(0, 5).map((t) => <li key={t} className="fact-pill">{t}</li>)}
        </ul>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <Badge tone={b.source === "ai" ? "ai" : "mute"} title={b.note}>{b.source === "ai" ? "AI briefing" : "Briefing"}</Badge>
        <span className="text-xs text-mute">{ago(b.at)}</span>
      </div>
    </div>
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
