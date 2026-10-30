import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { TfTabs, useSymbols } from "../components/Pickers";
import { CoinAvatar } from "../components/Polish";
import NewsBanner from "../components/NewsBanner";
import TradeCall, { GradeBadge, Market, verdictOf } from "../components/TradeCall";
import { Empty, ErrorBox, Loading } from "../components/ui";
import { useApi } from "../lib/api";
import { base, fmtPctRaw, fmtPrice, isNum } from "../lib/format";
import { useLive } from "../lib/live";
import { CALL_STATUS, fillLabel, livePnl, managedLabel, Pill, RiskBadge, RoiFigure } from "../components/SignalExtras";
import { AdjustHistory, adjustedPlan, UpdatedBadge } from "../components/SignalAdjust";

const TFS = ["15m", "1h", "4h", "12h", "1d", "3d"] as const;
const DOT = { bull: "bg-bull", bear: "bg-bear", wait: "bg-glass/30" } as const;
const TXT = { bull: "text-bull", bear: "text-bear", wait: "text-mute" } as const;
type Dir = "all" | "long" | "short";
type Grade = "all" | "A" | "B";
type St = "all" | "open" | "closed";

/** Direction of a row's call on this market ("long" / "short" / null when it is a wait). */
function dirOf(r: any, market: Market): "long" | "short" | null {
  const t = verdictOf(r, market).tone;
  return t === "bull" ? "long" : t === "bear" ? "short" : null;
}
/** Open / closed from the tracked call (contract field row.call); rows without it count as neither. */
function callState(r: any): "open" | "closed" | null {
  const st = r?.call?.status;
  if (!st) return null;
  return st === "OPEN" ? "open" : "closed";
}

function Seg<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: readonly (readonly [T, string])[]; onChange: (v: T) => void }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map(([k, l]) => (
        <button key={k} type="button" aria-pressed={value === k} onClick={() => onChange(k)}>{l}</button>
      ))}
    </div>
  );
}

