// v2.20 desktop navigation (screens ≥ 1024 px, Appearance "Sidebar", the default): a left sidebar with grouped,
// icon-led sections (collapsible to icons) and a top bar with the page title, live status + clock, the alerts bell and
// a profile menu. Tablets and phones keep the classic header + bottom bar (App.tsx).
// Nothing here reads extra Firestore documents: the bell counts useLive().alerts (already subscribed), the profile
// line reuses the users/{uid} listener the session already has (members) and the engine age reads views/health,
// which the classic header already subscribes to (one listener in the SDK).
import { signOut, User } from "firebase/auth";
import { memo, ReactNode, useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useApi } from "../lib/api";
import { useAppearance } from "../lib/appearance";
import { auth } from "../lib/firebase";
import { ago, fmtDate } from "../lib/format";
import { useLive } from "../lib/live";
import { useMyRecord } from "../lib/membership";
import { BRAND } from "../lib/brand";
import { AnimatedLogo } from "./Logo";
import { Badge } from "./kit";

export type NavItem = readonly [string, string];
export interface NavGroup { title: string; items: NavItem[]; fold?: boolean }

/* ---- icons (24-unit paths, stroke) --------------------------------------------------------------------------- */
const ICON: Record<string, string> = {
  "/": "M3 11l9-7 9 7v9a1 1 0 01-1 1h-5v-6h-6v6H4a1 1 0 01-1-1z",
  "/signals": "M2 12h3l3-8 4 16 3-8h7",
  "/paper": "M7 4v16M7 4l-3 3M7 4l3 3M17 20V4M17 20l-3-3M17 20l3-3",
  "/results": "M4 20V10M10 20V4M16 20v-7M22 20H2",
  "/news": "M4 5h13v14H5a1 1 0 01-1-1zM17 9h3v9a1 1 0 01-1 1h-2M7 9h7M7 13h7M7 16h4",
  "/radar": "M12 12l6-6M12 3a9 9 0 109 9M12 7a5 5 0 105 5M12 12h.01",
  "/community": "M16 19v-1a4 4 0 00-4-4H7a4 4 0 00-4 4v1M9.5 10a3 3 0 100-6 3 3 0 000 6zM21 19v-1a4 4 0 00-3-3.9M16 4.1a3 3 0 010 5.8",
  "/alerts": "M6 8a6 6 0 0112 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.9 1.9 0 003.4 0",
  "/settings": "M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 01-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 010-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 014 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 010 4h-.1a1.7 1.7 0 00-1.5 1z",
  "/scanner": "M11 18a7 7 0 100-14 7 7 0 000 14zM21 21l-4.3-4.3",
  "/backtest": "M3 12a9 9 0 109-9 9.7 9.7 0 00-6.7 2.7L3 8M3 3v5h5M12 7v5l3 3",
  "/replay": "M12 21a9 9 0 100-18 9 9 0 000 18zM10 8l6 4-6 4z",
  "/report": "M14 3H6a2 2 0 00-2 2v14a2 2 0 002 2h12a2 2 0 002-2V9zM14 3v6h6M8 13h8M8 17h5",
  "/achievements": "M8 21h8M12 17v4M7 4h10v5a5 5 0 01-10 0zM17 5h3v2a3 3 0 01-3 3M7 5H4v2a3 3 0 003 3",
  "/health": "M3 12h4l3-7 4 14 3-7h4",
  "/rich": "M5 21V4M5 4h11l-2 4 2 4H5",
  "/guardian": "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10zM9 12l2 2 4-4",
  "/users": "M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM17 11l2 2 4-4",
  tools: "M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.8-3.8a6 6 0 01-7.9 7.9l-6.9 6.9a2.1 2.1 0 01-3-3l6.9-6.9a6 6 0 017.9-7.9z",
  help: "M12 22a10 10 0 100-20 10 10 0 000 20zM9.1 9a3 3 0 015.8 1c0 2-3 3-3 3M12 17h.01",
  sun: "M12 17a5 5 0 100-10 5 5 0 000 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  moon: "M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z",
  fold: "M15 18l-6-6 6-6",
  chevron: "M6 9l6 6 6-6",
  out: "M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9",
};
export function Ico({ name, size = 18, className = "" }: { name: string; size?: number; className?: string }) {
  return (
    <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
      strokeLinecap="round" strokeLinejoin="round" className={`shrink-0 ${className}`}><path d={ICON[name] ?? ICON["/"]} /></svg>
  );
}

