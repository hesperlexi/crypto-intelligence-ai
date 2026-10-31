import { createContext, ReactNode, useContext, useEffect, useLayoutEffect, useRef, useState } from "react";

/** Themes and layout preferences. Saved per device (browser storage); everything works without it.
 *  Theme ids are stable keys in saved preferences: "gold" is Midnight Gold and "light" is Ivory. The colours of each
 *  theme live in index.css under [data-theme="<id>"]. */
export const THEMES = [
  { id: "gold", name: "Midnight Gold", sub: "Default · near-black, gold", dark: true },
  { id: "obsidian", name: "Obsidian", sub: "Deep black, champagne gold", dark: true },
  { id: "graphite", name: "Graphite Pro", sub: "Neutral grey, muted gold", dark: true },
  { id: "aurora", name: "Aurora", sub: "Navy, gold, cyan accent", dark: true },
  { id: "light", name: "Ivory", sub: "Light, cool grey, deep gold", dark: false },
  { id: "system", name: "System", sub: "Follows the device", dark: true },
] as const;
export type ThemeId = (typeof THEMES)[number]["id"];
export type ResolvedTheme = Exclude<ThemeId, "system">;

export interface Appearance {
  theme: ThemeId;
  nav: "top" | "side";             // desktop navigation
  density: "comfortable" | "compact";
  width: "contained" | "wide";
  glass: boolean;                  // frosted blur (switch off on slow phones)
}
const DEFAULTS: Appearance = { theme: "gold", nav: "top", density: "comfortable", width: "contained", glass: true };
const KEY = "cia-appearance-v2";     // v2: the new Gold look becomes everyone's starting theme once
// names people might have saved under other spellings; anything else unknown falls back to Midnight Gold
const ALIASES: Record<string, ThemeId> = { midnight: "gold", "midnight-gold": "gold", dark: "gold", ivory: "light" };

/** A saved theme id made safe: aliases mapped, retired or unknown ids (abyss, nexora, trado …) → Midnight Gold. */
export function normalizeTheme(t: unknown): ThemeId {
  const id = typeof t === "string" ? (ALIASES[t] ?? t) : "gold";
  return THEMES.some((x) => x.id === id) ? (id as ThemeId) : "gold";
}

function load(): Appearance {
  try {
    const a = { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) ?? "{}") };
    a.theme = normalizeTheme(a.theme);
    return a;
  } catch { return DEFAULTS; }
}

const darkQuery = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null);
const reducedMotion = () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** The concrete theme in use ("system" resolves to Midnight Gold or Ivory). */
export function resolveTheme(t: ThemeId): ResolvedTheme {
  if (t !== "system") return t;
  return darkQuery()?.matches === false ? "light" : "gold";
}

/** True for the light theme(s): used where a third party (TradingView) needs "light" or "dark". */
export const isLightTheme = (t: string) => t === "light";

const Ctx = createContext<{ a: Appearance; resolved: ResolvedTheme; set: (p: Partial<Appearance>) => void }>({
  a: DEFAULTS, resolved: "gold", set: () => {},
});

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [a, setA] = useState<Appearance>(load);
  const [osDark, setOsDark] = useState(darkQuery()?.matches ?? true);
  const resolved: ResolvedTheme = a.theme === "system" ? (osDark ? "gold" : "light") : a.theme;
  const first = useRef(true);

  useEffect(() => {
    const q = darkQuery();
    if (!q) return;
    const on = (e: MediaQueryListEvent) => setOsDark(e.matches);
    q.addEventListener?.("change", on);
    return () => q.removeEventListener?.("change", on);
  }, []);

  // layout effect: the new data-theme is in place before the charts' effects read the colours
  useLayoutEffect(() => {
    const el = document.documentElement;
    let timer = 0;
    // short cross-fade when the theme changes (not on first paint, not with reduced motion)
    if (!first.current && el.dataset.theme !== resolved && !reducedMotion()) {
      el.classList.add("theme-switching");
      timer = window.setTimeout(() => el.classList.remove("theme-switching"), 280);
    }
    first.current = false;
    el.dataset.theme = resolved;
    el.dataset.density = a.density;
    el.dataset.glass = a.glass ? "on" : "off";
    el.style.colorScheme = isLightTheme(resolved) ? "light" : "dark";
    const bg = getComputedStyle(el).getPropertyValue("--ink").trim();
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", bg ? `rgb(${bg.split(/\s+/).join(",")})` : "#0b0e13");
    try { localStorage.setItem(KEY, JSON.stringify(a)); } catch { /* private mode: not remembered */ }
    return () => { if (timer) { window.clearTimeout(timer); el.classList.remove("theme-switching"); } };
  }, [a, resolved]);

  return <Ctx.Provider value={{ a, resolved, set: (p) => setA((x) => ({ ...x, ...p })) }}>{children}</Ctx.Provider>;
}

export const useAppearance = () => useContext(Ctx);

/** Colours for the canvas charts, read from the active theme. */
export function chartColors() {
  const css = getComputedStyle(document.documentElement);
  const v = (n: string, alpha = 1) => `rgba(${css.getPropertyValue(n).trim().split(/\s+/).join(",")},${alpha})`;
  return {
    text: v("--mute"), grid: v("--line", 0.45), border: v("--line"), bg: v("--ink"),
    bull: v("--bull"), bear: v("--bear"), bullSoft: (a: number) => v("--bull", a), bearSoft: (a: number) => v("--bear", a),
  };
}
