// What signed-out visitors see: a short, honest sales page with live prices, features, pricing and sign-in.
import { signInWithPopup } from "firebase/auth";
import { useEffect, useState } from "react";
import { tickers as restTickers } from "../lib/binance";
import { auth, googleProvider } from "../lib/firebase";
import { base, fmtPctRaw, fmtPrice } from "../lib/format";
import { useMembershipConfig } from "../lib/membership";
import TrackRecord from "./TrackRecord";
import { APP_VERSION, BUILD_ID, COPYRIGHT } from "../lib/version";
import { CoinAvatar } from "./Polish";

const COINS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT"];

const FEATURES: [string, string, string][] = [
  ["M9 9h6v6H9zM4 4h16v16H4zM9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3", "4 AI models vote", "LSTM, GRU, Transformer and gradient boosting forecast every coin. A call counts only when they agree."],
  ["M12 2v20M5 9h14M7 15h10", "Ready-made trade plans", "Entry zone, stop-loss and three take-profit targets on every signal, sized from real volatility."],
  ["M3 17l6-6 4 4 8-8M15 7h6v6", "Spot & futures", "Long and short calls with safe leverage, liquidation price, funding and open interest built in."],
  ["M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 01-3.4 0", "Instant phone alerts", "Pick a coin and a condition. Get a notification the moment a setup appears, with the full plan."],
  ["M2 6h20v13H2zM2 10h20M6 15h4", "Practise risk-free", "Paper trading for spot and futures, hedge mode included, plus demo bots trading the signals 24/7."],
  ["M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM8.5 12l2.5 2.5 4.5-5", "Honest accuracy", "Every model is scored on data it never saw. You see the real hit rate before you trust a call."],
];

function Icon({ d }: { d: string }) {
  return <svg aria-hidden="true" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>;
}

