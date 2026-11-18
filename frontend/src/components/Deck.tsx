// v2.56 Intelligence Deck (owner brief, 18 Nov 2026): pieces of the redesigned Home. Real data only, from documents
// Home already reads (views/dashboard_4h, /context, views/track_record) and the live price socket - no extra reads.
//   MarketDial        one instrument for the whole market: the watchlist as a ring of segments (each coin's 4H
//                     regime / call colour), Fear & Greed as an inner arc with a gold needle, BTC's live price inside.
//   OpportunityBoard  the strongest setups that pass every check right now, as a ranked board.
import { memo } from "react";
import { Link } from "react-router-dom";
import { base, DASH, fmtPctRaw, fmtPrice, isNum, slug } from "../lib/format";
import { useTickerThrottled } from "../lib/live";
import { CoinAvatar } from "./Polish";

const TAU = Math.PI * 2;
function arc(cx: number, cy: number, r: number, a0: number, a1: number) {
  const p = (a: number) => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  const [x0, y0] = p(a0), [x1, y1] = p(a1);
  return `M${x0.toFixed(2)} ${y0.toFixed(2)} A${r} ${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}
const side = (r: any) => {
  const s = String(r?.signal ?? r?.decision ?? "");
  if (/BUY|LONG/.test(s)) return 1;
  if (/SELL|SHORT/.test(s)) return -1;
  const g = String(r?.regime ?? "");
  return /BULL|UP/.test(g) ? 0.5 : /BEAR|DOWN/.test(g) ? -0.5 : 0;
};
const segColor = (v: number) => (v >= 1 ? "rgb(var(--bull))" : v > 0 ? "rgb(var(--bull) / 0.45)" : v <= -1 ? "rgb(var(--bear))" : v < 0 ? "rgb(var(--bear) / 0.45)" : "rgb(var(--glass) / 0.16)");

/** The market as one dial. Outer ring: one segment per watched coin (green = buy call, faint green = bullish regime,
 *  red / faint red the same for sells, grey = neutral). Inner arc: Fear & Greed 0-100 with a needle. Centre: BTC live. */
export const MarketDial = memo(function MarketDial({ rows, fg, fgLabel, status, size = 240 }: {
  rows?: any[]; fg?: number | null; fgLabel?: string; status?: any; size?: number;
}) {
  const r = (rows ?? []).filter((x) => x?.symbol);
  const n = Math.max(1, r.length);
  const C = 120, R1 = 104, R2 = 82;
  const gap = n > 1 ? 0.035 : 0;
  const start = -Math.PI / 2;
  // Fear & Greed arc: 240° sweep at the bottom-open orientation
  const f0 = Math.PI * 0.75, f1 = Math.PI * 2.25;
  const fv = isNum(fg) ? Math.max(0, Math.min(100, fg)) : null;
  const fa = fv == null ? null : f0 + (f1 - f0) * (fv / 100);
  const bull = status?.bull ?? r.filter((x) => side(x) > 0).length;
  const bear = status?.bear ?? r.filter((x) => side(x) < 0).length;
  return (
    <figure className="deck-dial" style={{ width: size, maxWidth: "100%" }}>
      <svg viewBox="0 0 240 240" role="img" aria-label={`Market dial: ${bull} bullish and ${bear} bearish of ${r.length} coins; Fear and Greed ${fv ?? "unknown"}`}>
        <defs>
          <radialGradient id="dd-core"><stop offset="0%" stopColor="rgb(var(--accent) / 0.16)" /><stop offset="70%" stopColor="rgb(var(--ai) / 0.05)" /><stop offset="100%" stopColor="transparent" /></radialGradient>
          <linearGradient id="dd-fg" x1="0" x2="1"><stop offset="0%" stopColor="rgb(var(--bear))" /><stop offset="50%" stopColor="rgb(var(--accent))" /><stop offset="100%" stopColor="rgb(var(--bull))" /></linearGradient>
        </defs>
        <circle cx={C} cy={C} r={70} fill="url(#dd-core)" />
        {/* tick ring */}
        {Array.from({ length: 60 }, (_, i) => {
          const a = (i / 60) * TAU;
          const long = i % 5 === 0;
          return <line key={i} x1={C + 114 * Math.cos(a)} y1={C + 114 * Math.sin(a)} x2={C + (long ? 109 : 111) * Math.cos(a)} y2={C + (long ? 109 : 111) * Math.sin(a)} stroke="rgb(var(--glass) / 0.22)" strokeWidth={long ? 1.2 : 0.6} />;
        })}
        {/* breadth ring: one segment per coin */}
        {r.map((x, i) => {
          const a0 = start + (i / n) * TAU + gap / 2, a1 = start + ((i + 1) / n) * TAU - gap / 2;
          return (
            <Link key={x.symbol} to={`/asset/${slug(x.symbol)}`} aria-label={`${base(x.symbol)}: ${x.signal ?? x.regime ?? "neutral"}`}>
              <path d={arc(C, C, R1, a0, a1)} stroke={segColor(side(x))} strokeWidth={9} fill="none" strokeLinecap="butt" className="deck-seg"><title>{`${base(x.symbol)} · ${x.signal ?? String(x.regime ?? "neutral").replace(/_/g, " ").toLowerCase()}`}</title></path>
            </Link>
          );
        })}
        {/* fear & greed arc */}
        <path d={arc(C, C, R2, f0, f1)} stroke="rgb(var(--glass) / 0.08)" strokeWidth={5} fill="none" strokeLinecap="round" />
        {fa != null && <path d={arc(C, C, R2, f0, fa)} stroke="url(#dd-fg)" strokeWidth={5} fill="none" strokeLinecap="round" opacity={0.9} />}
        {fa != null && <circle cx={C + R2 * Math.cos(fa)} cy={C + R2 * Math.sin(fa)} r={5} fill="rgb(var(--accent-2))" stroke="rgb(var(--ink))" strokeWidth={2} />}
      </svg>
      <DialCentre />
      <figcaption className="deck-dial-cap">
        <span><b className="text-bull">{bull}</b> bull · <b className="text-bear">{bear}</b> bear <span className="text-mute">of {r.length}</span></span>
        <span className="text-mute">Fear &amp; Greed <b className="num text-text">{fv ?? DASH}</b>{fgLabel ? ` · ${fgLabel}` : ""}</span>
      </figcaption>
    </figure>
  );
});

/** BTC live inside the dial: its own 1 s subscription, so the dial does not redraw on every price. */
function DialCentre() {
  const t = useTickerThrottled("BTC/USDT", 1000);
  const ch = t?.change_pct;
  return (
    <div className="deck-dial-centre" aria-live="off">
      <span className="text-xs text-mute">Bitcoin</span>
      <span className="num text-xl font-semibold tracking-tight">{isNum(t?.last) ? `$${fmtPrice(t!.last)}` : DASH}</span>
      <span className={`num text-xs font-medium ${!isNum(ch) ? "text-mute" : ch >= 0 ? "text-bull" : "text-bear"}`}>{isNum(ch) ? `${ch >= 0 ? "▲" : "▼"} ${fmtPctRaw(ch)}` : ""}</span>
    </div>
  );
}

/** The setups that pass every check right now (views/dashboard opportunities), ranked; each row opens its signal. */
export function OpportunityBoard({ rows, tf = "4h" }: { rows?: any[]; tf?: string }) {
  const list = (rows ?? []).slice(0, 6);
  if (!list.length) return <div className="empty-state">No setup passes every check right now. The engine checks again every cycle.</div>;
  return (
    <ol className="deck-board">
      {list.map((o, i) => {
        const s = side(o) > 0 ? 1 : side(o) < 0 ? -1 : 0;
        return (
          <li key={o.symbol}>
            <Link to={`/signals?timeframe=${tf}&symbol=${encodeURIComponent(o.symbol)}`} className={`deck-opp ${s > 0 ? "is-long" : s < 0 ? "is-short" : ""}`}>
              <span className="deck-rank num">{i + 1}</span>
              <span className="flex min-w-0 items-center gap-2"><CoinAvatar symbol={o.symbol} size={22} /><b className="truncate">{base(o.symbol)}</b></span>
              <span className={`deck-side ${s > 0 ? "text-bull" : s < 0 ? "text-bear" : "text-mute"}`}>{s > 0 ? "▲ Long" : s < 0 ? "▼ Short" : o.decision ?? "Wait"}</span>
              <span className="text-xs text-mute">{o.grade ? `Grade ${o.grade}` : tf.toUpperCase()}</span>
              <span className="num text-right text-sm">{isNum(o.risk_reward) ? <>1 : {o.risk_reward.toFixed(1)}</> : DASH}<span className="block text-xs text-mute">reward</span></span>
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
