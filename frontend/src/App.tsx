import { onAuthStateChanged, signInWithPopup, signOut, User } from "firebase/auth";
import { collection, onSnapshot, query, where } from "firebase/firestore";
import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import AppearanceButton from "./components/AppearancePanel";
import InstallButton from "./components/InstallButton";
import UpdateNotice from "./components/UpdateNotice";
import { Badge } from "./components/ui";
import { useApi } from "./lib/api";
import { useAppearance } from "./lib/appearance";
import { Role, SessionCtx, setSession, useIsAdmin, watchRole } from "./lib/session";
import { auth, db, googleProvider } from "./lib/firebase";
import { ago } from "./lib/format";
import { LiveProvider, useLive } from "./lib/live";
import Bots from "./pages/Bots";
import Accuracy from "./pages/Accuracy";
import Alerts from "./pages/Alerts";
import Asset from "./pages/Asset";
import Backtest from "./pages/Backtest";
import Dashboard from "./pages/Dashboard";
import Futures from "./pages/Futures";
import Health from "./pages/Health";
import History from "./pages/History";
import Paper from "./pages/Paper";
import Replay from "./pages/Replay";
import Scanner from "./pages/Scanner";
import Settings from "./pages/Settings";
import Users from "./pages/Users";
import { APP_VERSION, BUILD_ID, COPYRIGHT } from "./lib/version";

const NAV = [
  ["/", "Dashboard"],
  ["/scanner", "Scanner"],
  ["/futures", "Futures"],
  ["/accuracy", "Accuracy"],
  ["/bots", "Demo bots"],
  ["/backtest", "Backtest"],
  ["/replay", "Replay"],
  ["/history", "Signals"],
  ["/paper", "Paper"],
  ["/alerts", "Alerts"],
  ["/health", "Health"],
  ["/settings", "Settings"],
] as const;

// phone bottom bar: four main sections + "More" for the rest
const PRIMARY: [string, string, string][] = [["/", "Home", "◧"], ["/futures", "Futures", "⇅"], ["/bots", "Bots", "⚙"], ["/paper", "Paper", "◎"]];

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

