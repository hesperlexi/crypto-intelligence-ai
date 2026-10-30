// The Crypto Intelligence AI logo: the original artwork (brand-source/logo-source.png, gold neural brain, gear,
// C / infinity with the rising arrow and "AI"), cropped just inside its baked gold frame and exported as WebP + PNG
// at 96 / 192 / 384 px (public/brand/logo-*.{webp,png}).
//
// It is shown as a 3D tile: a CSS perspective container, a back plate a few pixels behind the face (the edge that
// shows when the tile turns), a gold rim, a light sweep across the face and a soft glow (index.css "logo3d-*").
//   hero    slow tilt (rotateY ±18°, a little rotateX, 8 s loop) + sweep + glow; rises / turns into place once
//           per session. Landing, sign-in / access screens, error pages.
//   header  small; sweep + glow only, no rotation.
//   static  the tile with no motion (lists, footers).
// Animations use transform / opacity only and stop with prefers-reduced-motion.
import { useState } from "react";

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
  return <Tile size={size} variant="static" className={className} title={title} />;
}

/** Header logo: a light sweep every ~6 s and a soft glow; no rotation. */
export function AnimatedLogo({ size = 36, className = "", title }: Props) {
  return <Tile size={size} variant="header" className={className} title={title} />;
}

/** Hero logo (landing, sign-in, access and loading screens): the full 3D tilt, sweep, glow and a one-time intro. */
export function HeroLogo({ size = 96, className = "", title }: Props) {
  return <Tile size={size} variant="hero" className={className} title={title} />;
}

/** Loading indicator: the logo inside a turning gold ring. */
export function LogoSpinner({ size = 56, label = "Loading" }: { size?: number; label?: string }) {
  const inner = Math.round(size * 0.72);
  return (
    <span role="status" aria-label={label} className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox="0 0 64 64" className="absolute inset-0" aria-hidden="true">
        <circle cx="32" cy="32" r="30" fill="none" stroke="rgb(var(--accent) / .15)" strokeWidth="2" />
        <circle className="logo-ring" cx="32" cy="32" r="30" fill="none" stroke="url(#logo-ring-g)" strokeWidth="2.4" strokeLinecap="round" strokeDasharray="46 160" />
        <defs><linearGradient id="logo-ring-g" x1="0" x2="1"><stop offset="0" stopColor="#FFE58A" /><stop offset="1" stopColor="#F0B90B" /></linearGradient></defs>
      </svg>
      <Tile size={inner} variant="header" />
    </span>
  );
}
