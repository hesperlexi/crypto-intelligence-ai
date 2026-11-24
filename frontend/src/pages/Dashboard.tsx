import MarketInsights from "../components/MarketInsights";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { FirstWeekGuide } from "../components/TodayPulse";
import WelcomeTour from "../components/WelcomeTour";
import { Decisions, MarketStatus, MyCapital, MyPositions } from "../components/V3Home";
import { ThinkingSpectrum } from "../components/Instruments";
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
  // owner 24 Nov 2026: the mood card turns through 15M → 1H → 4H every 10 s (tap a timeframe to hold it; paused on hover
  // and while the tab is hidden). +2 view listeners (15m / 1h dashboards) while Home is open.
  const mood15 = useApi<any>("/dashboard?timeframe=15m", 60000);
  const mood1h = useApi<any>("/dashboard?timeframe=1h", 60000);
  const rot = useMoodRotation();
  const moodData = [mood15.data, mood1h.data, dash4.data][rot.i];
  const moodTf = MOOD_TFS[rot.i];
  const openCount = ((track.data?.live?.signals ?? []) as any[]).filter((x) => x.status === "OPEN").length;

  return (
    <div className="space-y-4 sm:space-y-5">
      <NewsBanner />
      {/* V3.0 Overview (owner-approved layout, 24 Nov 2026): A market & risk status · B my capital + F my positions ·
          E AI decisions · C market intelligence · D watchlist board · G recent developments. Phones: A, F, B, E, … */}
      {/* owner 24 Nov 2026: the market mood card is back, with the V3 market & risk status embedded in it */}
      <section className="panel panel-hero v3-glass mood-card p-4 sm:p-6" aria-label="Market mood" onPointerEnter={() => rot.hover(true)} onPointerLeave={() => rot.hover(false)}>
        <MoodTfSwitch rot={rot} />
        <div className="mood-grid">
          <div className="min-w-0">
            <OverviewHead rows={moodData?.rows} status={moodData?.market_status} briefing={briefing} tfLabel={moodTf.toUpperCase()} />
            <MarketStatus status4={moodData?.market_status} rows={moodData?.rows} embedded tfLabel={moodTf.toUpperCase()} />
            <TodayLine track={track.data} />
          </div>
          <ThinkingSpectrum rows={moodData?.rows} status={moodData?.market_status} fg={sentiment?.value} fgLabel={sentiment?.label} tfLabel={moodTf.toUpperCase()} />
        </div>
      </section>

      <FirstWeekGuide />
      <WelcomeTour />
      <div className="grid-even grid gap-4 lg:grid-cols-2">
        <div className="order-2 lg:order-1"><MyCapital /></div>
        <div className="order-1 lg:order-2"><MyPositions /></div>
      </div>

      <Decisions rows={dash4.data?.rows} track={track.data} />

      <PhoneFold id="market" title="Market today" sub="BTC, market cap, volatility, sentiment, chart, AI briefing">
      {/* C market intelligence: the four measured figures, then the BTC chart beside the AI briefing */}
      <section className="panel p-0" aria-label="Market intelligence">
        <header className="card-head flex items-center justify-between border-b px-4 py-2.5"><h2 className="label">Market today</h2>
          <span className="text-xs text-mute">Measured data · Binance, CoinGecko</span></header>
        <div className="ov-strip px-4 pb-4 sm:px-5 grid grid-cols-1 min-[360px]:grid-cols-2 xl:grid-cols-4">
          <BtcCard />
          <MarketCapCard mc={mc.data} ctx={ctx.data} />
          <VolatilityCard />
          <SentimentCard status={status4} sentiment={sentiment} />
        </div>
      </section>
      <div className="ov-pair grid gap-4 xl:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)]">
        <BtcChartCard />
        <IntelBrief b={briefing} loading={mc.loading} rows={dash4.data?.rows} status={status4} />
      </div>

      </PhoneFold>
      <PhoneFold id="coins" title="Coins" sub="Every coin we follow: trend, signal, AI outlook">
      {/* D the watchlist: one board for every coin (table or heatmap) */}
      {dash.error && <ErrorBox error={dash.error} retry={dash.reload} />}
      <MarketBoard d={d} tf={tf} onTf={setTf} loading={dash.loading} />

      </PhoneFold>
      <PhoneFold id="activity" title="Recent developments" sub="Activity, signal performance, market context">
      {/* G recent developments + signal performance + market context */}
      <div className="grid-even grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        <RecentActivityCard track={track.data} briefing={briefing} />
        <div className="ov-stack flex min-w-0 flex-col gap-4">
          {admin && <GuardianCard />}
          <PerformanceCard track={track.data} loading={track.loading} />
        </div>
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

      </PhoneFold>
      <PhoneFold id="details" title="Market details" sub="Dominance, altcoin season, options, traditional markets">
      <DetailsFold>
        <MarketInsights />
        <div className="grid-even grid gap-4 lg:grid-cols-2">
          <VolOptionsCard />
          <MacroCard />
        </div>
      </DetailsFold>
      </PhoneFold>
    </div>
  );
}

