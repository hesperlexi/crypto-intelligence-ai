import { KeyboardEvent, useEffect, useRef, useState } from "react";
import { Appearance, THEMES, ThemeId, useAppearance } from "../lib/appearance";

function Choice<K extends keyof Appearance>({ label, k, options }: { label: string; k: K; options: [Appearance[K], string][] }) {
  const { a, set } = useAppearance();
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5 border-t border-glass/[0.07] pt-3">
      <div className="text-sm text-text/90">{label}</div>
      <div className="seg" role="group" aria-label={label}>
        {options.map(([v, text]) => (
          <button key={String(v)} type="button" aria-pressed={a[k] === v} onClick={() => set({ [k]: v } as Partial<Appearance>)}>{text}</button>
        ))}
      </div>
    </div>
  );
}

/** A miniature of the app drawn with the theme's real tokens: the box carries data-theme, so every colour inside
 *  (Tailwind's bg-panel, text-bull …) resolves to that theme. */
function Mini({ theme }: { theme: string }) {
  return (
    <div data-theme={theme} className="theme-preview" aria-hidden="true">
      {/* nav bar */}
      <div className="flex h-[18px] items-center gap-1.5 border-b border-glass/[0.08] bg-panel px-2">
        <span className="h-2 w-2 rounded-[3px] bg-accent" />
        <span className="relative h-1 w-5 rounded-full bg-text/70"><span className="absolute -bottom-[5px] left-0 right-0 h-[1.5px] rounded-full bg-accent" /></span>
        <span className="h-1 w-4 rounded-full bg-mute/50" />
        <span className="h-1 w-4 rounded-full bg-mute/50" />
        <span className="ml-auto h-1.5 w-4 rounded-full bg-bull/70" />
      </div>
      <div className="flex gap-1.5 p-1.5">
        {/* card with a tiny chart */}
        <div className="min-w-0 flex-1 rounded-[5px] border border-glass/[0.08] bg-panel p-1.5">
          <div className="flex items-center justify-between">
            <span className="h-1 w-6 rounded-full bg-mute/60" />
            <span className="text-[8px] font-semibold leading-none text-bull">+2.4%</span>
          </div>
          <svg viewBox="0 0 80 26" className="mt-1 h-[30px] w-full" preserveAspectRatio="none">
            <path d="M0 21 L10 18 L18 20 L28 13 L37 15 L47 9 L56 11 L66 5 L80 3 V26 H0 Z" fill="rgb(var(--accent) / 0.12)" />
            <path d="M0 21 L10 18 L18 20 L28 13 L37 15 L47 9 L56 11 L66 5 L80 3" fill="none" stroke="rgb(var(--accent))" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
          </svg>
        </div>
        {/* side column: bull / bear figures and the gold button */}
        <div className="flex w-[38%] flex-col gap-1">
          <div className="flex items-center justify-between rounded-[4px] border border-glass/[0.08] bg-panel px-1 py-[3px]">
            <span className="h-1 w-3 rounded-full bg-mute/60" /><span className="whitespace-nowrap text-[8px] font-semibold leading-none text-bull">▲ 1.8</span>
          </div>
          <div className="flex items-center justify-between rounded-[4px] border border-glass/[0.08] bg-panel px-1 py-[3px]">
            <span className="h-1 w-3 rounded-full bg-mute/60" /><span className="whitespace-nowrap text-[8px] font-semibold leading-none text-bear">▼ 0.9</span>
          </div>
          <div className="mt-auto flex h-[14px] items-center justify-center rounded-[4px] text-[7px] font-bold leading-none" style={{ background: "rgb(var(--primary))", color: "rgb(var(--on-primary))" }}>BUY</div>
        </div>
      </div>
    </div>
  );
}

/** System: half Midnight Gold, half Ivory. */
function SystemMini() {
  return (
    <div className="relative">
      <Mini theme="gold" />
      <div className="absolute inset-0" style={{ clipPath: "polygon(58% 0, 100% 0, 100% 100%, 42% 100%)" }}><Mini theme="light" /></div>
    </div>
  );
}

function ThemePicker() {
  const { a, set } = useAppearance();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const idx = Math.max(0, THEMES.findIndex((t) => t.id === a.theme));
  // radiogroup keyboard pattern: arrows move and select, Home / End jump
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const n = THEMES.length;
    const to = e.key === "ArrowRight" || e.key === "ArrowDown" ? (idx + 1) % n
      : e.key === "ArrowLeft" || e.key === "ArrowUp" ? (idx - 1 + n) % n
      : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : -1;
    if (to < 0) return;
    e.preventDefault();
    set({ theme: THEMES[to].id as ThemeId });
    refs.current[to]?.focus();
  };
  return (
    <div role="radiogroup" aria-label="Theme" onKeyDown={onKey} className="grid grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-2.5">
      {THEMES.map((t, i) => {
        const on = a.theme === t.id;
        return (
          <button key={t.id} ref={(el) => { refs.current[i] = el; }} type="button" role="radio" aria-checked={on} tabIndex={on ? 0 : -1}
            onClick={() => set({ theme: t.id })} className="theme-card">
            {t.id === "system" ? <SystemMini /> : <Mini theme={t.id} />}
            <span className="theme-check" aria-hidden="true">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
            </span>
            <span className="min-w-0 pl-1 pr-6">
              <span className={`block truncate text-[13px] font-semibold ${on ? "text-accent" : "text-text"}`}>{t.name}</span>
              <span className="block truncate text-[11px] text-mute">{t.sub}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

/** Theme previews + layout options. Used in the header popover and on the Settings page. */
export function AppearancePanel() {
  return (
    <div className="space-y-4">
      <div>
        <div className="label mb-2">Theme</div>
        <ThemePicker />
      </div>
      <div className="space-y-3">
        <Choice label="Menu (computer)" k="nav" options={[["top", "Top bar"], ["side", "Sidebar"]]} />
        <Choice label="Density" k="density" options={[["comfortable", "Comfortable"], ["compact", "Compact"]]} />
        <Choice label="Page width" k="width" options={[["contained", "Centered"], ["wide", "Full width"]]} />
        <Choice label="Glass effect" k="glass" options={[[true, "On"], [false, "Off (faster)"]]} />
      </div>
      <p className="text-[11px] text-mute">Saved on this device.</p>
    </div>
  );
}

/** Header button that opens the appearance popover. */
export default function AppearanceButton() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: globalThis.KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <div className="relative" ref={ref}>
      {/* icon-only, same height and corners as the header's status badge */}
      <button onClick={() => setOpen((v) => !v)} aria-expanded={open} title="Theme and layout" aria-label="Theme and layout"
        className={`inline-flex h-[22px] w-[26px] items-center justify-center rounded border transition-colors ${open ? "border-accent/60 bg-accent/10 text-accent" : "border-glass/15 bg-glass/[0.04] text-accent/90 hover:border-accent/50 hover:text-accent"}`}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
          {/* half-moon disc (light / dark) with a small spark: "appearance" */}
          <circle cx="11" cy="13" r="8" stroke="currentColor" strokeWidth="2" />
          <path d="M11 5a8 8 0 0 1 0 16z" fill="currentColor" />
          <path d="M19.5 2.5v3M18 4h3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      </button>
      {open && (
        <div className="panel popover animate-in fixed inset-x-3 top-14 z-50 max-h-[75vh] overflow-y-auto p-4 sm:absolute sm:inset-x-auto sm:right-0 sm:top-10 sm:w-[30rem]">
          <AppearancePanel />
        </div>
      )}
    </div>
  );
}
