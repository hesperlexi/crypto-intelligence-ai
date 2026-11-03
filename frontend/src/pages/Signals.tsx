import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { TfTabs, useSymbols } from "../components/Pickers";
import { CoinAvatar } from "../components/Polish";
import NewsBanner from "../components/NewsBanner";
import TradeCall, { Market, verdictOf } from "../components/TradeCall";
import { Empty, ErrorBox, Loading, Segmented } from "../components/ui";
import { useApi } from "../lib/api";
import { base, fmtPctRaw, fmtPrice, isNum } from "../lib/format";
import { useLive } from "../lib/live";
import { CALL_STATUS, fillLabel, livePnl, managedLabel, riskLevel, RoiFigure } from "../components/SignalExtras";
import { AdjustHistory, adjustedPlan } from "../components/SignalAdjust";
import { AllList, isSort, SIG_TFS, SortKey, SortMenu, SORTS, sortRows } from "../components/SignalsAll";

const TFS = SIG_TFS;
const TF_OPTIONS = [...SIG_TFS, "all"] as const;
// Timeframe policy (v2.12): mirrors backend/app/services/analysis.py A_ONLY_TFS ("15m,1h,1d,3d"), DEMO_ONLY_TFS ("")
// and PAUSED_TFS (""). The engine does not publish these lists, so they are kept here; change both together.
const TF_NOTES: Partial<Record<string, readonly [string, string]>> = {
  "15m": ["grade A", "15M: grade A calls only"],
  "1h": ["grade A", "1H: grade A calls only"],
  "1d": ["grade A", "1D: grade A calls only"],
  "3d": ["grade A", "3D: grade A calls only"],
};
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