function greeting() {
  const h = new Date().getHours();
  return h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

/** Top line of Home (kept from the old hero, owner 4 Nov 2026): the 4H market line, "Know why" (the briefing) and the
 *  quick actions Signals / Set an alert / Paper trade. */
function OverviewHead({ rows, status, briefing, tfLabel = "4H" }: { rows?: any[]; status?: any; briefing?: any; tfLabel?: string }) {
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
    <section>
      <div className="min-w-0 max-w-3xl">
        <p className="text-sm text-mute">{greeting()}{first ? `, ${first}` : ""}</p>
        <h1 className="v3-title mt-1">The market is <span className={moodCls}>{moodText}</span>.</h1>
        <p className="mt-1 text-sm text-mute">
          {r.length ? <>On the {tfLabel} chart: <span className="font-medium text-bull">{buys} buy</span> · <span className="font-medium text-bear">{sells} sell</span> signals across {r.length} coins{best ? <> · strongest: <Link to={`/asset/${slug(best.symbol)}`} className="font-medium text-text hover:text-accent">{base(best.symbol)} {best.signal}</Link></> : null}</> : "Signals appear after the next engine run."}
          {briefing?.text && <>{" "}<button type="button" className="tap-h whitespace-nowrap font-medium text-accent hover:underline" aria-expanded={why} aria-controls="market-why" onClick={() => setWhy((v) => !v)}>{why ? "Hide why" : "Know why ›"}</button></>}
        </p>
        {why && briefing?.text && <BriefingPanel b={briefing} />}
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
/** V3.0 phones: the lower Overview sections fold into one line each (closed by default, remembered), so the phone page
 *  shows status, positions, capital and decisions first. Computers always show them open. */
function PhoneFold({ id, title, sub, children }: { id: string; title: string; sub: string; children: React.ReactNode }) {
  const phone = typeof window !== "undefined" && window.matchMedia?.("(max-width: 767px)").matches;
  const key = `cia-fold-${id}`;
  const [open, setOpen] = useState(() => { try { return localStorage.getItem(key) === "1"; } catch { return false; } });
  if (!phone) return <>{children}</>;
  const flip = () => setOpen((v) => { try { localStorage.setItem(key, v ? "0" : "1"); } catch { /* ignore */ } return !v; });
  return (
    <section className="space-y-4" aria-label={title}>
      <button type="button" onClick={flip} aria-expanded={open} className="panel flex w-full items-center gap-3 px-4 py-3.5 text-left">
        <span className="min-w-0 flex-1"><span className="block text-[0.9375rem] font-semibold">{title}</span><span className="block truncate text-xs text-mute">{sub}</span></span>
        <span className="text-sm font-medium text-accent">{open ? "Hide" : "Show"}</span>
      </button>
      {open && children}
    </section>
  );
}

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


const MOOD_TFS = ["15m", "1h", "4h"] as const;
const MOOD_EVERY_MS = 10_000;

/** Which timeframe the mood card shows: turns every 10 s unless held (a tap), hovered, or the tab is hidden. */
function useMoodRotation() {
  const [i, setI] = useState(2);
  const [held, setHeld] = useState(false);
  const hovered = useRef(false);
  const [tick, setTick] = useState(0);              // restarts the progress bar
  useEffect(() => {
    if (held) return;
    const t = window.setInterval(() => {
      if (hovered.current || document.hidden) return;
      setI((v) => (v + 1) % MOOD_TFS.length); setTick((n) => n + 1);
    }, MOOD_EVERY_MS);
    return () => window.clearInterval(t);
  }, [held]);
  return {
    i, held, tick,
    pick: (k: number) => { setI(k); setHeld(true); },
    auto: () => { setHeld(false); setTick((n) => n + 1); },
    hover: (v: boolean) => { hovered.current = v; },
  };
}

function MoodTfSwitch({ rot }: { rot: ReturnType<typeof useMoodRotation> }) {
  return (
    <div className="mood-tf" role="group" aria-label="Timeframe of the market mood">
      {MOOD_TFS.map((tf, k) => (
        <button key={tf} type="button" aria-pressed={rot.i === k} className={rot.i === k ? "on" : ""} onClick={() => rot.pick(k)}>
          {tf.toUpperCase()}
          {rot.i === k && !rot.held && <i key={rot.tick} className="mood-tf-bar" aria-hidden="true" />}
        </button>
      ))}
      <button type="button" className={`mood-tf-auto ${rot.held ? "" : "on"}`} aria-pressed={!rot.held} onClick={rot.auto}
        title="Turn through 15M, 1H and 4H every 10 seconds">{rot.held ? "▶ Auto" : "Auto"}</button>
    </div>
  );
}
