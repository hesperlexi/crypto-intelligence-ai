// v2.46 Command Centre additions (owner, 16 Nov 2026) + practice badges on the Trade page. Firebase-light by design:
// everything below reads documents the page already has (track_record, dashboard_4h, news) or public Binance data in the
// browser; the compare panel adds one read (views/radar) only when it is opened.
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/api";
import { useKlines } from "../lib/klines";
import { useLive } from "../lib/live";
import { ago, base, fmtPrice, isNum, slug } from "../lib/format";
import { stopNow } from "./RecordDetails";
import { Ring } from "./Premium";
import { CoinAvatar } from "./Polish";

const name = (s: string) => (base(s) === "PAXG" ? "GOLD" : base(s));
const pct = (v: number | null | undefined, d = 1) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "—");
const clamp = (v: number, a = 0, b = 1) => Math.max(a, Math.min(b, v));

/* ---------------------------------------------------------------- live signal journeys */
// v2.67 (owner, 22 Nov 2026): the same-side cap is 12, so up to 12 running calls are shown (the rest behind a link), and
// the two places get their own premium look: Command Centre = "flight corridors" (one lane per call), Home = "gauges"
// (one arc instrument per call). Both read only views/track_record (already open) and the live price socket.
export const JOURNEY_MAX = 12;

type Leg = {
  x: any; s: 1 | -1; tps: number[]; hits: boolean[]; at: (p: number) => number; px?: number; pending: boolean;
  sNow?: number; r: number | null; e: number; c: number; up: boolean; next: number; toNext: number | null; label: string;
};

function legOf(x: any, px: number | undefined): Leg {
  const s: 1 | -1 = x.side === "SHORT" ? -1 : 1;
  const tps = [x.tp1, x.tp2, x.tp3].filter(isNum) as number[];
  const end = x.runner?.on && isNum(x.runner.target) ? x.runner.target : tps[tps.length - 1];
  const span = s * (end - x.stop);
  const at = (p: number) => (span > 0 ? clamp((s * (p - x.stop)) / span) : 0);
  const pending = x.fill_status === "PENDING";
  const sNow = stopNow(x)?.price;
  const hits = [x.tp1_hit, x.tp2_hit, x.tp3_hit].map(Boolean);
  const r = isNum(px) && !pending && x.entry !== x.stop ? (s * (px - x.entry)) / Math.abs(x.entry - x.stop) : null;
  const e = at(x.entry), c = isNum(px) && !pending ? at(px) : e;
  const next = tps.findIndex((_t, k) => !hits[k]);
  const toNext = next >= 0 && isNum(px) ? (s * (tps[next] - px) / px) * 100 : null;
  const label = pending ? "waiting for entry" : next < 0 ? "all targets hit" : isNum(toNext) ? `TP${next + 1} in ${Math.abs(toNext).toFixed(2)}%` : `TP${next + 1} next`;
  return { x, s, tps, hits, at, px, pending, sNow, r, e, c, up: r == null || r >= 0, next, toNext, label };
}

function useOpenCalls(track: any) {
  const all: any[] = (track?.live?.signals ?? []).filter((x: any) => x.status === "OPEN");
  return { shown: all.slice(0, JOURNEY_MAX), more: Math.max(0, all.length - JOURNEY_MAX), total: all.length };
}

const Empty = () => <p className="py-6 text-center text-sm text-mute">No signals running right now. New calls appear here the moment they open.</p>;
const More = ({ n }: { n: number }) => (n > 0 ? <Link to="/results?tab=track" className="mt-2 block text-center text-xs font-medium text-accent hover:underline">+{n} more running · see all in Results</Link> : null);
const rTxt = (r: number | null) => (r == null ? "—" : `${r >= 0 ? "+" : ""}${r.toFixed(2)}R`);

/** Command Centre (owner's pick, 22 Nov 2026): one slim row per running call - coin, a thin line with the entry (gold)
 *  and target dots (lit when hit), the live price dot and its trail from the entry, the result in R and the next target.
 *  Summary strip on top; best progress first. */
