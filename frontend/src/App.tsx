import { onAuthStateChanged, signInWithPopup, signOut, User } from "firebase/auth";
import { collection, onSnapshot } from "firebase/firestore";
import { lazy, Suspense, useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import AppearanceButton from "./components/AppearancePanel";
import InstallButton from "./components/InstallButton";
import UpdateNotice from "./components/UpdateNotice";
import NotifyPrompt from "./components/NotifyPrompt";
import { Badge } from "./components/ui";
import { useApi } from "./lib/api";
import { useAppearance } from "./lib/appearance";
import { Role, SessionCtx, setSession, useIsAdmin, watchRole } from "./lib/session";
import { auth, db, googleProvider } from "./lib/firebase";
import { ago } from "./lib/format";
import { LiveProvider, useLive } from "./lib/live";
import Dashboard from "./pages/Dashboard";
import { APP_VERSION, BUILD_ID, COPYRIGHT } from "./lib/version";
import { PaymentPanel, RenewBanner, SupportLink } from "./components/Membership";
import { TickerTape } from "./components/Polish";
import Landing from "./components/Landing";
import TelegramLink from "./components/TelegramLink";
import { fmtDate, useMyRecord } from "./lib/membership";
import { startPresence } from "./lib/presence";

// pages load on first visit (smaller first download); the busiest ones are fetched in the background after start.
// After an update an old page may ask for a file that no longer exists: reload once to get the new version.
const page = <T,>(load: () => Promise<T>) => lazy(() => load().catch((e) => {
  try {
    if (!sessionStorage.getItem("chunk-reload")) { sessionStorage.setItem("chunk-reload", "1"); location.reload(); }
  } catch { /* storage blocked: just report */ }
  throw e;
}) as Promise<any>);
const Alerts = page(() => import("./pages/Alerts"));
const Asset = page(() => import("./pages/Asset"));
const Backtest = page(() => import("./pages/Backtest"));
const Health = page(() => import("./pages/Health"));
const News = page(() => import("./pages/News"));
const Results = page(() => import("./pages/Results"));
const Radar = page(() => import("./pages/Radar"));
const Report = page(() => import("./pages/Report"));
const Achievements = page(() => import("./pages/Achievements"));
const Paper = page(() => import("./pages/Paper"));
const Replay = page(() => import("./pages/Replay"));
const Scanner = page(() => import("./pages/Scanner"));
const Settings = page(() => import("./pages/Settings"));
const Signals = page(() => import("./pages/Signals"));
const Users = page(() => import("./pages/Users"));
try { window.setTimeout(() => sessionStorage.removeItem("chunk-reload"), 15000); } catch { /* ignore */ }
const prefetch = () => { void import("./pages/Signals"); void import("./pages/Paper"); void import("./pages/Results"); void import("./pages/Asset"); };
if (typeof window !== "undefined") window.setTimeout(() => ((window as any).requestIdleCallback ?? ((f: () => void) => f()))(prefetch), 2500);

const NAV = [
  ["/", "Home"],
  ["/signals", "Signals"],
  ["/paper", "Trade"],
  ["/news", "News"],
  ["/radar", "Radar"],
  ["/results", "Results"],
  ["/alerts", "Alerts"],
  ["/settings", "Settings"],
] as const;
// owner-only tools: marketing material and system health
const ADMIN_NAV = [["/report", "Weekly report"], ["/achievements", "Achievements"], ["/health", "Health"]] as const;

// phone bottom bar: four main sections + "More" for the rest
const PRIMARY: [string, string, string][] = [["/", "Home", "◧"], ["/signals", "Signals", "◆"], ["/paper", "Trade", "◎"], ["/results", "Results", "▤"]];

function StatusPill({ user }: { user: User }) {
  const { connected, feed } = useLive();
  const health = useApi<any>("/system/health");
  const eng = health.data?.engine;
  const status: string = feed?.status ?? (connected ? "LIVE" : "…");
  const tone = status.startsWith("LIVE") ? "bull" : status === "OFFLINE" ? "bear" : "warn";
  const lastRun = eng?.last_tick_finished;
  const late = lastRun && Date.now() - lastRun > 45 * 60_000;
  return (
    <div className="flex items-center gap-3 text-xs text-mute">
      <span className="hidden sm:inline">Prices</span>
      <Badge tone={tone} title={feed?.transport ?? ""}>● {status}</Badge>
      <span className={`num hidden md:inline ${late ? "text-warn" : ""}`} title="The prediction engine runs on a schedule">
        engine {lastRun ? ago(lastRun) : "not run yet"}
      </span>
      <button className="hidden text-mute hover:text-text lg:inline" onClick={() => signOut(auth)} title={user.email ?? ""}>Sign out</button>
    </div>
  );
}


function Toasts() {
  const { alerts, dismissAlert } = useLive();
  if (!alerts.length) return null;
  return (
    <div className="fixed bottom-20 right-4 z-50 flex md:bottom-4 w-80 max-w-[calc(100vw-2rem)] flex-col gap-2" aria-live="polite">
      {alerts.map((a) => (
        <div key={a.id} className="panel flex items-start justify-between gap-3 border-accent/50 p-3 text-sm">
          <span>{a.message}</span>
          <button className="text-mute hover:text-text" onClick={() => dismissAlert(a.id)} aria-label="Dismiss alert">
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [role, setRole] = useState<Role>("loading");
  useEffect(() => onAuthStateChanged(auth, (u) => { setUser(u); setRole("loading"); }), []);
  useEffect(() => (user ? watchRole(user, setRole) : undefined), [user]);
  useEffect(() => { if (user && role !== "loading") startPresence(); }, [user, role]);
  if (user === undefined || (user && role === "loading")) return <div className="py-20 text-center text-sm text-mute">Loading…</div>;
  if (!user) return <Landing error={null} />;
  const session = { uid: user.uid, email: user.email ?? "", name: user.displayName ?? "", role };
  setSession(session);
  if (role === "pending" || role === "expired" || role === "blocked") return <AccessScreen user={user} role={role} />;
  return <SessionCtx.Provider value={session}><LiveProvider><Shell user={user} /></LiveProvider></SessionCtx.Provider>;
}

function AccessScreen({ user, role }: { user: User; role: Role }) {
  const rec = useMyRecord();
  const logo = <img src={`/icons/icon-512.png?v=${BUILD_ID}`} alt="Crypto Intelligence AI logo" className="mx-auto mb-3 h-20 w-20 drop-shadow-[0_8px_24px_rgb(var(--accent)/0.35)]" />;
  if (role === "blocked") {
    return (
      <div className="flex min-h-full items-center justify-center px-4">
        <div className="panel w-full max-w-sm p-7 text-center">
          {logo}
          <h1 className="text-xl font-semibold tracking-tight">No access</h1>
          <p className="mt-2 text-sm text-mute">The account <span className="text-text">{user.email}</span> does not have access to this app. Ask the owner if you think this is a mistake.</p>
          <button className="btn mt-5 w-full" onClick={() => signOut(auth)}>Use another account</button>
          <SupportLink className="mt-3 block text-sm text-accent hover:underline" />
          <p className="mt-5 text-[11px] text-mute">{COPYRIGHT} · v{APP_VERSION}</p>
        </div>
      </div>
    );
  }
  const expired = role === "expired";
  return (
    <div className="flex min-h-full items-start justify-center px-3 py-6 sm:items-center sm:px-4">
      <div className="panel w-full max-w-2xl p-5 sm:p-7">
        <div className="text-center">
          {logo}
          <h1 className="text-xl font-semibold tracking-tight">{expired ? "Your membership has ended" : <>Become a member of Crypto Intelligence <span className="text-accent">AI</span></>}</h1>
          <p className="mx-auto mt-2 max-w-md text-sm text-mute">
            {expired
              ? <>Membership for <span className="text-text">{user.email}</span> ended on {fmtDate(rec?.expires_at)}. Renew below to continue: your paper accounts, alerts and settings are kept.</>
              : <>Signed in as <span className="text-text">{user.email}</span>. Choose a plan, pay with Binance or MEXC and send the proof. The app opens by itself as soon as the owner approves.</>}
          </p>
        </div>
        <div className="mt-6">{rec === undefined ? <p className="text-center text-sm text-mute">Loading…</p> : <PaymentPanel record={rec} />}</div>
        <div className="mt-6 flex flex-wrap items-center justify-between gap-2 border-t border-glass/[0.06] pt-4 text-xs text-mute">
          <a href={`/manual.pdf?v=${BUILD_ID}`} target="_blank" rel="noopener" className="text-accent hover:underline">What you get: read the user manual (PDF)</a>
          <span className="flex items-center gap-4"><TelegramLink variant="link" /><SupportLink className="text-accent hover:underline" label="Problem? Contact support" /><button className="hover:text-text" onClick={() => signOut(auth)}>Use another account</button></span>
        </div>
        <p className="mt-3 text-center text-[11px] text-mute">{COPYRIGHT} · v{APP_VERSION} · Analysis and demo trading only, not financial advice.</p>
      </div>
    </div>
  );
}

function Footer({ className = "" }: { className?: string }) {
  return (
    <footer className={`border-t border-glass/[0.06] px-4 py-3 text-center text-xs text-mute ${className}`}>
      <div>{COPYRIGHT} · Crypto Intelligence AI · <span className="num">Version {APP_VERSION}</span> · <a href={`/manual.pdf?v=${BUILD_ID}`} target="_blank" rel="noopener" className="text-accent hover:underline">User manual (PDF)</a> · <SupportLink className="text-accent hover:underline" /> · <TelegramLink variant="link" /></div>
      <div className="mt-1 hidden md:block">
        Research tool, not financial advice. Forecasts are probabilities with uncertainty, never certainties. No real orders are placed. Demo bots and paper trading use virtual money.
      </div>
    </footer>
  );
}

function usePendingCount(admin: boolean) {
  const [n, setN] = useState(0);
  // waiting = new requests plus payment proofs (new members and renewals) not yet checked
  useEffect(() => (admin ? onSnapshot(collection(db, "users"), (q) => setN(q.docs.filter((d) => { const u = d.data(); return u.status === "pending" || u.payment?.status === "submitted"; }).length), () => setN(0)) : undefined), [admin]);
  return n;
}

function Shell({ user }: { user: User }) {
  const loc = useLocation();
  const [more, setMore] = useState(false);
  const admin = useIsAdmin();
  const pending = usePendingCount(admin);
  const nav: (readonly [string, string])[] = [...NAV, ...(admin ? [...ADMIN_NAV, ["/users", pending ? `Users (${pending})` : "Users"] as const] : [])];
  const { a } = useAppearance();
  const side = a.nav === "side";
  const width = a.width === "wide" ? "max-w-none" : "max-w-[1600px]";
  const navCls = ({ isActive }: { isActive: boolean }) =>
    `whitespace-nowrap rounded-lg px-3 py-1.5 text-sm transition-colors ${isActive ? "bg-accent/10 font-medium text-accent shadow-[inset_0_-2px_0_rgb(var(--accent)),inset_0_1px_0_rgb(var(--glass)/0.06)]" : "text-mute hover:text-text"}`;
  const brand = (
    <div className="flex min-w-0 items-center gap-2.5">
      <img src={`/icons/icon-192.png?v=${BUILD_ID}`} alt="" className="h-8 w-8" />
      <NavLink to="/" className="truncate text-[15px] font-semibold tracking-tight text-text">
        Crypto Intelligence <span className="text-accent">AI</span>
      </NavLink>
    </div>
  );
  return (
    <div className="flex min-h-full">
      {/* computer: optional sidebar */}
      {side && (
        <aside className="glass-bar sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r md:flex">
          <div className="px-4 py-3.5">{brand}</div>
          <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto px-2" aria-label="Sections">
            {nav.map(([to, label]) => <NavLink key={to} to={to} end={to === "/"} className={navCls}>{label}</NavLink>)}
          </nav>
          <div className="border-t border-glass/[0.06] px-4 py-3 text-xs text-mute">
            <div className="truncate">{user.email}</div>
            <button className="mt-1 text-text hover:text-accent" onClick={() => signOut(auth)}>Sign out</button>
          </div>
        </aside>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="glass-bar safe-top sticky top-0 z-40 border-b">
          <div className={`mx-auto flex ${width} items-center justify-between gap-3 px-3 py-2.5 sm:px-4`}>
            <div className={`flex min-w-0 items-center gap-2.5 ${side ? "md:hidden" : ""}`}>
              {brand}
              <span className="hidden sm:inline"><Badge tone="mute" title="This application never places real orders">Analysis only</Badge></span>
            </div>
            {side && <span className="hidden md:inline"><Badge tone="mute" title="This application never places real orders">Analysis only</Badge></span>}
            <div className="flex items-center gap-2">
              <InstallButton compact />
              <AppearanceButton />
              <StatusPill user={user} />
            </div>
          </div>
          {!side && (
            <nav className={`mx-auto hidden ${width} gap-1 overflow-x-auto px-3 pb-2 md:flex`} aria-label="Sections">
              {nav.map(([to, label]) => (
                <NavLink key={to} to={to} end={to === "/"} className={navCls}>{label}</NavLink>
              ))}
            </nav>
          )}
        </header>
        <TickerTape />
        {!admin && <RenewBanner />}
        <main className={`mx-auto w-full ${width} flex-1 px-3 py-4 sm:px-4`}>
          <div key={loc.pathname} className="page-enter">
          <Suspense fallback={<div className="space-y-3 py-2" aria-busy="true"><div className="skeleton h-24 rounded-xl" /><div className="skeleton h-64 rounded-xl" /></div>}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/asset/:symbol" element={<Asset />} />
            <Route path="/signals" element={<Signals />} />
            <Route path="/scanner" element={<Scanner />} />
            <Route path="/futures" element={<Navigate to="/signals?market=futures" replace />} />
            <Route path="/news" element={<News />} />
            <Route path="/results" element={<Results />} />
            <Route path="/track" element={<Navigate to="/results?tab=track" replace />} />
            <Route path="/radar" element={<Radar />} />
            <Route path="/report" element={<Report />} />
            <Route path="/achievements" element={<Achievements />} />
            <Route path="/accuracy" element={<Navigate to="/results?tab=accuracy" replace />} />
            <Route path="/bots" element={<Navigate to="/results?tab=bots" replace />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/replay" element={<Replay />} />
            <Route path="/history" element={<Navigate to="/results?tab=log" replace />} />
            <Route path="/paper" element={<Paper />} />
            <Route path="/trade" element={<Navigate to="/paper" replace />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/health" element={<Health />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/users" element={<Users />} />
            <Route path="*" element={<div className="py-10 text-center text-mute">Page not found</div>} />
          </Routes>
          </Suspense>
          </div>
        </main>
        <Footer className="pb-24 md:pb-3" />
      </div>

      {/* phone navigation */}
      <nav className="glass-bar safe-bottom fixed inset-x-0 bottom-0 z-50 border-t md:hidden" aria-label="Main sections">
        <div className="grid grid-cols-5">
          {PRIMARY.map(([to, label, icon]) => (
            <NavLink key={to} to={to} end={to === "/"} onClick={() => setMore(false)}
              className={({ isActive }) => `flex flex-col items-center gap-0.5 py-2 text-[11px] ${isActive ? "text-accent" : "text-mute"}`}>
              <span className="text-lg leading-none" aria-hidden>{icon}</span>{label}
            </NavLink>
          ))}
          <button onClick={() => setMore((v) => !v)} aria-expanded={more}
            className={`flex flex-col items-center gap-0.5 py-2 text-[11px] ${more ? "text-accent" : "text-mute"}`}>
            <span className="relative text-lg leading-none" aria-hidden>⋯{pending > 0 && <span className="absolute -right-2 -top-1 h-2 w-2 rounded-full bg-warn" />}</span>More
          </button>
        </div>
      </nav>
      {more && (
        <div className="fixed inset-0 z-[45] md:hidden" onClick={() => setMore(false)}>
          <div className="absolute inset-0 bg-ink/60 backdrop-blur-sm" />
          {/* positioned wrapper: .panel sets its own position, so the sheet's placement lives on this div */}
          <div className="absolute inset-x-3 bottom-[calc(4.5rem+env(safe-area-inset-bottom))] max-h-[calc(100dvh-7rem)] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
          <div className="panel animate-in p-2">
            <div className="grid grid-cols-2 gap-1">
              {nav.filter(([to]) => !PRIMARY.some((p) => p[0] === to)).map(([to, label]) => (
                <NavLink key={to} to={to} onClick={() => setMore(false)} className={navCls}>{label}</NavLink>
              ))}
            </div>
            <div className="mt-2 flex items-center justify-between border-t border-glass/[0.06] px-2 pt-2 text-xs text-mute">
              <span className="truncate">{user.email}</span>
              <button className="text-text" onClick={() => signOut(auth)}>Sign out</button>
            </div>
            <SupportLink className="mx-2 mt-2 block rounded-lg border border-glass/10 px-3 py-2 text-center text-sm" label="✉ Contact support" />
            <a className="mx-2 mt-2 block rounded-lg border border-glass/10 px-3 py-2 text-center text-sm text-accent" href="https://github.com/hesperlexi/crypto-intelligence-ai/releases/download/android/crypto-intelligence-ai.apk">⬇ Download Android app (APK)</a>
            <p className="px-2 pt-2 text-[11px] text-mute">Research tool, not financial advice. No real orders are ever placed.</p>
            <p className="px-2 pt-1 text-[11px] text-mute">{COPYRIGHT} · v{APP_VERSION}</p>
          </div>
          </div>
        </div>
      )}
      <Toasts />
      <UpdateNotice />
      <NotifyPrompt />
    </div>
  );
}
