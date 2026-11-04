import FearGreed from "../components/FearGreed";
import MarketInsights from "../components/MarketInsights";
import { useState } from "react";
import { Link } from "react-router-dom";
import MyCoins from "../components/MyCoins";
import { BriefingPanel } from "../components/Polish";
import { ActiveSignalsCard, AiBriefCard, BtcCard, BtcChartCard, GlobalStatusCard, GuardianCard, MarketCapCard, PerformanceCard, RecentActivityCard, SentimentCard, VolatilityCard } from "../components/Overview";
import { useIsAdmin, useSession } from "../lib/session";
import NewsBanner, { countdown } from "../components/NewsBanner";
import { TfTabs } from "../components/Pickers";
import { Badge, Card, Empty, ErrorBox, Loading, Meter, Note, RegimeBadge, regimeTone, SignalBadge } from "../components/ui";
import { useApi } from "../lib/api";
import { base, DASH, fmtPct, fmtPctRaw, fmtPrice, fmtProb, isNum, slug, tone } from "../lib/format";
import { RoiFigure } from "../components/SignalExtras";
import { useLive } from "../lib/live";
import { useIsPro } from "../lib/mode";

const HORIZONS = ["15M", "1H", "4H", "12H", "24H", "3D"];

function heatColor(pct: number | null | undefined): string {
  if (!isNum(pct)) return "rgba(111,126,145,0.12)";
  const a = Math.min(0.55, 0.1 + Math.abs(pct) / 12);
  return pct >= 0 ? `rgba(14,203,129,${a})` : `rgba(246,70,93,${a})`;
}

