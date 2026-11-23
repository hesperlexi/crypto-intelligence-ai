import MarketInsights from "../components/MarketInsights";
import { useState } from "react";
import { Link } from "react-router-dom";
import { FirstWeekGuide } from "../components/TodayPulse";
import WelcomeTour from "../components/WelcomeTour";
import { OpportunityBoard } from "../components/Deck";
import { OrbitDial } from "../components/Instruments";
import { BriefingPanel } from "../components/Polish";
import MarketBoard, { IntelBrief } from "../components/MarketBoard";
import { MacroCard, UnlocksList, VolOptionsCard } from "../components/Derivs";
import { BtcCard, BtcChartCard, GuardianCard, MarketCapCard, PerformanceCard, RecentActivityCard, SentimentCard, VolatilityCard } from "../components/Overview";
import { useIsAdmin, useSession } from "../lib/session";
import NewsBanner, { countdown } from "../components/NewsBanner";
import { Card, ErrorBox } from "../components/ui";
import { useApi } from "../lib/api";
import { base, isNum, slug, tone } from "../lib/format";

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
  const openCount = ((track.data?.live?.signals ?? []) as any[]).filter((x) => x.status === "OPEN").length;

  return (
    <div className="space-y-4 sm:space-y-5">
      <NewsBanner />
      {/* v2.56 Intelligence Deck: one lead instrument - the market line and actions beside the market dial,
          then the four figures as a divided strip */}
      <section className="panel panel-hero deck-hero p-4 sm:p-6" aria-label="Market today">
        <div className="deck-hero-grid">
          <OverviewHead rows={dash4.data?.rows} status={status4} briefing={briefing} track={track.data} />
          <OrbitDial rows={dash4.data?.rows} status={status4} fg={sentiment?.value} fgLabel={sentiment?.label} />
        </div>
        <div className="ov-strip mt-5 grid grid-cols-1 min-[360px]:grid-cols-2 xl:grid-cols-4">
          <BtcCard />
          <MarketCapCard mc={mc.data} ctx={ctx.data} />
          <VolatilityCard />
          <SentimentCard status={status4} sentiment={sentiment} />
        </div>
      </section>

      <FirstWeekGuide />
      <WelcomeTour />
      {/* row 2: what is running (live journeys) beside what is setting up (the opportunity board) */}
      {/* v2.78 (owner, 23 Nov 2026: "too crowded"): the live-signal gauges are gone from Overview (Signals / Results / Command
          Centre still show every running call); the opportunity board is the wide strip here */}
      <div className="grid gap-4">
        <Card title="Opportunity board" right={<span className="text-xs text-mute">4H · passes every check</span>} className="deck-fill deck-wide">
          <OpportunityBoard rows={dash4.data?.opportunities} />
        </Card>
      </div>

      {/* row 3: BTC chart beside the market intelligence brief (v2.70: headline, breadth, facts, leaders / laggards) */}
      <div className="ov-pair grid gap-4 xl:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)]">
        <BtcChartCard />
        <IntelBrief b={briefing} loading={mc.loading} rows={dash4.data?.rows} status={status4} />
      </div>

      {/* row 4 (v2.70): ONE market board - coins, trend, signal, AI outlook, watch notes; table or heatmap */}
      {dash.error && <ErrorBox error={dash.error} retry={dash.reload} />}
      <MarketBoard d={d} tf={tf} onTf={setTf} loading={dash.loading} />

      {/* row 5: performance (+ Trade Guardian for the admin) · recent activity · market context, equal heights */}
      <div className="grid-even grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        <div className="ov-stack flex min-w-0 flex-col gap-4">
          {admin && <GuardianCard />}
          <PerformanceCard track={track.data} loading={track.loading} />
        </div>
        <RecentActivityCard track={track.data} briefing={briefing} />
        <div className="lg:col-span-2 xl:col-span-1">
          <Card title="Market context" className="h-full">
            {sentiment?.divergence && <p className="mb-2 text-sm text-warn">{sentiment.divergence}</p>}
            {(cross.data?.observations ?? []).length > 0 && (
              <ul className="ctx-notes">
                {(cross.data?.observations ?? []).map((o: string) => <li key={o}>{o}</li>)}
              </ul>
            )}
            <ComingUp />
            <RadarMini />
            <UnlocksList />
          </Card>
        </div>
      </div>

      {/* v2.76 (owner: the page is long): the deeper market cards sit in one fold, open by default, remembered */}
      <DetailsFold>
        {/* dominance, altcoin season, market pulse, top headline */}
        <MarketInsights />

        {/* v2.75: options / volatility beside the traditional markets (views/derivs) */}
        <div className="grid-even grid gap-4 lg:grid-cols-2">
          <VolOptionsCard />
          <MacroCard />
        </div>
      </DetailsFold>
    </div>
  );
}

