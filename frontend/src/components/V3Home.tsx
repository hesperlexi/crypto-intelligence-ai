import { useMemo } from "react";
import { Link } from "react-router-dom";
import { Card } from "./ui";
import { CoinAvatar } from "./Polish";
import { useApi } from "../lib/api";
import { useTickerThrottled } from "../lib/live";
import { DASH, ago, base, fmtPrice, isNum, slug } from "../lib/format";

/* V3.0 Overview blocks (owner-approved layout, 24 Nov 2026). Real data only:
   A  MarketStatus   views/risk_state (central risk state) + 4H mood (dashboard_4h) + freshness
   B  MyCapital      the member's practice futures account (paper/{uid}_futures) + auto-trade protection settings
   F  MyPositions    the same account's open positions, with a protection status per position
   E  Decisions      record calls (track_record) + the 4H board's blocked / no-trade rows (dashboard_4h) */

const STATE_TONE: Record<string, string> = { NORMAL: "text-bull", CAUTION: "text-warn", HIGH: "text-bear", SEVERE: "text-bear", RECOVERY: "text-ai" };
const VERDICT: Record<string, [string, string]> = {
  NORMAL: ["Conditions normal", "v3-ok"], CAUTION: ["Trade with caution", "v3-watch"], HIGH: ["Be very selective", "v3-act"],
  SEVERE: ["Stand aside", "v3-act"], RECOVERY: ["Stay selective", "v3-watch"],
};
const LEVEL: Record<string, number> = { NORMAL: 1, CAUTION: 2, RECOVERY: 2, HIGH: 4, SEVERE: 5 };

function Gauge({ state }: { state?: string }) {
  const lv = LEVEL[state ?? ""] ?? 0;
  const C = 2 * Math.PI * 32;
  const col = state === "NORMAL" ? "var(--bull)" : state === "CAUTION" || state === "RECOVERY" ? "var(--warn)" : state ? "var(--bear)" : "var(--mute)";
  return (
    <svg viewBox="0 0 80 80" className="h-[72px] w-[72px] shrink-0" aria-hidden>
      <circle cx="40" cy="40" r="32" fill="none" stroke="rgb(var(--raised))" strokeWidth="7" />
      <circle cx="40" cy="40" r="32" fill="none" stroke={`rgb(${col})`} strokeWidth="7" strokeLinecap="round"
        strokeDasharray={`${(lv / 5) * C} ${C}`} transform="rotate(-90 40 40)" />
      <text x="40" y="45" textAnchor="middle" className="num" fontSize="15" fill="rgb(var(--text))">{lv ? `${lv}/5` : DASH}</text>
    </svg>
  );
}

