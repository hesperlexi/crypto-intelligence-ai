import { useState } from "react";
import { Link } from "react-router-dom";
import MyCoins from "../components/MyCoins";
import { TfTabs } from "../components/Pickers";
import { Badge, Card, Empty, ErrorBox, Loading, Meter, Note, RegimeBadge, regimeTone, SignalBadge, Stat } from "../components/ui";
import { useApi } from "../lib/api";
import { base, DASH, fmtCompact, fmtPct, fmtPctRaw, fmtPrice, fmtProb, isNum, slug, tone } from "../lib/format";
import { useLive } from "../lib/live";

const HORIZONS = ["1H", "4H", "12H", "24H", "3D", "7D"];

function heatColor(pct: number | null | undefined): string {
  if (!isNum(pct)) return "rgba(111,126,145,0.12)";
  const a = Math.min(0.55, 0.1 + Math.abs(pct) / 12);
  return pct >= 0 ? `rgba(46,189,133,${a})` : `rgba(240,80,110,${a})`;
}

export default function Dashboard() {
  const [tf, setTf] = useState("4h");
  const { tickers, refreshAt } = useLive();
  const dash = useApi<any>(`/dashboard?timeframe=${tf}`, 60000);
  const ctx = useApi<any>("/context", 600000);
  const cross = useApi<any>("/cross-asset?timeframe=1d", 300000);
  const d = dash.data;
  const ms = d?.market_status;
  const market = ctx.data?.market;
  const sentiment = ctx.data?.sentiment;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Market overview</h1>
          <p className="text-sm text-mute">Signals and regimes on the {tf.toUpperCase()} timeframe{refreshAt ? " · forecasts refreshed just now" : ""}</p>
        </div>
        <TfTabs value={tf} onChange={setTf} />
      </div>
      {dash.error && <ErrorBox error={dash.error} retry={dash.reload} />}
      {!d && dash.loading && <Loading what="Loading market overview" />}

      <MyCoins rows={d?.rows} />

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Market status">
          {ms ? (
            <>
              <div className="flex items-center gap-2">
                <Badge tone={regimeTone(ms.status)}>{ms.status}</Badge>
                <span className="num text-sm text-mute">{ms.bull} bull · {ms.neutral} neutral · {ms.bear} bear</span>
              </div>
              <Note>{ms.basis}</Note>
            </>
          ) : <Empty>{DASH}</Empty>}
        </Card>
        <Card title="Total market">
          {market ? (
            <Stat label="Market cap (CoinGecko)" value={`$${fmtCompact(market.total_market_cap_usd)}`}
              sub={<><span className={tone(market.market_cap_change_24h_pct)}>{fmtPctRaw(market.market_cap_change_24h_pct)} 24h</span> · BTC dom. {fmtPctRaw(market.btc_dominance, 1, false)}</>} />
          ) : cross.data?.basket ? (
            <Stat label="Tracked-asset basket, 20d" value={<span className={tone(cross.data.basket.return)}>{fmtPct(cross.data.basket.return)}</span>}
              sub="Equal-weight proxy, not total market cap" />
          ) : <Empty>No market-wide data available</Empty>}
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Market regime">
          <div className="space-y-2.5">
            {(d?.regimes ?? []).map((r: any) => (
              <div key={r.symbol} className="grid grid-cols-[4rem_1fr_3rem] items-center gap-3 text-sm">
                <Link to={`/asset/${slug(r.symbol)}`} className="font-medium hover:text-accent">{base(r.symbol)}</Link>
                <div><RegimeBadge regime={r.regime} /><div className="mt-1"><Meter value={r.confidence} tone={regimeTone(r.regime)} /></div></div>
                <span className="num text-right text-mute" title="Share of regime inputs that agree">{fmtProb(r.confidence)}</span>
              </div>
            ))}
            {!d?.regimes?.length && <Empty>No regimes yet: candles are still loading</Empty>}
          </div>
        </Card>
        <Card title="Top signals">
          <div className="space-y-2">
            {(d?.top_signals ?? []).map((s: any) => (
              <Link key={s.symbol} to={`/asset/${slug(s.symbol)}`} className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-sm hover:bg-raised">
                <span className="w-14 font-medium">{base(s.symbol)}</span>
                <SignalBadge signal={s.signal} />
                <span className="num text-mute" title="Signal score">{isNum(s.score) ? `${s.score.toFixed(0)}/100` : DASH}</span>
                <span className="text-xs text-mute">→ {s.decision}</span>
              </Link>
            ))}
            {!d?.top_signals?.length && <Empty>No signals yet</Empty>}
          </div>
        </Card>
        <Card title="Sentiment & context">
          {sentiment ? (
            <div className="space-y-2">
              <Stat label="Fear & Greed" value={`${sentiment.value} · ${sentiment.label}`} sub={isNum(sentiment.change_7d) ? `${sentiment.change_7d > 0 ? "+" : ""}${sentiment.change_7d} over 7 days` : undefined} />
              {sentiment.divergence && <Badge tone="warn">{sentiment.divergence}</Badge>}
            </div>
          ) : <Empty>{ctx.data?.reason ?? ctx.data?.sentiment_error ?? "Sentiment source unavailable"}</Empty>}
          {(cross.data?.observations ?? []).map((o: string) => <p key={o} className="mt-2 text-sm text-text">• {o}</p>)}
          <Note>Context only. Sentiment is never allowed to override price data.</Note>
        </Card>
      </div>

      <Card title="Forecast table — expected return per horizon" right={<span className="text-xs text-mute">each horizon uses its own timeframe model</span>}>
        <div className="overflow-x-auto">
          <table className="grid-table">
            <thead><tr><th>Asset</th><th className="text-right">Current</th>{HORIZONS.map((h) => <th key={h} className="text-right">{h}</th>)}</tr></thead>
            <tbody>
              {(d?.forecast_table ?? []).map((r: any) => (
                <tr key={r.symbol}>
                  <td><Link to={`/asset/${slug(r.symbol)}`} className="font-medium hover:text-accent">{r.symbol}</Link></td>
                  <td className="num text-right">{fmtPrice(tickers[r.symbol]?.last ?? r.price)}</td>
                  {HORIZONS.map((h) => {
                    const c = r.horizons[h];
                    return isNum(c?.expected_return) ? (
                      <td key={h} className={`num text-right ${tone(c.expected_return)}`} title={`P(up) ${fmtProb(c.p_up)}${c.edge_confirmed ? "" : " · no confirmed edge"}`}>
                        {fmtPct(c.expected_return)}{!c.edge_confirmed && <span className="text-mute">*</span>}
                      </td>
                    ) : <td key={h} className="text-right text-xs text-mute">{c?.status === "INSUFFICIENT DATA" ? "insufficient data" : c?.status === "MODEL NOT TRAINED" ? "not trained" : DASH}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Note>* The model for that horizon has no statistically confirmed out-of-sample edge after costs. Point forecasts are the centre of a wide range; open an asset for the intervals.</Note>
      </Card>

      <Card title="Market heatmap — 24h change">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          {(d?.heatmap ?? []).map((h: any) => {
            const ch = tickers[h.symbol]?.change_pct ?? h.change_24h_pct;
            return (
              <Link key={h.symbol} to={`/asset/${slug(h.symbol)}`} className="rounded-md border border-line p-3 transition-colors hover:border-accent/50" style={{ background: heatColor(ch) }}>
                <div className="flex items-center justify-between"><span className="font-semibold">{base(h.symbol)}</span><span className="num text-sm">{fmtPctRaw(ch)}</span></div>
                <div className="mt-1 text-xs text-text/80">{h.signal} · {h.regime}</div>
              </Link>
            );
          })}
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Top opportunities">
          {d?.opportunities?.length ? d.opportunities.map((o: any) => (
            <Link key={o.symbol} to={`/asset/${slug(o.symbol)}`} className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-sm hover:bg-raised">
              <span className="font-medium">{o.symbol}</span><SignalBadge signal={o.decision} />
              <span className="num text-mute">conf. {fmtProb(o.confidence)}</span><span className="num text-mute">R:R 1:{isNum(o.risk_reward) ? o.risk_reward.toFixed(1) : DASH}</span>
            </Link>
          )) : <Empty>No setup currently passes every check (confidence, model agreement, risk/reward). That is a valid outcome.</Empty>}
        </Card>
        <Card title="Top risks">
          {d?.risks?.length ? d.risks.map((r: any, i: number) => (
            <div key={i} className="flex items-center justify-between gap-3 border-b border-line/50 py-1.5 text-sm last:border-0">
              <span className="font-medium">{r.symbol}</span><span className="text-warn">{r.risk}</span>
            </div>
          )) : <Empty>No elevated risks flagged</Empty>}
        </Card>
      </div>
    </div>
  );
}
