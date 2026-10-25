import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { TfTabs, useSymbols } from "../components/Pickers";
import { CoinAvatar } from "../components/Polish";
import TradeCall, { GradeBadge, Market, verdictOf } from "../components/TradeCall";
import { Empty, ErrorBox, Loading } from "../components/ui";
import { useApi } from "../lib/api";
import { base, fmtPrice } from "../lib/format";
import { useLive } from "../lib/live";

const TFS = ["1h", "4h", "12h", "1d"] as const;
const DOT = { bull: "bg-bull", bear: "bg-bear", wait: "bg-glass/30" } as const;
const TXT = { bull: "text-bull", bear: "text-bear", wait: "text-mute" } as const;

/** Pick a coin, pick spot or futures: one clear call with entry, stop and targets. */
export default function Signals() {
  const [params, setParams] = useSearchParams();
  const [tf, setTf] = useState<string>(params.get("timeframe") ?? "4h");
  const [market, setMarket] = useState<Market>((params.get("market") as Market) ?? "futures");
  const v = useApi<any>(`/futures?timeframe=${tf}`);
  const symbols = useSymbols();
  const mkt = useApi<any>(market === "futures" && symbols.length ? `/futures/market?symbols=${symbols.join(",")}` : null, 60_000);
  const { tickers } = useLive();
  const rows: any[] = useMemo(() => {
    const r = [...(v.data?.rows ?? [])];
    const rank = (x: any) => (verdictOf(x, market).tone === "wait" ? 2 : x.grade === "A" ? 0 : 1);
    return r.sort((a, b) => rank(a) - rank(b) || (b.confidence ?? 0) - (a.confidence ?? 0));
  }, [v.data, market]);
  const sel = params.get("symbol") ?? rows[0]?.symbol;
  const row = rows.find((r) => r.symbol === sel) ?? rows[0];
  const pick = (s: string) => { const p = new URLSearchParams(params); p.set("symbol", s); setParams(p, { replace: true }); };
  const active = rows.filter((r) => verdictOf(r, market).tone !== "wait").length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Trade signals</h1>
          <p className="text-sm text-mute">{rows.length ? `${active} of ${rows.length} coins have a ${market === "futures" ? "long or short" : "buy or sell"} call on the ${tf.toUpperCase()} chart.` : "One clear call per coin: direction, entry, stop-loss and targets."}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-xl border border-glass/10 bg-ink/40 p-1" role="group" aria-label="Market">
            {(["futures", "spot"] as const).map((k) => (
              <button key={k} aria-pressed={market === k} onClick={() => setMarket(k)}
                className={`rounded-lg px-4 py-1.5 text-sm font-semibold transition ${market === k ? "bg-accent text-ink shadow" : "text-mute hover:text-text"}`}>
                {k === "futures" ? "Futures" : "Spot"}
              </button>
            ))}
          </div>
          <TfTabs value={tf} onChange={setTf} options={TFS} />
        </div>
      </div>

      {v.error && <ErrorBox error={v.error} retry={v.reload} />}
      {!v.data && v.loading && <Loading what="Loading signals" />}
      {v.data === null && !v.loading && <Empty>Signals appear after the next engine run (within about 15 minutes).</Empty>}

      {rows.length > 0 && (
        <>
          {/* coin picker */}
          <div className="-mx-3 flex gap-2 overflow-x-auto px-3 pb-1 sm:mx-0 sm:flex-wrap sm:px-0" role="tablist" aria-label="Coins">
            {rows.map((r) => {
              const vv = verdictOf(r, market);
              const on = r.symbol === row?.symbol;
              return (
                <button key={r.symbol} role="tab" aria-selected={on} onClick={() => pick(r.symbol)}
                  className={`flex shrink-0 items-center gap-2 rounded-xl border px-3 py-2 text-sm transition ${on ? "border-accent bg-accent/10" : "border-glass/10 bg-glass/[0.03] hover:border-accent/40"}`}>
                  <CoinAvatar symbol={r.symbol} size={20} />
                  <span className="font-semibold">{base(r.symbol)}</span>
                  <span className={`h-2 w-2 rounded-full ${DOT[vv.tone]}`} aria-hidden="true" />
                  <span className={`text-[11px] font-bold ${TXT[vv.tone]}`}>{vv.label}</span>
                </button>
              );
            })}
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
            <TradeCall r={row} market={market} m={mkt.data?.rows?.[row?.symbol]} />

            {/* all coins at a glance */}
            <section className="panel self-start p-0">
              <div className="card-head border-b border-glass/[0.06] px-4 py-2.5"><h2 className="label">All coins · {market}</h2></div>
              <ul className="divide-y divide-glass/[0.06]">
                {rows.map((r) => {
                  const vv = verdictOf(r, market);
                  const p = r.plan;
                  const show = vv.tone !== "wait" && p && (market === "futures" || p.side === "LONG");
                  return (
                    <li key={r.symbol}>
                      <button onClick={() => pick(r.symbol)} className={`grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-4 py-3 text-left hover:bg-glass/[0.04] ${r.symbol === row?.symbol ? "bg-accent/[0.06]" : ""}`}>
                        <CoinAvatar symbol={r.symbol} size={28} />
                        <div className="min-w-0">
                          <div className="flex items-center gap-2"><span className="font-semibold">{base(r.symbol)}</span>{vv.tone !== "wait" && <GradeBadge grade={r.grade} small />}<span className="num truncate text-xs text-mute">{fmtPrice(tickers[r.symbol]?.last ?? r.price)}</span></div>
                          <div className="num truncate text-xs text-mute">{show ? `entry ${fmtPrice(p.entry)} · stop ${fmtPrice(p.stop)} · TP1 ${fmtPrice(p.targets?.[0]?.price)}` : `leans ${r.lean ?? "—"} · no setup`}</div>
                        </div>
                        <span className={`rounded-md px-2 py-1 text-[11px] font-bold ${vv.tone === "bull" ? "bg-bull/15 text-bull" : vv.tone === "bear" ? "bg-bear/15 text-bear" : "bg-glass/10 text-mute"}`}>{vv.label}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          </div>
        </>
      )}
      <p className="text-xs text-mute">Signals are analysis, not financial advice. Spot calls are buy-only (sell means take profit or stay out); futures calls can be long or short. Practise any call with one tap in paper trading.</p>
    </div>
  );
}
