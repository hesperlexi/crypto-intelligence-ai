// The Crypto Intelligence AI logo, V3.5 (owner, 26 Nov 2026): gold neural arc, C, rising arrow, "AI" and gear in 3D
// crystal gold on a graphite glass tile. Source: brand-source/make_logo_v35.py (SVG + data/logoV35.ts) and
// render_logo_v35.cjs (every PNG / WebP / icon). LiveLogo = the animated version (five moving parts); Logo = still image.
import { useId, useMemo, useState } from "react";
import { LOGO_V35 } from "../data/logoV35";

const SIZES = [96, 192, 384] as const;

// The intro plays once per browser session, on the first hero logo shown.
let introUsed = false;
function takeIntro(): boolean {
  if (introUsed) return false;
  introUsed = true;
  try {
    if (sessionStorage.getItem("cia-logo-intro")) return false;
    sessionStorage.setItem("cia-logo-intro", "1");
    return true;
  } catch { return false; }   // storage blocked: no intro
}

/** The artwork itself, at the right resolution for the size it is drawn at (2x for sharp screens). */
function Art({ size, eager = false }: { size: number; eager?: boolean }) {
  const need = size * 2;
  const pick = SIZES.find((s) => s >= need) ?? 384;
  const set = (ext: string) => SIZES.map((s) => `/brand/logo-${s}.${ext} ${s}w`).join(", ");
  return (
    <picture>
      <source type="image/webp" srcSet={set("webp")} sizes={`${size}px`} />
      <img src={`/brand/logo-${pick}.png`} srcSet={set("png")} sizes={`${size}px`} width={size} height={size} alt=""
        draggable={false} decoding="async" loading={eager ? "eager" : "lazy"} className="logo3d-img" />
    </picture>
  );
}

type Variant = "hero" | "header" | "static";
interface Props { size?: number; className?: string; title?: string }

function Tile({ size, variant, className = "", title }: Props & { size: number; variant: Variant }) {
  const [intro] = useState(() => variant === "hero" && takeIntro());
  const depth = Math.max(2, Math.round(size * 0.05));
  return (
    <span className={`logo3d logo3d-${variant} ${className}`} style={{ width: size, height: size, ["--logo-depth" as any]: `${depth}px` }}
      role={title ? "img" : undefined} aria-label={title} aria-hidden={title ? undefined : true}>
      {variant !== "static" && <span className="logo3d-glow" />}
      <span className={`logo3d-stage ${intro ? "logo3d-intro" : ""}`}>
        <span className="logo3d-tile">
          <span className="logo3d-back" />
          <span className="logo3d-face">
            <Art size={size} eager={variant !== "static"} />
            {variant !== "static" && <span className="logo3d-sweep" />}
          </span>
        </span>
      </span>
    </span>
  );
}

/** Still logo (lists, pages, footers). */
export function Logo({ size = 32, className = "", title }: Props) {
  const pick = [96, 192, 384].find((s) => s >= size * 2) ?? 384;
  return <img src={`/brand/logo-${pick}.png`} width={size} height={size} alt={title ?? ""} aria-hidden={title ? undefined : true}
    className={`inline-block ${className}`} draggable={false} decoding="async" />;
}

/** Header logo: the live logo (blinking neurons, lightning links) at header size. */
export function AnimatedLogo({ size = 36, className = "", title }: Props) {
  return <LiveLogo size={size} className={className} title={title} />;
}
// keep the 3D tile available for any future still use
void Tile;

/** Hero logo (landing, sign-in, access and loading screens): the v2.28 live logo - the original artwork as the core of
 *  the V3.0 tile with a gold pulse and the turning cyan ring. */
export function HeroLogo({ size = 96, className = "", title }: Props) {
  return <LiveLogo size={size} className={className} title={title} />;
}

/** V3.5 (owner, 26 Nov 2026): the gold 3D crystal logo (brand-source/make_logo_v35.py -> data/logoV35.ts), drawn live.
 *  Each of the five parts moves on its own: 1 the neural arc rocks gently, 2 the C breathes, 3 the rising arrow draws
 *  itself, 4 "AI" floats, 5 the gear turns. Transform / stroke only; everything is still under prefers-reduced-motion.
 *  `tile` = the graphite glass tile behind it (default); off = the bare mark. */
export function LiveLogo({ size = 96, className = "", title, tile = true }: Props & { tile?: boolean }) {
  const raw = useId();
  const pfx = "lg" + raw.replace(/[^a-zA-Z0-9]/g, "");
  const L = LOGO_V35;
  const fix = (x: string) => x.split("__P__").join(pfx);
  const html = useMemo(() => {
    const p = L.parts;
    return [
      `<defs>${fix(L.defs)}</defs>`,
      tile ? fix(L.tile) : "",
      `<g transform="${L.content}">`,
      `<g clip-path="url(#${pfx}gearClip)"><g class="lg5-gear">${fix(p.gear)}</g></g>`,
      `<g class="lg5-neural">${fix(p.neural)}</g>`,
      `<g class="lg5-c">${fix(p.c_cut)}${fix(p.c)}</g>`,
      `<g class="lg5-arrow">${fix(p.arrow_cut)}${fix(p.arrow)}</g>`,
      `<g class="lg5-ai">${fix(p.ai)}</g>`,
      `</g>`,
    ].join("");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pfx, tile]);
  return (
    <span className={`lg5 ${className}`} style={{ width: size, height: size }} role={title ? "img" : undefined} aria-label={title} aria-hidden={title ? undefined : true}>
      <svg viewBox="0 0 1024 1024" width={size} height={size} dangerouslySetInnerHTML={{ __html: html }} />
    </span>
  );
}

/** Loading indicator: the logo inside a turning gold ring. */
export function LogoSpinner({ size = 56, label = "Loading" }: { size?: number; label?: string }) {
  const inner = Math.round(size * 0.72);
  return (
    <span role="status" aria-label={label} className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox="0 0 64 64" className="absolute inset-0" aria-hidden="true">
        <circle cx="32" cy="32" r="30" fill="none" stroke="rgb(var(--accent) / .15)" strokeWidth="2" />
        <circle className="logo-ring" cx="32" cy="32" r="30" fill="none" stroke="url(#logo-ring-g)" strokeWidth="2.4" strokeLinecap="round" strokeDasharray="46 160" />
        <defs><linearGradient id="logo-ring-g" x1="0" x2="1"><stop offset="0" stopColor="#F6E37A" /><stop offset="1" stopColor="#E8B637" /></linearGradient></defs>
      </svg>
      <LiveLogo size={inner} />
    </span>
  );
}
