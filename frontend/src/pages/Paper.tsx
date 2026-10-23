import { useState } from "react";
import { SymbolSelect, useSymbols } from "../components/Pickers";
import { Badge, Card, Empty, ErrorBox, Loading, Note, Stat } from "../components/ui";
import { post, useApi } from "../lib/api";
import { fmtNum, fmtPctRaw, fmtPrice, fmtTime, tone } from "../lib/format";
import { useLive } from "../lib/live";

export default function Paper() {
  const symbols = useSymbols();
  const { tickers } = useLive();
  const st = useApi<any>("/paper", 15000);
  const [symbol, setSymbol] = useState("BTC/USDT");
  const [amount, setAmount] = useState("1000");
  const [balance, setBalance] = useState("10000");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const d = st.data;

  const order = async (side: "BUY" | "SELL", qty?: number) => {
    try {
      const r = await post<any>("/paper/order", qty != null ? { symbol, side, qty } : { symbol, side, notional: Number(amount) });
      setMsg({ ok: true, text: `PAPER ${side} ${fmtNum(r.trade.qty, 6)} ${symbol} at ${fmtPrice(r.trade.price)} (fee $${fmtNum(r.trade.fee)})` });
      st.reload();
    } catch (e: any) {
      setMsg({ ok: false, text: e.message });
    }
  };
  const reset = async () => {
    if (!window.confirm("Reset the paper account? Positions and history of the current account are archived.")) return;
    try {
      await post("/paper/reset", { starting_balance: Number(balance) });
      setMsg({ ok: true, text: "Paper account reset" });
      st.reload();
    } catch (e: any) {
      setMsg({ ok: false, text: e.message });
    }
  };
  const held = d?.positions?.find((p: any) => p.symbol === symbol);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight">Paper trading</h1>
        <Badge tone="warn">Paper trading — virtual money, no real orders</Badge>
      </div>
      {st.error && <ErrorBox error={st.error} retry={st.reload} />}
      {!d && st.loading && <Loading />}
      {d && (
        <>
          <Card title="Virtual account">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
              <Stat label="Equity" value={`$${fmtNum(d.equity)}`} sub={`started with $${fmtNum(d.account.starting_balance)}`} />
              <Stat label="Return" value={fmtPctRaw(d.return_pct)} className={tone(d.return_pct)} />
              <Stat label="Cash" value={`$${fmtNum(d.cash)}`} />
              <Stat label="Unrealized P&L" value={`$${fmtNum(d.unrealized_pnl)}`} className={tone(d.unrealized_pnl)} />
              <Stat label="Realized P&L" value={`$${fmtNum(d.realized_pnl)}`} className={tone(d.realized_pnl)} sub="net of fees" />
              <Stat label="Fees / slippage paid" value={`$${fmtNum(d.fees)} / $${fmtNum(d.slippage)}`} />
            </div>
            <div className="mt-4 rounded-md border border-line bg-raised/40 p-3 text-sm">
              <span className="text-mute">{d.benchmark.label}: </span><span className={`num ${tone(d.benchmark.return_pct)}`}>{fmtPctRaw(d.benchmark.return_pct)}</span>
              <span className="text-mute"> · your account vs benchmark: </span><span className={`num ${tone(d.benchmark.excess_pct)}`}>{fmtPctRaw(d.benchmark.excess_pct)}</span>
              <span className="text-mute"> · compare rule-based and AI strategies on the Backtest page.</span>
            </div>
          </Card>
          <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
            <Card title="Virtual order">
              <div className="space-y-3">
                <SymbolSelect value={symbol} onChange={setSymbol} symbols={symbols.length ? symbols : [symbol]} />
                <div className="num text-2xl">{fmtPrice(tickers[symbol]?.last)}</div>
                <label className="block text-xs text-mute">Amount (USDT)<input className="input mt-1" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
                <div className="grid grid-cols-2 gap-2">
                  <button className="btn border-bull/50 bg-bull/15 text-bull hover:bg-bull/25" onClick={() => order("BUY")}>Virtual BUY</button>
                  <button className="btn border-bear/50 bg-bear/15 text-bear hover:bg-bear/25" onClick={() => order("SELL")}>Virtual SELL</button>
                </div>
                {held && <button className="btn w-full" onClick={() => order("SELL", held.qty)}>Close whole {symbol} position</button>}
                {msg && <p className={`text-sm ${msg.ok ? "text-accent" : "text-bear"}`}>{msg.text}</p>}
                <Note>Fills use the live price plus the configured slippage and half-spread, and pay the trading fee. Spot only: you cannot sell more than you hold.</Note>
                <div className="flex items-end gap-2 border-t border-line pt-3">
                  <label className="flex-1 text-xs text-mute">Starting balance<input className="input mt-1" inputMode="decimal" value={balance} onChange={(e) => setBalance(e.target.value)} /></label>
                  <button className="btn" onClick={reset}>Reset account</button>
                </div>
              </div>
            </Card>
            <div className="space-y-4">
              <Card title="Positions">
                {d.positions.length ? (
                  <div className="overflow-x-auto"><table className="grid-table">
                    <thead><tr><th>Asset</th><th className="text-right">Quantity</th><th className="text-right">Avg price</th><th className="text-right">Mark</th><th className="text-right">Value</th><th className="text-right">Unrealized</th><th className="text-right">%</th></tr></thead>
                    <tbody>{d.positions.map((p: any) => { const mark = tickers[p.symbol]?.last ?? p.mark; const u = mark != null ? p.qty * (mark - p.avg_price) : null; return (
                      <tr key={p.symbol}><td className="font-medium">{p.symbol}</td><td className="num text-right">{fmtNum(p.qty, 6)}</td><td className="num text-right">{fmtPrice(p.avg_price)}</td><td className="num text-right">{fmtPrice(mark)}</td>
                        <td className="num text-right">${fmtNum(mark != null ? p.qty * mark : null)}</td><td className={`num text-right ${tone(u)}`}>${fmtNum(u)}</td><td className={`num text-right ${tone(u)}`}>{fmtPctRaw(mark != null ? (mark / p.avg_price - 1) * 100 : null)}</td></tr>); })}</tbody>
                  </table></div>
                ) : <Empty>No open positions</Empty>}
              </Card>
              <Card title={`Trades (${d.trade_count})`}>
                {d.trades.length ? (
                  <div className="max-h-80 overflow-auto"><table className="grid-table">
                    <thead><tr><th>Time</th><th>Mode</th><th>Asset</th><th>Side</th><th className="text-right">Quantity</th><th className="text-right">Fill</th><th className="text-right">Fee</th><th className="text-right">Slippage</th><th className="text-right">Realized</th></tr></thead>
                    <tbody>{d.trades.map((t: any) => (
                      <tr key={t.id}><td className="text-mute">{fmtTime(t.created_at)}</td><td><Badge tone="warn">{t.mode}</Badge></td><td>{t.symbol}</td><td className={t.side === "BUY" ? "text-bull" : "text-bear"}>{t.side}</td>
                        <td className="num text-right">{fmtNum(t.qty, 6)}</td><td className="num text-right">{fmtPrice(t.price)}</td><td className="num text-right">{fmtNum(t.fee)}</td><td className="num text-right">{fmtNum(t.slippage_cost)}</td>
                        <td className={`num text-right ${tone(t.realized_pnl)}`}>{t.side === "SELL" ? fmtNum(t.realized_pnl) : "—"}</td></tr>
                    ))}</tbody>
                  </table></div>
                ) : <Empty>No paper trades yet</Empty>}
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