/** Pick a coin, pick spot or futures: one clear call with entry, stop and targets. */
export default function Signals() {
  const [params, setParams] = useSearchParams();
  const tfParam = params.get("timeframe");
  const tf: string = tfParam && (TF_OPTIONS as readonly string[]).includes(tfParam) ? tfParam : "4h";
  const all = tf === "all";
  const sortParam = params.get("sort");
  const sort: SortKey = isSort(sortParam) && (all || sortParam !== "tf") ? sortParam : "ready";
  const waits = params.get("waits") === "1";
  /** Change URL query values (timeframe, sort, waits, symbol); null removes one. */
  const setQuery = (kv: Record<string, string | null>) => {
    const p = new URLSearchParams(params);
    for (const [k, val] of Object.entries(kv)) { if (val == null) p.delete(k); else p.set(k, val); }
    setParams(p, { replace: true });
  };
  const setTf = (t: string) => setQuery({ timeframe: t, symbol: null, ...(t !== "all" && sort === "tf" ? { sort: null } : {}) });
  const [market, setMarket] = useState<Market>((params.get("market") as Market) ?? "futures");
  const v = useApi<any>(all ? null : `/futures?timeframe=${tf}`);
  // "All": the six boards, loaded only while "All" is open
  const b15 = useApi<any>(all ? "/futures?timeframe=15m" : null);
  const b1h = useApi<any>(all ? "/futures?timeframe=1h" : null);
  const b4h = useApi<any>(all ? "/futures?timeframe=4h" : null);
  const b12 = useApi<any>(all ? "/futures?timeframe=12h" : null);
  const b1d = useApi<any>(all ? "/futures?timeframe=1d" : null);
  const b3d = useApi<any>(all ? "/futures?timeframe=3d" : null);
  const boards = [b15, b1h, b4h, b12, b1d, b3d];
  const symbols = useSymbols();
  const mkt = useApi<any>(!all && market === "futures" && symbols.length ? `/futures/market?symbols=${symbols.join(",")}` : null, 60_000);
  const { tickers } = useLive();
  const px = (s: string): number | undefined => tickers[s]?.last ?? undefined;
  const [dir, setDir] = useState<Dir>("all");
  const [grade, setGrade] = useState<Grade>("all");
  const [st, setSt] = useState<St>("all");
  const [q, setQ] = useState("");
  const boardData = boards.map((b) => b.data);
  const allRows: any[] = useMemo(() => {
    if (!all) return [...(v.data?.rows ?? [])].map((r: any) => ({ ...r, timeframe: r.timeframe ?? tf }));
    const out: any[] = [];
    boardData.forEach((d, i) => { for (const r of d?.rows ?? []) out.push({ ...r, timeframe: r.timeframe ?? TFS[i] }); });
    return waits ? out : out.filter((r) => verdictOf(r, market).tone !== "wait");
  }, [all, v.data, tf, waits, market, ...boardData]);
  const hasCalls = allRows.some((r) => r.call);
  const filteredRows: any[] = useMemo(() => {
    const needle = q.trim().toUpperCase();
    return allRows.filter((r) => {
      if (needle && !base(r.symbol).toUpperCase().includes(needle) && !String(r.symbol).toUpperCase().includes(needle)) return false;
      if (dir !== "all" && dirOf(r, market) !== dir) return false;
      if (grade !== "all" && (dirOf(r, market) == null || r.grade !== grade)) return false;
      if (st !== "all" && callState(r) !== st) return false;
      return true;
    });
  }, [allRows, q, dir, grade, st, market]);
  // sorted with live prices ("in the entry zone now" moves with the price)
  const rows: any[] = sortRows(filteredRows, sort, market, px);
  const boardsLoading = all && boards.some((b) => b.loading && !b.data);
  const boardsErr = all ? boards.find((b) => b.error) : undefined;
  const boardsEmpty = all && !boardsLoading && boards.every((b) => !b.data);
  const openOne = (r: any) => setQuery({ timeframe: r.timeframe, symbol: r.symbol, ...(sort === "tf" ? { sort: null } : {}) });
  const filtered = rows.length !== allRows.length;
  const sel = params.get("symbol") ?? rows[0]?.symbol;
  const row = rows.find((r) => r.symbol === sel) ?? rows[0];
  const pick = (s: string) => setQuery({ symbol: s });
  const active = rows.filter((r) => verdictOf(r, market).tone !== "wait").length;

  return (
    <div className="space-y-4">
      <NewsBanner />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="page-title">Trade signals</h1>
          <p className="page-sub">{all ? `${active} calls · all timeframes` : rows.length ? `${active} of ${rows.length} coins with a call · ${tf.toUpperCase()}` : "One call per coin."}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Segmented label="Market" value={market} onChange={setMarket} strong className="[&>button]:!px-4 [&>button]:!text-sm"
            options={[["futures", "Futures"], ["spot", "Spot"]] as const} />
          <TfTabs value={tf} onChange={setTf} options={TF_OPTIONS} notes={TF_NOTES} />
        </div>
      </div>

      {(allRows.length > 0 || (all && !boardsLoading && !boardsEmpty)) && (
        <div className="relative z-30 flex flex-wrap items-center gap-2" aria-label="Filters">
          <label className="w-full sm:w-auto">
            <span className="sr-only">Search coin</span>
            <input className="input input-sm w-full sm:w-44" type="search" placeholder="Search coin" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
          <Segmented label="Direction" value={dir} onChange={setDir} options={[["all", "All"], ["long", market === "futures" ? "Long" : "Buy"], ["short", market === "futures" ? "Short" : "Sell"]] as const} />
          <Segmented label="Grade" value={grade} onChange={setGrade} options={[["all", "Any grade"], ["A", "A"], ["B", "B"]] as const} />
          {hasCalls && <Segmented label="Status" value={st} onChange={setSt} options={[["all", "Any status"], ["open", "Open"], ["closed", "Closed"]] as const} />}
          {all && (
            <label className="tap-h flex cursor-pointer items-center gap-1.5 text-xs text-mute">
              <input type="checkbox" className="accent-[rgb(var(--accent))]" checked={waits} onChange={(e) => setQuery({ waits: e.target.checked ? "1" : null })} />
              Show waits
            </label>
          )}
          {filtered && <button type="button" className="btn btn-ghost btn-sm text-accent" onClick={() => { setDir("all"); setGrade("all"); setSt("all"); setQ(""); }}>Clear filters</button>}
          <div className="ml-auto"><SortMenu value={sort} onChange={(k) => setQuery({ sort: k === "ready" ? null : k })} options={all ? SORTS : SORTS.filter(([k]) => k !== "tf")} /></div>
        </div>
      )}
      {allRows.length > 0 && rows.length === 0 && <Empty>No coin matches these filters.</Empty>}

      {!all && v.error && <ErrorBox error={v.error} retry={v.reload} />}
      {!all && !v.data && v.loading && <Loading what="Loading signals" />}
      {!all && v.data === null && !v.loading && <Empty>Signals appear after the next engine run (within about 5 minutes).</Empty>}
      {boardsErr && <ErrorBox error={boardsErr.error ?? ""} retry={boardsErr.reload} />}
      {boardsLoading && <Loading what="Loading all timeframes" />}
      {boardsEmpty && !boardsErr && <Empty>Signals appear after the next engine run (within about 5 minutes).</Empty>}
      {all && !boardsLoading && !boardsEmpty && allRows.length === 0 && <Empty>No trade calls right now.{waits ? "" : " Tick “Show waits” to see every coin."}</Empty>}

      {all && rows.length > 0 && <AllList rows={rows} market={market} px={px} onOpen={openOne} />}

      {!all && rows.length > 0 && (
        <>
          {/* coin picker */}
          <div className="-mx-3 flex gap-2 overflow-x-auto px-3 pb-1 sm:mx-0 sm:flex-wrap sm:px-0" role="tablist" aria-label="Coins">
            {rows.map((r) => {
              const vv = verdictOf(r, market);
              const on = r.symbol === row?.symbol;
              return (
                <button key={r.symbol} role="tab" aria-selected={on} onClick={() => pick(r.symbol)}
                  className={`tap-h flex shrink-0 items-center gap-2 rounded-lg border px-2.5 py-1.5 text-sm transition-colors ${on ? "border-accent/60 bg-accent/[0.07]" : "border-glass/[0.08] bg-glass/[0.02] hover:border-glass/25"}`}>
                  <CoinAvatar symbol={r.symbol} size={20} />
                  <span className="font-semibold">{base(r.symbol)}</span>
                  <span className={`h-2 w-2 rounded-full ${DOT[vv.tone]}`} aria-hidden="true" />
                  <span className={`text-xs font-bold ${TXT[vv.tone]}`}>{vv.label}</span>
                </button>
              );
            })}
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
            <TradeCall r={row} market={market} m={mkt.data?.rows?.[row?.symbol]} />

            {/* all coins at a glance: table-like rows, side rule on the left */}
            <section className="panel self-start overflow-hidden p-0">
              <div className="card-head flex items-center justify-between border-b px-4 py-2.5"><h2 className="label">All coins · {market}</h2><span className="text-xs text-mute">{active} active</span></div>
              <div className="sig-row sig-head label border-b border-glass/[0.06]" aria-hidden="true">
                <span>Coin</span><span className="text-right">Entry</span><span className="text-right">Stop</span><span className="text-right">TP1</span><span className="text-right">Call</span>
              </div>
              <ul className="divide-y divide-glass/[0.06]">
                {rows.map((r) => {
                  const vv = verdictOf(r, market);
                  const p = adjustedPlan(r.plan, r.call);
                  const show = vv.tone !== "wait" && p && (market === "futures" || p.side === "LONG");
                  const px = tickers[r.symbol]?.last ?? r.price;
                  return (
                    <li key={r.symbol}>
                      <button onClick={() => pick(r.symbol)} aria-current={r.symbol === row?.symbol ? "true" : undefined} className="sig-row"
                        style={{ ["--side" as any]: vv.tone === "bull" ? "rgb(var(--bull))" : vv.tone === "bear" ? "rgb(var(--bear))" : "rgb(var(--glass) / 0.15)" }}>
                        <div className="flex min-w-0 items-center gap-2.5">
                          <CoinAvatar symbol={r.symbol} size={26} />
                          <div className="min-w-0">
                            <div className="flex min-w-0 items-center gap-1.5"><span className="truncate font-semibold">{base(r.symbol)}</span>{vv.tone !== "wait" && (r.grade === "A" || r.grade === "B") && <span className={`grade-mini ${r.grade === "A" ? "is-a" : ""}`} title={r.grade === "A" ? "Grade A · strong: trend, AI models and their track record all agree" : "Grade B · moderate: AI-led call where the model's out-of-sample record shows an edge"}>{r.grade}</span>}</div>
                            <div className="num truncate text-xs text-mute">{fmtPrice(px)}</div>
                          </div>
                        </div>
                        {/* desktop: aligned price columns */}
                        {show ? (<>
                          <span className="num hidden text-right text-sm text-accent sm:block">{fmtPrice(p.entry)}</span>
                          <span className="num hidden text-right text-sm text-bear sm:block">{fmtPrice(p.stop)}</span>
                          <span className="num hidden text-right text-sm text-bull sm:block">{fmtPrice(p.targets?.[0]?.price)}</span>
                        </>) : <span className="hidden truncate text-right text-xs text-mute sm:col-span-3 sm:block">{r.stale === true ? "Data delayed — no trade" : `leans ${r.lean ?? "—"} · no setup`}</span>}
                        <span className={`sig-side ${TXT[vv.tone]}`}>{vv.tone === "bull" ? "▲ " : vv.tone === "bear" ? "▼ " : ""}{vv.label}</span>
                        {/* phone: the levels as one line; both: status line */}
                        <div className="num col-span-full min-w-0 pl-[2.1rem] text-xs text-mute sm:hidden">{r.stale === true ? "Data delayed — no trade" : show ? `entry ${fmtPrice(p.entry)} · stop ${fmtPrice(p.stop)} · TP1 ${fmtPrice(p.targets?.[0]?.price)}` : `leans ${r.lean ?? "—"} · no setup`}</div>
                        <div className="col-span-full min-w-0 pl-[2.1rem] empty:hidden"><RowExtras r={r} show={!!show} market={market} px={px} /></div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          </div>
        </>
      )}
      <p className="text-xs text-mute">Analysis only, not financial advice. Spot calls are buy-only.</p>
    </div>
  );
}

/** Small status line under a row: call status, fill, managed exit, live P&L, risk — as quiet text, not pills.
 *  Nothing for old rows. */
const TONE_TXT = { bull: "text-bull", bear: "text-bear", warn: "text-warn", accent: "text-accent", mute: "text-mute" } as const;
function RowExtras({ r, show, market, px }: { r: any; show: boolean; market: Market; px?: number }) {
  const c = r.call;
  const st = c ? CALL_STATUS[c.status] : null;
  const fill = c ? fillLabel(c.fill_status) : null;
  const managed = c?.managed === 1 ? managedLabel(c.exit_reason) : null;
  const pnl = c?.status === "OPEN" && c.fill_status !== "PENDING" && c.fill_status !== "NOT_FILLED" ? livePnl(c.side, c.entry, px) : null;
  const p = r.plan;
  const risk = show && p ? riskLevel(p.entry, p.stop, market === "futures" ? p.suggested_leverage : 1) : null;
  const last = c?.adjustments?.length ? c.adjustments[c.adjustments.length - 1] : null;
  if (!st && !fill && !managed && pnl == null && !risk && !last) return null;
  const items: React.ReactNode[] = [];
  if (last) items.push(<span key="u" className="font-semibold text-warn" title="Changed by the admin. Results use the original levels before each change and the new ones after it.">Updated</span>);
  if (st) items.push(<span key="s" className={`font-semibold ${TONE_TXT[st[1]]}`}>{st[0]}</span>);
  if (fill) items.push(<span key="f" className={TONE_TXT[fill[1]]}>{fill[0]}</span>);
  if (managed) items.push(<span key="m" className="text-accent">{managed}</span>);
  if (pnl != null) items.push(isNum(c?.leverage) && c.leverage > 1
    ? <span key="p" className={`num font-semibold ${pnl >= 0 ? "text-bull" : "text-bear"}`} title={`Live ROI on margin at ${c.leverage}x · price ${fmtPctRaw(pnl, 2)}`}>{fmtPctRaw(pnl * c.leverage, 2)} ROI</span>
    : <span key="p" className={`num font-semibold ${pnl >= 0 ? "text-bull" : "text-bear"}`} title="Live price move">{fmtPctRaw(pnl, 2)} price</span>);
  if (c && c.status !== "OPEN" && isNum(c.return_pct)) items.push(<span key="r" className="inline-flex items-center"><RoiFigure x={c} size="sm" label={false} align="left" /></span>);
  if (risk) items.push(<span key="k" className={risk.level === "Low" ? "text-bull" : risk.level === "Medium" ? "text-warn" : "text-bear"} title={`If the stop is hit: about ${risk.lossAtStop.toFixed(1)}% of the position's margin`}>{risk.level} risk</span>);
  return (
    <>
    <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs">
      {items.map((it, i) => <span key={i} className="inline-flex items-center gap-1.5">{i > 0 && <span className="text-mute/50" aria-hidden="true">·</span>}{it}</span>)}
    </div>
    {c?.adjustments?.length > 0 && <AdjustHistory adj={c.adjustments.slice(-1)} compact />}
    </>
  );
}
