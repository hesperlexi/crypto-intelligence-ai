// v2.68 public results page (/record, owner 22 Nov 2026): the record after fees for anyone - shareable in Telegram or
// ads. Data = views/public_record (summary, per timeframe, last 7 days, daily running total, last 30 CLOSED calls). Open
// calls and price levels are never shown; wins and losses alike.
import { useApi } from "../lib/api";
import { base, isNum } from "../lib/format";
import { CoinAvatar } from "./Polish";

const pct = (v: number | null | undefined, d = 2) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "—");
const STATUS: Record<string, string> = { TP1: "Target 1", TP2: "Target 2", TP3: "Target 3", STOPPED: "Stop-loss", BE: "Break-even", EXPIRED: "Time limit", CLOSED: "Closed" };
const day = (ms: number) => new Date(ms).toLocaleDateString(undefined, { day: "numeric", month: "short" });

function RunLine({ pts }: { pts: { day: string; cum: number }[] }) {
  if (pts.length < 2) return null;
  const W = 600, H = 150, lo = Math.min(0, ...pts.map((p) => p.cum)), hi = Math.max(0, ...pts.map((p) => p.cum)) || 1;
  const x = (i: number) => (i / (pts.length - 1)) * W, y = (v: number) => H - 8 - ((v - lo) / (hi - lo || 1)) * (H - 16);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.cum).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1].cum;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-36 w-full" role="img" aria-label={`Running total ${pct(last)} after fees`}>
      <defs><linearGradient id="pr-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={last >= 0 ? "rgb(var(--bull))" : "rgb(var(--bear))"} stopOpacity="0.28" /><stop offset="1" stopColor="transparent" /></linearGradient></defs>
      <line x1="0" x2={W} y1={y(0)} y2={y(0)} stroke="rgb(var(--glass) / 0.25)" strokeDasharray="4 5" vectorEffect="non-scaling-stroke" />
      <path d={`${d} L${W} ${H} L0 ${H} Z`} fill="url(#pr-fill)" />
      <path d={d} fill="none" stroke={last >= 0 ? "rgb(var(--bull))" : "rgb(var(--bear))"} strokeWidth="2.4" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}

export default function PublicRecord() {
  const v = useApi<any>("/public-record");
  const d = v.data;
  const share = async () => {
    const url = `${window.location.origin}/record`;
    try { if (navigator.share) await navigator.share({ title: "Crypto Intelligence AI - results", url }); else { await navigator.clipboard.writeText(url); alert("Link copied"); } } catch { /* closed */ }
  };
  if (!d) return <p className="text-sm text-mute">{v.loading ? "Loading the record…" : "The record will appear here after the next engine run."}</p>;
  const s = d.summary ?? {};
  return (
    <div className="pr space-y-5">
      <p className="text-sm">Every signal the AI published{d.since ? ` since ${day(d.since)}` : ""}, wins and losses alike, <b className="text-text">after fees</b>. Open signals are not shown.</p>
      <div className="pr-kpis">
        <div><span>Win rate</span><b className="num">{isNum(s.win_rate) ? `${Math.round(s.win_rate * 100)}%` : "—"}</b><em>{s.closed ?? 0} closed</em></div>
        <div><span>Total result</span><b className={`num ${(s.total_return_pct ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{pct(s.total_return_pct, 1)}</b><em>sum of price moves, no leverage</em></div>
        <div><span>Profit factor</span><b className="num">{isNum(s.profit_factor) ? s.profit_factor.toFixed(2) : "—"}</b><em>won ÷ lost</em></div>
        <div><span>Last 7 days</span><b className={`num ${(d.last_7d?.total_return_pct ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{pct(d.last_7d?.total_return_pct, 1)}</b><em>{d.last_7d?.wins ?? 0} won · {d.last_7d?.losses ?? 0} lost</em></div>
      </div>
      <section className="pr-box">
        <div className="flex items-baseline justify-between"><h3>Running total</h3><span className="text-xs">daily, after fees</span></div>
        <RunLine pts={d.daily ?? []} />
      </section>
      <section className="pr-box">
        <h3>By timeframe</h3>
        <ul className="pr-tf">
          {Object.entries<any>(d.by_timeframe ?? {}).map(([tf, x]) => (
            <li key={tf}><b>{tf.toUpperCase()}</b><span>{x.closed} closed</span><span>{isNum(x.win_rate) ? `${Math.round(x.win_rate * 100)}% won` : "—"}</span><span className={`num ${(x.total_return_pct ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{pct(x.total_return_pct, 1)}</span></li>
          ))}
        </ul>
      </section>
      <section className="pr-box">
        <h3>Latest closed signals</h3>
        <ul className="pr-list">
          {(d.recent ?? []).map((r: any, i: number) => (
            <li key={i}>
              <CoinAvatar symbol={r.symbol} size={24} />
              <b>{base(r.symbol)}</b>
              <span className={r.side === "LONG" ? "text-bull" : "text-bear"}>{r.side === "LONG" ? "▲" : "▼"} {String(r.timeframe).toUpperCase()}</span>
              <span className="pr-st">{STATUS[r.status] ?? r.status}</span>
              <span className={`num ml-auto font-semibold ${(r.net_pct ?? 0) > 0 ? "text-bull" : "text-bear"}`}>{pct(r.net_pct)}</span>
              <span className="pr-day">{isNum(r.closed_at) ? day(r.closed_at) : ""}</span>
            </li>
          ))}
        </ul>
      </section>
      {d.method && <p className="text-xs leading-relaxed">{d.method}</p>}
      <p className="text-xs leading-relaxed">Past results do not promise future results. Signals are analysis, not financial advice; trading with leverage can lose more than you expect.</p>
      <div className="flex flex-wrap gap-2"><button type="button" className="btn btn-primary" onClick={share}>Share this page</button><a className="btn" href="/">Open the app</a></div>
    </div>
  );
}
