// UI v2.15 design system: the few building blocks every page shares. Older names (Stat, Pill, GradeBadge, Badge in
// ui.tsx, Tabs, TfTabs) stay as thin wrappers around these, so call sites keep working.
//   Tile       one number with a small label and an optional quiet line (plain / box / strip cell)
//   Badge      a small status label (tones bull / bear / warn / accent / mute / ai), pill shaped
//   Segmented  one bordered track of options (timeframes, Futures / Spot, view switches)
//   Chip       one standalone toggle / filter pill (News sources, coin filters)
// Type scale: 12 / 14 / 16 / 20 / 28 px (text-xs / sm / base / xl / 2xl). Nothing below 12 px on phones.
// Touch: every control is at least 44 px tall on phones and touch screens (index.css), compact on desktop.
import { ReactNode } from "react";
import { Link } from "react-router-dom";

export type Tone = "bull" | "bear" | "warn" | "mute" | "accent" | "ai" | "text";

const BADGE_TONES: Record<Tone, string> = {
  bull: "border-bull/30 bg-bull/[0.08] text-bull",
  bear: "border-bear/30 bg-bear/[0.08] text-bear",
  warn: "border-warn/30 bg-warn/[0.08] text-warn",
  mute: "border-glass/[0.12] bg-glass/[0.04] text-mute",
  accent: "border-accent/40 bg-accent/[0.1] text-accent",
  ai: "border-ai/30 bg-ai/[0.1] text-ai",
  text: "border-glass/20 bg-glass/[0.05] text-text/85",
};

/** Small status label. `caps`: uppercase with letter spacing (signals, regimes); otherwise sentence case. */
export function Badge({ tone = "mute", children, title, caps = false, className = "" }: { tone?: Tone; children: ReactNode; title?: string; caps?: boolean; className?: string }) {
  return (
    <span title={title}
      className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-full border px-2 py-1 text-xs font-semibold leading-none ${caps ? "uppercase tracking-[0.04em]" : ""} ${BADGE_TONES[tone]} ${className}`}>
      {children}
    </span>
  );
}

/** One figure: label, value, optional sub line.
 *  plain = no frame (inside cards) · box = framed tile · strip = a cell of `.metric-strip` (hairlines between cells). */
export function Tile({ label, value, sub, valueClass = "", variant = "plain", to, title, className = "", big = false }: {
  label: ReactNode; value: ReactNode; sub?: ReactNode; valueClass?: string; variant?: "plain" | "box" | "strip"; to?: string; title?: string; className?: string;
  /** headline figures (Results tiles): 28 px value */
  big?: boolean;
}) {
  const strip = variant === "strip";
  const body = (
    <>
      <div className={strip ? "metric-k" : "label leading-snug"} title={title ?? (typeof label === "string" ? label : undefined)}>{label}</div>
      <div className={`${strip ? "metric-v" : big ? "mt-1.5 truncate text-2xl font-semibold leading-none" : "mt-1 truncate text-xl leading-tight"} num ${valueClass}`}>{value}</div>
      {sub != null && sub !== false && <div className={strip ? "metric-sub num" : "mt-1 text-xs leading-snug text-mute"}>{sub}</div>}
    </>
  );
  const cls = `${strip ? "metric" : variant === "box" ? `tile ${big ? "p-4" : "p-3"}` : ""} block min-w-0 ${className}`;
  return to ? <Link to={to} className={`${cls} transition-colors hover:border-accent/40`}>{body}</Link> : <div className={cls}>{body}</div>;
}

export type SegOption<T extends string> = T | readonly [T, ReactNode] | readonly [T, ReactNode, string];

/** Segmented control: one track, the chosen option raised. Options are values, or [value, label, tooltip?]. */
export function Segmented<T extends string>({ value, options, onChange, label, className = "", upper = false, strong = false, after }: {
  value: T; options: readonly SegOption<T>[]; onChange: (v: T) => void; label?: string; className?: string; upper?: boolean; strong?: boolean;
  after?: (v: T) => ReactNode;
}) {
  return (
    <div className={`seg max-w-full flex-wrap ${className}`} role="group" aria-label={label}>
      {options.map((o) => {
        const [k, l, tip] = typeof o === "string" ? [o as T, o, undefined] : [o[0], o[1], o[2]];
        return (
          <button key={k} type="button" aria-pressed={k === value} title={tip} onClick={() => onChange(k)}
            className={`${upper ? "num uppercase" : ""} ${strong ? "seg-strong" : ""}`}>
            {l}{after?.(k)}
          </button>
        );
      })}
    </div>
  );
}

/** One toggle / filter pill. */
export function Chip({ on, onClick, children, title, className = "", count }: { on: boolean; onClick: () => void; children: ReactNode; title?: string; className?: string; count?: number }) {
  return (
    <button type="button" aria-pressed={on} title={title} onClick={onClick} className={`chip ${className}`}>
      {children}{count != null && <span className="num text-mute">{count}</span>}
    </button>
  );
}

/** Page-level tabs (Results, Track record): underlined, 44 px tall, scroll sideways on narrow screens. */
export function TabStrip<T extends string>({ value, options, onChange, label, className = "" }: {
  value: T; options: readonly (readonly [T, ReactNode])[]; onChange: (v: T) => void; label?: string; className?: string;
}) {
  return (
    <div className={`flex gap-1 overflow-x-auto border-b border-glass/[0.08] ${className}`} role="tablist" aria-label={label}>
      {options.map(([k, l]) => (
        <button key={k} type="button" role="tab" aria-selected={value === k} onClick={() => onChange(k)}
          className={`-mb-px min-h-[44px] whitespace-nowrap border-b-2 px-3 text-sm transition-colors ${value === k ? "border-accent font-semibold text-text" : "border-transparent text-mute hover:text-text"}`}>{l}</button>
      ))}
    </div>
  );
}
