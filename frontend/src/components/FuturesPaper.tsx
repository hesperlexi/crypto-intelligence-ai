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
  const mode: "oneway" | "hedge" = d?.mode ?? "oneway";

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
          <div className="mb-3 flex items-end justify-between gap-3 sm:hidden">
            <div><div className="label">Equity</div><div className="num text-2xl">${fmtNum(d.equity)}</div></div>
            <div className={`num text-lg ${tone(d.return_pct)}`}>{fmtPctRaw(d.return_pct)}</div>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4 lg:grid-cols-8">
            <div className="hidden sm:block"><Stat label="Equity" value={`$${fmtNum(d.equity)}`} sub={`started $${fmtNum(d.account.starting_balance, 0)}`} /></div>
            <div className="hidden sm:block"><Stat label="Return" value={fmtPctRaw(d.return_pct)} className={tone(d.return_pct)} /></div>
            <Stat label="Available" value={`$${fmtNum(d.wallet)}`} />
            <Stat label="Margin in use" value={`$${fmtNum(d.margin_used)}`} sub={`exposure $${fmtNum(d.exposure, 0)}`} />
            <Stat label="Unrealized P&L" value={`$${fmtNum(d.unrealized_pnl)}`} className={tone(d.unrealized_pnl)} />
            <Stat label="Realized P&L" value={`$${fmtNum(d.realized_pnl)}`} className={tone(d.realized_pnl)} sub="after fees & funding" />
            <Stat label="Win rate" value={fmtProb(d.win_rate)} sub={`${d.closed} closed trades`} />
            <Stat label="Fees / funding" value={`$${fmtNum(d.fees)} / $${fmtNum(d.funding)}`} sub={`${d.liquidations} liquidation${d.liquidations === 1 ? "" : "s"}`} />
          </div>
        </Card>
      )}
      <div className="grid grid-cols-1 gap-4 items-start lg:grid-rows-[auto_1fr] lg:grid-cols-[24rem_minmax(0,1fr)]">
        <div className="lg:col-start-2 lg:row-start-1">
          <Positions d={d} busy={busy} act={act} />
        </div>
        <div className="lg:col-start-1 lg:row-span-2 lg:row-start-1">
        <Card title="New virtual futures order">
          <div className="space-y-3">
            <div className="grid grid-cols-[minmax(0,1fr)_auto] items-end gap-3">
              <SymbolSelect stacked value={symbol} onChange={setSymbol} symbols={symbols.length ? symbols : [symbol]} />
              <div className="pb-1 text-right"><div className="label">Live price</div><div className="num text-xl leading-tight">{fmtPrice(px)}</div></div>
            </div>
            <div>
              <div className="mb-1 flex items-center justify-between text-xs text-mute"><span>Position mode</span>
                <span>{mode === "hedge" ? "long and short can be open together" : "one direction per coin"}</span></div>
              <div className="grid grid-cols-2 gap-1 rounded-lg border border-glass/10 p-1" role="group" aria-label="Position mode">
                {(["oneway", "hedge"] as const).map((m) => (
                  <button key={m} className={`rounded-md px-2 py-1.5 text-sm transition-colors ${mode === m ? "bg-accent/15 text-accent" : "text-mute hover:text-text"}`}
                    aria-pressed={mode === m} disabled={busy}
                    onClick={() => mode !== m && act(() => PF.setMode(m), m === "hedge" ? "Hedge mode on: you can now hold a long and a short on the same coin." : "One-way mode on.")}>
                    {m === "oneway" ? "One-way" : "Hedge"}
                  </button>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <button className={`btn py-2.5 ${side > 0 ? "border-bull/60 bg-bull/20 text-bull" : ""}`} aria-pressed={side > 0} onClick={() => setSide(1)}>▲ Long</button>
              <button className={`btn py-2.5 ${side < 0 ? "border-bear/60 bg-bear/20 text-bear" : ""}`} aria-pressed={side < 0} onClick={() => setSide(-1)}>▼ Short</button>
            </div>
            <label className="block text-xs text-mute">Leverage: <span className="num text-text">{L}x</span>
              <input type="range" min={1} max={PF.MAX_LEV} value={L} onChange={(e) => setLev(e.target.value)} className="mt-1 w-full accent-[rgb(var(--accent))]" />
            </label>
            <div className="flex flex-wrap gap-1">{[1, 2, 3, 5, 10, 20].map((x) => <button key={x} className={`btn px-3 py-1 text-xs ${L === x ? "btn-on" : ""}`} onClick={() => setLev(String(x))}>{x}x</button>)}</div>
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
            {mode === "oneway" && d?.positions?.some((p: any) => p.symbol === symbol && p.side !== side) && (
              <p className="text-xs text-warn">You hold the opposite side of {symbol}. Switch to Hedge mode to open this side as well, or close that position first.</p>
            )}
            {stopBeyondLiq && <p className="text-xs text-bear">Your stop is beyond the liquidation price: you would be liquidated first. Lower the leverage or move the stop.</p>}
            <button className={`btn w-full py-3 text-base font-medium ${side > 0 ? "border-bull/50 bg-bull/15 text-bull hover:bg-bull/25" : "border-bear/50 bg-bear/15 text-bear hover:bg-bear/25"}`} disabled={busy || !px} onClick={place}>
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
        </div>
        <div className="lg:col-start-2">
          <Card title={`History${d ? ` (${d.trades.length})` : ""}`}>
            {d?.trades?.length ? (<>
              <ul className="divide-y divide-glass/[0.06] sm:hidden">
                {d.trades.slice(0, 60).map((t: any) => (
                  <li key={t.id} className="py-2.5">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="truncate"><span className="font-medium">{t.symbol}</span> <span className={`text-xs font-semibold ${t.side > 0 ? "text-bull" : "text-bear"}`}>{t.side > 0 ? "LONG" : "SHORT"}{isNum(t.leverage) ? ` ${fmtNum(t.leverage, 0)}x` : ""}</span></span>
                      {t.type === "CLOSE" ? <span className={`num shrink-0 text-sm ${tone(t.realized_pnl)}`}>${fmtNum(t.realized_pnl)} <span className="text-xs">({fmtPctRaw(t.roe_pct, 1)})</span></span>
                        : <span className="num shrink-0 text-xs text-mute">margin ${fmtNum(t.margin, 0)}</span>}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-mute">
                      {t.type === "OPEN" ? <Badge tone="accent">open</Badge> : <Badge tone={t.reason === "liquidated" ? "bear" : t.reason === "take-profit" ? "bull" : "mute"}>{t.reason ?? "close"}</Badge>}
                      <span className="num">{fmtTime(t.created_at)} · @ {fmtPrice(t.price)} · fee {fmtNum(t.fee)}</span>
                    </div>
                  </li>
                ))}
              </ul>
              <div className="hidden max-h-96 overflow-auto sm:block"><table className="grid-table">
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
            </>) : <Empty>No futures paper trades yet.</Empty>}
          </Card>
        </div>
      </div>
    </div>
  );
}

function Positions({ d, busy, act }: { d: any; busy: boolean; act: (fn: () => Promise<any>, ok: string) => void }) {
  const { tickers } = useLive();
  const rows = (d?.positions ?? []).map((p: any) => {
    const mark = tickers[p.symbol]?.last ?? p.mark;
    const u = mark != null ? p.side * p.qty * (mark - p.entry) : null;
    return { ...p, mark, u, roe: u != null ? (u / p.margin) * 100 : null, size: p.qty * (mark ?? p.entry) };
  });
  const closeBtns = (p: any, wide = false) => (
    <div className={`flex gap-2 ${wide ? "" : "justify-end"}`}>
      <button className={`btn py-1 text-xs ${wide ? "flex-1 px-3" : "px-2"}`} title="Close half" disabled={busy} onClick={() => act(() => PF.close(p.key, 0.5), `Closed half of ${p.symbol} ${p.side > 0 ? "LONG" : "SHORT"}.`)}>{wide ? "Close ½" : "½"}</button>
      <button className={`btn py-1 text-xs ${wide ? "flex-1 border-bear/40 px-3 text-bear" : "px-2"}`} disabled={busy} onClick={() => act(() => PF.close(p.key, 1), `Closed ${p.symbol} ${p.side > 0 ? "LONG" : "SHORT"}.`)}>Close</button>
    </div>
  );
  return (
    <Card title={`Open positions${rows.length ? ` (${rows.length})` : ""}`}>
      {d?.hedges?.length > 0 && (
        <div className="mb-3 space-y-2">
          {d.hedges.map((h: any) => (
            <div key={h.symbol} className="rounded-xl border border-accent/30 bg-accent/[0.06] p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold">{h.symbol} <Badge tone="accent">hedged</Badge></span>
                <span className={`num ${tone(h.pnl)}`}>${fmtNum(h.pnl)} combined</span>
              </div>
              <div className="num mt-1 text-xs text-mute">
                long ${fmtNum(h.long, 0)} · short ${fmtNum(h.short, 0)} · net {h.net >= 0 ? "long" : "short"} ${fmtNum(Math.abs(h.net), 0)} · margin ${fmtNum(h.margin, 0)}
              </div>
              <div className="mt-1 text-xs text-mute">While both sides are open, price moves mostly cancel out; fees and funding still apply to each side.</div>
            </div>
          ))}
        </div>
      )}
      {!rows.length ? <Empty>No open futures positions. Use the order form, or tap “Paper trade this” on the Futures page.</Empty> : (<>
        <div className="space-y-3 sm:hidden">
          {rows.map((p: any) => (
            <div key={p.key} className="tile p-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="font-semibold">{p.symbol}</div>
                  <span className={`text-xs font-semibold ${p.side > 0 ? "text-bull" : "text-bear"}`}>{p.side > 0 ? "▲ LONG" : "▼ SHORT"} {fmtNum(p.leverage, 1)}x</span>
                </div>
                <div className="text-right">
                  <div className={`num text-lg ${tone(p.u)}`}>{p.u != null ? `$${fmtNum(p.u)}` : DASH}</div>
                  <div className={`num text-xs ${tone(p.u)}`}>{fmtPctRaw(p.roe, 1)} on margin</div>
                </div>
              </div>
              <div className="num mt-2 grid grid-cols-3 gap-2 text-xs">
                <div><div className="text-mute">Entry</div>{fmtPrice(p.entry)}</div>
                <div><div className="text-mute">Mark</div>{fmtPrice(p.mark)}</div>
                <div><div className="text-mute">Liq.</div><span className="text-warn">{fmtPrice(p.liq)}</span></div>
                <div><div className="text-mute">Margin</div>${fmtNum(p.margin, 0)}</div>
                <div><div className="text-mute">Size</div>${fmtNum(p.size, 0)}</div>
                <div><div className="text-mute">SL / TP</div>{p.stop ? fmtPrice(p.stop) : "—"} / {p.take ? fmtPrice(p.take) : "—"}</div>
              </div>
              <div className="mt-3">{closeBtns(p, true)}</div>
            </div>
          ))}
        </div>
        <div className="hidden overflow-x-auto sm:block"><table className="grid-table">
          <thead><tr><th>Coin</th><th>Side</th><th className="hidden text-right 2xl:table-cell">Size</th><th className="text-right">Entry</th><th className="text-right">Mark</th><th className="text-right">Liq.</th><th className="text-right">Margin</th><th className="text-right">P&L (ROE)</th><th className="text-right">SL / TP</th><th /></tr></thead>
          <tbody>{rows.map((p: any) => (
            <tr key={p.key}>
              <td className="font-medium">{p.symbol}</td>
              <td className={p.side > 0 ? "text-bull" : "text-bear"}>{p.side > 0 ? "LONG" : "SHORT"} {fmtNum(p.leverage, 1)}x</td>
              <td className="num hidden text-right 2xl:table-cell">${fmtNum(p.size, 0)}</td>
              <td className="num text-right">{fmtPrice(p.entry)}</td>
              <td className="num text-right">{fmtPrice(p.mark)}</td>
              <td className="num text-right text-warn">{fmtPrice(p.liq)}</td>
              <td className="num text-right">${fmtNum(p.margin)}</td>
              <td className={`num text-right ${tone(p.u)}`}>{p.u != null ? `$${fmtNum(p.u)} (${fmtPctRaw(p.roe, 1)})` : DASH}</td>
              <td className="num text-right text-xs leading-tight text-mute"><div>{p.stop ? fmtPrice(p.stop) : "—"}</div><div>{p.take ? fmtPrice(p.take) : "—"}</div></td>
              <td>{closeBtns(p)}</td>
            </tr>
          ))}</tbody>
        </table></div>
      </>)}
    </Card>
  );
}