export function MarketStatus({ status4, rows, embedded = false, tfLabel = "4H" }: { status4?: any; rows?: any[]; embedded?: boolean; tfLabel?: string }) {
  const rs = useApi<any>("/risk-state", 60000).data;
  const btc = (rows ?? []).find((r) => r.symbol === "BTC/USDT");
  const state: string | undefined = rs?.state;
  const [verdict, vcls] = VERDICT[state ?? ""] ?? ["Checking conditions", "v3-muted"];
  const mood = status4?.status === "BULL" ? "Leaning up" : status4?.status === "BEAR" ? "Leaning down" : status4?.status ? "Mixed" : DASH;
  const vol = (rs?.factors ?? []).find((f: any) => f.key === "btc_vol");
  const stale = rs?.generated_at && Date.now() - rs.generated_at > 45 * 60_000;   // audit F-08: published every 30 min when unchanged
  const unavailable: string[] = rs?.unavailable ?? [];
  return (
    <section className={embedded ? "mood-risk" : "panel v3-glass p-4 sm:p-5"} aria-label="Market and risk status">
      <div className="flex flex-wrap items-center gap-x-7 gap-y-4">
        <Link to="/risk" className="flex items-center gap-4" aria-label="Open Risk">
          <Gauge state={state} />
          <div>
            <div className="v3-eyebrow">Market risk</div>
            <div className={`v3-state ${STATE_TONE[state ?? ""] ?? "text-mute"}`}>{rs?.label ?? "Checking"}</div>
          </div>
        </Link>
        <div className="v3-facts min-w-0 flex-1">
          <div><div className="v3-k">Mood · {tfLabel}</div><div className="v3-v">{mood}</div></div>
          <div><div className="v3-k">BTC trend</div><div className="v3-v">{btc?.regime ? String(btc.regime).toLowerCase().replace(/^./, (c) => c.toUpperCase()) : DASH}</div></div>
          <div><div className="v3-k">Volatility</div><div className="v3-v">{vol ? (vol.status === "high" ? "High" : vol.status === "warn" ? "Raised" : vol.status === "ok" ? "Normal" : "Unknown") : DASH}</div></div>
          <div><div className="v3-k">Breadth · {tfLabel}</div><div className="v3-v num">{status4 ? `${status4.bull ?? 0} up · ${status4.bear ?? 0} down` : DASH}</div></div>
        </div>
        <span className={`v3-pill ${vcls} !px-3.5 !py-1.5 text-[0.8125rem] font-semibold`}>{verdict}</span>
      </div>
      <div className="mt-4 flex flex-col gap-2 border-t pt-3.5 text-sm sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-5" style={{ borderColor: "var(--hair)" }}>
        <span className="min-w-0 flex-1 text-text/90">{rs ? <>Why: {rs.why}. {rs.policy}</> : "Reading the market risk state…"}</span>
        <span className="flex items-center gap-2 text-xs text-mute">
          <span className="v3-dot" style={{ background: `rgb(var(${stale ? "--warn" : "--bull"}))` }} />
          {rs?.generated_at ? `${stale ? "Data late" : "Data fresh"} · checked ${ago(rs.generated_at)}` : "Waiting for data"}
          {unavailable.length > 0 && <span className="text-warn">· missing: {unavailable.join(", ")}</span>}
        </span>
      </div>
    </section>
  );
}

const dayStart = () => { const d = new Date(); d.setUTCHours(0, 0, 0, 0); return d.getTime(); };

export function MyCapital() {
  const acc = useApi<any>("/paper/futures").data;
  const auto = useApi<any>("/auto-paper").data;
  const today = useMemo(() => {
    const t0 = dayStart();
    return ((acc?.trades ?? []) as any[]).filter((t) => t.type === "CLOSE" && (t.created_at ?? 0) >= t0).reduce((a, t) => a + (Number(t.realized_pnl) || 0), 0);
  }, [acc?.trades]);
  const eq = acc?.equity, used = acc ? (acc.margin_used ?? 0) + (acc.reserved ?? 0) : null;
  const exp = isNum(eq) && eq > 0 && isNum(used) ? (used / eq) * 100 : null;
  const lossPct = Number(auto?.daily_loss_pct ?? 5);
  const expMax = Number(auto?.max_exposure_pct ?? 50);
  const allowance = isNum(eq) ? Math.max(0, eq * lossPct / 100 + Math.min(0, today)) : null;
  const usd = (v: any, sign = false) => (isNum(v) ? `${sign && v > 0 ? "+" : v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}` : DASH);
  return (
    <Card title={<span className="flex items-center gap-2">My capital <span className="v3-pill v3-muted">Practice</span></span>}
      right={<Link to="/paper" className="text-xs text-accent hover:underline">Trade ›</Link>} className="h-full">
      <div className="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-3">
        <div><div className="v3-k">Account value</div><div className="num mt-0.5 text-xl">{usd(eq)}</div><div className="text-xs text-mute">deposited {usd(acc?.deposited)}</div></div>
        <div><div className="v3-k">Today (closed)</div><div className={`num mt-0.5 text-xl ${today > 0 ? "text-bull" : today < 0 ? "text-bear" : ""}`}>{acc ? usd(today, true) : DASH}</div><div className="text-xs text-mute">UTC day</div></div>
        <div><div className="v3-k">Open P&amp;L</div><div className={`num mt-0.5 text-xl ${(acc?.unrealized_pnl ?? 0) > 0 ? "text-bull" : (acc?.unrealized_pnl ?? 0) < 0 ? "text-bear" : ""}`}>{acc ? usd(acc.unrealized_pnl, true) : DASH}</div><div className="text-xs text-mute">{acc ? `${acc.positions?.length ?? 0} open` : ""}</div></div>
        <div><div className="v3-k">Capital in use</div><div className="num mt-0.5 text-xl">{isNum(exp) ? `${exp.toFixed(0)}%` : DASH}</div>
          <div className="v3-bar mt-1.5"><i style={{ width: `${Math.min(100, ((exp ?? 0) / expMax) * 100)}%`, background: `rgb(var(${(exp ?? 0) >= expMax ? "--bear" : "--accent"}))` }} /></div>
          <div className="mt-1 text-xs text-mute">limit {expMax}%</div></div>
        <div><div className="v3-k">Daily loss left</div><div className="num mt-0.5 text-xl">{usd(allowance)}</div>
          <div className="v3-bar mt-1.5"><i style={{ width: `${isNum(eq) && isNum(allowance) && eq > 0 ? Math.min(100, (allowance / (eq * lossPct / 100)) * 100) : 0}%`, background: "rgb(var(--bull))" }} /></div>
          <div className="mt-1 text-xs text-mute">auto-trade stops at −{lossPct}%</div></div>
        <div><div className="v3-k">All time</div><div className={`num mt-0.5 text-xl ${(acc?.pnl ?? 0) > 0 ? "text-bull" : (acc?.pnl ?? 0) < 0 ? "text-bear" : ""}`}>{acc ? usd(acc.pnl, true) : DASH}</div><div className="text-xs text-mute">{acc?.closed ?? 0} closed trades</div></div>
      </div>
    </Card>
  );
}

