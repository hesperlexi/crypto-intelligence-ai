import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import TradeTerminal from "../components/TradeTerminal";
import { SymbolSelect, useSymbols } from "../components/Pickers";
import { Badge, Card, Empty, ErrorBox, Loading, Note, Stat } from "../components/ui";
import { post, useApi } from "../lib/api";
import { fmtNum, fmtPctRaw, fmtPrice, fmtTime, tone } from "../lib/format";
import { useLive } from "../lib/live";

export default function Paper() {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight">Trade</h1>
        <Badge tone="warn">Practice account · virtual USDT</Badge>
      </div>
      <TradeTerminal />
    </div>
  );
}

function SpotPaper() {
  const symbols = useSymbols();
  const { spotTickers: tickers } = useLive();   // spot practice: spot prices
  const st = useApi<any>("/paper", 15000);
  const [symbol, setSymbol] = useState("BTC/USDT");
  const [amount, setAmount] = useState("1000");
  const [balance, setBalance] = useState("10000");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const d = st.data;

  const order = async (side: "BUY" | "SELL", qty?: number, sym: string = symbol) => {
    try {
      const r = await post<any>("/paper/order", qty != null ? { symbol: sym, side, qty } : { symbol: sym, side, notional: Number(amount) });
      setMsg({ ok: true, text: `PAPER ${side} ${fmtNum(r.trade.qty, 6)} ${sym} at ${fmtPrice(r.trade.price)} (fee $${fmtNum(r.trade.fee)})` });
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
      {st.error && <ErrorBox error={st.error} retry={st.reload} />}
      {!d && st.loading && <Loading />}
      {d && (
        <>
          <Card title="Virtual account">
            <div className="mb-3 flex items-end justify-between gap-3 sm:hidden">
              <div><div className="label">Equity</div><div className="num text-2xl">${fmtNum(d.equity)}</div></div>
              <div className={`num text-lg ${tone(d.return_pct)}`}>{fmtPctRaw(d.return_pct)}</div>
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 lg:grid-cols-6 [&>*:nth-child(-n+2)]:hidden sm:[&>*:nth-child(-n+2)]:block">
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
          <div className="grid grid-cols-1 gap-4 items-start lg:grid-rows-[auto_1fr] lg:grid-cols-[22rem_minmax(0,1fr)]">
            <div className="lg:col-start-2 lg:row-start-1"><SpotPositions d={d} onClose={(s: string, q: number) => order("SELL", q, s)} /></div>
            <div className="lg:col-start-1 lg:row-span-2 lg:row-start-1">
            <Card title="Virtual order">
              <div className="space-y-3">
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-end gap-3">
                  <SymbolSelect stacked value={symbol} onChange={setSymbol} symbols={symbols.length ? symbols : [symbol]} />
                  <div className="pb-1 text-right"><div className="label">Live price</div><div className="num text-xl leading-tight">{fmtPrice(tickers[symbol]?.last)}</div></div>
                </div>
                <label className="block text-xs text-mute">Amount (USDT)<input className="input mt-1" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
                <div className="grid grid-cols-2 gap-2">
                  <button className="btn border-bull/50 bg-bull/15 py-2.5 text-bull hover:bg-bull/25" onClick={() => order("BUY")}>Virtual BUY</button>
                  <button className="btn border-bear/50 bg-bear/15 py-2.5 text-bear hover:bg-bear/25" onClick={() => order("SELL")}>Virtual SELL</button>
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
            </div>
            <div className="lg:col-start-2">
              <Card title={`Trades (${d.trade_count})`}>
                {d.trades.length ? (<>
                  <ul className="divide-y divide-glass/[0.06] sm:hidden">
                    {d.trades.slice(0, 60).map((t: any) => (
                      <li key={t.id} className="py-2.5">
                        <div className="flex items-center justify-between gap-2">
                          <span><span className={`font-semibold ${t.side === "BUY" ? "text-bull" : "text-bear"}`}>{t.side}</span> <span className="font-medium">{t.symbol}</span></span>
                          {t.side === "SELL" && <span className={`num text-sm ${tone(t.realized_pnl)}`}>${fmtNum(t.realized_pnl)}</span>}
                        </div>
                        <div className="num mt-0.5 text-xs text-mute">{fmtTime(t.created_at)} · {fmtNum(t.qty, 6)} @ {fmtPrice(t.price)} · fee {fmtNum(t.fee)}</div>
                      </li>
                    ))}
                  </ul>
                  <div className="hidden max-h-80 overflow-auto sm:block"><table className="grid-table">
                    <thead><tr><th>Time</th><th>Mode</th><th>Asset</th><th>Side</th><th className="text-right">Quantity</th><th className="text-right">Fill</th><th className="text-right">Fee</th><th className="text-right">Slippage</th><th className="text-right">Realized</th></tr></thead>
                    <tbody>{d.trades.map((t: any) => (
                      <tr key={t.id}><td className="text-mute">{fmtTime(t.created_at)}</td><td><Badge tone="warn">{t.mode}</Badge></td><td>{t.symbol}</td><td className={t.side === "BUY" ? "text-bull" : "text-bear"}>{t.side}</td>
                        <td className="num text-right">{fmtNum(t.qty, 6)}</td><td className="num text-right">{fmtPrice(t.price)}</td><td className="num text-right">{fmtNum(t.fee)}</td><td className="num text-right">{fmtNum(t.slippage_cost)}</td>
                        <td className={`num text-right ${tone(t.realized_pnl)}`}>{t.side === "SELL" ? fmtNum(t.realized_pnl) : "—"}</td></tr>
                    ))}</tbody>
                  </table></div>
                </>) : <Empty>No paper trades yet</Empty>}
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function SpotPositions({ d, onClose }: { d: any; onClose: (symbol: string, qty: number) => void }) {
  const { spotTickers: tickers } = useLive();   // spot practice: spot prices
  const rows = (d?.positions ?? []).map((p: any) => {
    const mark = tickers[p.symbol]?.last ?? p.mark;
    const u = mark != null ? p.qty * (mark - p.avg_price) : null;
    return { ...p, mark, u, value: mark != null ? p.qty * mark : null, pct: mark != null ? (mark / p.avg_price - 1) * 100 : null };
  });
  return (
    <Card title={`Positions${rows.length ? ` (${rows.length})` : ""}`}>
      {!rows.length ? <Empty>No open positions</Empty> : (<>
        <div className="space-y-3 sm:hidden">
          {rows.map((p: any) => (
            <div key={p.symbol} className="tile p-3">
              <div className="flex items-start justify-between gap-2">
                <div><div className="font-semibold">{p.symbol}</div><div className="num text-xs text-mute">{fmtNum(p.qty, 6)} coins</div></div>
                <div className="text-right"><div className={`num text-lg ${tone(p.u)}`}>${fmtNum(p.u)}</div><div className={`num text-xs ${tone(p.u)}`}>{fmtPctRaw(p.pct)}</div></div>
              </div>
              <dl className="mt-3 grid grid-cols-1 gap-y-1.5 border-t border-glass/[0.06] pt-2.5 text-xs">
                {([["Avg price", fmtPrice(p.avg_price)], ["Mark price", fmtPrice(p.mark)], ["Value", `$${fmtNum(p.value)}`]] as const).map(([k, v]) => (
                  <div key={k} className="flex items-baseline justify-between gap-2"><dt className="text-mute">{k}</dt><dd className="num text-right">{v}</dd></div>
                ))}
              </dl>
              <button className="btn mt-3 w-full py-1.5 text-xs" onClick={() => onClose(p.symbol, p.qty)}>Sell all {p.symbol}</button>
            </div>
          ))}
        </div>
        <div className="hidden overflow-x-auto sm:block"><table className="grid-table">
          <thead><tr><th>Asset</th><th className="text-right">Quantity</th><th className="text-right">Avg price</th><th className="text-right">Mark</th><th className="text-right">Value</th><th className="text-right">Unrealized</th><th className="text-right">%</th><th /></tr></thead>
          <tbody>{rows.map((p: any) => (
            <tr key={p.symbol}><td className="font-medium">{p.symbol}</td><td className="num text-right">{fmtNum(p.qty, 6)}</td><td className="num text-right">{fmtPrice(p.avg_price)}</td><td className="num text-right">{fmtPrice(p.mark)}</td>
              <td className="num text-right">${fmtNum(p.value)}</td><td className={`num text-right ${tone(p.u)}`}>${fmtNum(p.u)}</td><td className={`num text-right ${tone(p.u)}`}>{fmtPctRaw(p.pct)}</td>
              <td className="text-right"><button className="btn px-2 py-0.5 text-xs" onClick={() => onClose(p.symbol, p.qty)}>Sell all</button></td></tr>
          ))}</tbody>
        </table></div>
      </>)}
    </Card>
  );
}