export function SignalJourneys({ track }: { track: any }) {
  const { tickers } = useLive();
  const { shown, more, total } = useOpenCalls(track);
  if (!total) return <Empty />;
  const legs = shown.map((x) => legOf(x, tickers[x.symbol]?.last ?? undefined)).sort((a, b) => (b.r ?? -99) - (a.r ?? -99));
  const live = legs.filter((l) => l.r != null);
  const green = live.filter((l) => (l.r ?? 0) >= 0).length;
  const avg = live.length ? live.reduce((t, l) => t + (l.r ?? 0), 0) / live.length : null;
  const hitCount = legs.reduce((t, l) => t + l.hits.filter(Boolean).length, 0);
  return (
    <div className="fc-wrap">
      <div className="fc-sum">
        <span><b className="num">{total}</b> running</span>
        <span><b className="num text-bull">{green}</b> in profit</span>
        <span><b className="num text-bear">{live.length - green}</b> below entry</span>
        <span>avg <b className={`num ${(avg ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{rTxt(avg)}</b></span>
        <span><b className="num text-accent">{hitCount}</b> targets hit</span>
      </div>
      <ul className="sl-list">{legs.map((l) => <DeckRow key={l.x.id ?? `${l.x.symbol}${l.x.created_at}`} l={l} />)}</ul>
      <More n={more} />
    </div>
  );
}

/** Home (owner's pick, 22 Nov 2026): one arc gauge per running call. Left end = stop, right end = last target; red arc =
 *  risk, gold/green arc = room to the targets; the live price is the glowing needle tip, the filled arc runs from the
 *  entry to it; target diamonds light up when hit. */
export function SignalDeck({ track }: { track: any }) {
  const { tickers } = useLive();
  const { shown, more, total } = useOpenCalls(track);
  if (!total) return <Empty />;
  return (
    <div>
      <ul className="gd-grid">
        {shown.map((x) => <Gauge key={x.id ?? `${x.symbol}${x.created_at}`} l={legOf(x, tickers[x.symbol]?.last ?? undefined)} />)}
      </ul>
      <More n={more} />
    </div>
  );
}

function Gauge({ l }: { l: Leg }) {
  const { x } = l;
  const W = 168, cx = 84, cy = 80, R = 62;
  const pt = (t: number, rr = R) => { const a = Math.PI * (1 - t); return [cx + rr * Math.cos(a), cy - rr * Math.sin(a)] as const; };
  const arc = (t0: number, t1: number, rr = R) => {
    if (t1 - t0 < 0.002) return "";
    const [x0, y0] = pt(t0, rr), [x1, y1] = pt(t1, rr);
    return `M${x0.toFixed(2)} ${y0.toFixed(2)} A${rr} ${rr} 0 0 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
  };
  const tone = l.r == null ? "rgb(var(--mute))" : l.up ? "rgb(var(--bull))" : "rgb(var(--bear))";
  const [nx, ny] = pt(l.c);
  const st = l.at(isNum(l.sNow) ? l.sNow : x.stop), nt = l.next >= 0 ? l.at(l.tps[l.next]) : 1;
  const hp = nt > st ? (l.c - st) / (nt - st) : 0;
  const status: [string, string] = l.pending ? ["Waiting", "mute"] : l.r == null ? ["—", "mute"] : l.next < 0 ? ["All hit", "bull"]
    : hp >= 0.5 ? ["Healthy", "bull"] : hp >= 0.25 ? ["Watch", "warn"] : ["At risk", "bear"];
  const gid = `gd${String(x.id ?? x.symbol).replace(/[^\w]/g, "")}`;
  return (
    <li className={`gd-tile ${l.r == null ? "" : l.up ? "is-up" : "is-down"}`}>
      <Link to={`/asset/${slug(x.symbol)}?tf=${x.timeframe}`} className="gd-head">
        <CoinAvatar symbol={x.symbol} size={22} />
        <b className="truncate">{name(x.symbol)}</b>
        <span className={`gd-side ${l.s > 0 ? "is-long" : "is-short"}`}>{l.s > 0 ? "LONG" : "SHORT"}</span>
      </Link>
      <svg viewBox={`0 0 ${W} 96`} className="gd-svg" role="img" aria-label={`${name(x.symbol)}: ${l.pending ? "waiting for entry" : rTxt(l.r)}, ${l.hits.filter(Boolean).length} of ${l.tps.length} targets hit`}>
        <defs>
          <linearGradient id={`${gid}-rk`} x1="0" x2="1"><stop offset="0" stopColor="rgb(var(--bear))" stopOpacity="0.9" /><stop offset="1" stopColor="rgb(var(--bear))" stopOpacity="0.25" /></linearGradient>
          <linearGradient id={`${gid}-rw`} x1="0" x2="1"><stop offset="0" stopColor="rgb(var(--accent))" stopOpacity="0.35" /><stop offset="1" stopColor="rgb(var(--bull))" stopOpacity="0.55" /></linearGradient>
          <filter id={`${gid}-gl`} x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.2" /></filter>
        </defs>
        {Array.from({ length: 31 }, (_, i) => { const t = i / 30, [a1, b1] = pt(t, R + 9), [a2, b2] = pt(t, R + (i % 5 ? 11 : 13)); return <line key={i} x1={a1} y1={b1} x2={a2} y2={b2} stroke="rgb(var(--glass) / 0.22)" strokeWidth={i % 5 ? 0.6 : 1} />; })}
        <path d={arc(0, 1)} stroke="rgb(var(--glass) / 0.08)" strokeWidth={9} fill="none" strokeLinecap="round" />
        <path d={arc(0, l.e)} stroke={`url(#${gid}-rk)`} strokeWidth={4} fill="none" strokeLinecap="round" />
        <path d={arc(l.e, 1)} stroke={`url(#${gid}-rw)`} strokeWidth={4} fill="none" strokeLinecap="round" />
        {!l.pending && l.r != null && <>
          <path d={arc(Math.min(l.e, l.c), Math.max(l.e, l.c))} stroke={tone} strokeWidth={8} fill="none" strokeLinecap="round" opacity={0.35} filter={`url(#${gid}-gl)`} />
          <path d={arc(Math.min(l.e, l.c), Math.max(l.e, l.c))} stroke={tone} strokeWidth={4} fill="none" strokeLinecap="round" />
        </>}
        {(() => { const [a1, b1] = pt(l.e, R - 8), [a2, b2] = pt(l.e, R + 7); return <line x1={a1} y1={b1} x2={a2} y2={b2} stroke="rgb(var(--accent))" strokeWidth={2} strokeLinecap="round" />; })()}
        {isNum(l.sNow) && l.sNow !== x.stop && (() => { const [a1, b1] = pt(l.at(l.sNow), R - 7), [a2, b2] = pt(l.at(l.sNow), R + 6); return <line x1={a1} y1={b1} x2={a2} y2={b2} stroke="rgb(var(--warn))" strokeWidth={2} strokeLinecap="round" />; })()}
        {l.tps.map((t, k) => { const [a, b] = pt(l.at(t)); return (
          <g key={k}>
            <rect x={a - 3.6} y={b - 3.6} width={7.2} height={7.2} transform={`rotate(45 ${a} ${b})`} fill={l.hits[k] ? "rgb(var(--bull))" : "rgb(var(--panel))"} stroke="rgb(var(--bull))" strokeWidth={1.4}
              className={!l.hits[k] && k === l.next ? "gd-next" : undefined} />
            {l.hits[k] && <rect x={a - 3.6} y={b - 3.6} width={7.2} height={7.2} transform={`rotate(45 ${a} ${b})`} fill="rgb(var(--bull))" filter={`url(#${gid}-gl)`} />}
          </g>); })}
        {!l.pending && isNum(l.px) && <>
          <line x1={cx} y1={cy} x2={nx} y2={ny} stroke={tone} strokeOpacity={0.35} strokeWidth={1} strokeDasharray="2 3" />
          <circle cx={nx} cy={ny} r={7.5} fill={tone} opacity={0.35} filter={`url(#${gid}-gl)`} className="gd-pulse" style={{ transformBox: "fill-box", transformOrigin: "center" }} />
          <circle cx={nx} cy={ny} r={4} fill="#fff" stroke={tone} strokeWidth={2} />
        </>}
        <text x={cx} y={cy - 12} textAnchor="middle" fontSize="19" fontWeight="700" className="num" fill={tone}>{l.pending ? "waiting" : rTxt(l.r)}</text>
        <text x={cx} y={cy + 2} textAnchor="middle" fontSize="9.5" fill="rgb(var(--mute))">{l.pending ? "for entry" : l.label}</text>
        <text x={cx - R} y={cy + 13} textAnchor="middle" fontSize="8.5" fontWeight="700" fill="rgb(var(--bear) / 0.85)">SL</text>
        <text x={cx + R} y={cy + 13} textAnchor="middle" fontSize="8.5" fontWeight="700" fill="rgb(var(--bull) / 0.85)">TP{l.tps.length}</text>
      </svg>
      <div className="gd-foot">
        <span className={`gd-status is-${status[1]}`}>{status[0]}</span>
        <span className="text-mute"><b className="gd-tf">{String(x.timeframe).toUpperCase()}</b> {ago(x.filled_at ?? x.created_at)}</span>
      </div>
    </li>
  );
}

/** Command Centre row: one slim line per running call. */
function DeckRow({ l }: { l: Leg }) {
  const { x } = l;
  return (
    <li className={`sl-row ${l.r == null ? "" : l.up ? "is-up" : "is-down"}`}>
      <Link to={`/asset/${slug(x.symbol)}?tf=${x.timeframe}`} className="sl-id">
        <CoinAvatar symbol={x.symbol} size={24} />
        <b className="truncate">{name(x.symbol)}</b>
        <span className={`sl-side ${l.s > 0 ? "text-bull" : "text-bear"}`}>{l.s > 0 ? "▲" : "▼"} {String(x.timeframe).toUpperCase()}</span>
      </Link>
      <div className="sl-line">
        <span className="sl-base" />
        {!l.pending && l.r != null && <span className={`sl-fill ${l.up ? "" : "is-down"}`} style={{ left: `${Math.min(l.e, l.c) * 100}%`, width: `${Math.abs(l.c - l.e) * 100}%` }} />}
        <span className="sl-dot sl-e" style={{ left: `${l.e * 100}%` }} />
        {l.tps.map((t, k) => <span key={k} className={`sl-dot ${l.hits[k] ? "is-hit" : ""}`} style={{ left: `${l.at(t) * 100}%` }} />)}
        {!l.pending && isNum(l.px) && <span className={`sl-now ${l.up ? "" : "is-down"}`} style={{ left: `${l.c * 100}%` }} />}
      </div>
      <span className={`num sl-r ${l.r == null ? "text-mute" : l.up ? "text-bull" : "text-bear"}`}>{l.pending ? "waiting" : rTxt(l.r)}</span>
      <span className="sl-next text-xs text-mute">{l.pending ? "for entry" : l.label}</span>
    </li>
  );
}

/* ---------------------------------------------------------------- market heat globe */

/* ---------------------------------------------------------------- coin vs coin */
const COLORS = ["#f0b90b", "rgb(var(--bull))", "#9ec5ff"];
function Line({ data, color, lo, hi }: { data: number[]; color: string; lo: number; hi: number }) {
  if (data.length < 2) return null;
  const d = data.map((v, i) => `${i ? "L" : "M"}${((i / (data.length - 1)) * 600).toFixed(1)} ${(160 - ((v - lo) / (hi - lo || 1)) * 150 - 5).toFixed(1)}`).join(" ");
  return <path d={d} fill="none" stroke={color} strokeWidth="2.2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />;
}

export function CoinCompare({ rows }: { rows: any[] }) {
  const all = rows.map((r) => r.symbol);
  const [picked, setPicked] = useState<string[]>(() => all.slice(0, 3));
  const [opened, setOpened] = useState(false);
  const sel = picked.filter((s) => all.includes(s)).slice(0, 3);
  const k = [useKlines(sel[0] ?? "BTC/USDT", "1h", 168, 900_000), useKlines(sel[1] ?? "ETH/USDT", "1h", 168, 900_000), useKlines(sel[2] ?? "SOL/USDT", "1h", 168, 900_000)];
  const radar = useApi<any>(opened ? "/radar" : null);         // our record per coin: one read, only once the panel is used
  const series = sel.map((s, i) => {
    const c = k[i].data ?? [];
    return c.length ? c.map((x) => (x[4] / c[0][4] - 1) * 100) : [];
  });
  const flat = series.flat();
  const lo = Math.min(0, ...flat), hi = Math.max(0, ...flat);
  const toggle = (s: string) => { setOpened(true); setPicked((p) => (p.includes(s) ? p.filter((x) => x !== s) : [...p, s].slice(-3))); };
  const card = (s: string) => (radar.data?.scorecard?.coins ?? []).find((c: any) => c.symbol === s);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {all.map((s) => {
          const i = sel.indexOf(s);
          return <button key={s} type="button" onClick={() => toggle(s)} aria-pressed={i >= 0} className={`chip ${i >= 0 ? "border-accent/60" : ""}`} style={i >= 0 ? { color: COLORS[i] } : undefined}>{name(s)}</button>;
        })}
      </div>
      <svg viewBox="0 0 600 170" preserveAspectRatio="none" className="h-40 w-full" role="img" aria-label="7-day price change of the coins picked">
        <line x1="0" x2="600" y1={160 - ((0 - lo) / (hi - lo || 1)) * 150 - 5} y2={160 - ((0 - lo) / (hi - lo || 1)) * 150 - 5} stroke="rgb(var(--text) / 0.25)" strokeDasharray="3 4" vectorEffect="non-scaling-stroke" />
        {series.map((d, i) => <Line key={sel[i]} data={d} color={COLORS[i]} lo={lo} hi={hi} />)}
      </svg>
      <div className="grid gap-2 sm:grid-cols-3">
        {sel.map((s, i) => {
          const r = rows.find((x) => x.symbol === s);
          const sc = card(s);
          const d = series[i];
          return (
            <div key={s} className="cc-cell" style={{ borderColor: COLORS[i] }}>
              <div className="flex items-baseline justify-between"><Link to={`/asset/${slug(s)}`} className="font-semibold hover:underline" style={{ color: COLORS[i] }}>{name(s)}</Link><span className={`num text-sm font-semibold ${(d[d.length - 1] ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{pct(d[d.length - 1])} 7d</span></div>
              <dl className="mt-1.5 grid grid-cols-2 gap-x-2 gap-y-1 text-xs">
                <dt className="text-mute">Trend 4H</dt><dd className="text-right">{r?.trend_label ?? "—"}</dd>
                <dt className="text-mute whitespace-nowrap">AI lean</dt><dd className="num text-right">{isNum(r?.p_up) ? `${Math.round(r.p_up * 100)} / ${Math.round(r.p_down * 100)}%` : "—"}</dd>
                <dt className="text-mute">Volatility</dt><dd className="text-right">{r?.volatility ? String(r.volatility).toLowerCase() : "—"}</dd>
                <dt className="text-mute">RSI 14</dt><dd className="num text-right">{isNum(r?.rsi) ? r.rsi.toFixed(0) : "—"}</dd>
                <dt className="text-mute">Our record</dt><dd className="num text-right">{!opened ? <button className="text-accent" onClick={() => setOpened(true)}>show</button> : sc ? `${sc.wins}/${sc.closed} won · ${pct(sc.total_net_pct)}` : radar.loading ? "…" : "no calls yet"}</dd>
              </dl>
            </div>
          );
        })}
      </div>
      <p className="text-xs text-mute">Lines: hourly price change over the last 7 days from Binance. Our record is after fees.</p>
    </div>
  );
}

/* ---------------------------------------------------------------- practice badges */
type Badge = { k: string; title: string; text: string; have: number; need: number; fmt?: (v: number) => string };
/** Progress to the next practice badges, from the member's own futures practice account (already open on the page). */
export function PracticeBadges({ d }: { d: any }) {
  const badges = useMemo<Badge[]>(() => {
    const closes = (d?.trades ?? []).filter((t: any) => t.type === "CLOSE").sort((a: any, b: any) => (a.created_at ?? 0) - (b.created_at ?? 0));
    let run = 0, best = 0;
    for (const c of closes) { if (Number(c.realized_pnl) > 0) { run += 1; best = Math.max(best, run); } else run = 0; }
    const wins = closes.filter((c: any) => Number(c.realized_pnl) > 0).length;
    const ret = Number(d?.return_pct ?? 0);
    return [
      { k: "first", title: "First win", text: "Close a practice trade in profit", have: Math.min(wins, 1), need: 1 },
      { k: "ten", title: "10 trades", text: "Close 10 practice trades", have: Math.min(closes.length, 10), need: 10 },
      { k: "streak", title: "Hot streak", text: "5 wins in a row", have: Math.min(best, 5), need: 5 },
      { k: "plus10", title: "+10% account", text: "Grow the account by 10%", have: clamp(ret / 10, 0, 1) * 10, need: 10, fmt: (v) => `${(v).toFixed(1)}%` },
      { k: "safe", title: "Risk master", text: "20 trades, no liquidation", have: Number(d?.liquidations ?? 0) ? 0 : Math.min(closes.length, 20), need: 20 },
    ];
  }, [d]);
  if (!d) return null;
  return (
    <section className="panel p-4" aria-label="Practice badges">
      <div className="flex items-baseline justify-between"><h2 className="label">Practice badges</h2><span className="text-xs text-mute">demo account only</span></div>
      <ul className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {badges.map((b) => {
          const p = clamp(b.have / b.need);
          const done = p >= 1;
          return (
            <li key={b.k} className={`badge-cell ${done ? "is-done" : ""}`}>
              <Ring value={p} size={52} stroke={5} tone={done ? "--accent" : "--mute"} label={`${b.title}: ${Math.round(p * 100)}%`}>
                <span className={`text-xs font-bold ${done ? "text-accent" : "text-mute"}`}>{done ? "★" : `${Math.round(p * 100)}%`}</span>
              </Ring>
              <div className="min-w-0"><div className="text-sm font-semibold">{b.title}</div><div className="text-xs text-mute">{done ? "Earned" : b.fmt ? `${b.fmt(b.have)} of ${b.fmt(b.need)}` : `${Math.floor(b.have)} of ${b.need}`} · {b.text}</div></div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
