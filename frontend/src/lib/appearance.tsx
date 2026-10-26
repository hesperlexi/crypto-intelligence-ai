import { createContext, ReactNode, useContext, useEffect, useState } from "react";

/** Themes and layout preferences. Saved per device (browser storage); everything works without it. */
export const THEMES = [
  { id: "gold", name: "Gold", sub: "exchange classic", swatch: ["#0b0e11", "#f0b90b", "#0ecb81"] },
  { id: "abyss", name: "Abyss", sub: "futuristic crypto", swatch: ["#04060f", "#22e4ff", "#8b5cf6"] },
  { id: "nexora", name: "Nexora", sub: "pro dashboard", swatch: ["#0a0f1c", "#3b82f6", "#22d3ee"] },
  { id: "trado", name: "Trado", sub: "minimal black & green", swatch: ["#000000", "#00e676", "#141414"] },
  { id: "light", name: "Light", sub: "bright", swatch: ["#f5f6f8", "#c99400", "#ffffff"] },
  { id: "system", name: "Auto", sub: "follows the device", swatch: ["#0b0e11", "#f5f6f8", "#f0b90b"] },
] as const;
export type ThemeId = (typeof THEMES)[number]["id"];

export interface Appearance {
  theme: ThemeId;
  nav: "top" | "side";             // desktop navigation
  density: "comfortable" | "compact";
  width: "contained" | "wide";
  glass: boolean;                  // frosted blur (switch off on slow phones)
}
const DEFAULTS: Appearance = { theme: "gold", nav: "top", density: "comfortable", width: "contained", glass: true };
const KEY = "cia-appearance-v2";     // v2: the new Gold look becomes everyone's starting theme once

function load(): Appearance {
  try {
    const a = { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) ?? "{}") };
    if (!THEMES.some((t) => t.id === a.theme)) a.theme = "gold";      // a retired theme falls back to Gold
    return a;
  } catch { return DEFAULTS; }
}

const darkQuery = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null);

/** The concrete theme in use ("system" resolves to Midnight or Light). */
export function resolveTheme(t: ThemeId): Exclude<ThemeId, "system"> {
  if (t !== "system") return t;
  return darkQuery()?.matches === false ? "light" : "gold";
}

const Ctx = createContext<{ a: Appearance; resolved: string; set: (p: Partial<Appearance>) => void }>({
  a: DEFAULTS, resolved: "gold", set: () => {},
});

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [a, setA] = useState<Appearance>(load);
  const [osDark, setOsDark] = useState(darkQuery()?.matches ?? true);
  const resolved = a.theme === "system" ? (osDark ? "gold" : "light") : a.theme;

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