export default function Dashboard() {
  const admin = useIsAdmin();
  const [tf, setTf] = useState("4h");
  const dash = useApi<any>(`/dashboard?timeframe=${tf}`, 60000);
  const dash4 = useApi<any>("/dashboard?timeframe=4h", 60000);    // same document as `dash` while 4H is chosen (one listener)
  const ctx = useApi<any>("/context", 600000);
  const cross = useApi<any>("/cross-asset?timeframe=1d", 300000);
  const mc = useApi<any>("/market-context");                  // same document as MarketInsights (one listener in the SDK)
  const track = useApi<any>("/track-record");                 // v2.20: active signals, activity, performance (+1 read per open)
  const d = dash.data;
  const sentiment = ctx.data?.sentiment;
  const status4 = dash4.data?.market_status;
  const briefing = mc.data?.briefing;

  return (
    <div className="space-y-4 sm:space-y-5">
      <NewsBanner />
      <OverviewHead rows={dash4.data?.rows} status={status4} briefing={briefing} />

      {/* row 1: four figures with a small line each (phones: 2-up from 360 px, one column below) */}
      <div className="grid grid-cols-1 gap-3 min-[360px]:grid-cols-2 sm:gap-4 xl:grid-cols-4">
        <BtcCard />
        <MarketCapCard mc={mc.data} ctx={ctx.data} />
        <VolatilityCard />
        <SentimentCard status={status4} sentiment={sentiment} />
      </div>

      {/* row 2: BTC chart + AI market intelligence (the v2.16 briefing) */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)]">
        <BtcChartCard />
        <AiBriefCard b={briefing} loading={mc.loading} />
      </div>

      {/* row 3: market status · open calls of the record · Trade Guardian (admin, only when its view exists) */}
      <div className={`grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.45fr)] ${admin ? "2xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.5fr)_minmax(0,0.8fr)]" : ""}`}>
        <GlobalStatusCard mc={mc.data} ctx={ctx.data} />
        <ActiveSignalsCard track={track.data} loading={track.loading} />
        {admin && <GuardianCard />}
      </div>

      {/* row 4: what happened lately · results since the restart (after fees) */}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <RecentActivityCard track={track.data} briefing={briefing} />
        <PerformanceCard track={track.data} loading={track.loading} />
      </div>

      {/* everything Home had before v2.20, below the overview */}
      <SectionHead title="Market overview" sub={<>{tf.toUpperCase()} timeframe<Refreshed /></>} right={<TfTabs value={tf} onChange={setTf} />} />
      {dash.error && <ErrorBox error={dash.error} retry={dash.reload} />}
      {!d && dash.loading && <Loading what="Loading market overview" />}

      <MyCoins rows={d?.rows} />
      <MoreDetail>
      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Market regime" right={<span className="text-xs text-mute">{(d?.regimes ?? []).length} coins</span>}>
          <div className="-mr-2 max-h-[34rem] space-y-3 overflow-y-auto pr-2">
            {(d?.regimes ?? []).map((r: any) => (
              <div key={r.symbol} className="grid grid-cols-[3.5rem_minmax(0,1fr)_3rem] items-center gap-3 text-sm">
                <Link to={`/asset/${slug(r.symbol)}`} className="tap-h inline-flex items-center font-medium hover:text-accent">{base(r.symbol)}</Link>
                <div><RegimeBadge regime={r.regime} /><div className="mt-1"><Meter value={r.confidence} tone={regimeTone(r.regime)} /></div></div>
                <span className="num text-right text-mute" title="Share of regime inputs that agree">{fmtProb(r.confidence)}</span>
              </div>
            ))}
            {!d?.regimes?.length && <Empty>No regimes yet: candles are still loading</Empty>}
          </div>
        </Card>
        <TopSignals d={d} />
        <Card title="Sentiment & context" right={<span className="text-xs text-mute">Fear &amp; Greed index</span>}>
          {sentiment ? (
            <div className="space-y-2">
              <FearGreed value={sentiment.value} label={sentiment.label} change7d={isNum(sentiment.change_7d) ? sentiment.change_7d : null} history={sentiment.history ?? []} />
              {sentiment.divergence && <Badge tone="warn">{sentiment.divergence}</Badge>}
            </div>
          ) : <Empty>{ctx.data?.reason ?? ctx.data?.sentiment_error ?? "Sentiment source unavailable"}</Empty>}
          {(cross.data?.observations ?? []).length > 0 && (
            <ul className="mt-3 space-y-1.5 border-t border-glass/[0.06] pt-3">
              {(cross.data?.observations ?? []).map((o: string) => (
                <li key={o} className="flex gap-2 rounded-lg bg-glass/[0.03] px-2.5 py-1.5 text-sm text-text"><span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-accent" aria-hidden="true" />{o}</li>
              ))}
            </ul>
          )}
          <ComingUp />
          <RadarMini />
        </Card>
      </div>

      {/* directly below the Fear & Greed row: dominance, altcoin season, market pulse, top headline */}
      <MarketInsights />

      <SectionHead title="Models & forecasts" sub="Context, not advice." />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
        <ForecastCard rows={d?.forecast_table} />
        <HeatmapCard rows={d?.heatmap} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Top opportunities">
          {d?.opportunities?.length ? d.opportunities.map((o: any) => (
            <Link key={o.symbol} to={`/asset/${slug(o.symbol)}`} className="grid min-h-[44px] grid-cols-[minmax(3rem,1fr)_auto] items-center gap-x-3 gap-y-1 rounded-lg px-2 py-1.5 text-sm hover:bg-glass/[0.05] sm:grid-cols-[minmax(0,1fr)_auto_4.5rem_4.5rem]">
              <span className="truncate font-medium">{base(o.symbol)}</span><SignalBadge signal={o.decision} />
              <span className="text-mute sm:text-right">{o.grade ? <span className="text-xs">Grade {o.grade === "A" ? "A · strong" : o.grade === "B" ? "B · moderate" : o.grade}</span> : DASH}</span><span className="num text-right text-mute">1:{isNum(o.risk_reward) ? o.risk_reward.toFixed(1) : DASH}<span className="text-xs"> R:R</span></span>
            </Link>
          )) : <Empty>No setup currently passes every check (grade, model agreement, risk/reward). That is a valid outcome.</Empty>}
        </Card>
        <Card title="Top risks">
          {d?.risks?.length ? d.risks.map((r: any, i: number) => (
            <div key={i} className="flex items-center justify-between gap-3 border-b border-line/50 px-2 py-2 text-sm last:border-0">
              <span className="font-medium">{base(r.symbol)}</span><span className="text-right text-warn">{r.risk}</span>
            </div>
          )) : <Empty>No elevated risks flagged</Empty>}
        </Card>
      </div>
      </MoreDetail>
    </div>
  );
}

