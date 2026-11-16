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

const name = (s: string) => (base(s) === "PAXG" ? "GOLD" : base(s));
const pct = (v: number | null | undefined, d = 1) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "—");
const clamp = (v: number, a = 0, b = 1) => Math.max(a, Math.min(b, v));

/* ---------------------------------------------------------------- live signal journeys */
/** Each running record call as a journey from its stop to TP3: entry, targets (lit when hit), the stop in force and
 *  the live price as a moving craft; published / filled times underneath. */
export function SignalJourneys({ track }: { track: any }) {
  const { tickers } = useLive();
  const open: any[] = (track?.live?.signals ?? []).filter((x: any) => x.status === "OPEN").slice(0, 8);
  if (!open.length) return <p className="py-6 text-center text-sm text-mute">No signals running right now. New calls appear here the moment they open.</p>;
  return (
    <ul className="space-y-3">
      {open.map((x) => {
        const s = x.side === "SHORT" ? -1 : 1;
        const tps = [x.tp1, x.tp2, x.tp3].filter(isNum);
        const end = x.runner?.on && isNum(x.runner.target) ? x.runner.target : tps[tps.length - 1];
        const span = s * (end - x.stop);
        const at = (p: number) => (span > 0 ? clamp((s * (p - x.stop)) / span) : 0);
        const px = tickers[x.symbol]?.last;
        const pending = x.fill_status === "PENDING";
        const sNow = stopNow(x)?.price;
        const hits = [x.tp1_hit, x.tp2_hit, x.tp3_hit];
        const r = isNum(px) && x.entry !== x.stop ? (s * (px - x.entry)) / Math.abs(x.entry - x.stop) : null;
        return (
          <li key={x.id ?? `${x.symbol}${x.created_at}`} className="journey">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <Link to={`/asset/${slug(x.symbol)}?tf=${x.timeframe}`} className="font-semibold hover:text-accent">
                {name(x.symbol)} <span className={s > 0 ? "text-bull" : "text-bear"}>{s > 0 ? "▲ LONG" : "▼ SHORT"}</span> <span className="text-xs text-mute">{String(x.timeframe).toUpperCase()}{x.grade ? ` · ${x.grade}` : ""}</span>
              </Link>
              <span className={`num text-sm font-semibold ${r == null || pending ? "text-mute" : r >= 0 ? "text-bull" : "text-bear"}`}>{pending ? "waiting for entry" : r == null ? "—" : `${r >= 0 ? "+" : ""}${r.toFixed(2)}R`}</span>
            </div>
            <div className="journey-track" aria-hidden="true">
              <span className="j-mark j-stop" style={{ left: 0 }} />
              {isNum(sNow) && sNow !== x.stop && <span className="j-mark j-stopnow" style={{ left: `${at(sNow) * 100}%` }} title="Stop in force" />}
              <span className="j-mark j-entry" style={{ left: `${at(x.entry) * 100}%` }} />
              {tps.map((t, i) => <span key={i} className={`j-mark j-tp ${hits[i] ? "is-hit" : ""}`} style={{ left: `${at(t) * 100}%` }} />)}
              {isNum(px) && !pending && <span className={`j-craft ${r != null && r < 0 ? "is-down" : ""}`} style={{ left: `${at(px) * 100}%` }} />}
            </div>
            <div className="mt-1 flex flex-wrap justify-between gap-x-3 text-xs text-mute">
              <span>Stop {fmtPrice(sNow ?? x.stop)}{isNum(sNow) && sNow !== x.stop ? " (moved)" : ""}</span>
              <span>{hits.filter(Boolean).length ? `${hits.filter(Boolean).length} target${hits.filter(Boolean).length > 1 ? "s" : ""} hit` : "no target hit yet"}</span>
              <span>opened {ago(x.filled_at ?? x.created_at)}</span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/* ---------------------------------------------------------------- market heat globe */
const CITIES: [string, number, number, number, number][] = [   // name, lon, lat, open UTC h, close UTC h (main stock session)
  ["Tokyo", 139.7, 35.7, 0, 6], ["Dubai", 55.3, 25.2, 6, 11], ["London", -0.1, 51.5, 8, 16.5], ["New York", -74, 40.7, 14.5, 21],
];
/** A gold globe: night side shaded from the real sun position, the four main stock sessions lit while
 *  open, BTC's last-hour volume against its 48-hour average, and the next US data release. */
export function HeatGlobe({ news }: { news: any }) {
  const k = useKlines("BTC/USDT", "1h", 48, 600_000);
  const now = new Date();
  const h = now.getUTCHours() + now.getUTCMinutes() / 60;
  const sunLon = (12 - h) * 15;                               // longitude under the sun
  const view = sunLon + 25;                                   // keep the day side in view
  const R = 92, C = 110;
  const proj = (lon: number, lat: number) => {
    const l = ((lon - view) * Math.PI) / 180, p = (lat * Math.PI) / 180;
    return { x: C + R * Math.cos(p) * Math.sin(l), y: C - R * Math.sin(p) * 0.98, front: Math.cos(p) * Math.cos(l) > 0 };
  };
  const vols = (k.data ?? []).map((c) => c[5]);
  const last = vols.length > 1 ? vols[vols.length - 2] : null;          // last closed hour
  const avg = vols.length > 2 ? vols.slice(0, -1).reduce((a, b) => a + b, 0) / (vols.length - 1) : null;
  const ratio = isNum(last) && isNum(avg) && avg ? last / avg : null;
  const openNow = CITIES.filter(([, , , o, c]) => h >= o && h < c && now.getUTCDay() % 6 !== 0);
  const next = news?.next_high && news.next_high.ts > Date.now() ? news.next_high : null;
  const nightX = C + R * Math.sin(((sunLon + 180 - view) * Math.PI) / 180);
  return (
    <div className="grid items-center gap-4 sm:grid-cols-[200px_minmax(0,1fr)] xl:grid-cols-1 2xl:grid-cols-[200px_minmax(0,1fr)]">
      <svg viewBox="0 0 220 220" className="mx-auto w-full max-w-[220px]" role="img" aria-label={`World markets now: ${openNow.length ? openNow.map((c) => c[0]).join(", ") + " open" : "main stock markets closed"}; crypto trades 24/7`}>
        <defs>
          <radialGradient id="hg-sea" cx="38%" cy="32%"><stop offset="0%" stopColor="#3a3226" /><stop offset="100%" stopColor="#14110d" /></radialGradient>
          <clipPath id="hg-clip"><circle cx={C} cy={C} r={R} /></clipPath>
        </defs>
        <circle cx={C} cy={C} r={R + 10} fill="rgb(var(--accent) / 0.06)" />
        <circle cx={C} cy={C} r={R} fill="url(#hg-sea)" stroke="rgb(var(--accent) / 0.55)" />
        <g clipPath="url(#hg-clip)">
          {[-60, -30, 0, 30, 60].map((lat) => <ellipse key={lat} cx={C} cy={C - R * Math.sin((lat * Math.PI) / 180)} rx={R * Math.cos((lat * Math.PI) / 180)} ry={3} fill="none" stroke="rgb(var(--accent) / 0.16)" />)}
          <g>
            {[0, 30, 60, 90, 120, 150].map((d) => <ellipse key={d} cx={C} cy={C} rx={Math.abs(R * Math.cos((d * Math.PI) / 180))} ry={R} fill="none" stroke="rgb(var(--accent) / 0.14)" />)}
          </g>
          <ellipse cx={nightX} cy={C} rx={R * 1.15} ry={R * 1.2} fill="rgb(0 0 0 / 0.3)" />
        </g>
        {CITIES.map(([n, lon, lat, o, c]) => {
          const p = proj(lon, lat);
          if (!p.front) return null;
          const on = h >= o && h < c && now.getUTCDay() % 6 !== 0;
          return (
            <g key={n}>
              {on && <circle cx={p.x} cy={p.y} r="9" fill="rgb(var(--accent) / 0.25)" className="hg-pulse" />}
              <circle cx={p.x} cy={p.y} r="3.5" fill={on ? "#f0b90b" : "rgb(var(--mute))"} />
              <text x={p.x + (p.x >= C ? 7 : -7)} y={p.y + (n === "New York" || n === "Dubai" ? 15 : -7)} textAnchor={p.x >= C ? "start" : "end"} fontSize="12" fill={on ? "#fff1c4" : "rgb(var(--mute))"}>{n}</text>
            </g>
          );
        })}
      </svg>
      <div className="space-y-2.5">
        <div className="cc-cell"><div className="text-xs text-mute">Stock markets open now</div><div className="font-semibold">{openNow.length ? openNow.map((c) => c[0]).join(" · ") : "None (crypto trades 24/7)"}</div></div>
        <div className="cc-cell"><div className="text-xs text-mute">BTC volume, last hour vs 48 h average</div>
          <div className={`font-semibold ${ratio == null ? "" : ratio >= 1.3 ? "text-accent" : ratio < 0.7 ? "text-mute" : ""}`}>{ratio == null ? "—" : `${ratio.toFixed(2)}×  ${ratio >= 1.3 ? "busy" : ratio < 0.7 ? "quiet" : "normal"}`}</div>
          {ratio != null && <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-glass/[0.08]"><div className="h-full rounded-full bg-accent" style={{ width: `${clamp(ratio / 2) * 100}%` }} /></div>}
        </div>
        <div className="cc-cell"><div className="text-xs text-mute">Next high-impact US release</div><div className="font-semibold">{next ? next.title : "None scheduled soon"}</div>{next && <div className="text-xs text-mute">{new Date(next.ts).toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" })} · new signals pause 45 min before</div>}</div>
      </div>
    </div>
  );
}

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
                <dt className="text-mute">AI up / down</dt><dd className="num text-right">{isNum(r?.p_up) ? `${Math.round(r.p_up * 100)} / ${Math.round(r.p_down * 100)}%` : "—"}</dd>
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
