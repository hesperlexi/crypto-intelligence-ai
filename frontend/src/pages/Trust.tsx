// Public information pages: About, Contact, Terms, Risk disclosure (the Privacy Policy text is archived in docs/legal/privacy-policy.md). Reachable signed out (own layout)
// and signed in (inside the app shell). Written from what the app actually does; anything we cannot state
// (company details, jurisdiction) points to support instead of being made up.
import { ReactNode, useEffect } from "react";
import { Link } from "react-router-dom";
import { BRAND } from "../lib/brand";
import { AnimatedLogo } from "../components/Logo";
import SiteFooter, { TRUST_LINKS } from "../components/SiteFooter";
import { VerifyBox } from "../components/SealProof";

export const LAST_UPDATED = "31 Oct 2026";
export type TrustKind = "about" | "contact" | "terms" | "risk" | "verify";
export const TRUST_PATHS: Record<string, TrustKind> = { "/about": "about", "/contact": "contact", "/terms": "terms", "/risk": "risk", "/verify": "verify" };

const Mail = () => <a className="text-accent hover:underline" href={`mailto:${BRAND.supportEmail}`}>{BRAND.supportEmail}</a>;

function H({ children }: { children: ReactNode }) { return <h2 className="mt-8 text-lg font-semibold text-text">{children}</h2>; }

function About() {
  return (
    <>
      <p>{BRAND.name} is an analysis app for people who trade crypto. It reads market data, runs its own machine-learning models and
        technical analysis, and publishes trade ideas ("signals") with an entry, a stop-loss and up to three targets.</p>
      <H>What it does</H>
      <ul className="list-disc space-y-1 pl-5">
        <li>Signals and forecasts for a watchlist of coins on several timeframes, spot and futures.</li>
        <li>A public track record: every signal is followed until it closes, wins and losses alike.</li>
        <li>Practice trading (spot and futures) with virtual money, plus demo bots that trade the signals with virtual money.</li>
        <li>Price and signal alerts, including phone notifications if you turn them on.</li>
        <li>News, an economic calendar and a market radar.</li>
      </ul>
      <H>What it does not do</H>
      <ul className="list-disc space-y-1 pl-5">
        <li>It never places real orders and never asks for exchange API keys.</li>
        <li>It does not hold your money. Membership is paid by you directly in USDT and checked by hand.</li>
        <li>It is not financial advice. See the <Link to="/risk" className="text-accent hover:underline">Risk disclosure</Link>.</li>
      </ul>
      <H>Where to find it</H>
      <p>Web: <a className="text-accent hover:underline" href={BRAND.url}>{BRAND.url.replace("https://", "")}</a> · Android app · Telegram: <a className="text-accent hover:underline" href={BRAND.telegram} target="_blank" rel="noopener">@crypappai</a></p>
      <p className="mt-2">Questions: <Mail /></p>
    </>
  );
}

function Contact() {
  return (
    <>
      <p>For questions about your membership, a payment, your data, or anything else, email us:</p>
      <p className="mt-4"><a className="btn btn-primary" href={`mailto:${BRAND.supportEmail}`}>Email {BRAND.supportEmail}</a></p>
      <p className="mt-4">Please write from the email address you sign in with and, for payments, include the order or transaction ID. Payments are checked by hand, so a reply can take some time.</p>
      <p className="mt-4">Public channel (free signal and results): <a className="text-accent hover:underline" href={BRAND.telegram} target="_blank" rel="noopener">@crypappai on Telegram</a>.</p>
    </>
  );
}

function Terms() {
  return (
    <>
      <p>By using {BRAND.name} you agree to these terms.</p>
      <H>The service</H>
      <p>{BRAND.name} provides market analysis, signals, alerts and practice trading with virtual money. It never places real orders and never connects to your exchange account. Features may change as the app is improved.</p>
      <H>Not financial advice</H>
      <p>Everything in the app is analysis for information and education. It is not financial, investment or trading advice, and no result is guaranteed. You alone decide whether to trade and you are responsible for your own trades. Read the <Link to="/risk" className="text-accent hover:underline">Risk disclosure</Link>.</p>
      <H>Accounts and membership</H>
      <ul className="list-disc space-y-1 pl-5">
        <li>You sign in with Google or with your email address and a password, and keep your account to yourself.</li>
        <li>Your username and anything you post in Community are visible to other members. Keep posts respectful; the owner can remove posts or block an account.</li>
        <li>Membership is paid manually in USDT (Binance or MEXC). Access opens after the owner checks your payment proof; it ends on the expiry date shown in the app unless you renew.</li>
        <li>The owner can refuse a membership request or block an account. If you think this happened by mistake, contact support.</li>
      </ul>
      <H>Availability</H>
      <p>We try to keep the app running, but data feeds, the analysis engine and third-party services can be delayed or unavailable. Signals can arrive late or not at all.</p>
      <p className="mt-8">For more information, contact <Mail />.</p>
    </>
  );
}