/** Pick a coin, pick spot or futures: one clear call with entry, stop and targets. */
export default function Signals() {
  const [params, setParams] = useSearchParams();
  const [tf, setTf] = useState<string>(params.get("timeframe") ?? "4h");
  const [market, setMarket] = useState<Market>((params.get("market") as Market) ?? "futures");
  const v = useApi<any>(`/futures?timeframe=${tf}`);
  const symbols = useSymbols();
  const mkt = useApi<any>(market === "futures" && symbols.length ? `/futures/market?symbols=${symbols.join(",")}` : null, 60_000);
  const { tickers } = useLive();
  const [dir, setDir] = useState<Dir>("all");
  const [grade, setGrade] = useState<Grade>("all");
  const [st, setSt] = useState<St>("all");
  const [q, setQ] = useState("");
  const allRows: any[] = useMemo(() => {
    const r = [...(v.data?.rows ?? [])];
    const rank = (x: any) => (verdictOf(x, market).tone === "wait" ? 2 : x.grade === "A" ? 0 : 1);
    return r.sort((a, b) => rank(a) - rank(b) || (b.confidence ?? 0) - (a.confidence ?? 0));
  }, [v.data, market]);
  const hasCalls = allRows.some((r) => r.call);
  const rows: any[] = useMemo(() => {
    const needle = q.trim().toUpperCase();
    return allRows.filter((r) => {
      if (needle && !base(r.symbol).toUpperCase().includes(needle) && !String(r.symbol).toUpperCase().includes(needle)) return false;
      if (dir !== "all" && dirOf(r, market) !== dir) return false;
      if (grade !== "all" && (dirOf(r, market) == null || r.grade !== grade)) return false;
      if (st !== "all" && callState(r) !== st) return false;
      return true;
    });
  }, [allRows, q, dir, grade, st, market]);
  const filtered = rows.length !== allRows.length;
  const sel = params.get("symbol") ?? rows[0]?.symbol;
  const row = rows.find((r) => r.symbol === sel) ?? rows[0];
  const pick = (s: string) => { const p = new URLSearchParams(params); p.set("symbol", s); setParams(p, { replace: true }); };
  const active = rows.filter((r) => verdictOf(r, market).tone !== "wait").length;

  return (
    <div className="space-y-4">
      <NewsBanner />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="page-title">Trade signals</h1>
          <p className="page-sub">{rows.length ? `${active} of ${rows.length} coins have a ${market === "futures" ? "long or short" : "buy or sell"} call on the ${tf.toUpperCase()} chart.` : "One clear call per coin: direction, entry, stop-loss and targets."}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="seg" role="group" aria-label="Market">
            {(["futures", "spot"] as const).map((k) => (
              <button key={k} type="button" aria-pressed={market === k} onClick={() => setMarket(k)}
                className="seg-strong !px-4 !text-sm">
                {k === "futures" ? "Futures" : "Spot"}
              </button>
            ))}
          </div>
          <TfTabs value={tf} onChange={setTf} options={TFS} />
        </div>
      </div>

      {allRows.length > 0 && (
        <div className="flex flex-wrap items-center gap-2" aria-label="Filters">
          <label className="w-full sm:w-auto">
            <span className="sr-only">Search coin</span>
            <input className="input input-sm w-full sm:w-44" type="search" placeholder="Search coin" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
          <Seg label="Direction" value={dir} onChange={setDir} options={[["all", "All"], ["long", market === "futures" ? "Long" : "Buy"], ["short", market === "futures" ? "Short" : "Sell"]] as const} />
          <Seg label="Grade" value={grade} onChange={setGrade} options={[["all", "Any grade"], ["A", "A"], ["B", "B"]] as const} />
          {hasCalls && <Seg label="Status" value={st} onChange={setSt} options={[["all", "Any status"], ["open", "Open"], ["closed", "Closed"]] as const} />}
          {filtered && <button type="button" className="btn btn-ghost btn-sm text-accent" onClick={() => { setDir("all"); setGrade("all"); setSt("all"); setQ(""); }}>Clear filters</button>}
        </div>
      )}
      {allRows.length > 0 && rows.length === 0 && <Empty>No coin matches these filters.</Empty>}

      {v.error && <ErrorBox error={v.error} retry={v.reload} />}
      {!v.data && v.loading && <Loading what="Loading signals" />}
      {v.data === null && !v.loading && <Empty>Signals appear after the next engine run (within about 5 minutes).</Empty>}

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
                  const p = adjustedPlan(r.plan, r.call);
                  const show = vv.tone !== "wait" && p && (market === "futures" || p.side === "LONG");
                  return (
                    <li key={r.symbol}>
                      <button onClick={() => pick(r.symbol)} className={`grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-4 py-3 text-left hover:bg-glass/[0.04] ${r.symbol === row?.symbol ? "bg-accent/[0.06]" : ""}`}>
                        <CoinAvatar symbol={r.symbol} size={28} />
                        <div className="min-w-0">
                          <div className="flex min-w-0 items-center gap-2"><span className="font-semibold">{base(r.symbol)}</span>{vv.tone !== "wait" && <GradeBadge grade={r.grade} small />}<span className="num ml-auto truncate text-xs text-mute sm:ml-0">{fmtPrice(tickers[r.symbol]?.last ?? r.price)}</span></div>
                          <div className="num truncate text-xs text-mute">{r.stale === true ? "Data delayed — no trade" : show ? `entry ${fmtPrice(p.entry)} · stop ${fmtPrice(p.stop)} · TP1 ${fmtPrice(p.targets?.[0]?.price)}` : `leans ${r.lean ?? "—"} · no setup`}</div>
                          <RowExtras r={r} show={!!show} market={market} px={tickers[r.symbol]?.last ?? r.price} />
                        </div>
                        <span className={`max-w-[6.5rem] whitespace-normal rounded-md px-2 py-1 text-center text-[11px] font-bold leading-tight ${vv.tone === "bull" ? "bg-bull/15 text-bull" : vv.tone === "bear" ? "bg-bear/15 text-bear" : "bg-glass/10 text-mute"}`}>{vv.label}</span>
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

/** Small status line under a row: call status, fill, managed exit, live P&L, risk. Nothing for old rows. */
function RowExtras({ r, show, market, px }: { r: any; show: boolean; market: Market; px?: number }) {
  const c = r.call;
  const st = c ? CALL_STATUS[c.status] : null;
  const fill = c ? fillLabel(c.fill_status) : null;
  const managed = c?.managed === 1 ? managedLabel(c.exit_reason) : null;
  const pnl = c?.status === "OPEN" && c.fill_status !== "PENDING" && c.fill_status !== "NOT_FILLED" ? livePnl(c.side, c.entry, px) : null;
  const p = r.plan;
  if (!st && !fill && !managed && pnl == null && !(show && p) && !c?.adjustments?.length) return null;
  return (
    <>
    <div className="mt-1 flex flex-wrap items-center gap-1">
      <UpdatedBadge adj={c?.adjustments} />
      {st && <Pill tone={st[1]}>{st[0]}</Pill>}
      {fill && <Pill tone={fill[1]}>{fill[0]}</Pill>}
      {managed && <Pill tone="accent">{managed}</Pill>}
      {pnl != null && (isNum(c?.leverage) && c.leverage > 1
        ? <span className={`num text-[11px] font-semibold ${pnl >= 0 ? "text-bull" : "text-bear"}`} title={`Live ROI on margin at ${c.leverage}x · price ${fmtPctRaw(pnl, 2)}`}>{fmtPctRaw(pnl * c.leverage, 2)} ROI</span>
        : <span className={`num text-[11px] font-semibold ${pnl >= 0 ? "text-bull" : "text-bear"}`} title="Live price move">{fmtPctRaw(pnl, 2)} price</span>)}
      {c && c.status !== "OPEN" && isNum(c.return_pct) && <span className="inline-flex items-center gap-1"><RoiFigure x={c} size="sm" label={false} align="left" /></span>}
      {show && p && <RiskBadge entry={p.entry} stop={p.stop} leverage={market === "futures" ? p.suggested_leverage : 1} />}
    </div>
    {c?.adjustments?.length > 0 && <AdjustHistory adj={c.adjustments.slice(-1)} compact />}
    </>
  );
}
