import { ReactNode } from "react";
import { DASH, fmtProb, isNum } from "../lib/format";

export function Card({ title, right, children, className = "" }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`panel ${className}`}>
      {(title || right) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <h2 className="label">{title}</h2>
          {right}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Stat({ label, value, sub, className = "" }: { label: string; value: ReactNode; sub?: ReactNode; className?: string }) {
  return (
    <div className="min-w-0">
      <div className="label">{label}</div>
      <div className={`num mt-0.5 truncate text-lg ${className}`}>{value}</div>
      {sub != null && <div className="mt-0.5 truncate text-xs text-mute">{sub}</div>}
    </div>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return <div className="py-6 text-center text-sm text-mute">{what}…</div>;
}

export function ErrorBox({ error, retry }: { error: string; retry?: () => void }) {
  return (
    <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-bear/40 bg-bear/10 px-3 py-2 text-sm text-bear">
      <span>{error}</span>
      {retry && (
        <button className="btn" onClick={retry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-6 text-center text-sm text-mute">{children}</div>;
}

type Tone = "bull" | "bear" | "warn" | "mute" | "accent";
const TONES: Record<Tone, string> = {
  bull: "border-bull/40 bg-bull/10 text-bull",
  bear: "border-bear/40 bg-bear/10 text-bear",
  warn: "border-warn/40 bg-warn/10 text-warn",
  mute: "border-line bg-raised text-mute",
  accent: "border-accent/40 bg-accent/10 text-accent",
};

export function Badge({ tone = "mute", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${TONES[tone]}`}>
      {children}
    </span>
  );
}

export function signalTone(s?: string | null): Tone {
  if (!s) return "mute";
  if (s.includes("BUY")) return "bull";
  if (s.includes("SELL")) return "bear";
  if (s.includes("NO TRADE") || s.includes("INSUFFICIENT")) return "warn";
  return "mute";
}

/** Text is always shown; colour is only reinforcement. */
export function SignalBadge({ signal }: { signal?: string | null }) {
  const arrow = signal?.includes("BUY") ? "▲ " : signal?.includes("SELL") ? "▼ " : "";
  return <Badge tone={signalTone(signal)}>{arrow}{signal ?? DASH}</Badge>;
}

export function regimeTone(r?: string | null): Tone {
  if (!r) return "mute";
  if (r.includes("UNSTABLE") || r.includes("INSUFFICIENT")) return "warn";
  if (r.includes("BULL")) return "bull";
  if (r.includes("BEAR")) return "bear";
  return "mute";
}

export function RegimeBadge({ regime }: { regime?: string | null }) {
  return <Badge tone={regimeTone(regime)}>{regime ?? DASH}</Badge>;
}

export function FlagList({ flags }: { flags?: string[] | null }) {
  if (!flags?.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {flags.map((f) => (
        <Badge key={f} tone="warn">
          {f}
        </Badge>
      ))}
    </div>
  );
}

/** Three-way probability bar with numbers. */
export function ProbBar({ up, neutral, down }: { up?: number | null; neutral?: number | null; down?: number | null }) {
  if (!isNum(up) || !isNum(neutral) || !isNum(down)) return <div className="text-sm text-mute">No model probabilities</div>;
  return (
    <div>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-raised" role="img" aria-label={`Bullish ${fmtProb(up)}, neutral ${fmtProb(neutral)}, bearish ${fmtProb(down)}`}>
        <div className="bg-bull" style={{ width: `${up * 100}%` }} />
        <div className="bg-mute/50" style={{ width: `${neutral * 100}%` }} />
        <div className="bg-bear" style={{ width: `${down * 100}%` }} />
      </div>
      <div className="num mt-1.5 flex justify-between text-xs">
        <span className="text-bull">Bullish {fmtProb(up)}</span>
        <span className="text-mute">Neutral {fmtProb(neutral)}</span>
        <span className="text-bear">Bearish {fmtProb(down)}</span>
      </div>
    </div>
  );
}

/** Horizontal bar for a score in [-1, 1], centred at zero. */
export function ScoreBar({ value }: { value?: number | null }) {
  if (!isNum(value)) return <div className="h-1.5 rounded-full bg-raised" />;
  const w = Math.min(1, Math.abs(value)) * 50;
  return (
    <div className="relative h-1.5 rounded-full bg-raised">
      <div className="absolute top-0 h-full w-px bg-mute/60" style={{ left: "50%" }} />
      <div className={`absolute top-0 h-full rounded-full ${value >= 0 ? "bg-bull" : "bg-bear"}`} style={value >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }} />
    </div>
  );
}

export function Meter({ value, tone = "accent" }: { value?: number | null; tone?: Tone }) {
  const color = { bull: "bg-bull", bear: "bg-bear", warn: "bg-warn", mute: "bg-mute", accent: "bg-accent" }[tone];
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-raised">
      <div className={`h-full ${color}`} style={{ width: `${isNum(value) ? Math.max(0, Math.min(1, value)) * 100 : 0}%` }} />
    </div>
  );
}

export function Row({ k, v, className = "" }: { k: ReactNode; v: ReactNode; className?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line/50 py-1.5 text-sm last:border-0">
      <span className="text-mute">{k}</span>
      <span className={`num text-right ${className}`}>{v}</span>
    </div>
  );
}

export function Tabs<T extends string>({ value, options, onChange, label }: { value: T; options: readonly T[]; onChange: (v: T) => void; label?: string }) {
  return (
    <div className="flex flex-wrap gap-1" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o} className={`btn px-2.5 py-1 text-xs uppercase ${o === value ? "btn-on" : ""}`} aria-pressed={o === value} onClick={() => onChange(o)}>
          {o}
        </button>
      ))}
    </div>
  );
}

export function Note({ children }: { children: ReactNode }) {
  return <p className="text-xs leading-relaxed text-mute">{children}</p>;
}

export function Check({ ok, children }: { ok: boolean | null | undefined; children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 text-sm">
      <span className={ok ? "text-bull" : ok === false ? "text-bear" : "text-mute"} aria-hidden>
        {ok ? "✓" : ok === false ? "✕" : "·"}
      </span>
      <span>
        {children} <span className="sr-only">{ok ? "(passed)" : ok === false ? "(failed)" : ""}</span>
      </span>
    </div>
  );
}