function greeting() {
  const h = new Date().getHours();
  return h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

/** Top line of Home (kept from the old hero, owner 4 Nov 2026): the 4H market line, "Know why" (the briefing) and the
 *  quick actions Signals / Set an alert / Paper trade. */
function OverviewHead({ rows, status, briefing, track }: { rows?: any[]; status?: any; briefing?: any; track?: any }) {
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
        <p className="text-sm text-mute">{greeting()}{first ? `, ${first}` : ""}</p>
        <h1 className="font-display mt-1 text-2xl font-semibold leading-tight tracking-[-0.03em] sm:text-[2.125rem] sm:leading-[2.5rem]">The market is <span className={moodCls}>{moodText}</span>.</h1>
        <p className="mt-1 text-sm text-mute">
          {r.length ? <>On the 4H chart: <span className="font-medium text-bull">{buys} buy</span> · <span className="font-medium text-bear">{sells} sell</span> signals across {r.length} coins{best ? <> · strongest: <Link to={`/asset/${slug(best.symbol)}`} className="font-medium text-text hover:text-accent">{base(best.symbol)} {best.signal}</Link></> : null}</> : "Signals appear after the next engine run."}
          {briefing?.text && <>{" "}<button type="button" className="tap-h whitespace-nowrap font-medium text-accent hover:underline" aria-expanded={why} aria-controls="market-why" onClick={() => setWhy((v) => !v)}>{why ? "Hide why" : "Know why ›"}</button></>}
        </p>
        {why && briefing?.text && <BriefingPanel b={briefing} />}
        <TodayLine track={track} />
        <div className="mt-5 flex flex-wrap gap-2">
        <Link to="/futures" className="btn btn-primary px-4"><span className="sm:hidden">Signals</span><span className="hidden sm:inline">Futures signals</span></Link>
        <Link to="/alerts" className="btn px-4">Set an alert</Link>
        <Link to="/paper" className="btn px-4">Paper trade</Link>
        </div>
      </div>
    </section>
  );
}

/** Today in one line: open calls and what closed today (Dubai day), after fees - from the record already loaded. */
function TodayLine({ track }: { track?: any }) {
  const sigs: any[] = track?.live?.signals ?? [];
  if (!track) return null;
  const DUBAI = 4 * 3_600_000, day = (ms: number) => Math.floor((ms + DUBAI) / 86_400_000), today = day(Date.now());
  const open = sigs.filter((x) => x.status === "OPEN").length;
  const closed = sigs.filter((x) => ["STOPPED", "TP1", "TP2", "TP3", "EXPIRED"].includes(x.status) && isNum(x.closed_at) && day(x.closed_at) === today && isNum(x.return_pct));
  const sum = closed.reduce((a, x) => a + x.return_pct, 0), won = closed.filter((x) => x.return_pct > 0).length;
  return (
    <div className="deck-today mt-4">
      <span><b className="num">{open}</b> open signal{open === 1 ? "" : "s"}</span>
      <span>{closed.length ? <>Closed today <b className={`num ${sum >= 0 ? "text-bull" : "text-bear"}`}>{sum >= 0 ? "+" : ""}{sum.toFixed(1)}%</b> <span className="text-mute">({won} won · {closed.length - won} lost, after fees)</span></> : <span className="text-mute">Nothing closed yet today</span>}</span>
    </div>
  );
}

/* ---- extra dashboard sections (they keep the three cards in this row the same height) ---------------------- */
function MiniHead({ title, to }: { title: string; to: string }) {
  return (
    <div className="mb-2 mt-4 flex items-center justify-between border-t border-glass/[0.06] pt-3">
      <span className="text-sm font-medium text-text">{title}</span>
      <Link to={to} className="tap-h inline-flex items-center text-xs text-accent hover:underline">See all</Link>
    </div>
  );
}

/** The next high-impact US releases (signals pause around them). */
function ComingUp() {
  const v = useApi<any>("/news", 300_000);
  const now = Date.now();
  const evs: any[] = (v.data?.calendar ?? []).filter((e: any) => e.impact === "High" && e.ts > now - 30 * 60_000).slice(0, 3);
  return (
    <>
      <MiniHead title="Coming up: US data" to="/news" />
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
      <MiniHead title="Beating the market (radar)" to="/radar" />
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

/** Market details fold (v2.76): dominance, altcoin season, pulse, volatility & options, traditional markets. */
function DetailsFold({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(() => { try { return localStorage.getItem("cia-home-details") !== "0"; } catch { return true; } });
  const flip = () => setOpen((v) => { try { localStorage.setItem("cia-home-details", v ? "0" : "1"); } catch { /* ignore */ } return !v; });
  return (
    <section aria-label="Market details" className="space-y-4">
      <button type="button" onClick={flip} aria-expanded={open} className="fold-head">
        <span className="font-display text-xl font-semibold">Market details</span>
        <span className="text-sm text-mute">dominance · altcoin season · volatility · traditional markets</span>
        <span className="ml-auto text-sm font-medium text-accent">{open ? "Hide ▴" : "Show ▾"}</span>
      </button>
      {open && children}
    </section>
  );
}