function greeting() {
  const h = new Date().getHours();
  return h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

/** Top line of Home (kept from the old hero, owner 4 Nov 2026): the 4H market line, "Know why" (the briefing) and the
 *  quick actions Signals / Set an alert / Paper trade. */
function OverviewHead({ rows, status, briefing }: { rows?: any[]; status?: any; briefing?: any }) {
  const s = useSession();
  const [why, setWhy] = useState(false);
  const first = (s?.username || s?.name || s?.email || "").split(/[ @]/)[0];
  const r = rows ?? [];
  const buys = r.filter((x) => x.signal?.includes("BUY")).length;
  const sells = r.filter((x) => x.signal?.includes("SELL")).length;
  const best = [...r].filter((x) => x.signal && !x.signal.includes("HOLD")).sort((a, b) => (b.score ?? 0) - (a.score ?? 0))[0];
  const mood = status?.status ?? null;
  const moodText = mood === "BULL" ? "leaning bullish" : mood === "BEAR" ? "leaning bearish" : mood === "NEUTRAL" ? "mixed" : "warming up";
  const moodCls = mood === "BULL" ? "text-bull" : mood === "BEAR" ? "text-bear" : "text-accent";
  return (
    <section className="flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
      <div className="min-w-0 max-w-3xl">
        <p className="text-xs text-mute">{greeting()}{first ? `, ${first}` : ""} · 4H chart</p>
        <h1 className="font-display mt-0.5 text-xl font-semibold leading-tight tracking-tight sm:text-2xl">The market is <span className={moodCls}>{moodText}</span>.</h1>
        <p className="mt-1 text-sm text-mute">
          {r.length ? <><span className="font-medium text-bull">{buys} buy</span> · <span className="font-medium text-bear">{sells} sell</span> signals across {r.length} coins{best ? <> · strongest: <Link to={`/asset/${slug(best.symbol)}`} className="font-medium text-text hover:text-accent">{base(best.symbol)} {best.signal}</Link></> : null}</> : "Signals appear after the next engine run."}
          {briefing?.text && <>{" "}<button type="button" className="tap-h whitespace-nowrap font-medium text-accent hover:underline" aria-expanded={why} aria-controls="market-why" onClick={() => setWhy((v) => !v)}>{why ? "Hide why" : "Know why ›"}</button></>}
        </p>
        {why && briefing?.text && <BriefingPanel b={briefing} />}
      </div>
      <div className="flex flex-wrap gap-2">
        <Link to="/futures" className="btn btn-primary px-4"><span className="sm:hidden">Signals</span><span className="hidden sm:inline">Futures signals</span></Link>
        <Link to="/alerts" className="btn px-4">Set an alert</Link>
        <Link to="/paper" className="btn px-4">Paper trade</Link>
      </div>
    </section>
  );
}

function Refreshed() {
  const { refreshAt } = useLive();
  return <>{refreshAt ? " · refreshed just now" : ""}</>;
}

/** The older, deeper Home sections: shown by default, can be folded away (remembered on this device). */
function MoreDetail({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(() => { try { return localStorage.getItem("cia-home-detail") !== "0"; } catch { return true; } });
  const flip = () => setOpen((v) => { try { localStorage.setItem("cia-home-detail", v ? "0" : "1"); } catch { /* ignore */ } return !v; });
  return (
    <>
      <button type="button" onClick={flip} aria-expanded={open} aria-controls="home-more" className="btn btn-sm w-full justify-center sm:w-auto">
        {open ? "Hide market detail ▴" : "More market detail ▾"}
      </button>
      {open && <div id="home-more" className="space-y-5">{children}</div>}
    </>
  );
}

function TopSignals({ d }: { d: any }) {
  const pro = useIsPro();
  return (
    <Card title="Top signals">
      <div className="space-y-2">
        {(d?.top_signals ?? []).map((s: any) => (
          <Link key={s.symbol} to={`/asset/${slug(s.symbol)}`} className={`grid min-h-[44px] items-center gap-3 rounded-lg px-2 py-1.5 text-sm hover:bg-glass/[0.05] ${pro ? "grid-cols-[3.5rem_minmax(0,1fr)_3.5rem]" : "grid-cols-[3.5rem_minmax(0,1fr)]"}`}>
            <span className="font-medium">{base(s.symbol)}</span>
            {/* call and decision as two chips that wrap instead of one clipped line */}
            <span className="flex min-w-0 flex-wrap items-center gap-1.5"><SignalBadge signal={s.signal} />{s.decision && <Badge tone="mute">→ {s.decision}</Badge>}</span>
            {pro && <span className="num text-right text-mute" title="Signal score">{isNum(s.score) ? `${s.score.toFixed(0)}/100` : DASH}</span>}
          </Link>
        ))}
        {!d?.top_signals?.length && <Empty>No signals yet</Empty>}
      </div>
      <WinsMini />
    </Card>
  );
}

/** Forecast table (own component: it follows live prices, so a tick re-renders only this card). */
function ForecastCard({ rows }: { rows?: any[] }) {
  const { tickers } = useLive();
  return (
    <Card ai title="Forecast table — expected return per horizon">
      <div className="table-wrap">
        <table className="grid-table">
          <thead><tr><th>Asset</th><th className="text-right">Current</th>{HORIZONS.map((h) => <th key={h} className="text-right">{h}</th>)}</tr></thead>
          <tbody>
            {(rows ?? []).map((r: any) => (
              <tr key={r.symbol}>
                <td><Link to={`/asset/${slug(r.symbol)}`} className="tap-h inline-flex items-center font-medium hover:text-accent">{base(r.symbol)}</Link></td>
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
      <Note>* No proven edge for that model.</Note>
    </Card>
  );
}

function HeatmapCard({ rows }: { rows?: any[] }) {
  const { tickers } = useLive();
  return (
    <Card title="Market heatmap — 24h change">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-2 2xl:grid-cols-3">
        {(rows ?? []).map((h: any) => {
          const ch = tickers[h.symbol]?.change_pct ?? h.change_24h_pct;
          return (
            <Link key={h.symbol} to={`/asset/${slug(h.symbol)}`} className="rounded-xl border border-glass/10 p-3 transition-colors hover:border-accent/50" style={{ background: heatColor(ch) }}>
              <div className="flex items-center justify-between"><span className="font-semibold">{base(h.symbol)}</span><span className="num text-sm font-semibold">{fmtPctRaw(ch)}</span></div>
              <div className="mt-1.5 flex flex-wrap gap-1 text-xs uppercase tracking-wide text-text/80">
                {h.signal && <span className="rounded-full bg-ink/40 px-2 py-0.5">{h.signal}</span>}
                {h.regime && <span className="rounded-full bg-ink/40 px-2 py-0.5">{h.regime}</span>}
              </div>
            </Link>
          );
        })}
      </div>
    </Card>
  );
}


/** Section header used down the Home page: title, one line of context, optional controls on the right. */
function SectionHead({ title, sub, right }: { title: string; sub?: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 border-b border-glass/[0.07] pb-3 pt-3">
      <div className="min-w-0">
        <h2 className="section-title">{title}</h2>
        {sub && <p className="mt-1 text-sm text-mute">{sub}</p>}
      </div>
      {right}
    </div>
  );
}

/* ---- extra dashboard sections (they keep the three cards in this row the same height) ---------------------- */
function MiniHead({ title, to }: { title: string; to: string }) {
  return (
    <div className="mb-2 mt-4 flex items-center justify-between border-t border-glass/[0.06] pt-3">
      <span className="text-xs font-semibold uppercase tracking-wide text-mute">{title}</span>
      <Link to={to} className="tap-h inline-flex items-center text-xs text-accent hover:underline">See all →</Link>
    </div>
  );
}

/** Signals that hit their targets in the last 24 hours (else this week). */
function WinsMini() {
  const v = useApi<any>("/wins-today", 60_000);
  const wins: any[] = (v.data?.wins ?? []).slice(0, 5);
  const label: Record<string, string> = { TP1: "TP1", TP2: "TP2", TP3: "TP3" };
  return (
    <>
      <MiniHead title={v.data?.period === "today" ? "Wins today" : "Wins this week"} to="/results" />
      {wins.length ? (
        <ul className="space-y-1.5">
          {wins.map((w, i) => (
            <li key={i} className="flex items-center justify-between gap-2 rounded-md bg-bull/[0.06] px-2 py-1.5 text-sm">
              <span className="flex min-w-0 items-center gap-2">
                <span className="font-medium">{base(w.symbol)}</span>
                <span className={`text-xs font-bold ${w.side === "LONG" ? "text-bull" : "text-bear"}`}>{w.side}</span>
                <span className="text-xs uppercase text-mute">{w.timeframe}</span>
              </span>
              <span className="flex items-center gap-2">
                <span className="rounded bg-bull/15 px-1.5 text-xs font-bold text-bull">{label[w.status] ?? "WIN"}</span>
                <RoiFigure x={w} size="sm" label={false} align="left" />
              </span>
            </li>
          ))}
        </ul>
      ) : <p className="text-xs text-mute">No wins yet in this period.</p>}
    </>
  );
}

/** The next high-impact US releases (signals pause around them). */
function ComingUp() {
  const v = useApi<any>("/news", 300_000);
  const now = Date.now();
  const evs: any[] = (v.data?.calendar ?? []).filter((e: any) => e.impact === "High" && e.ts > now - 30 * 60_000).slice(0, 3);
  return (
    <>
      <MiniHead title="Coming up · US data" to="/news" />
      {evs.length ? (
        <ul className="space-y-1.5">
          {evs.map((e, i) => (
            <li key={i} className="flex items-center justify-between gap-2 text-sm">
              <span className="min-w-0 truncate">{e.title}</span>
              <span className="num shrink-0 text-xs text-warn">{countdown(e.ts, now)}</span>
            </li>
          ))}
        </ul>
      ) : <p className="text-xs text-mute">No high-impact release in the coming days.</p>}
    </>
  );
}

/** Radar: the strongest coins outside the app, against BTC. */
function RadarMini() {
  const v = useApi<any>("/radar", 600_000);
  const picks: any[] = (v.data?.picks ?? []).slice(0, 3);
  if (!picks.length) return null;
  return (
    <>
      <MiniHead title="Radar · beating the market" to="/radar" />
      <ul className="space-y-1.5">
        {picks.map((p) => (
          <li key={p.symbol} className="flex items-center justify-between gap-2 text-sm">
            <span className="flex items-center gap-2"><span className="w-4 text-center text-xs text-accent/80">{p.rank}</span><span className="font-medium">{base(p.symbol)}</span></span>
            <span className="num text-xs"><span className="text-mute">vs BTC 7d </span><span className={tone(p.rs_7d)}>{isNum(p.rs_7d) ? `${p.rs_7d > 0 ? "+" : ""}${(p.rs_7d * 100).toFixed(1)}%` : "—"}</span></span>
          </li>
        ))}
      </ul>
    </>
  );
}
