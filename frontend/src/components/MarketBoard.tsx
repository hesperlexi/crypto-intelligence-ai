// v2.70 Overview redesign (owner, 22 Nov 2026: "doesn't look premium", "heat map can be merged with coin list").
// MarketBoard = ONE board for every watchlist coin, replacing My coins tiles, Market regime, Top risks, the Forecast table
// and the Heatmap: live price + 24h, trend (regime + strength), engine signal, AI outlook per horizon, watch notes.
// Two views of the same rows: Table and Heatmap. Data: views/dashboard_<tf> (already loaded by Home) + views/meta (pins).
// IntelBrief = the Market intelligence card without the sonar: headline, breadth bar, the briefing's facts, leaders /
// laggards from the live 24h moves.
import { memo, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/api";
import { ago, base, DASH, fmtPctRaw, fmtPrice, isNum, slug } from "../lib/format";
import { useLive, useTickerThrottled } from "../lib/live";
import { Segmented } from "./kit";
import MyCoins from "./MyCoins";
import { CoinAvatar } from "./Polish";
import { Empty } from "./ui";

const HZ = ["15M", "1H", "4H", "12H", "24H"] as const;
const TFS = [["15m", "15M"], ["1h", "1H"], ["4h", "4H"], ["12h", "12H"], ["1d", "1D"], ["3d", "3D"]] as const;
const FIRST = 12;                                  // rows shown before "Show all"

type Lean = "bull" | "bear" | "flat" | "warn";
const REGIME: Record<string, [string, Lean]> = {
  "STRONG BULL": ["Strong uptrend", "bull"], BULL: ["Uptrend", "bull"], "BULLISH CONSOLIDATION": ["Uptrend, pausing", "bull"],
  NEUTRAL: ["Sideways", "flat"], "BEARISH CONSOLIDATION": ["Downtrend, pausing", "bear"], BEAR: ["Downtrend", "bear"],
  "STRONG BEAR": ["Strong downtrend", "bear"], "HIGH VOLATILITY / UNSTABLE": ["Unstable", "warn"],
};
export const regimeOf = (r?: string | null): [string, Lean] => (r && REGIME[r]) || [r ? r.charAt(0) + r.slice(1).toLowerCase() : DASH, "flat"];
const SIGNAL: Record<string, [string, Lean]> = {
  "STRONG BUY": ["Strong buy", "bull"], BUY: ["Buy", "bull"], HOLD: ["Hold", "flat"], SELL: ["Sell", "bear"], "STRONG SELL": ["Strong sell", "bear"],
};
const signalOf = (s?: string | null): [string, Lean] => (s && SIGNAL[s]) || [DASH, "flat"];
const leanCls: Record<Lean, string> = { bull: "text-bull", bear: "text-bear", flat: "text-mute", warn: "text-warn" };
const riskText = (r: string) => r.replace(/\b(HIGH|LOW|EXTREME|UNSTABLE MARKET|REDUCED CONFIDENCE)\b/g, (w) => w.charAt(0) + w.slice(1).toLowerCase()).replace(/ — /g, ", ");

type Row = { symbol: string; price?: number; change?: number; regime?: string; strength?: number; signal?: string;
  hz?: Record<string, any>; risk?: string; pinned: boolean; mine: boolean; order: number };

function useRows(d: any): Row[] {
  const meta = useApi<any>("/meta");
  return useMemo(() => {
    const wl: any[] = meta.data?.watchlist ?? [];
    const pin = new Map(wl.map((w, i) => [w.symbol, { pinned: !!w.pinned, mine: !!w.mine, i }]));
    const reg = new Map(((d?.regimes ?? []) as any[]).map((r) => [r.symbol, r]));
    const fc = new Map(((d?.forecast_table ?? []) as any[]).map((r) => [r.symbol, r.horizons]));
    const risk = new Map<string, string>();
    for (const r of (d?.risks ?? []) as any[]) if (!risk.has(r.symbol)) risk.set(r.symbol, r.risk);
    return ((d?.rows ?? []) as any[]).filter((r) => r?.symbol).map((r, i) => {
      const p = pin.get(r.symbol);
      return { symbol: r.symbol, price: r.price, change: r.change_24h_pct, regime: r.regime ?? reg.get(r.symbol)?.regime,
        strength: reg.get(r.symbol)?.confidence, signal: r.signal, hz: fc.get(r.symbol), risk: risk.get(r.symbol),
        pinned: !!p?.pinned, mine: !!p?.mine, order: p ? p.i : 1000 + i };
    });
  }, [d, meta.data]);
}

type Sort = "list" | "move" | "trend" | "az";
type Filter = "all" | "bull" | "bear" | "pinned";

export default function MarketBoard({ d, tf, onTf, loading }: { d: any; tf: string; onTf: (tf: string) => void; loading?: boolean }) {
  const rows = useRows(d);
  const { tickers } = useLive();
  const [view, setView] = useState<"table" | "heat">(() => { try { return localStorage.getItem("cia-board-view") === "heat" ? "heat" : "table"; } catch { return "table"; } });
  const [sort, setSort] = useState<Sort>("list");
  const [filter, setFilter] = useState<Filter>("all");
  const [all, setAll] = useState(false);
  const [manage, setManage] = useState(false);
  const pick = (v: "table" | "heat") => { setView(v); try { localStorage.setItem("cia-board-view", v); } catch { /* ignore */ } };

  const chg = (r: Row) => tickers[r.symbol]?.change_pct ?? r.change;
  const list = useMemo(() => {
    let x = rows.filter((r) => filter === "all" || (filter === "pinned" ? r.pinned || r.mine : regimeOf(r.regime)[1] === filter));
    const k = (r: Row) => (r.pinned ? 0 : 1);
    x = [...x].sort(sort === "az" ? (a, b) => base(a.symbol).localeCompare(base(b.symbol))
      : sort === "move" ? (a, b) => (chg(b) ?? -1e9) - (chg(a) ?? -1e9)
      : sort === "trend" ? (a, b) => trendScore(b) - trendScore(a)
      : (a, b) => k(a) - k(b) || a.order - b.order);
    return x;
  // tickers change often; the order follows them only when sorting by the 24h move
  }, [rows, sort, filter, sort === "move" ? tickers : null]);   // eslint-disable-line react-hooks/exhaustive-deps

  const counts = useMemo(() => ({ bull: rows.filter((r) => regimeOf(r.regime)[1] === "bull").length,
    bear: rows.filter((r) => regimeOf(r.regime)[1] === "bear").length, pinned: rows.filter((r) => r.pinned || r.mine).length }), [rows]);
  const shown = all || view === "heat" ? list : list.slice(0, FIRST);
  const head = (key: Sort, label: string, cls = "") => (
    <button type="button" className={`mb-sort ${cls} ${sort === key ? "is-on" : ""}`} onClick={() => setSort(sort === key ? "list" : key)} aria-pressed={sort === key}>{label}</button>
  );

  return (
    <section className="panel mb-board" aria-label="Market board">
      <header className="mb-head">
        <div className="min-w-0">
          <h2 className="mb-title">Market board</h2>
          <p className="mb-sub">{rows.length ? `${rows.length} coins · ${tf.toUpperCase()} trend and signals · live prices` : "Coins appear after the next engine run"}</p>
        </div>
        <div className="mb-controls">
          <Segmented value={tf} onChange={onTf} options={TFS as any} label="Timeframe" className="mb-seg" />
          <Segmented value={view} onChange={pick} options={[["table", "Table"], ["heat", "Heatmap"]] as any} label="View" className="mb-seg" />
        </div>
      </header>
      <div className="mb-filters">
        <div className="mb-chips" role="group" aria-label="Show">
          {([["all", `All ${rows.length || ""}`], ["bull", `Uptrend ${counts.bull}`], ["bear", `Downtrend ${counts.bear}`], ["pinned", `★ Pinned ${counts.pinned}`]] as [Filter, string][]).map(([k, l]) => (
            <button key={k} type="button" className={`mb-chip ${filter === k ? "is-on" : ""}`} aria-pressed={filter === k} onClick={() => setFilter(k)}>{l}</button>
          ))}
        </div>
        <button type="button" className="mb-link" onClick={() => setManage((v) => !v)} aria-expanded={manage}>{manage ? "Done" : "Manage coins"}</button>
      </div>
      {manage && <div className="mb-manage"><MyCoins rows={d?.rows} startEdit onDone={() => setManage(false)} /></div>}

      {!rows.length ? <div className="p-4">{loading ? <div className="skeleton h-40 w-full rounded-lg" /> : <Empty>No coins yet: candles are still loading.</Empty>}</div>
        : view === "heat" ? <Heat rows={list} /> : (
        <div className="mb-table" role="table" aria-label="Coins">
          <div className="mb-row mb-th" role="row">
            <span role="columnheader">{head("az", "Coin")}</span>
            <span role="columnheader" className="text-right">Price</span>
            <span role="columnheader" className="text-right">{head("move", "24h", "justify-end")}</span>
            <span role="columnheader">{head("trend", "Trend")}</span>
            <span role="columnheader" className="mb-hide-sm">Signal</span>
            <span role="columnheader" className="mb-hide-md" title="AI expected move for 15M, 1H, 4H, 12H and 24H: up bars above the line, down below; faint = no proven edge">AI outlook <span className="mb-hz">15M → 24H</span></span>
            <span role="columnheader" className="mb-hide-lg">Watch</span>
          </div>
          {shown.map((r) => <BoardRow key={r.symbol} r={r} />)}
        </div>
      )}
      {view === "table" && list.length > FIRST && (
        <button type="button" className="mb-more" onClick={() => setAll((v) => !v)} aria-expanded={all}>{all ? "Show fewer" : `Show all ${list.length} coins`}</button>
      )}
    </section>
  );
}

function trendScore(r: Row) {
  const l = regimeOf(r.regime)[1];
  return (l === "bull" ? 1 : l === "bear" ? -1 : 0) * (1 + (r.strength ?? 0)) + (r.regime?.startsWith("STRONG") ? 0.5 * (l === "bull" ? 1 : -1) : 0);
}

const BoardRow = memo(function BoardRow({ r }: { r: Row }) {
  const t = useTickerThrottled(r.symbol, 1000);
  const px = t?.last ?? r.price, ch = t?.change_pct ?? r.change;
  const [rg, rl] = regimeOf(r.regime);
  const [sg, sl] = signalOf(r.signal);
  return (
    <Link to={`/asset/${slug(r.symbol)}`} className="mb-row mb-tr" role="row">
      <span className="mb-coin" role="cell">
        <CoinAvatar symbol={r.symbol} size={28} />
        <span className="min-w-0 overflow-hidden"><b>{base(r.symbol)}</b>{(r.pinned || r.mine) && <span className="mb-star" title={r.mine ? "Your coin" : "Pinned"}>★</span>}
          <span className="mb-coin-sub">{sg !== DASH ? <span className={leanCls[sl]}>{sg}</span> : null}<span className="text-mute">{sg !== DASH ? " · " : ""}{rg}</span></span></span>
      </span>
      <span className="num text-right" role="cell">{isNum(px) ? fmtPrice(px) : DASH}</span>
      <span className="text-right" role="cell"><Move v={ch} /></span>
      <span className="mb-trend" role="cell"><i className={`mb-dot mb-dot-${rl}`} aria-hidden="true" /><span className="min-w-0"><span className="mb-trend-w">{rg}</span><Strength v={r.strength} lean={rl} /></span></span>
      <span className={`mb-hide-sm mb-sig ${leanCls[sl]}`} role="cell">{sg}</span>
      <span className="mb-hide-md" role="cell"><Outlook hz={r.hz} /></span>
      <span className="mb-hide-lg mb-watch" role="cell">{r.risk ? riskText(r.risk) : ""}</span>
    </Link>
  );
});

/** 24h move: the number on a soft tint whose strength follows the size of the move. */
function Move({ v }: { v?: number | null }) {
  if (!isNum(v)) return <span className="text-mute">{DASH}</span>;
  const a = Math.min(0.32, 0.06 + Math.abs(v) / 30);
  return (
    <span className={`mb-move num ${v >= 0 ? "is-up" : "is-down"}`} style={{ background: `rgb(var(${v >= 0 ? "--bull" : "--bear"}) / ${a})` }}>{fmtPctRaw(v)}</span>
  );
}

/** Regime strength: five short segments. */
function Strength({ v, lean }: { v?: number | null; lean: Lean }) {
  const n = isNum(v) ? Math.max(1, Math.round(v * 5)) : 0;
  return (
    <span className="mb-strength" title={isNum(v) ? `${Math.round(v * 100)}% of the trend inputs agree` : undefined} aria-label={isNum(v) ? `strength ${n} of 5` : undefined}>
      {[0, 1, 2, 3, 4].map((i) => <i key={i} className={i < n ? `on-${lean}` : ""} />)}
    </span>
  );
}

/** AI expected move per horizon as five small bars around a midline (faint = no proven edge). */
function Outlook({ hz }: { hz?: Record<string, any> }) {
  const vals = HZ.map((h) => hz?.[h]);
  if (!vals.some((c) => isNum(c?.expected_return))) return <span className="text-xs text-mute">Not trained yet</span>;
  const max = Math.max(0.004, ...vals.map((c) => (isNum(c?.expected_return) ? Math.abs(c.expected_return) : 0)));
  return (
    <span className="mb-outlook" aria-label={HZ.map((h, i) => `${h} ${isNum(vals[i]?.expected_return) ? fmtPctRaw(vals[i].expected_return * 100) : "n/a"}`).join(", ")}>
      {vals.map((c, i) => {
        const v = c?.expected_return;
        if (!isNum(v)) return <span key={i} className="cell"><i className="na" /></span>;
        const h = Math.max(8, (Math.abs(v) / max) * 50);
        return <span key={i} className="cell" title={`${HZ[i]}: ${fmtPctRaw(v * 100)}${c.edge_confirmed ? "" : " · no proven edge"}`}>
          <i className={`${v >= 0 ? "up" : "down"} ${c.edge_confirmed ? "" : "faint"}`} style={{ height: `${h}%` }} /></span>;
      })}
    </span>
  );
}

/** Heatmap view: same rows, tiles coloured by the live 24h move. */
function Heat({ rows }: { rows: Row[] }) {
  return <div className="mb-heat">{rows.map((r) => <HeatTile key={r.symbol} r={r} />)}</div>;
}

const HeatTile = memo(function HeatTile({ r }: { r: Row }) {
  const t = useTickerThrottled(r.symbol, 2000);
  const ch = t?.change_pct ?? r.change;
  const a = isNum(ch) ? Math.min(0.62, 0.1 + Math.abs(ch) / 11) : 0;
  const bg = !isNum(ch) ? undefined : ch >= 0 ? `rgb(var(--bull) / ${a})` : `rgb(var(--bear) / ${a})`;
  const [rg, rl] = regimeOf(r.regime);
  return (
    <Link to={`/asset/${slug(r.symbol)}`} className="mb-tile" style={{ background: bg }}>
      <span className="mb-tile-top"><b>{base(r.symbol)}</b>{(r.pinned || r.mine) && <span className="mb-star">★</span>}</span>
      <span className="num mb-tile-pct">{isNum(ch) ? fmtPctRaw(ch) : DASH}</span>
      <span className="mb-tile-foot"><i className={`mb-dot mb-dot-${rl}`} aria-hidden="true" />{rg}</span>
    </Link>
  );
});

/* ================================================================== IntelBrief (Market intelligence) */
function firstSentence(text: string): string {
  const m = text.match(/^(.+?[.!?])(\s|$)/);
  return (m ? m[1] : text).trim();
}

export function IntelBrief({ b, loading, rows, status }: { b: any; loading: boolean; rows?: any[]; status?: any }) {
  const [open, setOpen] = useState(false);
  const { tickers } = useLive();
  const bull = status?.bull ?? 0, bear = status?.bear ?? 0, neutral = status?.neutral ?? 0, n = status?.assets ?? bull + bear + neutral;
  const mood = b?.mood ?? status?.status;
  const moodWord = mood === "BULL" ? "Bullish" : mood === "BEAR" ? "Bearish" : "Mixed";
  const moves = useMemo(() => ((rows ?? []) as any[]).map((r) => ({ s: r.symbol, v: tickers[r.symbol]?.change_pct ?? r.change_24h_pct }))
    .filter((x) => isNum(x.v)).sort((a, c) => c.v - a.v), [rows, tickers]);
  const up = moves.slice(0, 3), down = moves.slice(-3).reverse();
  const bullets: string[] = (b?.bullets ?? []).slice(0, 3);
  return (
    <section className="panel ib-card" aria-label="Market intelligence">
      <header className="ib-head">
        <span className="ib-kicker"><span className="ai-tag rounded px-1.5 py-0.5 text-xs font-semibold">AI</span>Market intelligence</span>
        <span className="text-xs text-mute">{b?.at ? `${b.source === "ai" ? "AI briefing" : "Briefing"} · ${ago(b.at)}` : ""}</span>
      </header>
      {!b?.text && loading ? <div className="space-y-2 p-4"><div className="skeleton h-5 w-2/3 rounded" /><div className="skeleton h-4 w-full rounded" /></div> : (
        <div className="ib-body">
          <p className={`ib-mood ib-mood-${mood === "BULL" ? "bull" : mood === "BEAR" ? "bear" : "flat"}`}>{moodWord} · 4H</p>
          <h3 className="ib-headline">{b?.text ? firstSentence(b.text) : "The briefing appears after the next hourly analysis."}</h3>
          {n > 0 && (
            <div className="ib-breadth" aria-label={`${bull} coins in an uptrend, ${neutral} sideways, ${bear} in a downtrend`}>
              <div className="ib-bar"><i className="bull" style={{ flexGrow: bull }} /><i className="flat" style={{ flexGrow: neutral }} /><i className="bear" style={{ flexGrow: bear }} /></div>
              <div className="ib-legend"><span><b className="text-bull">{bull}</b> uptrend</span><span><b>{neutral}</b> sideways</span><span><b className="text-bear">{bear}</b> downtrend</span></div>
            </div>
          )}
          {bullets.length > 0 && <ul className="ib-facts">{bullets.map((x) => <li key={x}>{x}</li>)}</ul>}
          {moves.length >= 6 && (
            <div className="ib-movers">
              <div><p className="ib-label">Leading · 24h</p>{up.map((x) => <Mover key={x.s} s={x.s} v={x.v} />)}</div>
              <div><p className="ib-label">Lagging · 24h</p>{down.map((x) => <Mover key={x.s} s={x.s} v={x.v} />)}</div>
            </div>
          )}
          {b?.text && (
            <>
              <button type="button" className="ib-more" aria-expanded={open} aria-controls="ib-full" onClick={() => setOpen((v) => !v)}>{open ? "Hide full briefing" : "Read full briefing"}</button>
              {open && <p id="ib-full" className="ib-full">{b.text}</p>}
            </>
          )}
        </div>
      )}
    </section>
  );
}

function Mover({ s, v }: { s: string; v: number }) {
  return (
    <Link to={`/asset/${slug(s)}`} className="ib-mover">
      <CoinAvatar symbol={s} size={20} /><span className="min-w-0 truncate">{base(s)}</span>
      <span className={`num ml-auto ${v >= 0 ? "text-bull" : "text-bear"}`}>{fmtPctRaw(v)}</span>
    </Link>
  );
}
