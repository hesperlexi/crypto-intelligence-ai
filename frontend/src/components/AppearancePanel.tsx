import { useEffect, useRef, useState } from "react";
import { Appearance, THEMES, useAppearance } from "../lib/appearance";

function Choice<K extends keyof Appearance>({ label, k, options }: { label: string; k: K; options: [Appearance[K], string][] }) {
  const { a, set } = useAppearance();
  return (
    <div>
      <div className="label mb-1.5">{label}</div>
      <div className="flex flex-wrap gap-1" role="group" aria-label={label}>
        {options.map(([v, text]) => (
          <button key={String(v)} className={`btn px-2.5 py-1 text-xs ${a[k] === v ? "btn-on" : ""}`} aria-pressed={a[k] === v}
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
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
          {THEMES.map((t) => (
            <button key={t.id} onClick={() => set({ theme: t.id })} aria-pressed={a.theme === t.id}
              className={`tile flex items-center gap-2 p-2 text-left text-xs transition-colors ${a.theme === t.id ? "!border-accent/70 text-accent" : "hover:border-accent/40"}`}>
              <span className="flex shrink-0 overflow-hidden rounded-md border border-glass/20" aria-hidden>
                {t.swatch.map((c) => <span key={c} className="h-6 w-2.5" style={{ background: c }} />)}
              </span>
              <span className="truncate">{t.name}</span>
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
      <button className={`btn px-2 py-1.5 text-sm ${open ? "btn-on" : ""}`} onClick={() => setOpen((v) => !v)} aria-expanded={open} title="Theme and layout" aria-label="Theme and layout">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M12 22a10 10 0 1 1 10-10c0 2.2-1.8 3-3.5 3H16a2 2 0 0 0-1.5 3.3A2 2 0 0 1 12 22z" />
          <circle cx="7.5" cy="10.5" r="1.2" fill="currentColor" /><circle cx="12" cy="7" r="1.2" fill="currentColor" /><circle cx="16.5" cy="10.5" r="1.2" fill="currentColor" />
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