function Risk() {
  return (
    <>
      <p className="rounded-lg border border-warn/40 bg-warn/10 p-3 text-text">Trading crypto is high risk. You can lose some or all of the money you trade with.</p>
      <ul className="mt-6 list-disc space-y-2 pl-5">
        <li><b>Volatility.</b> Crypto prices can move very fast, including large moves within minutes, gaps and sudden drops.</li>
        <li><b>Leverage.</b> On a real exchange, leverage magnifies losses as much as gains. A small move against you can liquidate the position, and with some products and conditions you can lose more than the margin you put up.</li>
        <li><b>Signals are analysis, not advice.</b> Signals, forecasts, grades and AI notes come from statistical models and can be wrong. They do not know your situation.</li>
        <li><b>Past results do not guarantee future results.</b> The track record shows how past calls ended; future calls can do worse.</li>
        <li><b>No guaranteed profits.</b> Nobody can promise profits in trading, and neither do we.</li>
        <li><b>The app never places real orders.</b> Practice trading, auto-trade and the demo bots use virtual money only. Real trades are placed by you on your own exchange, at your own risk, and real fills, fees and funding can differ from what the app shows.</li>
        <li><b>Data can be late.</b> Prices and signals depend on outside data sources and can be delayed or missing.</li>
      </ul>
      <p className="mt-6">Only trade with money you can afford to lose. If you are unsure, talk to a licensed financial adviser. Questions: <Mail /></p>
    </>
  );
}

function Verify() {
  return (
    <>
      <p>Every signal is sealed when it is published: a SHA-256 fingerprint of its coin, direction, entry, stop-loss, targets,
        publication time and a secret salt is posted to our public Telegram channel at once. When the signal closes, the full
        sealed text is posted. Paste it below (with the earlier fingerprint) to check that nothing was changed or added later.</p>
      <div className="mt-5 text-text"><VerifyBox /></div>
    </>
  );
}

const PAGES: Record<TrustKind, [string, () => JSX.Element]> = {
  about: ["About", About], contact: ["Contact", Contact], terms: ["Terms of Use", Terms], risk: ["Risk Disclosure", Risk],
  verify: ["Verify our signals", Verify],
};

/** The page body (used inside the app shell). */
export function TrustContent({ kind }: { kind: TrustKind }) {
  const [title, Body] = PAGES[kind];
  useEffect(() => { document.title = `${title} · ${BRAND.name}`; return () => { document.title = BRAND.name; }; }, [title]);
  return (
    <article className="panel mx-auto max-w-3xl p-5 text-sm leading-relaxed text-mute sm:p-8">
      <h1 className="text-2xl font-semibold tracking-tight text-text">{title}</h1>
      <p className="mt-1 text-xs">Last updated {LAST_UPDATED}</p>
      <div className="mt-5">
        <Body />
      </div>
      <nav aria-label="Other pages" className="mt-10 flex flex-wrap gap-x-4 gap-y-1 border-t border-glass/[0.06] pt-4 text-xs">
        {TRUST_LINKS.filter(([to]) => TRUST_PATHS[to] !== kind).map(([to, label]) => <Link key={to} to={to} className="text-accent hover:underline">{label}</Link>)}
      </nav>
    </article>
  );
}

/** Stand-alone layout for signed-out visitors. */
export default function TrustPage({ kind }: { kind: TrustKind }) {
  return (
    <div className="landing-bg flex min-h-full flex-col text-text">
      <header className="glass-bar sticky top-0 z-30 border-b">
        <div className="mx-auto flex max-w-4xl items-center justify-between gap-3 px-4 py-3">
          <Link to="/" className="flex items-center gap-2.5">
            <AnimatedLogo size={34} />
            <span className="font-display text-[15px] font-bold">Crypto Intelligence <span className="text-accent">AI</span></span>
          </Link>
          <Link to="/" className="btn px-3 py-1.5 text-sm">Home</Link>
        </div>
      </header>
      <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-8"><TrustContent kind={kind} /></main>
      <SiteFooter width="max-w-4xl" />
    </div>
  );
}
