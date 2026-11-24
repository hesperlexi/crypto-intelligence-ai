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

/** Header logo: the live logo (blinking neurons, lightning links) at header size. */
export function AnimatedLogo({ size = 36, className = "", title }: Props) {
  return <LiveLogo size={size} className={className} title={title} />;
}
// keep the 3D tile available for any future still use
void Tile;

/* owner 24 Nov 2026: "cyan links - dots must blink like red and green - and lines connecting them must be like
   lightning". The neuron map is the one baked into the tile (brand-source/make_logo.py mesh(seed 13)): p = points,
   l = links. Each link gets a jagged bolt that flashes now and then; each neuron blinks green or red. */
const MESH: { p: [number, number][]; l: [number, number][] } = {"p":[[242,495],[154,24],[336,443],[378,418],[236,62],[58,216],[195,467],[378,57],[462,275],[410,459],[347,24],[369,39],[492,178],[245,509],[11,276],[54,170],[112,421],[180,435],[361,31],[495,234],[25,174],[414,435],[69,325],[323,473],[251,478],[85,123],[409,420],[275,459],[329,457],[468,361],[463,194],[206,1],[445,309],[343,19],[129,104],[38,388],[444,93],[330,498],[85,428],[427,455],[63,109],[312,484],[53,143],[102,444],[143,431],[379,462]],"l":[[0,6],[0,13],[0,24],[0,27],[0,41],[1,31],[2,3],[2,9],[2,21],[2,23],[2,26],[2,27],[2,28],[2,37],[2,41],[2,45],[3,9],[3,21],[3,23],[3,26],[3,28],[3,39],[3,45],[4,31],[5,14],[5,15],[5,20],[5,42],[6,13],[6,17],[6,24],[6,44],[7,10],[7,11],[7,18],[7,33],[7,36],[8,19],[8,32],[9,21],[9,26],[9,39],[9,45],[10,11],[10,18],[10,33],[11,18],[11,33],[12,19],[12,30],[13,24],[13,27],[13,41],[14,22],[15,20],[15,25],[15,40],[15,42],[16,17],[16,38],[16,43],[16,44],[17,43],[17,44],[18,33],[19,30],[20,25],[20,40],[20,42],[21,26],[21,39],[21,45],[22,35],[23,24],[23,27],[23,28],[23,37],[23,41],[23,45],[24,27],[24,41],[25,34],[25,40],[25,42],[26,39],[26,45],[27,28],[27,37],[27,41],[28,37],[28,41],[28,45],[29,32],[34,40],[35,38],[37,41],[37,45],[38,43],[38,44],[39,45],[40,42],[41,45],[43,44]]};
const jit = (i: number) => (((i * 9301 + 49297) % 233280) / 233280) - 0.5;
const BOLTS = MESH.l.map(([a, b], i) => {
  const [x1, y1] = MESH.p[a], [x2, y2] = MESH.p[b];
  const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1, nx = -dy / len, ny = dx / len;
  const pt = (t: number, k: number) => `${(x1 + dx * t + nx * k).toFixed(1)} ${(y1 + dy * t + ny * k).toFixed(1)}`;
  const amp = Math.min(9, len * 0.16);
  return { d: `M${x1} ${y1}L${pt(0.3, amp * (0.6 + jit(i)))}L${pt(0.55, -amp * (0.7 + jit(i + 7)))}L${pt(0.78, amp * 0.5)}L${x2} ${y2}`,
    delay: ((i * 0.37) % 4.2).toFixed(2), dur: (2.6 + ((i * 0.53) % 2.4)).toFixed(2) };
});

/** Hero logo (landing, sign-in, access and loading screens): the v2.28 live logo - the original artwork as the core of
 *  the V3.0 tile with a gold pulse and the turning cyan ring. */
export function HeroLogo({ size = 96, className = "", title }: Props) {
  return <LiveLogo size={size} className={className} title={title} />;
}

/** V3.0 (owner, 24 Nov 2026: logo "B + D", no space): the still tile (brand-source/logo.svg rendered to
 *  /brand/logo-384.webp) with two quiet live layers - a soft gold pulse behind the medallion and the cyan dashed ring
 *  turning slowly. Transform / opacity only; still under prefers-reduced-motion. */
export function LiveLogo({ size = 96, className = "", title }: Props) {
  const id = "lx";
  return (
    <span className={`logox ${className}`} style={{ width: size, height: size }} role={title ? "img" : undefined} aria-label={title} aria-hidden={title ? undefined : true}>
      <svg viewBox="0 0 512 512" width={size} height={size}>
        <defs>
          <radialGradient id={`${id}glow`} cx=".5" cy=".5" r=".5"><stop offset=".6" stopColor="#E8B637" stopOpacity=".35" /><stop offset="1" stopColor="#E8B637" stopOpacity="0" /></radialGradient>
          <clipPath id={`${id}tc`}><rect x="16" y="16" width="480" height="480" rx="104" /></clipPath>
        </defs>
        <image href="/brand/logo-384.webp" x="0" y="0" width="512" height="512" />
        <g clipPath={`url(#${id}tc)`}>
          <circle cx="256" cy="256" r="214" fill={`url(#${id}glow)`} className="logox-pulse" style={{ mixBlendMode: "screen" }} />
          <circle cx="256" cy="256" r="190" fill="none" stroke="#5DF1DD" strokeOpacity=".55" strokeWidth="2.5" strokeDasharray="2 9" className="logox-spinr" />
          <g fill="none" stroke="#9FFFF2" strokeWidth="2.2" strokeLinejoin="miter" style={{ filter: "drop-shadow(0 0 4px #5DF1DD)" }}>
            {BOLTS.map((b, i) => <path key={i} d={b.d} className="logox-bolt" style={{ animationDelay: `${b.delay}s`, animationDuration: `${b.dur}s` }} />)}
          </g>
          <g>
            {MESH.p.map(([x, y], i) => <circle key={i} cx={x} cy={y} r="4.2" className={i % 2 ? "logox-red" : "logox-green"}
              style={{ animationDelay: `${((i * 0.29) % 1.8).toFixed(2)}s` }} />)}
          </g>
        </g>
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
        <defs><linearGradient id="logo-ring-g" x1="0" x2="1"><stop offset="0" stopColor="#F6E37A" /><stop offset="1" stopColor="#E8B637" /></linearGradient></defs>
      </svg>
      <LiveLogo size={inner} />
    </span>
  );
}