/* ---- page titles for the desktop top bar (one short line each) ------------------------------------------------ */
const TITLES: [string, string, string][] = [
  ["/asset/", "Coin", "Chart, AI view and the coin's report"],
  ["/signals", "Signals", "Trade calls per timeframe, with entry, stop and targets"],
  ["/paper", "Trade", "Practice trading with virtual money"],
  ["/results", "Results", "Every call since the restart, wins and losses alike"],
  ["/news", "News", "Headlines and the US economic calendar"],
  ["/radar", "Radar", "Coins outside the app that beat the market"],
  ["/community", "Community", "Talk with other members"],
  ["/alerts", "Alerts", "Your alert rules and what fired"],
  ["/settings", "Settings", "Account, notifications and appearance"],
  ["/scanner", "Scanner", "Every coin on one board"],
  ["/backtest", "Backtest", "Test a strategy on past data"],
  ["/replay", "Replay", "Step through past candles"],
  ["/report", "Weekly report", "Owner: marketing summary of the week"],
  ["/achievements", "Achievements", "Owner: milestones of the record"],
  ["/health", "Health", "Owner: engine, data and quotas"],
  ["/rich", "Hesper Challenge", "Owner: $100 → $1,000 demo challenge"],
  ["/guardian", "Trade Guardian", "Owner: recommendations on open calls"],
  ["/users", "Users", "Owner: members, payments and access"],
];
export function pageTitle(path: string): [string, string] {
  if (path === "/" || path === "") return ["Overview", "Market, signals and results at a glance"];
  const hit = TITLES.find(([p]) => path.startsWith(p));
  return hit ? [hit[1], hit[2]] : ["Crypto Intelligence AI", "Analysis and demo trading only"];
}

/* ---- sidebar --------------------------------------------------------------------------------------------------- */
const LABEL: Record<string, string> = { "/": "Overview" };
const readFold = (k: string) => { try { return localStorage.getItem(k) === "1"; } catch { return false; } };

function SideLink({ to, label, collapsed, count }: { to: string; label: string; collapsed: boolean; count?: number }) {
  const text = LABEL[to] ?? label;
  return (
    <NavLink to={to} end={to === "/"} title={collapsed ? text : undefined} aria-label={collapsed ? `${text}${count ? `, ${count} new` : ""}` : undefined}
      className={`side-link ${collapsed ? "justify-center" : ""}`}>
      <span className="relative inline-flex">
        <Ico name={to} />
        {collapsed && !!count && <span className="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-accent" aria-hidden="true" />}
      </span>
      {!collapsed && <span className="min-w-0 flex-1 truncate">{text}</span>}
      {!collapsed && !!count && <span className="num shrink-0 rounded-full bg-accent/15 px-1.5 text-xs font-bold leading-5 text-accent">{count}</span>}
    </NavLink>
  );
}

/** Light ↔ dark in one click: Ivory, or back to the last dark theme used (Midnight Gold by default). */
function ThemeToggle({ collapsed }: { collapsed: boolean }) {
  const { a, resolved, set } = useAppearance();
  const light = resolved === "light";
  const flip = () => {
    if (light) {
      let back = "gold";
      try { back = localStorage.getItem("cia-last-dark") || "gold"; } catch { /* ignore */ }
      set({ theme: back as any });
    } else {
      try { localStorage.setItem("cia-last-dark", a.theme === "system" ? "gold" : a.theme); } catch { /* ignore */ }
      set({ theme: "light" });
    }
  };
  const label = light ? "Switch to a dark theme" : "Switch to the light theme (Ivory)";
  if (collapsed) {
    return <button type="button" onClick={flip} className="side-link justify-center" title={label} aria-label={label}><Ico name={light ? "moon" : "sun"} /></button>;
  }
  return (
    <div className="flex items-center justify-between gap-2 rounded-lg border border-glass/[0.08] bg-glass/[0.03] px-3 py-2">
      <span className="text-xs text-mute">Theme</span>
      <button type="button" role="switch" aria-checked={!light} aria-label={label} title={label} onClick={flip} className="theme-switch">
        <span className={`theme-switch-knob ${light ? "" : "is-dark"}`}><Ico name={light ? "sun" : "moon"} size={13} /></span>
      </button>
    </div>
  );
}

