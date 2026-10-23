import { onAuthStateChanged, signInWithPopup, signOut, User } from "firebase/auth";
import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import InstallButton from "./components/InstallButton";
import { Badge } from "./components/ui";
import { useApi } from "./lib/api";
import { auth, googleProvider } from "./lib/firebase";
import { ago } from "./lib/format";
import { LiveProvider, useLive } from "./lib/live";
import Bots from "./pages/Bots";
import Accuracy from "./pages/Accuracy";
import Alerts from "./pages/Alerts";
import Asset from "./pages/Asset";
import Backtest from "./pages/Backtest";
import Dashboard from "./pages/Dashboard";
import Health from "./pages/Health";
import History from "./pages/History";
import Paper from "./pages/Paper";
import Replay from "./pages/Replay";
import Scanner from "./pages/Scanner";
import Settings from "./pages/Settings";

const NAV = [
  ["/", "Dashboard"],
  ["/scanner", "Scanner"],
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
const PRIMARY: [string, string, string][] = [["/", "Home", "◧"], ["/scanner", "Scanner", "☰"], ["/bots", "Bots", "⚙"], ["/accuracy", "Accuracy", "◎"]];

function StatusPill({ user }: { user: User }) {
  const { connected, feed } = useLive();
  const health = useApi<any>("/system/health");
  const eng = health.data?.engine;
  const status: string = connected ? "LIVE" : feed?.status ?? "…";
  const tone = status === "LIVE" ? "bull" : status === "CONNECTING" ? "warn" : "bear";
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
        <img src="/icons/icon-192.png" alt="" className="mx-auto mb-4 h-16 w-16 rounded-2xl" />
        <h1 className="text-xl font-semibold tracking-tight">Crypto Intelligence <span className="text-accent">AI</span></h1>
        <p className="mt-2 text-sm text-mute">Private research dashboard. Sign in with an allowed Google account.</p>
        <button className="btn btn-primary mt-5 w-full" onClick={() => signInWithPopup(auth, googleProvider).catch((e) => setErr(e.message))}>
          Sign in with Google
        </button>
        {err && <p className="mt-3 text-xs text-bear">{err}</p>}
        <p className="mt-5 text-xs text-mute">Analysis and demo trading only. No real orders are ever placed.</p>
      </div>
    </div>
  );
}

function Toasts() {
  const { alerts, dismissAlert } = useLive();
  if (!alerts.length) return null;
  return (
    <div className="fixed bottom-20 right-4 z-50 md:bottom-4 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2" aria-live="polite">
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
  useEffect(() => onAuthStateChanged(auth, setUser), []);
  if (user === undefined) return <div className="py-20 text-center text-sm text-mute">Loading…</div>;
  if (!user) return <Login error={null} />;
  return <LiveProvider><Shell user={user} /></LiveProvider>;
}

function Shell({ user }: { user: User }) {
  const [more, setMore] = useState(false);
  const navCls = ({ isActive }: { isActive: boolean }) =>
    `whitespace-nowrap rounded-lg px-3 py-1.5 text-sm transition-colors ${isActive ? "bg-white/[0.08] text-text shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]" : "text-mute hover:text-text"}`;
  return (
    <div className="flex min-h-full flex-col">
      <header className="glass-bar safe-top sticky top-0 z-40 border-b">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-3 px-3 py-2.5 sm:px-4">
          <div className="flex min-w-0 items-center gap-2.5">
            <img src="/icons/icon-192.png" alt="" className="h-7 w-7 rounded-lg" />
            <NavLink to="/" className="truncate text-[15px] font-semibold tracking-tight text-text">
              Crypto Intelligence <span className="text-accent">AI</span>
            </NavLink>
            <span className="hidden sm:inline"><Badge tone="mute" title="This application never places real orders">Analysis only</Badge></span>
          </div>
          <div className="flex items-center gap-2">
            <InstallButton compact />
            <StatusPill user={user} />
          </div>
        </div>
        <nav className="mx-auto hidden max-w-[1600px] gap-1 overflow-x-auto px-3 pb-2 md:flex" aria-label="Sections">
          {NAV.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"} className={navCls}>{label}</NavLink>
          ))}
        </nav>
      </header>
      <main className="mx-auto w-full max-w-[1600px] flex-1 px-3 py-4 pb-24 sm:px-4 md:pb-4">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/asset/:symbol" element={<Asset />} />
          <Route path="/scanner" element={<Scanner />} />
          <Route path="/accuracy" element={<Accuracy />} />
          <Route path="/bots" element={<Bots />} />
          <Route path="/backtest" element={<Backtest />} />
          <Route path="/replay" element={<Replay />} />
          <Route path="/history" element={<History />} />
          <Route path="/paper" element={<Paper />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/health" element={<Health />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<div className="py-10 text-center text-mute">Page not found</div>} />
        </Routes>
      </main>
      <footer className="hidden border-t border-white/[0.06] px-4 py-3 text-center text-xs text-mute md:block">
        Research tool, not financial advice. Forecasts are probabilities with uncertainty, never certainties. No real orders are placed. Demo bots and paper trading use virtual money.
      </footer>

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
            <span className="text-lg leading-none" aria-hidden>⋯</span>More
          </button>
        </div>
      </nav>
      {more && (
        <div className="fixed inset-0 z-30 md:hidden" onClick={() => setMore(false)}>
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" />
          <div className="panel safe-bottom absolute inset-x-3 bottom-20 p-2" onClick={(e) => e.stopPropagation()}>
            <div className="grid grid-cols-2 gap-1">
              {NAV.filter(([to]) => !PRIMARY.some((p) => p[0] === to)).map(([to, label]) => (
                <NavLink key={to} to={to} onClick={() => setMore(false)} className={navCls}>{label}</NavLink>
              ))}
            </div>
            <div className="mt-2 flex items-center justify-between border-t border-white/[0.06] px-2 pt-2 text-xs text-mute">
              <span className="truncate">{user.email}</span>
              <button className="text-text" onClick={() => signOut(auth)}>Sign out</button>
            </div>
            <p className="px-2 pt-2 text-[11px] text-mute">Research tool, not financial advice. No real orders are ever placed.</p>
          </div>
        </div>
      )}
      <Toasts />
    </div>
  );
}
