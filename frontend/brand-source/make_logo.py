"""v2.28 logo (owner, 14 Nov 2026: "A original with the effects of C"): the original artwork (logo-source.png, cropped
inside its baked frame, made round) set like the iris of the alien-eye concept - a cyan core glow behind it, a gold
ring and a ring of gold ticks around it, a tilted cyan orbit, stars and a violet nebula on a black tile with a gold
rim. Writes logo.svg (art linked as art.png, made by this script). render_logo_assets.cjs rasterises it; the moving
website version is components/Logo.tsx (same layers, animated in index.css "logo3d-*" / "logox-*")."""
import math
import pathlib
import random

from PIL import Image

HERE = pathlib.Path(__file__).parent

src = Image.open(HERE / "logo-source.png").convert("RGBA")
w, _ = src.size
inset = int(w * 0.035)
src.crop((inset, inset, w - inset, w - inset)).resize((1024, 1024), Image.LANCZOS).save(HERE / "art.png")

C = 256           # centre
R_ART = 168       # radius of the round artwork


def stars(seed: int = 11) -> str:
    r = random.Random(seed)
    out = []
    for _ in range(80):
        x, y = r.uniform(34, 478), r.uniform(34, 478)
        if math.hypot(x - C, y - C) < 228:
            continue
        out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r.choice([0.9, 1.2, 1.6, 2.2])}" fill="#FFF6D8" opacity="{r.uniform(.4, .95):.2f}"/>')
    return "".join(out)


ticks = "".join(
    f'<line x1="{C + 196 * math.cos(a):.1f}" y1="{C + 196 * math.sin(a):.1f}" x2="{C + (212 if i % 3 == 0 else 205) * math.cos(a):.1f}" '
    f'y2="{C + (212 if i % 3 == 0 else 205) * math.sin(a):.1f}" stroke="#F7C948" stroke-width="{3 if i % 3 == 0 else 2}" stroke-linecap="round"/>'
    for i, a in enumerate([k * math.pi / 30 for k in range(60)]))

SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 512 512">
<defs>
  <linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FFF4C2"/><stop offset=".35" stop-color="#F7C948"/><stop offset=".72" stop-color="#D99A14"/><stop offset="1" stop-color="#8A5A00"/></linearGradient>
  <linearGradient id="rim" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FFE7A3"/><stop offset=".5" stop-color="#C98A12"/><stop offset="1" stop-color="#FFD66B"/></linearGradient>
  <radialGradient id="bg" cx=".5" cy=".45" r=".78"><stop offset="0" stop-color="#211B3D"/><stop offset=".55" stop-color="#0D0B14"/><stop offset="1" stop-color="#050408"/></radialGradient>
  <radialGradient id="neb" cx=".8" cy=".14" r=".6"><stop offset="0" stop-color="#8F7CFF" stop-opacity=".34"/><stop offset="1" stop-color="#8F7CFF" stop-opacity="0"/></radialGradient>
  <radialGradient id="neb2" cx=".12" cy=".9" r=".55"><stop offset="0" stop-color="#2FE6D0" stop-opacity=".18"/><stop offset="1" stop-color="#2FE6D0" stop-opacity="0"/></radialGradient>
  <radialGradient id="core" cx=".5" cy=".5" r=".5"><stop offset=".55" stop-color="#5CF2DF" stop-opacity=".55"/><stop offset=".78" stop-color="#7B6CFF" stop-opacity=".28"/><stop offset="1" stop-color="#7B6CFF" stop-opacity="0"/></radialGradient>
  <filter id="gs" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <filter id="gl" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <clipPath id="tc"><rect x="16" y="16" width="480" height="480" rx="104"/></clipPath>
  <clipPath id="art"><circle cx="{C}" cy="{C}" r="{R_ART}"/></clipPath>
</defs>
<g clip-path="url(#tc)">
  <rect x="16" y="16" width="480" height="480" fill="url(#bg)"/>
  <rect x="16" y="16" width="480" height="480" fill="url(#neb)"/>
  <rect x="16" y="16" width="480" height="480" fill="url(#neb2)"/>
  {stars()}
  <circle cx="{C}" cy="{C}" r="232" fill="url(#core)"/>
  <path d="M30 318 A236 78 -22 0 1 482 194" fill="none" stroke="#5CF2DF" stroke-opacity=".35" stroke-width="3"/>
  <g>{ticks}</g>
  <circle cx="{C}" cy="{C}" r="186" fill="none" stroke="#5CF2DF" stroke-opacity=".55" stroke-width="2" stroke-dasharray="3 7"/>
  <image href="art.png" xlink:href="art.png" x="{C - R_ART - 18}" y="{C - R_ART - 18}" width="{2 * (R_ART + 18)}" height="{2 * (R_ART + 18)}" clip-path="url(#art)"/>
  <circle cx="{C}" cy="{C}" r="{R_ART}" fill="none" stroke="url(#g)" stroke-width="9" filter="url(#gs)"/>
  <path d="M482 194 A236 78 -22 0 1 30 318" fill="none" stroke="#5CF2DF" stroke-opacity=".95" stroke-width="4" filter="url(#gs)"/>
  <circle cx="470" cy="190" r="8" fill="#5CF2DF" filter="url(#gl)"/>
</g>
<rect x="16" y="16" width="480" height="480" rx="104" fill="none" stroke="url(#rim)" stroke-width="7"/>
</svg>"""

(HERE / "logo.svg").write_text(SVG)
print("written logo.svg + art.png")