function protectionOf(p: any, px: number | null, risk?: string): [string, string] {
  if (!isNum(px)) return ["Waiting for price", "v3-muted"];
  if (risk === "SEVERE") return ["Act: market risk severe", "v3-act"];
  const stop = Number(p.stop);
  if (!stop) return ["No stop set", "v3-act"];
  const dist = Math.abs(px - stop) / Math.abs(p.entry - stop || 1);
  const beyondEntry = p.side * (stop - p.entry) >= 0;
  if (beyondEntry) return ["OK · stop at entry or better", "v3-ok"];
  if (dist < 0.25) return ["Act: close to the stop", "v3-act"];
  if (dist < 0.6 || risk === "HIGH") return ["Watch", "v3-watch"];
  return ["OK", "v3-ok"];
}

function PositionRow({ p, risk }: { p: any; risk?: string }) {
  const t = useTickerThrottled(p.symbol, 2000);
  const px = (t?.last ?? p.mark ?? null) as number | null;
  const upnl = isNum(px) ? p.side * p.qty * (px - p.entry) : null;
  const [label, cls] = protectionOf(p, px, risk);
  return (
    <tr>
      <td><Link to={`/asset/${slug(p.symbol)}`} className="flex items-center gap-2.5"><CoinAvatar symbol={p.symbol} size={24} />
        <span>{base(p.symbol)} <span className={p.side > 0 ? "text-bull" : "text-bear"}>{p.side > 0 ? "long" : "short"}</span>
          <span className="num ml-1 text-xs text-mute">{Math.round(p.leverage)}x</span></span></Link></td>
      <td className={`num ${upnl == null ? "" : upnl >= 0 ? "text-bull" : "text-bear"}`}>{isNum(upnl) ? `${upnl >= 0 ? "+" : "−"}$${Math.abs(upnl).toFixed(2)}` : DASH}</td>
      <td className="num hidden text-mute sm:table-cell">{p.stop ? fmtPrice(p.stop) : DASH}</td>
      <td className="text-right"><span className={`v3-pill ${cls}`}>{label}</span></td>
    </tr>
  );
}