function Login({ error }: { error: string | null }) {
  const [err, setErr] = useState<string | null>(error);
  return (
    <div className="flex min-h-full items-center justify-center px-4">
      <div className="panel w-full max-w-sm p-7 text-center">
        <img src={`/icons/icon-512.png?v=${BUILD_ID}`} alt="Crypto Intelligence AI logo" className="mx-auto mb-4 h-24 w-24 drop-shadow-[0_8px_24px_rgba(56,189,248,0.35)]" />
        <h1 className="text-xl font-semibold tracking-tight">Crypto Intelligence <span className="text-accent">AI</span></h1>
        <p className="mt-2 text-sm text-mute">Sign in with Google. New accounts send an access request to the owner.</p>
        <button className="btn btn-primary mt-5 w-full" onClick={() => signInWithPopup(auth, googleProvider).catch((e) => setErr(e.message))}>
          Sign in with Google
        </button>
        {err && <p className="mt-3 text-xs text-bear">{err}</p>}
        <p className="mt-5 text-xs text-mute">Analysis and demo trading only. No real orders are ever placed.</p>
        <p className="mt-3 text-[11px] text-mute">{COPYRIGHT} · v{APP_VERSION}</p>
      </div>
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
  if (user === undefined || (user && role === "loading")) return <div className="py-20 text-center text-sm text-mute">Loading…</div>;
  if (!user) return <Login error={null} />;
  const session = { uid: user.uid, email: user.email ?? "", name: user.displayName ?? "", role };
  setSession(session);
  if (role === "pending" || role === "blocked") return <AccessScreen user={user} role={role} />;
  return <SessionCtx.Provider value={session}><LiveProvider><Shell user={user} /></LiveProvider></SessionCtx.Provider>;
}

function AccessScreen({ user, role }: { user: User; role: Role }) {
  return (
    <div className="flex min-h-full items-center justify-center px-4">
      <div className="panel w-full max-w-sm p-7 text-center">
        <img src={`/icons/icon-512.png?v=${BUILD_ID}`} alt="Crypto Intelligence AI logo" className="mx-auto mb-4 h-24 w-24 drop-shadow-[0_8px_24px_rgba(56,189,248,0.35)]" />
        <h1 className="text-xl font-semibold tracking-tight">{role === "pending" ? "Request sent" : "No access"}</h1>
        <p className="mt-2 text-sm text-mute">
          {role === "pending"
            ? <>Your access request for <span className="text-text">{user.email}</span> is waiting for the owner's approval. This page opens the app by itself as soon as you are approved.</>
            : <>The account <span className="text-text">{user.email}</span> does not have access to this app. Ask the owner if you think this is a mistake.</>}
        </p>
        {role === "pending" && <div className="mx-auto mt-5 h-1.5 w-24 overflow-hidden rounded-full bg-raised"><div className="h-full w-1/2 animate-pulse rounded-full bg-accent" /></div>}
        <button className="btn mt-5 w-full" onClick={() => signOut(auth)}>Use another account</button>
        <p className="mt-5 text-[11px] text-mute">{COPYRIGHT} · v{APP_VERSION}</p>
      </div>
    </div>
  );
}

function Footer({ className = "" }: { className?: string }) {
  return (
    <footer className={`border-t border-glass/[0.06] px-4 py-3 text-center text-xs text-mute ${className}`}>
      <div>{COPYRIGHT} · Crypto Intelligence AI · <span className="num">Version {APP_VERSION}</span></div>
      <div className="mt-1 hidden md:block">
        Research tool, not financial advice. Forecasts are probabilities with uncertainty, never certainties. No real orders are placed. Demo bots and paper trading use virtual money.
      </div>
    </footer>
  );
}

function usePendingCount(admin: boolean) {
  const [n, setN] = useState(0);
  useEffect(() => (admin ? onSnapshot(query(collection(db, "users"), where("status", "==", "pending")), (q) => setN(q.docs.length), () => setN(0)) : undefined), [admin]);
  return n;
}

function Shell({ user }: { user: User }) {
  const [more, setMore] = useState(false);
  const admin = useIsAdmin();
  const pending = usePendingCount(admin);
  const nav: (readonly [string, string])[] = [...NAV, ...(admin ? [["/users", pending ? `Users (${pending})` : "Users"] as const] : [])];
  const { a } = useAppearance();
  const side = a.nav === "side";
  const width = a.width === "wide" ? "max-w-none" : "max-w-[1600px]";
  const navCls = ({ isActive }: { isActive: boolean }) =>
    `whitespace-nowrap rounded-lg px-3 py-1.5 text-sm transition-colors ${isActive ? "bg-glass/[0.08] text-text shadow-[inset_0_1px_0_rgb(var(--glass)/0.06)]" : "text-mute hover:text-text"}`;
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
        <main className={`mx-auto w-full ${width} flex-1 px-3 py-4 sm:px-4`}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/asset/:symbol" element={<Asset />} />
            <Route path="/scanner" element={<Scanner />} />
            <Route path="/futures" element={<Futures />} />
            <Route path="/accuracy" element={<Accuracy />} />
            <Route path="/bots" element={<Bots />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/replay" element={<Replay />} />
            <Route path="/history" element={<History />} />
            <Route path="/paper" element={<Paper />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/health" element={<Health />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/users" element={<Users />} />
            <Route path="*" element={<div className="py-10 text-center text-mute">Page not found</div>} />
          </Routes>
        </main>
        <Footer className="pb-24 md:pb-3" />
      </div>

      {/* phone navigation */}
      <nav className="glass-bar safe-bottom fixed inset-x-0 bottom-0 z-40 border-t md:hidden" aria-label="Main sections">
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
        <div className="fixed inset-0 z-30 md:hidden" onClick={() => setMore(false)}>
          <div className="absolute inset-0 bg-ink/50 backdrop-blur-sm" />
          <div className="panel safe-bottom animate-in absolute inset-x-3 bottom-20 p-2" onClick={(e) => e.stopPropagation()}>
            <div className="grid grid-cols-2 gap-1">
              {nav.filter(([to]) => !PRIMARY.some((p) => p[0] === to)).map(([to, label]) => (
                <NavLink key={to} to={to} onClick={() => setMore(false)} className={navCls}>{label}</NavLink>
              ))}
            </div>
            <div className="mt-2 flex items-center justify-between border-t border-glass/[0.06] px-2 pt-2 text-xs text-mute">
              <span className="truncate">{user.email}</span>
              <button className="text-text" onClick={() => signOut(auth)}>Sign out</button>
            </div>
            <a className="mx-2 mt-2 block rounded-lg border border-glass/10 px-3 py-2 text-center text-sm text-accent" href="https://github.com/hesperlexi/crypto-intelligence-ai/releases/download/android/crypto-intelligence-ai.apk">⬇ Download Android app (APK)</a>
            <p className="px-2 pt-2 text-[11px] text-mute">Research tool, not financial advice. No real orders are ever placed.</p>
            <p className="px-2 pt-1 text-[11px] text-mute">{COPYRIGHT} · v{APP_VERSION}</p>
          </div>
        </div>
      )}
      <Toasts />
      <UpdateNotice />
    </div>
  );
}
