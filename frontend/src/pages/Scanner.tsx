import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { TfTabs } from "../components/Pickers";
import { Badge, Card, Empty, ErrorBox, Loading, RegimeBadge, SignalBadge, signalTone } from "../components/ui";
import { api, del, post, put, useApi } from "../lib/api";
import { DASH, fmtCompact, fmtNum, fmtPctRaw, fmtPrice, fmtProb, isNum, slug, tone } from "../lib/format";
import { useLive } from "../lib/live";
import { useIsAdmin } from "../lib/session";

const SORTS: Record<string, { label: string; key: (r: any) => number }> = {
  confidence: { label: "Highest confidence", key: (r) => r.confidence ?? -1 },
  bullish: { label: "Strongest bullish", key: (r) => r.composite ?? -9 },
  bearish: { label: "Strongest bearish", key: (r) => -(r.composite ?? 9) },
  rr: { label: "Best risk/reward", key: (r) => r.risk_reward ?? -1 },
  volume: { label: "Largest volume", key: (r) => r.quote_volume_24h ?? -1 },
  momentum: { label: "Momentum", key: (r) => r.momentum ?? -9 },
  breakout: { label: "Breakout base rate", key: (r) => r.breakout_base_rate ?? -1 },
};

export default function Scanner() {
  const admin = useIsAdmin();
  const [tf, setTf] = useState("4h");
  const [sort, setSort] = useState("confidence");
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<string[] | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const { tickers } = useLive();
  const scan = useApi<any>(`/scanner?timeframe=${tf}`, 60000);

  const rows = useMemo(() => {
    let r: any[] = scan.data?.rows ?? [];
    if (filter === "buy") r = r.filter((x) => x.signal?.includes("BUY"));
    if (filter === "sell") r = r.filter((x) => x.signal?.includes("SELL"));
    if (filter === "tradable") r = r.filter((x) => ["BUY", "BUY ON PULLBACK", "SELL"].includes(x.decision));
    if (filter === "bull") r = r.filter((x) => x.regime_group === "Bull");
    if (filter === "bear") r = r.filter((x) => x.regime_group === "Bear");
    const key = SORTS[sort].key;
    return [...r].sort((a, b) => Number(b.pinned) - Number(a.pinned) || key(b) - key(a));
  }, [scan.data, sort, filter]);

  const search = async () => {
    if (!query.trim()) return;
    try {
      setResults((await api<any>(`/search?q=${encodeURIComponent(query.trim())}`)).results);
      setMsg(null);
    } catch (e: any) {
      setMsg(e.message);
    }
  };
  const act = async (fn: () => Promise<any>, done: string) => {
    try {
      await fn();
      setMsg(done);
      scan.reload();
    } catch (e: any) {
      setMsg(e.message);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="page-title">Scanner</h1>
        <TfTabs value={tf} onChange={setTf} />
      </div>
      {admin && <Card title="Watchlist">
        <div className="flex flex-wrap items-center gap-2">
          <input className="input w-56" placeholder="Search a coin, e.g. PEPE" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} aria-label="Search cryptocurrency" />
          <button className="btn" onClick={search}>Search</button>
          {results?.map((s) => <button key={s} className="btn btn-primary px-2 py-1 text-xs" onClick={() => act(() => post("/watchlist", { symbol: s }), `${s} added. History is downloading; models train afterwards.`)}>+ {s}</button>)}
          {results && !results.length && <span className="text-sm text-mute">No USDT market found on this exchange</span>}
        </div>
        {msg && <p className="mt-2 text-sm text-accent">{msg}</p>}
      </Card>}
      <Card title="Universe" right={
        <div className="flex flex-wrap items-center gap-2">
          <select className="input w-40" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter">
            <option value="all">All assets</option><option value="tradable">Tradable decisions</option><option value="buy">Buy signals</option>
            <option value="sell">Sell signals</option><option value="bull">Bull regimes</option><option value="bear">Bear regimes</option>
          </select>
          <select className="input w-48" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
            {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
        </div>}>
        {scan.error && <ErrorBox error={scan.error} retry={scan.reload} />}
        {!scan.data && scan.loading && <Loading what="Scanning" />}
        <div className="table-wrap">
          <table className="grid-table">
            <thead><tr><th></th><th>Coin</th><th className="text-right">Price</th><th className="text-right">24h</th><th className="text-right">Volume</th><th>Trend</th><th className="text-right">RSI</th><th className="text-right">ADX</th><th className="text-right">ML P(up)</th><th>Regime</th><th>Signal</th><th>Decision</th><th className="text-right">Conf.</th><th className="text-right">R:R</th><th className="text-right">Breakout</th><th></th></tr></thead>
            <tbody>
              {rows.map((r) => {
                const tk = tickers[r.symbol];
                if (r.status !== "OK") return (
                  <tr key={r.symbol}><td /><td className="font-medium">{r.symbol}</td><td colSpan={13}><Badge tone="warn">Insufficient data</Badge> <span className="text-xs text-mute">{r.reason}</span></td>
                    <td>{admin && <button className="text-xs text-mute hover:text-bear" onClick={() => act(() => del(`/watchlist/${slug(r.symbol)}`), `${r.symbol} removed`)}>Remove</button>}</td></tr>
                );
                return (
                  <tr key={r.symbol}>
                    <td><button title={r.pinned ? "Unpin" : "Pin to top"} aria-pressed={r.pinned} disabled={!admin} className={r.pinned ? "text-warn" : "text-mute hover:text-warn"} onClick={() => act(() => put(`/watchlist/${slug(r.symbol)}/pin`, { pinned: !r.pinned }), r.pinned ? "Unpinned" : "Pinned")}>{r.pinned ? "★" : "☆"}</button></td>
                    <td><Link to={`/asset/${slug(r.symbol)}`} className="font-medium hover:text-accent">{r.symbol}</Link></td>
                    <td className="num text-right">{fmtPrice(tk?.last ?? r.price)}</td>
                    <td className={`num text-right ${tone(tk?.change_pct ?? r.change_24h_pct)}`}>{fmtPctRaw(tk?.change_pct ?? r.change_24h_pct)}</td>
                    <td className="num text-right text-mute">{fmtCompact(tk?.quote_volume ?? r.quote_volume_24h)}</td>
                    <td className={r.trend_label === "Up" ? "text-bull" : r.trend_label === "Down" ? "text-bear" : "text-mute"}>{r.trend_label === "Up" ? "▲ Up" : r.trend_label === "Down" ? "▼ Down" : "Flat"}</td>
                    <td className="num text-right">{fmtNum(r.rsi, 0)}</td><td className="num text-right">{fmtNum(r.adx, 0)}</td>
                    <td className="num text-right" title={r.edge_confirmed ? "edge confirmed" : r.model_status === "OK" ? "no confirmed edge" : r.model_status}>{isNum(r.p_up) ? fmtProb(r.p_up) + (r.edge_confirmed ? "" : "*") : <span className="text-xs text-mute">{r.model_status === "OK" ? DASH : "no model"}</span>}</td>
                    <td><RegimeBadge regime={r.regime} /></td><td><SignalBadge signal={r.signal} /></td>
                    <td title={r.decision_reason ?? ""}><Badge tone={signalTone(r.decision)}>{r.decision}</Badge></td>
                    <td className="num text-right">{fmtProb(r.confidence)}</td>
                    <td className="num text-right">{isNum(r.risk_reward) ? `1:${r.risk_reward.toFixed(1)}` : DASH}</td>
                    <td className="num text-right" title={`historical base rate, n=${r.breakout_n}`}>{fmtProb(r.breakout_base_rate)}</td>
                    <td>{admin && <button className="text-xs text-mute hover:text-bear" onClick={() => act(() => del(`/watchlist/${slug(r.symbol)}`), `${r.symbol} removed`)}>Remove</button>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {scan.data && !rows.length && <Empty>No assets match this filter</Empty>}
        <p className="mt-3 text-xs text-mute">* model has no statistically confirmed edge. “Breakout” is the historical frequency of a close above the 20-bar range within 5 bars from a similar position, not a model output. Hover a decision for its reason.</p>
      </Card>
    </div>
  );
}
