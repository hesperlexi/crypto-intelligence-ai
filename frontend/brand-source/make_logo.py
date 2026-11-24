"""V3.0 logo (24 Nov 2026, owner pick "B + D"): the original artwork on a soft-black tile, gold neurons + cyan links,
cyan dashed ring, gold rim - no space. Was: v2.28 logo (owner, 14 Nov 2026: "A original with the effects of C"): the original artwork (logo-source.png, cropped
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


def mesh(seed: int = 13) -> str:
    """V3.0 (owner, 24 Nov 2026: B + D): gold neurons joined by cyan links around the medallion - no stars, no space."""
    r = random.Random(seed)
    pts = []
    while len(pts) < 46:
        a, R = r.uniform(0, 2 * math.pi), r.uniform(185, 265)
        pts.append((C + math.cos(a) * R, C + math.sin(a) * R))
    lines = "".join(f'<line x1="{p[0]:.0f}" y1="{p[1]:.0f}" x2="{q[0]:.0f}" y2="{q[1]:.0f}"/>'
                    for i, p in enumerate(pts) for j, q in enumerate(pts) if j > i and math.hypot(p[0] - q[0], p[1] - q[1]) < 80)
    # owner 24 Nov 2026: neurons green / red (the live logo blinks them), links cyan
    dots = "".join(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="3.6" fill="{"#F6465D" if i % 2 else "#22D39A"}"/>' for i, (x, y) in enumerate(pts))
    return (f'<g stroke="#5DF1DD" stroke-opacity=".45" stroke-width="1.6">{lines}</g>'
            f'<g>{dots}</g>')


SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 512 512">
<defs>
  <linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#F6E37A"/><stop offset=".5" stop-color="#9C7417"/><stop offset="1" stop-color="#E8B637"/></linearGradient>
  <linearGradient id="rim" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#F6E37A"/><stop offset=".5" stop-color="#9C7417"/><stop offset="1" stop-color="#E8B637"/></linearGradient>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1A1B21"/><stop offset="1" stop-color="#0E0F12"/></linearGradient>
  <radialGradient id="glow" cx=".5" cy=".5" r=".5"><stop offset=".55" stop-color="#E8B637" stop-opacity=".28"/><stop offset="1" stop-color="#E8B637" stop-opacity="0"/></radialGradient>
  <linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity=".10"/><stop offset=".45" stop-color="#FFFFFF" stop-opacity="0"/></linearGradient>
  <clipPath id="tc"><rect x="16" y="16" width="480" height="480" rx="104"/></clipPath>
  <clipPath id="art"><circle cx="{C}" cy="{C}" r="{R_ART}"/></clipPath>
</defs>
<g clip-path="url(#tc)">
  <rect x="16" y="16" width="480" height="480" fill="url(#bg)"/>
  {mesh()}
  <circle cx="{C}" cy="{C}" r="205" fill="url(#glow)"/>
  <circle cx="{C}" cy="{C}" r="190" fill="none" stroke="#5DF1DD" stroke-opacity=".5" stroke-width="2" stroke-dasharray="2 9"/>
  <image href="art.png" xlink:href="art.png" x="{C - R_ART - 18}" y="{C - R_ART - 18}" width="{2 * (R_ART + 18)}" height="{2 * (R_ART + 18)}" clip-path="url(#art)"/>
  <circle cx="{C}" cy="{C}" r="{R_ART + 1}" fill="none" stroke="url(#g)" stroke-width="7"/>
  <rect x="16" y="16" width="480" height="480" fill="url(#sheen)"/>
</g>
<rect x="17.5" y="17.5" width="477" height="477" rx="103" fill="none" stroke="url(#rim)" stroke-width="3" stroke-opacity=".75"/>
</svg>"""

(HERE / "logo.svg").write_text(SVG)
print("written logo.svg + art.png")
