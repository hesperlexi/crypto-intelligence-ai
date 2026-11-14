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

/** Hero logo (landing, sign-in, access and loading screens): the v2.28 live logo - the original artwork as the core of
 *  a moving observatory (turning gold tick ring, cyan core pulse, radar sweep, satellite on its orbit). */
export function HeroLogo({ size = 96, className = "", title }: Props) {
  return <LiveLogo size={size} className={className} title={title} />;
}

/** v2.28 (owner, 14 Nov 2026: "original with the effects of C"). The same layers as brand-source/logo.svg (the still
 *  logo / icons), drawn live: everything moves with transform / opacity only and stops under prefers-reduced-motion. */
export function LiveLogo({ size = 96, className = "", title }: Props) {
  const id = "lx";
  const ticks = Array.from({ length: 60 }, (_, i) => {
    const a = (i * Math.PI) / 30, r2 = i % 3 === 0 ? 212 : 205;
    return <line key={i} x1={256 + 196 * Math.cos(a)} y1={256 + 196 * Math.sin(a)} x2={256 + r2 * Math.cos(a)} y2={256 + r2 * Math.sin(a)}
      stroke="#F7C948" strokeWidth={i % 3 === 0 ? 3 : 2} strokeLinecap="round" />;
  });
  return (
    <span className={`logox ${className}`} style={{ width: size, height: size }} role={title ? "img" : undefined} aria-label={title} aria-hidden={title ? undefined : true}>
      <svg viewBox="0 0 512 512" width={size} height={size}>
        <defs>
          <linearGradient id={`${id}g`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#FFF4C2" /><stop offset=".35" stopColor="#F7C948" /><stop offset=".72" stopColor="#D99A14" /><stop offset="1" stopColor="#8A5A00" /></linearGradient>
          <linearGradient id={`${id}rim`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#FFE7A3" /><stop offset=".5" stopColor="#C98A12" /><stop offset="1" stopColor="#FFD66B" /></linearGradient>
          <radialGradient id={`${id}bg`} cx=".5" cy=".45" r=".78"><stop offset="0" stopColor="#211B3D" /><stop offset=".55" stopColor="#0D0B14" /><stop offset="1" stopColor="#050408" /></radialGradient>
          <radialGradient id={`${id}neb`} cx=".8" cy=".14" r=".6"><stop offset="0" stopColor="#8F7CFF" stopOpacity=".34" /><stop offset="1" stopColor="#8F7CFF" stopOpacity="0" /></radialGradient>
          <radialGradient id={`${id}core`} cx=".5" cy=".5" r=".5"><stop offset=".55" stopColor="#5CF2DF" stopOpacity=".55" /><stop offset=".78" stopColor="#7B6CFF" stopOpacity=".28" /><stop offset="1" stopColor="#7B6CFF" stopOpacity="0" /></radialGradient>
          <linearGradient id={`${id}sw`} x1="0" y1="0" x2="1" y2="0"><stop offset="0" stopColor="#5CF2DF" stopOpacity="0" /><stop offset="1" stopColor="#5CF2DF" stopOpacity=".38" /></linearGradient>
          <filter id={`${id}gs`} x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.4" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
          <clipPath id={`${id}tc`}><rect x="16" y="16" width="480" height="480" rx="104" /></clipPath>
          <clipPath id={`${id}art`}><circle cx="256" cy="256" r="168" /></clipPath>
          <path id={`${id}orb`} d="M30 318 A236 78 -22 1 1 482 194 A236 78 -22 1 1 30 318" />
        </defs>
        <g clipPath={`url(#${id}tc)`}>
          <rect x="16" y="16" width="480" height="480" fill={`url(#${id}bg)`} />
          <rect x="16" y="16" width="480" height="480" fill={`url(#${id}neb)`} />
          {[[60, 90], [440, 60], [470, 420], [80, 440], [120, 150], [400, 470], [52, 300], [460, 300]].map(([x, y], i) => (
            <circle key={i} cx={x} cy={y} r={i % 3 ? 1.4 : 2.2} fill="#FFF6D8" className="logox-tw" style={{ animationDelay: `${i * 0.45}s` }} />
          ))}
          <circle cx="256" cy="256" r="232" fill={`url(#${id}core)`} className="logox-pulse" />
          <path d="M30 318 A236 78 -22 0 1 482 194" fill="none" stroke="#5CF2DF" strokeOpacity=".35" strokeWidth="3" />
          <g className="logox-spin">{ticks}</g>
          <circle cx="256" cy="256" r="186" fill="none" stroke="#5CF2DF" strokeOpacity=".55" strokeWidth="2" strokeDasharray="3 7" className="logox-spinr" />
          <image href="/brand/logo-art-384.webp" x="88" y="88" width="336" height="336" clipPath={`url(#${id}art)`} />
          <g clipPath={`url(#${id}art)`}><g className="logox-sweep"><path d="M256 256 L424 256 A168 168 0 0 0 393 159 Z" fill={`url(#${id}sw)`} /></g></g>
          <circle cx="256" cy="256" r="168" fill="none" stroke={`url(#${id}g)`} strokeWidth="9" filter={`url(#${id}gs)`} />
          <path d="M482 194 A236 78 -22 0 1 30 318" fill="none" stroke="#5CF2DF" strokeOpacity=".95" strokeWidth="4" filter={`url(#${id}gs)`} />
          <circle r="8" fill="#5CF2DF" filter={`url(#${id}gs)`} className="logox-sat">
            <animateMotion dur="7s" repeatCount="indefinite"><mpath href={`#${id}orb`} /></animateMotion>
          </circle>
        </g>
        <rect x="16" y="16" width="480" height="480" rx="104" fill="none" stroke={`url(#${id}rim)`} strokeWidth="7" />
      </svg>
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
        <defs><linearGradient id="logo-ring-g" x1="0" x2="1"><stop offset="0" stopColor="#FFE58A" /><stop offset="1" stopColor="#F0B90B" /></linearGradient></defs>
      </svg>
      <LiveLogo size={inner} />
    </span>
  );
}
