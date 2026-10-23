import { createContext, ReactNode, useContext, useEffect, useState } from "react";

/** Themes and layout preferences. Saved per device (browser storage); everything works without it. */
export const THEMES = [
  { id: "midnight", name: "Midnight", swatch: ["#080b10", "#5aa0ff", "#c084fc"] },
  { id: "aurora", name: "Aurora", swatch: ["#0c0915", "#a78bfa", "#2dd4bf"] },
  { id: "ocean", name: "Ocean", swatch: ["#04121a", "#22d3ee", "#3b82f6"] },
  { id: "graphite", name: "Graphite", swatch: ["#111214", "#e5e7eb", "#9ca3af"] },
  { id: "oled", name: "OLED black", swatch: ["#000000", "#5aa0ff", "#1f2937"] },
  { id: "light", name: "Light", swatch: ["#eef2f8", "#2563eb", "#ffffff"] },
  { id: "system", name: "Auto (device)", swatch: ["#080b10", "#eef2f8", "#5aa0ff"] },
] as const;
export type ThemeId = (typeof THEMES)[number]["id"];

export interface Appearance {
  theme: ThemeId;
  nav: "top" | "side";             // desktop navigation
  density: "comfortable" | "compact";
  width: "contained" | "wide";
  glass: boolean;                  // frosted blur (switch off on slow phones)
}
const DEFAULTS: Appearance = { theme: "midnight", nav: "top", density: "comfortable", width: "contained", glass: true };
const KEY = "cia-appearance";

function load(): Appearance {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) ?? "{}") }; } catch { return DEFAULTS; }
}

const darkQuery = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null);

/** The concrete theme in use ("system" resolves to Midnight or Light). */
export function resolveTheme(t: ThemeId): Exclude<ThemeId, "system"> {
  if (t !== "system") return t;
  return darkQuery()?.matches === false ? "light" : "midnight";
}

const Ctx = createContext<{ a: Appearance; resolved: string; set: (p: Partial<Appearance>) => void }>({
  a: DEFAULTS, resolved: "midnight", set: () => {},
});

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [a, setA] = useState<Appearance>(load);
  const [osDark, setOsDark] = useState(darkQuery()?.matches ?? true);
  const resolved = a.theme === "system" ? (osDark ? "midnight" : "light") : a.theme;

  useEffect(() => {
    const q = darkQuery();
    if (!q) return;
    const on = (e: MediaQueryListEvent) => setOsDark(e.matches);
    q.addEventListener?.("change", on);
    return () => q.removeEventListener?.("change", on);
  }, []);

  useEffect(() => {
    const el = document.documentElement;
    el.dataset.theme = resolved;
    el.dataset.density = a.density;
    el.dataset.glass = a.glass ? "on" : "off";
    el.style.colorScheme = resolved === "light" ? "light" : "dark";
    const bg = getComputedStyle(el).getPropertyValue("--ink").trim();
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", bg ? `rgb(${bg.split(" ").join(",")})` : "#080b10");
    try { localStorage.setItem(KEY, JSON.stringify(a)); } catch { /* private mode: not remembered */ }
  }, [a, resolved]);

  return <Ctx.Provider value={{ a, resolved, set: (p) => setA((x) => ({ ...x, ...p })) }}>{children}</Ctx.Provider>;
}

export const useAppearance = () => useContext(Ctx);

/** Colours for the canvas charts, read from the active theme. */
export function chartColors() {
  const css = getComputedStyle(document.documentElement);
  const v = (n: string, alpha = 1) => `rgba(${css.getPropertyValue(n).trim().split(/\s+/).join(",")},${alpha})`;
  return { text: v("--mute"), grid: v("--line", 0.5), border: v("--line") };
}
