// V3.4 Stage 5 (owner-approved 26 Nov 2026): six destinations. Every existing page keeps its own address (old links,
// pushes and the Android app keep working); a destination is the family of pages shown as tabs at the top.
export interface HubTab { to: string; label: string; admin?: boolean; also?: string[] }
export interface Hub { id: string; to: string; label: string; short: string; icon: string; tabs: HubTab[] }

export const HUBS: Hub[] = [
  { id: "overview", to: "/", label: "Overview", short: "Overview", icon: "/", tabs: [] },
  {
    id: "market", to: "/command", label: "Market Intelligence", short: "Market", icon: "/command",
    tabs: [
      { to: "/command", label: "AI Intelligence" },
      { to: "/regime", label: "Market regime" },
      { to: "/risk", label: "Risk" },
      { to: "/coins", label: "Coins", also: ["/asset/"] },
      { to: "/flow", label: "Money flow" },
      { to: "/news", label: "News" },
    ],
  },
  {
    id: "opps", to: "/signals", label: "Opportunities", short: "Signals", icon: "/signals",
    tabs: [
      { to: "/signals", label: "Signals" },
      { to: "/fast", label: "Fast radar" },
      { to: "/radar", label: "Radar" },
    ],
  },
  {
    id: "portfolio", to: "/portfolio", label: "Portfolio", short: "Portfolio", icon: "/portfolio",
    tabs: [
      { to: "/portfolio", label: "Positions & risk" },
      { to: "/paper", label: "Trade" },
    ],
  },
  {
    id: "performance", to: "/results", label: "Performance", short: "Results", icon: "/results",
    tabs: [
      { to: "/results", label: "Results" },
      { to: "/community", label: "Community" },
      { to: "/rich", label: "Hesper Challenge", admin: true },
      { to: "/lab", label: "Performance Lab", admin: true },
      { to: "/backtest", label: "Backtest", admin: true },
      { to: "/replay", label: "Replay", admin: true },
    ],
  },
  {
    id: "system", to: "/settings", label: "Settings & System", short: "Settings", icon: "/settings",
    tabs: [
      { to: "/settings", label: "Settings" },
      { to: "/alerts", label: "Alerts" },
      { to: "/system", label: "System status" },
      { to: "/health", label: "Control room", admin: true },
      { to: "/guardian", label: "Trade Guardian", admin: true },
      { to: "/users", label: "Users", admin: true },
      { to: "/report", label: "Share kit", admin: true, also: ["/achievements"] },
    ],
  },
];

const matches = (path: string, t: HubTab) =>
  path === t.to || path.startsWith(t.to + "/") || (t.also ?? []).some((a) => path.startsWith(a));

/** The destination a page belongs to (null for pages outside the six, e.g. the trust pages). */
export function hubOf(path: string): Hub | null {
  if (path === "/" || path === "") return HUBS[0];
  return HUBS.find((h) => h.tabs.some((t) => matches(path, t))) ?? null;
}

export function visibleTabs(h: Hub, admin: boolean): HubTab[] {
  return h.tabs.filter((t) => admin || !t.admin);
}

export function activeTab(h: Hub, path: string): HubTab | undefined {
  return h.tabs.find((t) => matches(path, t));
}

/** Sidebar / menus: a destination's entry is lit on every page of its family. */
export const HUB_ALIASES: Record<string, string[]> = Object.fromEntries(
  HUBS.filter((h) => h.tabs.length).map((h) => [h.to, h.tabs.flatMap((t) => [t.to, ...(t.also ?? [])]).filter((p) => p !== h.to)]),
);
