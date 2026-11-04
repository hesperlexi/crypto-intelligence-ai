import { createContext, ReactNode, useContext, useEffect, useLayoutEffect, useRef, useState } from "react";

/** Themes and layout preferences. Saved per device (browser storage); everything works without it.
 *  Theme ids are stable keys in saved preferences: "gold" is Midnight Gold and "light" is Ivory. The colours of each
 *  theme live in index.css under [data-theme="<id>"]. */
export const THEMES = [
  { id: "gold", name: "Midnight Gold", sub: "Default · warm black, rich gold", dark: true },
  { id: "obsidian", name: "Obsidian", sub: "Pure black, champagne gold", dark: true },
  { id: "aurora", name: "Aurora", sub: "Navy blue, gold and cyan", dark: true },
  { id: "violet", name: "Violet Night", sub: "Deep purple, violet glow", dark: true },
  { id: "light", name: "Ivory", sub: "Light paper, deep gold", dark: false },
  { id: "system", name: "System", sub: "Follows the device", dark: true },
] as const;
export type ThemeId = (typeof THEMES)[number]["id"];
export type ResolvedTheme = Exclude<ThemeId, "system">;

export interface Appearance {
  theme: ThemeId;
  nav: "top" | "side";             // desktop navigation (v2.20: sidebar by default on screens ≥ 1024 px)
  navChosen?: boolean;             // true once the person picked top / side themselves (then their choice is kept)
  sideCollapsed?: boolean;         // desktop sidebar folded to icons
  density: "comfortable" | "compact";
  width: "contained" | "wide";
  glass: boolean;                  // frosted blur (switch off on slow phones)
}
const DEFAULTS: Appearance = { theme: "gold", nav: "side", density: "comfortable", width: "contained", glass: true, sideCollapsed: false };
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
    // v2.20: the whole object used to be saved with the old default nav "top"; only an explicit choice is kept
    if (!a.navChosen) a.nav = "side";
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
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", bg ? `rgb(${bg.split(/\s+/).join(",")})` : "#0d0c0a");
    try { localStorage.setItem(KEY, JSON.stringify(a)); } catch { /* private mode: not remembered */ }
    return () => { if (timer) { window.clearTimeout(timer); el.classList.remove("theme-switching"); } };
  }, [a, resolved]);

  return <Ctx.Provider value={{ a, resolved, set: (p) => setA((x) => ({ ...x, ...p, ...("nav" in p ? { navChosen: true } : {})})) }}>{children}</Ctx.Provider>;
}

export const useAppearance = () => useContext(Ctx);

/** Colours for the canvas charts, read from the active theme. */
export function chartColors() {
  const css = getComputedStyle(document.documentElement);
  const v = (n: string, alpha = 1) => `rgba(${css.getPropertyValue(n).trim().split(/\s+/).join(",")},${alpha})`;
  return {
    text: v("--mute"), grid: v("--line", 0.45), border: v("--line"), bg: v("--ink"),
    bull: v("--bull"), bear: v("--bear"), bullSoft: (a: number) => v("--bull", a), bearSoft: (a: number) => v("--bear", a),
    accent: v("--accent"), warn: v("--warn"), ai: v("--ai"), mute: v("--mute"),
  };
}

/** A colour for canvas / chart libraries: a theme token ("--bear", "--accent", …) becomes the current theme's rgba;
 *  anything else (a hex) passes through. Read at draw time, so charts redrawn after a theme change follow it. */
export function themeColor(c: string, alpha = 1): string {
  if (!c.startsWith("--") || typeof document === "undefined") return c;
  const raw = getComputedStyle(document.documentElement).getPropertyValue(c).trim();
  return raw ? `rgba(${raw.split(/\s+/).join(",")},${alpha})` : c;
}
