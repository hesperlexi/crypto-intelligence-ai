// v2.75 market extras (owner, 22 Nov 2026): everything here reads ONE engine view, views/derivs (hourly; see
// backend/app/services/market_extras.py). CoinDerivatives = the coin page card (open interest, crowd positioning, taker
// flow, liquidations, funding, liquidation map estimate); VolOptionsCard / MacroCard = Overview; UnlocksList = the
// Overview market-context card; boardFutures = the Market board's "Futures" column. A missing part is simply not shown.
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/api";
import { base, DASH, fmtCompact, fmtPrice, isNum, slug } from "../lib/format";
import { Sparkline } from "./Overview";

const pct = (v: number | null | undefined, d = 2) => (isNum(v) ? `${v >= 0 ? "+" : ""}${v.toFixed(d)}%` : DASH);
const tone = (v: number | null | undefined) => (!isNum(v) ? "text-mute" : v >= 0 ? "text-bull" : "text-bear");
const day = (ms?: number | null) => (isNum(ms) ? new Date(ms).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : DASH);

export function useDerivs() { return useApi<any>("/derivs", 600_000); }

/* ---------------------------------------------------------------- coin page */
export function CoinDerivatives({ symbol }: { symbol: string }) {
  const v = useDerivs();
  const c = v.data?.coins?.[symbol];
  const map = v.data?.liq_maps?.[symbol];
  if (!c && !map) return null;
  const longPct = c?.long_pct, taker = c?.taker_buy_pct;
  return (
    <section className="panel dv-card p-4 sm:p-5" aria-label={`${base(symbol)} futures market`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-display text-lg font-semibold">Futures market</h2>
        <span className="text-xs text-mute">OKX open interest and flow · funding · updated hourly</span>
      </div>
      <div className="dv-grid mt-4">
        <div className="dv-tile">
          <span>Open interest</span>
          <b className="num">{isNum(c?.oi_usd) ? `$${fmtCompact(c.oi_usd)}` : DASH}</b>
          <em className={`num ${tone(c?.oi_chg_24h)}`}>{pct(c?.oi_chg_24h, 1)} 24h</em>
          {(c?.oi_series?.length ?? 0) > 2 && <Sparkline values={c.oi_series} tone="--accent" className="mt-1 h-8 w-full" label="Open interest, last 2 days" />}
        </div>
        <div className="dv-tile">
          <span>Crowd positioning</span>
          <b className="num">{isNum(longPct) ? `${longPct.toFixed(0)}% long` : DASH}</b>
          {isNum(longPct) && <div className="dv-split" aria-hidden="true"><i className="bull" style={{ width: `${longPct}%` }} /><i className="bear" /></div>}
          <em>{isNum(longPct) ? (longPct > 65 ? "Crowded long" : longPct < 35 ? "Crowded short" : "Balanced") : ""}</em>
        </div>
        <div className="dv-tile">
          <span>Taker flow · 24h</span>
          <b className="num">{isNum(taker) ? `${taker.toFixed(0)}% buys` : DASH}</b>
          {isNum(taker) && <div className="dv-split" aria-hidden="true"><i className="bull" style={{ width: `${taker}%` }} /><i className="bear" /></div>}
          <em>{isNum(taker) ? (taker > 55 ? "Buyers pushing" : taker < 45 ? "Sellers pushing" : "Even") : ""}</em>
        </div>
        <div className="dv-tile">
          <span>Funding · per 8 h</span>
          <b className={`num ${tone(isNum(c?.funding_8h_pct) ? -c.funding_8h_pct : null)}`}>{isNum(c?.funding_8h_pct) ? `${c.funding_8h_pct.toFixed(4)}%` : DASH}</b>
          {(c?.funding_days?.length ?? 0) > 1 && <FundingBars days={c.funding_days} />}
          <em>{isNum(c?.funding_8h_pct) ? (c.funding_8h_pct > 0.03 ? "Longs paying a lot" : c.funding_8h_pct < -0.01 ? "Shorts paying" : "Normal") : ""}</em>
        </div>
      </div>
      {c?.liq_24h && (
        <p className="mt-3 text-sm text-mute">Liquidated in 24 h: <span className="num text-bear">${fmtCompact(c.liq_24h.long ?? 0)}</span> of longs ·{" "}
          <span className="num text-bull">${fmtCompact(c.liq_24h.short ?? 0)}</span> of shorts</p>
      )}
      {map && <LiqMap m={map} />}
    </section>
  );
}

function FundingBars({ days }: { days: [number, number][] }) {
  const max = Math.max(0.0001, ...days.map((d) => Math.abs(d[1])));
  return (
    <span className="dv-fbars" aria-label="Funding per day, last 7 days">
      {days.map(([t, v]) => <i key={t} className={v >= 0 ? "up" : "down"} style={{ height: `${Math.max(8, (Math.abs(v) / max) * 50)}%` }} title={`${day(t)}: ${v.toFixed(4)}% per 8 h`} />)}
    </span>
  );
}

/** Liquidation map (estimate): where forced closes would cluster around the price. */
function LiqMap({ m }: { m: any }) {
  const n = m.longs.length, W = 600, H = 150, bw = W / n;
  const max = Math.max(1, ...m.longs, ...m.shorts);
  const px = ((m.price - m.low) / (m.high - m.low)) * W;
  const big = (arr: number[]) => { const i = arr.indexOf(Math.max(...arr)); return m.low + (i + 0.5) * ((m.high - m.low) / n); };
  return (
    <div className="mt-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">Liquidation map <span className="font-normal text-mute">· estimate</span></h3>
        <span className="text-xs text-mute">biggest long cluster <b className="num text-bear">{fmtPrice(big(m.longs))}</b> · short cluster <b className="num text-bull">{fmtPrice(big(m.shorts))}</b></span>
      </div>
      <svg viewBox={`0 0 ${W} ${H + 18}`} className="mt-2 w-full" role="img" aria-label="Estimated liquidation levels around the price">
        {m.longs.map((v: number, i: number) => v > 0 && <rect key={`l${i}`} x={i * bw + 1} y={H - (v / max) * H} width={bw - 2} height={(v / max) * H} rx="2" fill="rgb(var(--bear))" opacity={0.35 + 0.6 * (v / max)} />)}
        {m.shorts.map((v: number, i: number) => v > 0 && <rect key={`s${i}`} x={i * bw + 1} y={H - (v / max) * H} width={bw - 2} height={(v / max) * H} rx="2" fill="rgb(var(--bull))" opacity={0.35 + 0.6 * (v / max)} />)}
        <line x1={px} x2={px} y1="0" y2={H} stroke="rgb(var(--accent))" strokeWidth="1.5" strokeDasharray="3 3" />
        <text x={px} y={H + 14} textAnchor="middle" fontSize="11" fill="rgb(var(--accent))">{fmtPrice(m.price)}</text>
        <text x="2" y={H + 14} fontSize="11" fill="rgb(var(--mute))">{fmtPrice(m.low)}</text>
        <text x={W - 2} y={H + 14} textAnchor="end" fontSize="11" fill="rgb(var(--mute))">{fmtPrice(m.high)}</text>
      </svg>
      <p className="text-xs text-mute">Red = longs that would be closed if the price falls there; green = shorts if it rises there. Estimated from open interest, taker flow and common leverages.</p>
    </div>
  );
}

/* ---------------------------------------------------------------- Overview */
export function VolOptionsCard() {
  const v = useDerivs();
  const vol = v.data?.volatility;
  if (!vol?.dvol && !vol?.options) return null;
  return (
    <section className="panel dv-card flex flex-col p-4 sm:p-5" aria-label="Volatility and options">
      <div className="flex items-baseline justify-between gap-2"><h2 className="font-display text-lg font-semibold">Volatility &amp; options</h2><span className="text-xs text-mute">Deribit · hourly</span></div>
      <div className="dv-two mt-4 flex-1">
        {(["BTC", "ETH"] as const).map((cur) => {
          const d = vol.dvol?.[cur], o = vol.options?.[cur];
          return (
            <div key={cur} className="dv-tile">
              <span>{cur} implied volatility</span>
              <b className="num">{isNum(d?.value) ? d.value.toFixed(1) : DASH}</b>
              <em className={`num ${isNum(d?.chg_24h) ? (d.chg_24h > 0 ? "text-warn" : "text-mute") : "text-mute"}`}>{isNum(d?.chg_24h) ? `${d.chg_24h >= 0 ? "+" : ""}${d.chg_24h.toFixed(1)} in 24 h` : ""}</em>
              {(d?.series?.length ?? 0) > 2 && <Sparkline values={d.series} tone="--ai" className="mt-1 h-8 w-full" label={`${cur} volatility index, 8 days`} />}
              {o && <dl className="dv-mini">
                <div><dt>Put / call</dt><dd className="num">{isNum(o.put_call) ? o.put_call.toFixed(2) : DASH}</dd></div>
                <div><dt>Max pain {day(o.expiry)}</dt><dd className="num">{isNum(o.max_pain) ? fmtPrice(o.max_pain) : DASH}</dd></div>
              </dl>}
            </div>
          );
        })}
      </div>
      <p className="mt-3 text-xs text-mute">Higher volatility = bigger moves expected. Put / call above 1 = more protection being bought. Max pain = the price where most options expire worthless.</p>
    </section>
  );
}

export function MacroCard() {
  const v = useDerivs();
  const m = v.data?.macro;
  const rows = useMemo(() => (["SPX", "NDX", "DXY", "GOLD", "US10Y"] as const).filter((k) => m?.[k]).map((k) => [k, m[k]] as [string, any]), [m]);
  if (!rows.length) return null;
  const corr = m?.SPX?.btc_corr_30d;
  return (
    <section className="panel dv-card flex flex-col p-4 sm:p-5" aria-label="Traditional markets">
      <div className="flex items-baseline justify-between gap-2"><h2 className="font-display text-lg font-semibold">Traditional markets</h2><span className="text-xs text-mute">{m?.source ?? ""}</span></div>
      <ul className="mt-3 flex-1">
        {rows.map(([k, x]) => (
          <li key={k} className="dv-macro">
            <span className="min-w-0"><b>{x.name}</b></span>
            <Sparkline values={x.series ?? []} tone={(x.chg_1d ?? 0) >= 0 ? "--bull" : "--bear"} className="h-7 w-24" />
            <span className="num text-right">{k === "US10Y" ? `${x.value.toFixed(2)}%` : x.value >= 1000 ? x.value.toLocaleString("en-US", { maximumFractionDigits: 0 }) : x.value.toFixed(2)}</span>
            <span className={`num text-right ${tone(x.chg_1d)}`}>{pct(x.chg_1d)}</span>
          </li>
        ))}
      </ul>
      {isNum(corr) && <p className="mt-3 text-sm text-mute">BTC vs S&amp;P 500, 30 days: <b className={`num ${Math.abs(corr) >= 0.5 ? "text-accent" : "text-text"}`}>{corr.toFixed(2)}</b> {Math.abs(corr) >= 0.5 ? "· moving together - US data matters more" : "· mostly its own way"}</p>}
    </section>
  );
}

export function UnlocksList() {
  const v = useDerivs();
  const u: any[] = (v.data?.unlocks ?? []).filter((x: any) => x.pct_of_unlocked >= 0.05).slice(0, 4);
  if (!u.length) return null;
  return (
    <>
      <div className="mb-2 mt-4 flex items-center justify-between border-t border-glass/[0.06] pt-3"><span className="text-sm font-medium text-text">Token unlocks · next 30 days</span><span className="text-xs text-mute">DefiLlama</span></div>
      <ul className="space-y-1.5">
        {u.map((x) => (
          <li key={x.coin} className="flex items-center justify-between gap-2 text-sm">
            <Link to={`/asset/${slug(`${x.coin}/USDT`)}`} className="font-medium hover:text-accent">{x.coin}</Link>
            <span className="text-xs text-mute">{x.next_at ? `next ${day(x.next_at)} · ` : ""}<b className={`num ${x.pct_of_unlocked >= 2 ? "text-warn" : "text-text"}`}>+{x.pct_of_unlocked.toFixed(1)}%</b> supply</span>
          </li>
        ))}
      </ul>
    </>
  );
}

/** Market board "Futures" column: open interest 24 h change and funding, from views/derivs. */
export function BoardFutures({ symbol, d }: { symbol: string; d: any }) {
  const c = d?.coins?.[symbol];
  if (!c) return <span className="text-xs text-mute">—</span>;
  return (
    <span className="flex flex-col text-[13px] leading-tight">
      <span>OI <b className={`num font-medium ${tone(c.oi_chg_24h)}`}>{pct(c.oi_chg_24h, 1)}</b></span>
      <span className="text-mute">Funding <span className="num">{isNum(c.funding_8h_pct) ? `${c.funding_8h_pct.toFixed(3)}%` : DASH}</span></span>
    </span>
  );
}
