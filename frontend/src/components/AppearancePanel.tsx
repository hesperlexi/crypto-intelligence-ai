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
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
          {THEMES.map((t) => (
            <button key={t.id} onClick={() => set({ theme: t.id })} aria-pressed={a.theme === t.id}
              className={`tile flex items-center gap-2 p-2 text-left text-xs transition-colors ${a.theme === t.id ? "!border-accent/70 text-accent" : "hover:border-accent/40"}`}>
              <span className="flex shrink-0 overflow-hidden rounded-md border border-glass/20" aria-hidden>
                {t.swatch.map((c) => <span key={c} className="h-6 w-2.5" style={{ background: c }} />)}
              </span>
              <span className="min-w-0"><span className="block truncate font-semibold">{t.name}</span><span className="block truncate text-[10px] text-mute">{t.sub}</span></span>
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
  const { a: ap } = useAppearance();
  const cur = THEMES.find((t) => t.id === ap.theme) ?? THEMES[0];
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
      <button className={`btn h-8 gap-2 rounded-full py-0 pl-1 pr-2.5 text-xs font-medium ${open ? "btn-on" : ""}`} onClick={() => setOpen((v) => !v)}
        aria-expanded={open} title="Theme and layout" aria-label="Theme and layout">
        {/* the active theme's own colours, as a small orb */}
        <span className="relative grid h-6 w-6 place-items-center rounded-full ring-1 ring-glass/20" aria-hidden
          style={{ background: `conic-gradient(from 210deg, ${cur.swatch[1]}, ${cur.swatch[2]}, ${cur.swatch[1]})` }}>
          <span className="h-3.5 w-3.5 rounded-full" style={{ background: cur.swatch[0], boxShadow: `0 0 8px ${cur.swatch[1]}` }} />
        </span>
        <span className="hidden sm:inline">{cur.name}</span>
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
          className={`hidden text-mute transition-transform sm:block ${open ? "rotate-180" : ""}`} aria-hidden><path d="m6 9 6 6 6-6" /></svg>
      </button>
      {open && (
        <div className="panel popover animate-in fixed inset-x-3 top-14 z-50 max-h-[75vh] overflow-y-auto p-4 sm:absolute sm:inset-x-auto sm:right-0 sm:top-10 sm:w-[26rem]">
          <AppearancePanel />
        </div>
      )}
    </div>
  );
}