export const Sidebar = memo(function Sidebar({ groups, counts, collapsed, onToggle }: {
  groups: NavGroup[]; counts: Record<string, number>; collapsed: boolean; onToggle: () => void;
}) {
  const loc = useLocation();
  const [folds, setFolds] = useState<Record<string, boolean>>(() => Object.fromEntries(groups.filter((g) => g.fold).map((g) => [g.title, readFold(`cia-side-open-${g.title}`)])));
  const toggleFold = (t: string) => setFolds((f) => {
    const n = { ...f, [t]: !f[t] };
    try { localStorage.setItem(`cia-side-open-${t}`, n[t] ? "1" : "0"); } catch { /* ignore */ }
    return n;
  });
  return (
    <aside className={`side-bar glass-bar sticky top-0 hidden h-screen shrink-0 flex-col border-r lg:flex ${collapsed ? "w-[4.5rem]" : "w-60"}`} aria-label="Sidebar">
      <div className={`flex items-center gap-2.5 px-3 pb-2 pt-3.5 ${collapsed ? "flex-col" : ""}`}>
        <Link to="/" aria-label="Crypto Intelligence AI, Overview" className="flex min-w-0 flex-1 items-center gap-2.5">
          <AnimatedLogo size={34} className="shrink-0" />
          {!collapsed && <span className="font-display text-base font-semibold leading-tight tracking-tight text-text">Crypto Intelligence <span className="text-accent">AI</span></span>}
        </Link>
        <button type="button" onClick={onToggle} className="side-fold" aria-label={collapsed ? "Expand the sidebar" : "Collapse the sidebar to icons"} title={collapsed ? "Expand" : "Collapse"}>
          <Ico name="fold" size={16} className={collapsed ? "rotate-180" : ""} />
        </button>
      </div>
      <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto overflow-x-hidden px-2 pb-3" aria-label="Sections">
        {groups.map((g, i) => {
          const activeIn = g.items.some(([to]) => loc.pathname.startsWith(to));
          const open = !g.fold || collapsed || folds[g.title] || activeIn;
          return (
            <div key={g.title || i} className={`flex flex-col gap-0.5 ${i ? "mt-2 border-t border-glass/[0.07] pt-2" : ""}`}>
              {g.title && !collapsed && (g.fold ? (
                <button type="button" className="side-group justify-between" aria-expanded={open} onClick={() => toggleFold(g.title)}>
                  <span className="flex items-center gap-3"><Ico name="tools" />{g.title}</span>
                  <Ico name="chevron" size={14} className={`transition-transform ${open ? "rotate-180" : ""}`} />
                </button>
              ) : <div className="label px-3 pb-1 pt-1">{g.title}</div>)}
              {open && g.items.map(([to, label]) => <SideLink key={to} to={to} label={label} collapsed={collapsed} count={counts[to]} />)}
            </div>
          );
        })}
      </nav>
      <div className="space-y-1 border-t border-glass/[0.06] px-2 py-3">
        <ThemeToggle collapsed={collapsed} />
        <a href={`mailto:${BRAND.supportEmail}?subject=${encodeURIComponent("Crypto Intelligence AI: help")}`} className={`side-link ${collapsed ? "justify-center" : ""}`}
          title={collapsed ? "Help & support" : BRAND.supportEmail} aria-label={collapsed ? "Help and support (email)" : undefined}>
          <Ico name="help" />{!collapsed && <span className="truncate">Help &amp; support</span>}
        </a>
      </div>
    </aside>
  );
});

/* ---- top bar pieces -------------------------------------------------------------------------------------------- */
/** Price feed status with a ticking clock. Only this small chip re-renders every second. */
export function LiveChip() {
  const { connected, feed } = useLive();
  const health = useApi<any>("/system/health");
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(t); }, []);
  const status: string = feed?.status ?? (connected ? "LIVE" : "…");
  const live = status.startsWith("LIVE");
  const lastRun = health.data?.engine?.last_tick_finished;
  const late = lastRun && now - lastRun > 45 * 60_000;
  const time = new Date(now).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  return (
    <div className="flex items-center gap-2 text-xs" title={`Prices: ${status}${feed?.transport ? ` (${feed.transport})` : ""} · engine ${lastRun ? ago(lastRun) : "not run yet"}`}>
      <span className={`inline-flex items-center gap-1.5 font-semibold ${live ? "text-bull" : status === "OFFLINE" ? "text-bear" : "text-warn"}`}>
        <span className={`h-2 w-2 rounded-full ${live ? "live-dot bg-bull" : status === "OFFLINE" ? "bg-bear" : "bg-warn"}`} aria-hidden="true" />
        {live ? "Live" : status}
      </span>
      <span className="num text-mute">{time}</span>
      <span className={`num hidden text-mute xl:inline ${late ? "text-warn" : ""}`}>· engine {lastRun ? ago(lastRun) : "—"}</span>
    </div>
  );
}