export function MyPositions() {
  const acc = useApi<any>("/paper/futures").data;
  const risk = useApi<any>("/risk-state", 60000).data?.state;
  const ps: any[] = acc?.positions ?? [];
  return (
    <Card title="My open positions" right={<span className="text-xs text-mute">{acc ? `${ps.length} open · practice` : ""}</span>} className="h-full">
      {ps.length === 0 ? (
        <p className="text-sm text-mute">No open practice positions. <Link to="/signals" className="text-accent hover:underline">See today's signals</Link> or switch on auto-trade.</p>
      ) : (
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs text-mute"><th className="pb-2 font-normal">Coin</th><th className="pb-2 font-normal">P&amp;L</th>
            <th className="hidden pb-2 font-normal sm:table-cell">Stop</th><th className="pb-2 text-right font-normal">Protection</th></tr></thead>
          <tbody className="[&_td]:border-t [&_td]:py-2.5 [&_td]:align-middle [&_td]:[border-color:var(--hair)]">
            {ps.slice(0, 6).map((p) => <PositionRow key={p.key} p={p} risk={risk} />)}
          </tbody>
        </table>
      )}
    </Card>
  );
}

const GATE_WORDS: Record<string, string> = {
  "LIQUIDITY SWEEP": "stop run against it", "CAPITAL PROTECTION": "capital protection", "TOO MANY SAME-SIDE CALLS": "too many same-side calls",
  "AGAINST BIGGER TREND": "against the bigger trend", "VOLUME WALL AHEAD": "volume wall ahead", "STOP TOO TIGHT FOR FEES": "stop too tight for fees",
  "TARGET TOO SMALL FOR COSTS": "target too small for costs", "GRADE A ONLY": "needs grade A", "FILTERED": "AI trade filter",
  "NEWS": "news pause", "WATCH ONLY": "watch only", "BTC SHOCK": "against a BTC shock",
};

export function Decisions({ rows, track }: { rows?: any[]; track?: any }) {
  const sigs: any[] = track?.live?.signals ?? [];
  const day = Date.now() - 24 * 3_600_000;
  const approved = sigs.filter((s) => s.status === "OPEN" && s.fill_status !== "PENDING").sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0));
  const waiting = sigs.filter((s) => s.fill_status === "PENDING");
  const r = rows ?? [];
  const blocked = r.filter((x) => x.decision === "NO TRADE" && (x.flags ?? []).some((f: string) => f in GATE_WORDS));
  const noTrade = r.filter((x) => x.decision === "NO TRADE" && !(x.flags ?? []).some((f: string) => f in GATE_WORDS));
  const recent = approved.filter((s) => (s.created_at ?? 0) >= day).length;
  const lane = (title: string, n: number, items: [string, string][], more?: string) => (
    <div className="v3-lane">
      <div className="mb-1 flex justify-between text-[0.8125rem] text-mute"><span>{title}</span><b className="num font-medium text-text">{n}</b></div>
      {items.length === 0 ? <div className="v3-lane-row text-mute">None right now</div> :
        items.slice(0, 3).map(([a, b], i) => <div key={i} className="v3-lane-row"><span className="truncate">{a}</span><span className="shrink-0 text-right text-xs text-mute">{b}</span></div>)}
      {more && <div className="pt-1 text-xs text-mute">{more}</div>}
    </div>
  );
  const name = (s: any) => `${base(s.symbol)} ${s.side > 0 || s.signal === "LONG" ? "long" : "short"} ${String(s.timeframe ?? "").toUpperCase()}`;
  return (
    <Card title="AI opportunities & decisions" right={<Link to="/signals" className="text-xs text-accent hover:underline">Signals ›</Link>}>
      <p className="mb-3 text-sm text-mute">Every call passes the risk checks first. {recent} new in the last 24 hours.</p>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {lane("Running", approved.length, approved.map((s) => [name(s), s.grade ? `grade ${s.grade}` : ""]))}
        {lane("Waiting for entry", waiting.length, waiting.map((s) => [name(s), "limit set"]))}
        {lane("Blocked · 4H", blocked.length, blocked.map((x) => [`${base(x.symbol)} ${x.signal === "SELL" || x.signal === "STRONG SELL" ? "short" : "long"}`,
          GATE_WORDS[(x.flags ?? []).find((f: string) => f in GATE_WORDS)] ?? "held back"]))}
        {lane("No trade · 4H", noTrade.length, noTrade.slice(0, 2).map((x) => [base(x.symbol), String(x.decision_reason ?? "no clear edge").slice(0, 28)]),
          noTrade.length > 2 ? `+${noTrade.length - 2} more coins` : undefined)}
      </div>
    </Card>
  );
}
