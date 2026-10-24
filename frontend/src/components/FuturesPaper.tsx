import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { SymbolSelect, useSymbols } from "./Pickers";
import { Badge, Card, Empty, ErrorBox, Loading, Note, Stat } from "./ui";
import { useApi } from "../lib/api";
import { DASH, fmtNum, fmtPctRaw, fmtPrice, fmtProb, fmtTime, isNum, tone } from "../lib/format";
import { useLive } from "../lib/live";
import * as PF from "../lib/paperFutures";

/** Manual futures paper trading: long / short with leverage, stop-loss, take-profit, liquidation and funding. */
export default function FuturesPaper() {
  const symbols = useSymbols();
  const { tickers } = useLive();
  const [params] = useSearchParams();
  const st = useApi<any>("/paper/futures");
  const [symbol, setSymbol] = useState(params.get("symbol") ?? "BTC/USDT");
  const [side, setSide] = useState<1 | -1>(params.get("side") === "SHORT" ? -1 : 1);
  const [lev, setLev] = useState(params.get("lev") ?? "5");
  const [margin, setMargin] = useState("500");
  const [sl, setSl] = useState(params.get("sl") ?? "");
  const [tp, setTp] = useState(params.get("tp") ?? "");
  const [balance, setBalance] = useState("10000");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const d = st.data;

  useEffect(() => { if (params.get("symbol")) setMsg({ ok: true, text: "Order form filled from the Futures prediction. Check it, then place the virtual order." }); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const px = tickers[symbol]?.last ?? null;
  const L = Math.max(1, Math.min(PF.MAX_LEV, Math.round(Number(lev) || 1)));
  const M = Number(margin) || 0;
  const liq = px ? PF.liqPrice(px, side, L) : null;
  const notional = M * L;
  const stopN = Number(sl) || null;
  const lossAtStop = px && stopN ? Math.abs(px - stopN) / px * notional : null;
  const stopBeyondLiq = px && stopN && liq ? side * (stopN - liq) <= 0 : false;

  const act = async (fn: () => Promise<any>, ok: string) => {
    setBusy(true);
    try { await fn(); setMsg({ ok: true, text: ok }); } catch (e: any) { setMsg({ ok: false, text: e.message }); } finally { setBusy(false); }
  };
  const place = () => act(() => PF.open({ symbol, side, margin: M, leverage: L, stop: stopN, take: Number(tp) || null }),
    `Virtual ${side > 0 ? "LONG" : "SHORT"} ${symbol} ${L}x opened with $${fmtNum(M)} margin ($${fmtNum(notional)} position).`);
  const reset = () => {
    if (!window.confirm("Reset the futures paper account? Open positions are dropped and a new account starts.")) return;
    act(() => PF.reset(Number(balance)), "Futures paper account reset.");
  };

  return (
    <div className="space-y-4">
      {st.error && <ErrorBox error={st.error} retry={st.reload} />}
      {!d && st.loading && <Loading />}
      {d && (
        <Card title="Futures account (virtual USDT)">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-8">
            <Stat label="Equity" value={`$${fmtNum(d.equity)}`} sub={`started $${fmtNum(d.account.starting_balance, 0)}`} />
            <Stat label="Return" value={fmtPctRaw(d.return_pct)} className={tone(d.return_pct)} />
            <Stat label="Available" value={`$${fmtNum(d.wallet)}`} />
            <Stat label="Margin in use" value={`$${fmtNum(d.margin_used)}`} sub={`exposure $${fmtNum(d.exposure, 0)}`} />
            <Stat label="Unrealized P&L" value={`$${fmtNum(d.unrealized_pnl)}`} className={tone(d.unrealized_pnl)} />
            <Stat label="Realized P&L" value={`$${fmtNum(d.realized_pnl)}`} className={tone(d.realized_pnl)} sub="after fees & funding" />
            <Stat label="Win rate" value={fmtProb(d.win_rate)} sub={`${d.closed} closed trades`} />
            <Stat label="Fees / funding" value={`$${fmtNum(d.fees)} / $${fmtNum(d.funding)}`} sub={`${d.liquidations} liquidation${d.liquidations === 1 ? "" : "s"}`} />
          </div>
        </Card>
      )}
      <div className="grid gap-4 lg:grid-cols-[24rem_1fr]">
        <Card title="New virtual futures order">
          <div className="space-y-3">
            <SymbolSelect value={symbol} onChange={setSymbol} symbols={symbols.length ? symbols : [symbol]} />
            <div className="num text-2xl">{fmtPrice(px)}</div>
            <div className="grid grid-cols-2 gap-2">
              <button className={`btn ${side > 0 ? "border-bull/60 bg-bull/20 text-bull" : ""}`} aria-pressed={side > 0} onClick={() => setSide(1)}>▲ Long</button>
              <button className={`btn ${side < 0 ? "border-bear/60 bg-bear/20 text-bear" : ""}`} aria-pressed={side < 0} onClick={() => setSide(-1)}>▼ Short</button>
            </div>
            <label className="block text-xs text-mute">Leverage: <span className="num text-text">{L}x</span>
              <input type="range" min={1} max={PF.MAX_LEV} value={L} onChange={(e) => setLev(e.target.value)} className="mt-1 w-full accent-[rgb(var(--accent))]" />
            </label>
            <div className="flex flex-wrap gap-1">{[1, 2, 3, 5, 10, 20].map((x) => <button key={x} className={`btn px-2 py-0.5 text-xs ${L === x ? "btn-on" : ""}`} onClick={() => setLev(String(x))}>{x}x</button>)}</div>
            <label className="block text-xs text-mute">Margin (USDT)<input className="input mt-1" inputMode="decimal" value={margin} onChange={(e) => setMargin(e.target.value)} /></label>
            <div className="grid grid-cols-2 gap-2">
              <label className="block text-xs text-mute">Stop-loss (optional)<input className="input mt-1" inputMode="decimal" value={sl} onChange={(e) => setSl(e.target.value)} placeholder={side > 0 ? "below entry" : "above entry"} /></label>
              <label className="block text-xs text-mute">Take-profit (optional)<input className="input mt-1" inputMode="decimal" value={tp} onChange={(e) => setTp(e.target.value)} placeholder={side > 0 ? "above entry" : "below entry"} /></label>
            </div>
            <div className="tile grid grid-cols-2 gap-x-3 gap-y-1 p-3 text-sm">
              <span className="text-mute">Position size</span><span className="num text-right">${fmtNum(notional)}</span>
              <span className="text-mute">Liquidation</span><span className="num text-right text-warn">{fmtPrice(liq)}</span>
              <span className="text-mute">Fee to open</span><span className="num text-right">${fmtNum(notional * PF.FEE)}</span>
              <span className="text-mute">Loss if stopped</span><span className="num text-right">{lossAtStop != null ? `$${fmtNum(lossAtStop)}` : DASH}</span>
            </div>
            {stopBeyondLiq && <p className="text-xs text-bear">Your stop is beyond the liquidation price: you would be liquidated first. Lower the leverage or move the stop.</p>}
            <button className={`btn w-full ${side > 0 ? "border-bull/50 bg-bull/15 text-bull hover:bg-bull/25" : "border-bear/50 bg-bear/15 text-bear hover:bg-bear/25"}`} disabled={busy || !px} onClick={place}>
              Open virtual {side > 0 ? "LONG" : "SHORT"} {L}x
            </button>
            {msg && <p className={`text-sm ${msg.ok ? "text-accent" : "text-bear"}`}>{msg.text}</p>}
            <Note>Fills at the live price plus slippage, 0.05% fee each way. Stop-loss, take-profit and liquidation are checked on every 15-minute candle — also for the time the app was closed — and on the live price while it is open. Funding is settled every 8 hours at Binance's current rate.</Note>
            <div className="flex items-end gap-2 border-t border-glass/[0.06] pt-3">
              <label className="flex-1 text-xs text-mute">Starting balance<input className="input mt-1" inputMode="decimal" value={balance} onChange={(e) => setBalance(e.target.value)} /></label>
              <button className="btn" onClick={reset}>Reset account</button>
            </div>
          </div>
        </Card>
        <div className="space-y-4">
          <Card title="Open positions">
            {d?.positions?.length ? (
              <div className="overflow-x-auto"><table className="grid-table">
                <thead><tr><th>Coin</th><th>Side</th><th className="text-right">Size</th><th className="text-right">Entry</th><th className="text-right">Mark</th><th className="text-right">Liq.</th><th className="text-right">Margin</th><th className="text-right">P&L (ROE)</th><th className="text-right">SL / TP</th><th /></tr></thead>
                <tbody>{d.positions.map((p: any) => {
                  const mark = tickers[p.symbol]?.last ?? p.mark;
                  const u = mark != null ? p.side * p.qty * (mark - p.entry) : null;
                  return (
                    <tr key={p.symbol}>
                      <td className="font-medium">{p.symbol}</td>
                      <td className={p.side > 0 ? "text-bull" : "text-bear"}>{p.side > 0 ? "LONG" : "SHORT"} {fmtNum(p.leverage, 1)}x</td>
                      <td className="num text-right">${fmtNum(p.qty * (mark ?? p.entry), 0)}</td>
                      <td className="num text-right">{fmtPrice(p.entry)}</td>
                      <td className="num text-right">{fmtPrice(mark)}</td>
                      <td className="num text-right text-warn">{fmtPrice(p.liq)}</td>
                      <td className="num text-right">${fmtNum(p.margin)}</td>
                      <td className={`num text-right ${tone(u)}`}>{u != null ? `$${fmtNum(u)} (${fmtPctRaw((u / p.margin) * 100, 1)})` : DASH}</td>
                      <td className="num text-right text-mute">{p.stop ? fmtPrice(p.stop) : "—"} / {p.take ? fmtPrice(p.take) : "—"}</td>
                      <td className="whitespace-nowrap text-right">
                        <button className="btn px-2 py-0.5 text-xs" disabled={busy} onClick={() => act(() => PF.close(p.symbol, 0.5), `Closed half of ${p.symbol}.`)}>½</button>{" "}
                        <button className="btn px-2 py-0.5 text-xs" disabled={busy} onClick={() => act(() => PF.close(p.symbol, 1), `Closed ${p.symbol}.`)}>Close</button>
                      </td>
                    </tr>
                  );
                })}</tbody>
              </table></div>
            ) : <Empty>No open futures positions. Use the order form, or tap “Paper trade this” on the Futures page.</Empty>}
          </Card>
          <Card title={`History${d ? ` (${d.trades.length})` : ""}`}>
            {d?.trades?.length ? (
              <div className="max-h-96 overflow-auto"><table className="grid-table">
                <thead><tr><th>Time</th><th>Action</th><th>Coin</th><th>Side</th><th className="text-right">Price</th><th className="text-right">Lev.</th><th className="text-right">Margin</th><th className="text-right">Fee</th><th className="text-right">P&L (ROE)</th></tr></thead>
                <tbody>{d.trades.map((t: any) => (
                  <tr key={t.id}>
                    <td className="text-mute">{fmtTime(t.created_at)}</td>
                    <td>{t.type === "OPEN" ? <Badge tone="accent">open</Badge> : <Badge tone={t.reason === "liquidated" ? "bear" : t.reason === "take-profit" ? "bull" : "mute"}>{t.reason ?? "close"}</Badge>}</td>
                    <td>{t.symbol}</td>
                    <td className={t.side > 0 ? "text-bull" : "text-bear"}>{t.side > 0 ? "LONG" : "SHORT"}</td>
                    <td className="num text-right">{fmtPrice(t.price)}</td>
                    <td className="num text-right">{isNum(t.leverage) ? `${fmtNum(t.leverage, 1)}x` : DASH}</td>
                    <td className="num text-right">${fmtNum(t.margin)}</td>
                    <td className="num text-right">{fmtNum(t.fee)}</td>
                    <td className={`num text-right ${tone(t.realized_pnl)}`}>{t.type === "CLOSE" ? `$${fmtNum(t.realized_pnl)} (${fmtPctRaw(t.roe_pct, 1)})` : "—"}</td>
                  </tr>
                ))}</tbody>
              </table></div>
            ) : <Empty>No futures paper trades yet.</Empty>}
          </Card>
        </div>
      </div>
    </div>
  );
}