export function AlertsBell({ unread }: { unread: number }) {
  return (
    <Link to="/alerts" className="relative inline-flex h-9 w-9 items-center justify-center rounded-lg border border-glass/15 bg-glass/[0.04] text-text/85 hover:border-accent/50 hover:text-accent"
      aria-label={unread ? `Alerts, ${unread} new` : "Alerts"} title="Alerts">
      <Ico name="/alerts" size={17} />
      {unread > 0 && <span className="num absolute -right-1.5 -top-1.5 min-w-[18px] rounded-full bg-bear px-1 text-center text-[11px] font-bold leading-[18px] text-white">{unread > 9 ? "9+" : unread}</span>}
    </Link>
  );
}

function initials(name: string, email: string) {
  const src = (name || email.split("@")[0] || "?").replace(/[._-]+/g, " ").trim();
  const parts = src.split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

/** Members: plan state from their own users record (the listener the session already has). */
function MemberLine() {
  const rec = useMyRecord();
  if (!rec) return <>Member</>;
  if (rec.status === "approved" && !rec.expires_at) return <>Member</>;
  if (rec.status === "approved") return <>Member · until {fmtDate(rec.expires_at)}</>;
  return <>{rec.status ?? "Member"}</>;
}

export function ProfileMenu({ user, admin, username, extra }: { user: User; admin: boolean; username?: string; extra?: ReactNode }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  const name = username || user.displayName || (user.email ?? "").split("@")[0];
  return (
    <div className="relative" ref={ref}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-haspopup="menu" aria-expanded={open}
        className="flex items-center gap-2.5 rounded-lg py-1 pl-1 pr-2 text-left hover:bg-glass/[0.05]">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-accent/40 bg-accent/10 text-xs font-bold text-accent" aria-hidden="true">{initials(user.displayName ?? "", user.email ?? "")}</span>
        <span className="hidden min-w-0 max-w-[11rem] xl:block">
          <span className="block truncate text-sm font-medium leading-tight">{name}</span>
          <span className="block truncate text-xs leading-tight text-mute">{admin ? "Owner" : <MemberLine />}</span>
        </span>
        <Ico name="chevron" size={14} className={`text-mute transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div role="menu" className="panel popover animate-in absolute right-0 top-[calc(100%+8px)] z-50 w-64 p-1.5">
          <div className="border-b border-glass/[0.07] px-3 pb-2 pt-1.5">
            <div className="truncate text-sm font-medium">{name}</div>
            <div className="truncate text-xs text-mute" title={user.email ?? ""}>{user.email}</div>
            <div className="mt-1.5">{admin ? <Badge tone="accent">Owner</Badge> : <Badge tone="text"><MemberLine /></Badge>}</div>
          </div>
          {extra}
          <NavLink to="/settings" role="menuitem" className="menu-item mt-1">Settings</NavLink>
          <NavLink to="/alerts" role="menuitem" className="menu-item">Alerts</NavLink>
          <button type="button" role="menuitem" className="menu-item w-full text-left" onClick={() => signOut(auth)}>
            <span className="inline-flex items-center gap-2"><Ico name="out" size={15} />Sign out</span>
          </button>
        </div>
      )}
    </div>
  );
}

/** The desktop page title (not a heading: each page keeps its own h1). */
export function PageTitle() {
  const loc = useLocation();
  const [title, sub] = pageTitle(loc.pathname);
  const icon = loc.pathname === "/" ? "/" : (Object.keys(ICON).find((k) => k !== "/" && k.startsWith("/") && loc.pathname.startsWith(k)) ?? "/");
  return (
    <div className="flex min-w-0 items-center gap-3">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-accent/25 bg-accent/[0.08] text-accent"><Ico name={icon} size={20} /></span>
      <div className="min-w-0">
        <div className="font-display truncate text-xl font-semibold leading-tight tracking-tight">{title}</div>
        <div className="truncate text-xs text-mute">{sub}</div>
      </div>
    </div>
  );
}
