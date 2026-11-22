// What signed-out visitors see: a short, honest sales page with live prices, features, pricing and sign-in.
import PlanCards from "./PlanCards";
import { signInWithPopup } from "firebase/auth";
import { Constellation, CyberHorizon, HoloOrbit, SignalWave } from "./Xeno";
import { useEffect, useState } from "react";
import { tickers as restTickers } from "../lib/binance";
import { raceSocket } from "../lib/ws";

const WS_HOSTS = ["wss://stream.binance.com:9443", "wss://stream.binance.com:443", "wss://data-stream.binance.vision"];
import { auth, googleProvider } from "../lib/firebase";
import { base, fmtPctRaw, fmtPrice } from "../lib/format";
import { useMembershipConfig } from "../lib/membership";
import WinsToday from "./WinsToday";
import LandingProof from "./LandingProof";
import TelegramLink from "./TelegramLink";
import { BUILD_ID } from "../lib/version";
import { mediaUrl, SHOW_APP_DEMO } from "../lib/media";
import { CoinAvatar } from "./Polish";
import SiteFooter, { TRUST_LINKS } from "./SiteFooter";
import { AuthDialog, AuthMode, GoogleIcon } from "./AuthPanel";
import { authMessage } from "../lib/account";
import { AnimatedLogo, HeroLogo } from "./Logo";
import { Link } from "react-router-dom";

const COINS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT"];

const FEATURES: [string, string, string][] = [
  ["M9 9h6v6H9zM4 4h16v16H4zM9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3", "4 AI models vote", "A call counts only when the models agree."],
  ["M12 2v20M5 9h14M7 15h10", "Ready-made trade plans", "Entry, stop-loss and three targets on every signal."],
  ["M3 17l6-6 4 4 8-8M15 7h6v6", "Spot & futures", "Long and short calls with a safe leverage."],
  ["M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 01-3.4 0", "Instant phone alerts", "Get notified the moment a setup appears."],
  ["M2 6h20v13H2zM2 10h20M6 15h4", "Practise risk-free", "Paper trading with virtual money and live prices."],
  ["M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM8.5 12l2.5 2.5 4.5-5", "Honest accuracy", "Real hit rates, scored on unseen data."],
];

function Icon({ d }: { d: string }) {
  return <svg aria-hidden="true" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>;
}