export default function Landing({ error }: { error: string | null }) {
  const [err, setErr] = useState<string | null>(error);
  const [busy, setBusy] = useState(false);
  const [px, setPx] = useState<Record<string, any>>({});
  const [demo, setDemo] = useState(false);
  useEffect(() => {
    let alive = true;
    const load = () => restTickers(COINS).then((t) => alive && setPx(t)).catch(() => {});
    load();
    const id = window.setInterval(load, 10000);
    return () => { alive = false; window.clearInterval(id); };
  }, []);
  const signIn = async () => {
    setBusy(true);
    try { await signInWithPopup(auth, googleProvider); } catch (e: any) { setErr(e.message); }
    setBusy(false);
  };
  const cfg = useMembershipConfig();
  const plans = cfg.plans;
  const monthly = plans[0].price;
  const cta = (big = false) => (
    <button className={`btn btn-primary ${big ? "px-6 py-3 text-base" : "px-4 py-2 text-sm"}`} onClick={signIn} disabled={busy}>
      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 48 48" className="mr-2 inline-block align-[-3px]"><path fill="currentColor" d="M44.5 20H24v8.5h11.8C34.7 33.9 30.1 37 24 37c-7.2 0-13-5.8-13-13s5.8-13 13-13c3.1 0 5.9 1.1 8.1 2.9l6.4-6.4C34.6 4.1 29.6 2 24 2 11.8 2 2 11.8 2 24s9.8 22 22 22c11 0 21-8 21-22 0-1.3-.2-2.7-.5-4z" /></svg>
      {busy ? "Opening Google…" : "Get started with Google"}
    </button>
  );

  return (
    <div className="landing-bg min-h-full text-text">
      <header className="glass-bar sticky top-0 z-30 border-b">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-2.5">
            <img src={`/icons/icon-192.png?v=${BUILD_ID}`} alt="" className="h-9 w-9" />
            <span className="font-display text-[15px] font-bold sm:text-base">Crypto Intelligence <span className="text-accent">AI</span></span>
          </div>
          <div className="flex items-center gap-2">
            <a href="#track" className="hidden px-2 text-sm text-mute hover:text-text sm:inline">Track record</a>
            <a href="#pricing" className="hidden px-2 text-sm text-mute hover:text-text sm:inline">Pricing</a>
            <a href={`/manual.pdf?v=${BUILD_ID}`} target="_blank" rel="noopener" className="hidden px-2 text-sm text-mute hover:text-text sm:inline">Manual</a>
            <button className="btn px-3 py-1.5 text-sm" onClick={signIn} disabled={busy}>Sign in</button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4">
        {/* hero */}
        <section className="grid items-center gap-10 py-12 sm:py-16 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
          <div>
            <span className="inline-flex items-center gap-2 rounded-full border border-accent/40 bg-accent/10 px-3 py-1 text-xs font-semibold tracking-wider text-accent">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-bull" /> AI · SPOT · FUTURES
            </span>
            <h1 className="font-display mt-5 text-[42px] font-extrabold leading-[1.02] tracking-tight sm:text-6xl">
              Know the setup<br /><span className="text-gradient">before</span> you trade.
            </h1>
            <p className="mt-5 max-w-xl text-lg leading-relaxed text-mute">
              AI forecasts, ready-made trade plans and instant phone alerts for every coin you follow. Then test them risk-free before you put real money in.
            </p>
            <div className="mt-7 flex flex-wrap items-center gap-3">
              {cta(true)}
              <button className="btn px-5 py-3 text-base" onClick={() => setDemo(true)}>▶ Watch the 90-second demo</button>
            </div>
            {err && <p className="mt-3 text-sm text-bear">{err}</p>}
            <p className="mt-5 text-xs text-mute">No exchange keys needed · the app never places real orders · from ${(plans[plans.length - 1].price / 12).toFixed(2)}/month</p>
          </div>

          {/* product preview */}
          <div className="relative">
            <div className="float-slow panel glow-ring relative overflow-hidden p-5">
              <div className="flex items-center justify-between">
                <span className="text-xs tracking-[0.14em] text-mute">TRADE SIGNAL · EXAMPLE</span>
                <span className="rounded-md bg-bull px-2.5 py-1 text-xs font-bold text-ink">▲ LONG</span>
              </div>
              <div className="mt-3 flex items-center gap-3">
                <CoinAvatar symbol="BTC/USDT" size={40} />
                <div>
                  <div className="font-display text-xl font-bold">BTC/USDT · 4H</div>
                  <div className="num text-sm text-mute">{px["BTC/USDT"]?.last ? `$${fmtPrice(px["BTC/USDT"].last)} live` : "live price"}</div>
                </div>
              </div>
              <svg aria-hidden="true" viewBox="0 0 300 90" className="mt-4 h-24 w-full" preserveAspectRatio="none">
                <defs><linearGradient id="lf" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="rgb(var(--bull))" stopOpacity="0.35" /><stop offset="1" stopColor="rgb(var(--bull))" stopOpacity="0" /></linearGradient></defs>
                <line x1="0" y1="62" x2="300" y2="62" stroke="rgb(var(--accent))" strokeDasharray="4 4" strokeWidth="1.2" />
                <line x1="0" y1="84" x2="300" y2="84" stroke="rgb(var(--bear))" strokeDasharray="4 4" strokeWidth="1.2" />
                <line x1="0" y1="14" x2="300" y2="14" stroke="rgb(var(--bull))" strokeDasharray="4 4" strokeWidth="1.2" />
                <path d="M0 70 L20 74 L40 66 L60 72 L80 64 L100 68 L120 58 L140 62 L160 50 L180 54 L200 40 L220 44 L240 30 L260 34 L280 22 L300 18 V90 H0Z" fill="url(#lf)" />
                <path d="M0 70 L20 74 L40 66 L60 72 L80 64 L100 68 L120 58 L140 62 L160 50 L180 54 L200 40 L220 44 L240 30 L260 34 L280 22 L300 18" fill="none" stroke="rgb(var(--bull))" strokeWidth="2.2" />
              </svg>
              <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                <dt className="text-mute">Entry</dt><dd className="text-right font-medium">entry zone</dd>
                <dt className="text-mute">Stop-loss</dt><dd className="text-right font-medium text-bear">placed for you</dd>
                <dt className="text-mute">Targets</dt><dd className="text-right font-medium text-bull">TP1 · TP2 · TP3</dd>
                <dt className="text-mute">Leverage</dt><dd className="text-right font-medium">safe maximum shown</dd>
              </dl>
              <div className="mt-4 flex items-center gap-2 rounded-lg border border-glass/10 bg-ink/50 px-3 py-2 text-xs text-mute">
                <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="rgb(var(--accent))" strokeWidth="2"><path d="M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9" /></svg>
                Pushed to your phone the moment the setup appears
              </div>
            </div>
          </div>
        </section>

        {/* live prices */}
        <section aria-label="Live prices" className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
          {COINS.map((s) => {
            const t = px[s];
            return (
              <div key={s} className="coin-tile p-3">
                <div className="flex items-center gap-2"><CoinAvatar symbol={s} size={24} /><span className="font-semibold">{base(s)}</span></div>
                <div className="num mt-2 text-lg font-semibold">{t?.last != null ? fmtPrice(t.last) : "—"}</div>
                <div className={`num text-xs ${t?.change_pct == null ? "text-mute" : t.change_pct >= 0 ? "text-bull" : "text-bear"}`}>{t?.change_pct != null ? `${fmtPctRaw(t.change_pct)} 24h` : "live"}</div>
              </div>
            );
          })}
        </section>

        {/* features */}
        <section className="py-16">
          <h2 className="font-display text-center text-3xl font-bold tracking-tight sm:text-4xl">Everything you need to trade with a plan</h2>
          <p className="mx-auto mt-3 max-w-2xl text-center text-mute">One app for spotting setups, planning the trade and practising it, on Android, iPhone and the web.</p>
          <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map(([d, t, p]) => (
              <div key={t} className="panel p-5 transition-transform hover:-translate-y-1">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent/10 text-accent ring-1 ring-accent/30"><Icon d={d} /></div>
                <h3 className="font-display mt-4 text-lg font-semibold">{t}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-mute">{p}</p>
              </div>
            ))}
          </div>
        </section>

        {/* public track record */}
        <section id="track" className="scroll-mt-20 py-8">
          <h2 className="font-display text-center text-3xl font-bold tracking-tight sm:text-4xl">Check our track record first</h2>
          <p className="mx-auto mt-2 max-w-2xl text-center text-sm text-mute">Every signal since launch with its real result, nothing removed. Plus how the AI scored on past data it never saw.</p>
          <div className="mt-8"><TrackRecord /></div>
        </section>

        {/* how it works */}
        <section id="how" className="scroll-mt-20 py-8">
          <h2 className="font-display text-center text-3xl font-bold tracking-tight sm:text-4xl">Start in three steps</h2>
          <ol className="mt-10 grid gap-4 md:grid-cols-3">
            {[["Sign in", "Use your Google account. No exchange keys, no forms."],
              ["Choose a plan", "Pay in seconds with Binance Pay and upload the receipt. Access opens as soon as it is checked."],
              ["Get signals", "Follow your coins, add your own, set alerts and practise with paper trading."]].map(([t, p], i) => (
              <li key={t} className="panel relative p-5">
                <span className="font-display text-5xl font-extrabold text-accent/25">0{i + 1}</span>
                <h3 className="font-display mt-1 text-lg font-semibold">{t}</h3>
                <p className="mt-1.5 text-sm text-mute">{p}</p>
              </li>
            ))}
          </ol>
        </section>

        {/* pricing */}
        <section id="pricing" className="scroll-mt-20 py-16">
          <h2 className="font-display text-center text-3xl font-bold tracking-tight sm:text-4xl">Simple pricing</h2>
          <p className="mt-3 text-center text-mute">Every plan includes every feature. The longer the plan, the less you pay per month.</p>
          <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {plans.map((p) => {
              const best = p.months === 12;
              const save = p.months > 1 ? Math.round((1 - p.price / (monthly * p.months)) * 100) : 0;
              return (
                <div key={p.months} className={`panel relative flex flex-col p-5 ${best ? "glow-ring" : ""}`}>
                  {best && <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-accent px-3 py-0.5 text-xs font-bold text-ink">BEST VALUE</span>}
                  <div className="text-sm text-mute">{p.label}</div>
                  <div className="font-display mt-1 text-4xl font-extrabold">${p.price}</div>
                  <div className="num mt-1 text-sm text-mute">${(p.price / p.months).toFixed(2)} / month{save ? <span className="ml-2 text-bull">save {save}%</span> : null}</div>
                  <ul className="mt-4 flex-1 space-y-1.5 text-sm text-mute">
                    <li>✓ All signals & AI forecasts</li><li>✓ Futures & phone alerts</li><li>✓ Paper trading & demo bots</li>
                  </ul>
                  <button className={`btn mt-5 w-full ${best ? "btn-primary" : ""}`} onClick={signIn} disabled={busy}>Choose {p.label}</button>
                </div>
              );
            })}
          </div>
          <p className="mt-4 text-center text-xs text-mute">Paid with Binance Pay (USDT). Renew any time; early renewals add on top of your remaining days.</p>
        </section>

        {/* questions */}
        <section className="mx-auto max-w-3xl pb-12">
          <h2 className="font-display text-center text-2xl font-bold">Good to know</h2>
          <div className="mt-6 space-y-3">
            {[["Does it trade for me?", "No. It analyses the market and gives you plans and alerts. You decide and place trades on your own exchange. It never asks for exchange keys."],
              ["How accurate is it?", "Crypto is hard to predict, and the app is open about it: the Accuracy page shows each model's real hit rate on data it never saw, so you can see when to trust a call."],
              ["Which devices?", "Android (app download), iPhone (add to Home Screen) and any web browser. Your account works on all of them."]].map(([q, a]) => (
              <details key={q} className="panel group p-4">
                <summary className="flex cursor-pointer list-none items-center justify-between font-medium">{q}<span className="text-accent transition-transform group-open:rotate-45">+</span></summary>
                <p className="mt-2 text-sm leading-relaxed text-mute">{a}</p>
              </details>
            ))}
          </div>
        </section>

        {/* final call */}
        <section className="hero mb-12 rounded-2xl p-8 text-center sm:p-12">
          <h2 className="font-display text-3xl font-bold tracking-tight sm:text-4xl">Trade with a plan, not a guess.</h2>
          <p className="mx-auto mt-3 max-w-xl text-mute">Join in a minute. Analysis and practice tool, not financial advice.</p>
          <div className="mt-6">{cta(true)}</div>
        </section>
      </main>

      {demo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4" onClick={() => setDemo(false)} role="dialog" aria-label="Demo video">
          <div className="relative h-full max-h-[90vh] w-auto" onClick={(e) => e.stopPropagation()}>
            <video src={`/demo.mp4?v=${BUILD_ID}`} className="h-full max-h-[90vh] rounded-2xl shadow-2xl" controls autoPlay playsInline />
            <button className="absolute -right-2 -top-2 h-9 w-9 rounded-full bg-panel text-lg" aria-label="Close video" onClick={() => setDemo(false)}>✕</button>
          </div>
        </div>
      )}
      <footer className="border-t border-glass/[0.06] px-4 py-6 text-center text-xs text-mute">
        {COPYRIGHT} · Crypto Intelligence AI · <span className="num">v{APP_VERSION}</span> · <a href={`/manual.pdf?v=${BUILD_ID}`} target="_blank" rel="noopener" className="text-accent hover:underline">User manual</a> · <a href={`mailto:${cfg.support_email}`} className="text-accent hover:underline">{cfg.support_email}</a>
        <div className="mt-1">Research tool, not financial advice. Forecasts are probabilities, never certainties. No real orders are placed.</div>
      </footer>
    </div>
  );
}
