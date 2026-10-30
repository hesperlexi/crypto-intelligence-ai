// The Crypto Intelligence AI mark as a clean vector, simplified from brand-source/logo-source.png:
// a gold C (crescent) that flows into an infinity loop, a rising up-right arrow through the middle and two
// node dots, with the source's coral/pink glow kept as a faint inner arc. Pure SVG + CSS (index.css "logo-*").
// Animations use transform/opacity only (the one-time intro draw uses stroke-dashoffset) and are switched
// off by prefers-reduced-motion.
import { useId, useState } from "react";

// The intro draw plays once per browser session, on the first logo shown.
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

// geometry on a 64x64 grid (kept in one place so every variant draws the same mark)
export const LOGO_PATHS = {
  c: "M39 21.1A17 17 0 1 0 39 42.9",                                   // the C, open to the right
  coral: "M19.8 21.2A12.5 12.5 0 0 0 19.8 42.8",                           // faint inner coral arc
  loop: "M39 42.9C43.5 40 44.5 28 51 28C56 28 59 32 59 36C59 41 55.5 44 51 44C46.5 44 43.5 40 41.5 36.5", // infinity lobe
  arrow: "M18 39L24 33L28.5 37.5L47 17",                                  // rising line
  head: "M41 15L49 15L49 23",                                   // arrow head
} as const;

type Variant = "static" | "animated" | "intro";

function Mark({ uid, variant }: { uid: string; variant: Variant }) {
  const g = `${uid}g`, k = `${uid}k`, m = `${uid}m`, s = `${uid}s`, b = `${uid}b`;
  const draw = variant === "intro" ? "logo-draw" : undefined;
  const strokes = (
    <>
      <path d={LOGO_PATHS.c} stroke={`url(#${g})`} strokeWidth="7" pathLength={1} className={draw} />
      <path d={LOGO_PATHS.loop} stroke={`url(#${g})`} strokeWidth="4.6" pathLength={1} className={draw} />
      <path d={LOGO_PATHS.arrow} stroke={`url(#${g})`} strokeWidth="3.6" pathLength={1} className={draw} />
      <path d={LOGO_PATHS.head} stroke={`url(#${g})`} strokeWidth="3.6" pathLength={1} className={draw} />
    </>
  );
  return (
    <>
      <defs>
        <linearGradient id={g} x1="8" y1="8" x2="56" y2="56" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#FFE58A" />
          <stop offset=".45" stopColor="#F0B90B" />
          <stop offset="1" stopColor="#B7860B" />
        </linearGradient>
        <linearGradient id={k} x1="20" y1="22" x2="20" y2="42" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#FFB199" />
          <stop offset="1" stopColor="#F56C9A" />
        </linearGradient>
        {variant !== "static" && (
          <>
            <filter id={b} x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="2.4" /></filter>
            <linearGradient id={s} x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stopColor="#fff" stopOpacity="0" />
              <stop offset=".5" stopColor="#FFF6D6" stopOpacity=".9" />
              <stop offset="1" stopColor="#fff" stopOpacity="0" />
            </linearGradient>
            <mask id={m} maskUnits="userSpaceOnUse" x="0" y="0" width="64" height="64">
              <g fill="none" stroke="#fff" strokeLinecap="round" strokeLinejoin="round">
                <path d={LOGO_PATHS.c} strokeWidth="7" /><path d={LOGO_PATHS.loop} strokeWidth="4.6" />
                <path d={LOGO_PATHS.arrow} strokeWidth="3.6" /><path d={LOGO_PATHS.head} strokeWidth="3.6" />
              </g>
            </mask>
          </>
        )}
      </defs>
      {variant !== "static" && (
        <g className="logo-glow" filter={`url(#${b})`} fill="none" stroke="#F0B90B" strokeLinecap="round" strokeLinejoin="round" opacity=".45">
          <path d={LOGO_PATHS.c} strokeWidth="7" /><path d={LOGO_PATHS.loop} strokeWidth="4.6" /><path d={LOGO_PATHS.arrow} strokeWidth="3.6" />
        </g>
      )}
      <path d={LOGO_PATHS.coral} fill="none" stroke={`url(#${k})`} strokeWidth="2" strokeLinecap="round" opacity=".6" className={variant === "intro" ? "logo-fade" : undefined} />
      <g fill="none" strokeLinecap="round" strokeLinejoin="round">{strokes}</g>
      <g fill={`url(#${g})`} className={variant === "intro" ? "logo-fade" : undefined}>
        <circle cx="24" cy="33" r="2.4" />
        <circle cx="51" cy="36" r="2.6" />
      </g>
      {variant !== "static" && (
        <g mask={`url(#${m})`} aria-hidden="true">
          <rect className="logo-sweep" x="-24" y="0" width="22" height="64" fill={`url(#${s})`} />
        </g>
      )}
    </>
  );
}

interface Props { size?: number; className?: string; title?: string }

/** Static mark (lists, pages, footers). */
export function Logo({ size = 32, className = "", title }: Props) {
  const uid = useId().replace(/:/g, "");
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" className={className} role={title ? "img" : undefined} aria-hidden={title ? undefined : true} aria-label={title}>
      <Mark uid={uid} variant="static" />
    </svg>
  );
}

/** Header mark: a light sweep every ~6 s and a soft glow pulse. On the first load of a session it draws itself once. */
export function AnimatedLogo({ size = 32, className = "", title }: Props) {
  const uid = useId().replace(/:/g, "");
  const [intro] = useState(takeIntro);
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" className={`logo-anim ${className}`} role={title ? "img" : undefined} aria-hidden={title ? undefined : true} aria-label={title}>
      <Mark uid={uid} variant={intro ? "intro" : "animated"} />
    </svg>
  );
}

/** Loading indicator: the mark with a turning gold ring. */
export function LogoSpinner({ size = 40, label = "Loading" }: { size?: number; label?: string }) {
  const uid = useId().replace(/:/g, "");
  return (
    <span role="status" aria-label={label} className="inline-flex items-center justify-center">
      <svg width={size} height={size} viewBox="0 0 64 64" className="logo-spinner">
        <circle cx="32" cy="32" r="30" fill="none" stroke="rgb(var(--accent) / .15)" strokeWidth="2.5" />
        <circle className="logo-ring" cx="32" cy="32" r="30" fill="none" stroke="rgb(var(--accent))" strokeWidth="2.5" strokeLinecap="round" strokeDasharray="40 160" />
        <g transform="translate(9.6 9.6) scale(.7)"><Mark uid={uid} variant="static" /></g>
      </svg>
    </span>
  );
}
