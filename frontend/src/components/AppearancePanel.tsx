import { useEffect, useRef, useState } from "react";
import { Appearance, THEMES, useAppearance } from "../lib/appearance";

function Choice<K extends keyof Appearance>({ label, k, options }: { label: string; k: K; options: [Appearance[K], string][] }) {
  const { a, set } = useAppearance();
  return (
    <div>
      <div className="label mb-1.5">{label}</div>
      <div className="flex flex-wrap gap-1" role="group" aria-label={label}>
        {options.map(([v, text]) => (
          <button key={String(v)} className={`btn btn-sm ${a[k] === v ? "btn-on" : ""}`} aria-pressed={a[k] === v}
            onClick={() => set({ [k]: v } as Partial<Appearance>)}>{text}</button>
        ))}
      </div>
    </div>
  );
}

/** Theme swatches + layout options. Used in the header popover and on the Settings page. */
export function AppearancePanel() {
  const { a, set } = useAppearance();
  return (
    <div className="space-y-4">
      <div>
        <div className="label mb-1.5">Theme</div>
        <div className="grid grid-cols-3 gap-2">
          {THEMES.map((t) => (
            <button key={t.id} onClick={() => set({ theme: t.id })} aria-pressed={a.theme === t.id}
              className={`tile flex flex-col items-stretch gap-2 p-2 text-left text-xs transition-colors ${a.theme === t.id ? "!border-accent/70 ring-1 ring-accent/40" : "hover:border-accent/40"}`}>
              <span className="flex h-9 overflow-hidden rounded-md border border-glass/20" aria-hidden>
                {t.swatch.map((c) => <span key={c} className="flex-1" style={{ background: c }} />)}
              </span>
              <span className="min-w-0 px-0.5"><span className={`block truncate text-sm font-semibold ${a.theme === t.id ? "text-accent" : ""}`}>{t.name}</span><span className="block truncate text-[11px] text-mute">{t.sub}</span></span>
            </button>
          ))}
        </div>
      </div>
      <Choice label="Menu (computer)" k="nav" options={[["top", "Top bar"], ["side", "Sidebar"]]} />
      <Choice label="Density" k="density" options={[["comfortable", "Comfortable"], ["compact", "Compact"]]} />
      <Choice label="Page width" k="width" options={[["contained", "Centered"], ["wide", "Full width"]]} />
      <Choice label="Glass effect" k="glass" options={[[true, "On"], [false, "Off (faster)"]]} />
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
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
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
        <div className="panel popover animate-in fixed inset-x-3 top-14 z-50 max-h-[75vh] overflow-y-auto p-4 sm:absolute sm:inset-x-auto sm:right-0 sm:top-10 sm:w-[26rem]">
          <AppearancePanel />
        </div>
      )}
    </div>
  );
}