export default function Landing({ error }: { error: string | null }) {
  const [err, setErr] = useState<string | null>(error);
  const [busy, setBusy] = useState(false);
  const [px, setPx] = useState<Record<string, any>>({});
  const [demo, setDemo] = useState<null | "demo" | "story">(null);
  const [dialog, setDialog] = useState<AuthMode | null>(null);
  useEffect(() => {
    // 24h stats over REST every 30 s, the price itself from every trade (Binance WebSocket), shown ~8x a second
    let alive = true, pending: Record<string, number> = {};
    const load = () => restTickers(COINS).then((t) => alive && setPx((cur) => {
      const out: Record<string, any> = { ...t };
      for (const k of Object.keys(out)) if (cur[k]?.last && Date.now() - (cur[k].ts ?? 0) < 5000) out[k] = { ...out[k], last: cur[k].last, ts: cur[k].ts };
      return out;
    })).catch(() => {});
    load();
    const id = window.setInterval(load, 30000);
    const by: Record<string, string> = Object.fromEntries(COINS.map((c) => [c.replace("/", ""), c]));
    const streams = COINS.map((c) => `${c.replace("/", "").toLowerCase()}@aggTrade`).join("/");
    const race = raceSocket(WS_HOSTS.map((h) => `${h}/stream?streams=${streams}`), (m) => {
      const d = m.data; const sym = d && by[d.s];
      if (sym) pending[sym] = +d.p;
    }, () => {});
    const flush = window.setInterval(() => {
      if (!Object.keys(pending).length) return;
      const p = pending; pending = {};
      setPx((cur) => {
        const out = { ...cur };
        for (const [k, v] of Object.entries(p)) {
          const t = cur[k];
          if (!t) continue;
          const open = t.last && t.change_pct != null ? t.last / (1 + t.change_pct / 100) : null;
          out[k] = { ...t, last: v, ts: Date.now(), change_pct: open ? (v / open - 1) * 100 : t.change_pct };
        }
        return out;
      });
    }, 125);
    return () => { alive = false; window.clearInterval(id); window.clearInterval(flush); race.close(); };
  }, []);
  const signIn = async () => {
    setBusy(true);
    try { await signInWithPopup(auth, googleProvider); } catch (e: any) { setErr(authMessage(e)); }
    setBusy(false);
  };
  const cfg = useMembershipConfig();
  const plans = cfg.plans;
  const cta = (big = false) => (
    <button className={`btn btn-primary ${big ? "px-6 py-3 text-base" : "px-4 py-2 text-sm"}`} onClick={signIn} disabled={busy}>
      <GoogleIcon />
      {busy ? "Opening Google…" : "Continue with Google"}
    </button>
  );
  const emailCta = (big = false) => (
    <button className={`btn ${big ? "px-5 py-3 text-base" : "px-4 py-2 text-sm"}`} onClick={() => setDialog("signup")}>
      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="mr-2 inline-block align-[-3px]"><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 7l9 6 9-6" /></svg>
      Sign up with email
    </button>
  );

  const btc = px["BTC/USDT"];
  return (
    <div className="landing-bg min-h-full overflow-x-clip text-text">
      <header className="glass-bar sticky top-0 z-30 border-b">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-2.5">
            <AnimatedLogo size={34} />
            <span className="font-display text-[15px] font-semibold tracking-tight sm:text-base">Crypto Intelligence <span className="text-accent">AI</span></span>
          </div>
          <nav className="flex items-center gap-1 sm:gap-2" aria-label="Site">
            <a href="#wins" className="hidden px-2 text-sm text-mute hover:text-text md:inline">Results</a>
            <a href="#pricing" className="hidden px-2 text-sm text-mute hover:text-text md:inline">Membership</a>
            <span className="hidden px-2 text-sm md:inline"><TelegramLink variant="link" /></span>
            <a href={`/manual.pdf?v=${BUILD_ID}`} target="_blank" rel="noopener" className="hidden px-2 text-sm text-mute hover:text-text lg:inline">Manual</a>
            <button className="btn px-4 py-1.5 text-sm" onClick={() => setDialog("signin")} disabled={busy}>Sign in</button>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4">
        {/* hero: the members' entrance - the product itself on the right, a live ticket */}
        <section className="relative isolate grid items-center gap-10 pb-10 pt-10 sm:pt-16 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)] lg:gap-14">
          <CyberHorizon className="pointer-events-none absolute -bottom-24 left-1/2 -z-20 h-[46%] w-screen max-w-none -translate-x-1/2 opacity-60" />
          <div>
            <HeroLogo size={112} title="Crypto Intelligence AI logo" className="mb-5" />
            <p className="flex items-center gap-2 text-sm text-mute">
              <span className="h-1.5 w-1.5 rounded-full bg-bull" aria-hidden="true" />
              AI trade plans for spot and futures, updated every few minutes
            </p>
            <h1 className="font-display mt-4 text-[40px] font-semibold leading-[1.04] tracking-[-0.035em] sm:text-[64px]">
              Know the setup before you trade.
            </h1>
            <p className="mt-5 max-w-lg text-lg leading-relaxed text-mute">
              Entry, stop-loss and three targets on every call, a phone alert the moment it appears, and a practice account to try it with virtual money first.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              {cta(true)}
              {emailCta(true)}
            </div>
            {err && <p className="mt-3 text-sm text-bear">{err}</p>}
            <p className="mt-4 text-sm text-mute">Already a member? <button className="text-accent hover:underline" onClick={() => setDialog("signin")}>Sign in</button> or <button className="text-accent hover:underline" onClick={() => setDialog("reset")}>reset your password</button>.</p>
            <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
              {SHOW_APP_DEMO && <button className="text-mute hover:text-text" onClick={() => setDemo("demo")}>▶ Watch the app (70 s)</button>}
              <button className="text-mute hover:text-text" onClick={() => setDemo("story")}>▶ Why traders use it (45 s)</button>
              <TelegramLink label="Free signals on Telegram" />
            </div>
          </div>

          {/* the live ticket, floating in front of a holographic orbit */}
          <div className="relative isolate">
            <HoloOrbit className="pointer-events-none absolute left-1/2 top-1/2 -z-10 w-[135%] max-w-none -translate-x-1/2 -translate-y-1/2 opacity-90" />
            <div className="panel panel-hero relative p-6 sm:p-7">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <CoinAvatar symbol="BTC/USDT" size={42} />
                  <div>
                    <div className="font-display text-lg font-semibold tracking-tight">Bitcoin <span className="text-mute">· 4H</span></div>
                    <div className="text-xs text-mute">Example of a trade card</div>
                  </div>
                </div>
                <span className="rounded-md bg-bull/15 px-2.5 py-1 text-xs font-semibold text-bull ring-1 ring-bull/30">Long</span>
              </div>
              <div className="mt-6">
                <div className="text-xs text-mute">Live price</div>
                <div className="num mt-1 flex items-baseline gap-3">
                  <span className="font-display text-[32px] font-semibold leading-none tracking-[-0.03em] sm:text-[40px]">{btc?.last ? `$${fmtPrice(btc.last)}` : "—"}</span>
                  {btc?.change_pct != null && <span className={`text-sm ${btc.change_pct >= 0 ? "text-bull" : "text-bear"}`}>{fmtPctRaw(btc.change_pct)} 24h</span>}
                </div>
              </div>
              <svg aria-hidden="true" viewBox="0 0 300 90" className="mt-5 h-20 w-full" preserveAspectRatio="none">
                <defs><linearGradient id="lf" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="rgb(var(--accent))" stopOpacity="0.28" /><stop offset="1" stopColor="rgb(var(--accent))" stopOpacity="0" /></linearGradient></defs>
                <line x1="0" y1="14" x2="300" y2="14" stroke="rgb(var(--bull))" strokeDasharray="3 5" strokeWidth="1" />
                <line x1="0" y1="62" x2="300" y2="62" stroke="rgb(var(--text) / 0.45)" strokeDasharray="3 5" strokeWidth="1" />
                <line x1="0" y1="84" x2="300" y2="84" stroke="rgb(var(--bear))" strokeDasharray="3 5" strokeWidth="1" />
                <path d="M0 70 L20 74 L40 66 L60 72 L80 64 L100 68 L120 58 L140 62 L160 50 L180 54 L200 40 L220 44 L240 30 L260 34 L280 22 L300 18 V90 H0Z" fill="url(#lf)" />
                <path d="M0 70 L20 74 L40 66 L60 72 L80 64 L100 68 L120 58 L140 62 L160 50 L180 54 L200 40 L220 44 L240 30 L260 34 L280 22 L300 18" fill="none" stroke="rgb(var(--accent))" strokeWidth="1.8" />
              </svg>
              <dl className="mt-5 grid grid-cols-3 gap-px overflow-hidden rounded-xl border border-glass/10 bg-glass/10 text-sm">
                {([["Entry", "zone on the card", ""], ["Stop-loss", "set for you", "text-bear"], ["Targets", "TP1 · TP2 · TP3", "text-bull"]] as const).map(([k, v, c]) => (
                  <div key={k} className="bg-panel/80 px-3 py-2.5">
                    <dt className="text-xs text-mute">{k}</dt>
                    <dd className={`mt-0.5 font-medium ${c}`}>{v}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-4 text-xs text-mute">Members get the real levels, the suggested leverage and an alert the moment a call opens.</p>
            </div>
          </div>
        </section>

        {/* live market ribbon: one crystal strip, not six cards */}
        <section aria-label="Live prices" className="panel grid grid-cols-2 divide-glass/10 overflow-hidden p-0 sm:grid-cols-3 lg:grid-cols-6 [&>*]:border-glass/10 max-lg:[&>*]:border-b lg:divide-x">
          {COINS.map((s) => {
            const t = px[s];
            return (
              <div key={s} className="min-w-0 px-4 py-3.5">
                <div className="flex items-center gap-2 text-sm"><CoinAvatar symbol={s} size={20} /><span className="font-medium">{base(s)}</span></div>
                <div className="num mt-1.5 truncate text-lg font-semibold tracking-tight">{t?.last != null ? fmtPrice(t.last) : "—"}</div>
                <div className={`num text-xs ${t?.change_pct == null ? "text-mute" : t.change_pct >= 0 ? "text-bull" : "text-bear"}`}>{t?.change_pct != null ? `${fmtPctRaw(t.change_pct)} 24h` : "live"}</div>
              </div>
            );
          })}
        </section>

        <div className="trust-strip mt-4 justify-center text-center">
          <span>✓ Every result shown, losses included</span><span>✓ Results after fees</span><span>✓ Never places real orders</span><span>✓ No exchange keys needed</span>
        </div>

        <SignalWave className="h-8 w-full" />

        {/* what members get: a quiet two-column list, not a card grid */}
        <section className="grid gap-10 py-20 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
          <div>
            <h2 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">A plan for every trade, before you place it.</h2>
            <p className="mt-4 max-w-md text-mute">On Android, iPhone and the web. The app never places real orders and never asks for exchange keys.</p>
            <Constellation className="mt-8 w-full max-w-lg" />
          </div>
          <ul className="divide-y divide-glass/10 border-y border-glass/10">
            {FEATURES.map(([d, t, p]) => (
              <li key={t} className="flex items-start gap-4 py-4">
                <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-accent ring-1 ring-accent/25"><Icon d={d} /></span>
                <div>
                  <h3 className="font-medium">{t}</h3>
                  <p className="mt-0.5 text-sm leading-relaxed text-mute">{p}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>

        {/* wins of the day */}
        <WinsToday />
        {/* v2.68 the whole record in one strip + how one signal plays out */}
        <LandingProof />

        {/* v2.76 the trader's tools added in v2.75 */}
        <ToolsStrip />

        <SignalWave className="h-8 w-full" />

        {/* how to start: a real sequence, so numbered */}
        <section id="how" className="scroll-mt-20 py-16">
          <h2 className="font-display text-2xl font-semibold tracking-tight sm:text-3xl">Start in three steps</h2>
          <ol className="mt-8 grid gap-6 md:grid-cols-3">
            {[["Sign in", "With Google or your email."],
              ["Choose a plan", "Pay in USDT with Binance or MEXC and upload the receipt."],
              ["Get the calls", "Follow coins, set alerts and practise with virtual money."]].map(([t, p], i) => (
              <li key={t} className="border-t border-glass/15 pt-4">
                <span className="num text-sm text-accent">Step {i + 1}</span>
                <h3 className="font-display mt-1 text-lg font-semibold">{t}</h3>
                <p className="mt-1 text-sm text-mute">{p}</p>
              </li>
            ))}
          </ol>
        </section>

        {/* membership */}
        <section id="pricing" className="scroll-mt-20 py-16">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="font-display text-2xl font-semibold tracking-tight sm:text-3xl">Membership</h2>
              <p className="mt-2 text-mute">Every plan includes every feature. Paid in USDT.</p>
            </div>
            <p className="text-sm text-mute">Renewing early adds to your remaining days.</p>
          </div>
          <div className="mt-8"><PlanCards plans={plans} onPick={() => setDialog("signup")} cta={(p) => `Choose ${p.label.toLowerCase()}`} disabled={busy} /></div>
          <p className="mt-4 text-sm text-mute">Not sure yet? Join the free Telegram channel for a daily call and the results.</p>
        </section>

        {/* questions: one list */}
        <section className="mx-auto max-w-3xl pb-16">
          <h2 className="font-display text-2xl font-semibold tracking-tight">Good to know</h2>
          <div className="mt-6 divide-y divide-glass/10 border-y border-glass/10">
            {[["Does it trade for me?", "No. It gives plans and alerts; you trade on your own exchange. No exchange keys."],
              ["How accurate is it?", "Results shows every call since the record started, losses included, after fees."],
              ["Which devices?", "The Android app, iPhone (add to Home Screen) and any browser."],
              ["How do I pay?", "In USDT through Binance Pay (QR) or a MEXC transfer. Upload the receipt and we approve it."],
              ["What if I renew early?", "The new period is added to the days you have left."],
              ["Can I see it before paying?", "Yes: the free Telegram channel posts a daily call and the results, wins and losses."]].map(([q, a]) => (
              <details key={q} className="group py-4">
                <summary className="flex cursor-pointer list-none items-center justify-between font-medium">{q}<span className="text-accent transition-transform group-open:rotate-45" aria-hidden="true">+</span></summary>
                <p className="mt-2 text-sm leading-relaxed text-mute">{a}</p>
              </details>
            ))}
          </div>
        </section>

        {/* final call */}
        <section className="panel panel-hero relative isolate mb-12 overflow-hidden p-8 text-center sm:p-12">
          <CyberHorizon className="pointer-events-none absolute inset-x-0 bottom-0 -z-10 h-[70%] w-full opacity-60" />
          <div className="relative mx-auto mb-5 h-28 w-28">
            <HoloOrbit label={false} className="pointer-events-none absolute -inset-10 h-[calc(100%+5rem)] w-[calc(100%+5rem)] opacity-70" />
            <HeroLogo size={96} title="Crypto Intelligence AI logo" className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2" />
          </div>
          <h2 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">Trade with a plan, not a guess.</h2>
          <p className="mx-auto mt-3 max-w-xl text-mute">Analysis only, not financial advice. Crypto is risky.</p>
          <div className="mt-7 flex flex-wrap justify-center gap-3">{cta(true)}{emailCta(true)}</div>
          <p className="mt-6 flex flex-wrap justify-center gap-x-4 gap-y-1 text-sm text-mute">
            {TRUST_LINKS.map(([to, label]) => <Link key={to} to={to} className="tap-h inline-flex items-center hover:text-text hover:underline">{label}</Link>)}
          </p>
        </section>
      </main>

      {demo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4" onClick={() => setDemo(null)} role="dialog" aria-label={demo === "demo" ? "App demo video" : "Why traders use it video"}>
          <div className="relative flex h-full max-h-[90vh] w-auto flex-col items-center gap-2" onClick={(e) => e.stopPropagation()}>
            {demo === "demo"
              ? <video src={mediaUrl("/demo.mp4")} className="h-full max-h-[86vh] rounded-2xl shadow-2xl" controls autoPlay playsInline />
              : <video src={mediaUrl("/ads/friends-ad.mp4")} poster="/ads/friends-ad.jpg" className="h-full max-h-[86vh] rounded-2xl shadow-2xl" controls autoPlay playsInline />}
            <button className="absolute -right-2 -top-2 h-9 w-9 rounded-full bg-panel text-lg" aria-label="Close video" onClick={() => setDemo(null)}>✕</button>
          </div>
        </div>
      )}
      {dialog && <AuthDialog mode={dialog} onClose={() => setDialog(null)} />}
      <SiteFooter apk />
    </div>
  );
}

/** v2.76 landing: the tools members get beside the signals (drawings are illustrations, not data). */
function ToolsStrip() {
  const items: [string, string, JSX.Element][] = [
    ["Position-size calculator", "Enter your balance and risk; it gives the size, margin and liquidation price for any signal.",
      <svg viewBox="0 0 120 56" className="lt-art" aria-hidden="true"><rect x="6" y="8" width="108" height="10" rx="5" className="lt-track" /><rect x="6" y="8" width="44" height="10" rx="5" className="lt-fill" /><rect x="6" y="30" width="50" height="18" rx="5" className="lt-box" /><rect x="64" y="30" width="50" height="18" rx="5" className="lt-box" /><text x="31" y="43" className="lt-num" textAnchor="middle">1%</text><text x="89" y="43" className="lt-num" textAnchor="middle">12x</text></svg>],
    ["Futures market data", "Open interest, funding, how crowded longs are and taker buying, per coin, updated hourly.",
      <svg viewBox="0 0 120 56" className="lt-art" aria-hidden="true">{[18, 30, 24, 36, 28, 42, 38].map((h, i) => <rect key={i} x={8 + i * 15} y={50 - h} width="9" height={h} rx="2" className={i > 4 ? "lt-fill" : "lt-bar"} />)}<path d="M8 22 C30 14 50 26 70 16 S104 10 114 8" className="lt-line" /></svg>],
    ["Liquidation map", "Where leveraged positions would be forced to close above and below the price - an estimate from real open interest.",
      <svg viewBox="0 0 120 56" className="lt-art" aria-hidden="true">{[6, 10, 16, 9, 22, 13, 5].map((w, i) => <rect key={`s${i}`} x={60} y={4 + i * 7} width={w * 2} height="5" rx="1.5" className="lt-short" />)}{[8, 18, 11, 24, 12, 7, 4].map((w, i) => <rect key={`l${i}`} x={60 - w * 2} y={4 + i * 7} width={w * 2} height="5" rx="1.5" className="lt-long" />)}<line x1="0" x2="120" y1="28" y2="28" className="lt-price" /></svg>],
  ];
  return (
    <section aria-labelledby="lt-title" className="py-14">
      <h2 id="lt-title" className="font-display text-2xl font-semibold tracking-tight sm:text-3xl">Tools beside every signal</h2>
      <p className="mt-2 max-w-xl text-sm text-mute">So you can size a trade and see what the futures crowd is doing before you act.</p>
      <ul className="mt-8 grid gap-4 md:grid-cols-3">
        {items.map(([t, p, art]) => (
          <li key={t} className="panel lt-card flex flex-col p-5">
            {art}
            <h3 className="font-display mt-4 text-lg font-semibold">{t}</h3>
            <p className="mt-1 text-sm leading-relaxed text-mute">{p}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
