"""V3.5 logo (owner, 26 Nov 2026): the owner's chosen design (neural arc, C, rising arrow, "AI", gear) redrawn as clean
vector shapes in the app's gold on graphite, with a 3D bevel (SVG lighting filter), crystal-glass shine and a glass tile.

Writes:  logo-v35.svg (app tile), logo-v35-mark.svg (no tile, transparent) and ../src/data/logoV35.ts (the same parts as
strings for the animated React logo; every id carries the "__P__" prefix, replaced per instance).
Run: python3 frontend/brand-source/make_logo_v35.py   then   node frontend/brand-source/render_logo_assets.cjs
"""
import json, math, pathlib
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

HERE = pathlib.Path(__file__).resolve().parent
FONT = HERE.parent.parent / "backend/app/assets/fonts/Inter-ExtraBold.otf"
INK = "#0F1013"
GOLD = [(0, "#FFF3C4"), (.16, "#F6D77A"), (.36, "#E8B637"), (.5, "#FBE6A2"), (.64, "#E2AA2E"), (.84, "#B8861E"), (1, "#E8B637")]
CONTENT = "translate(512 518) scale(1.02) translate(-646 -603)"     # design units -> 1024 tile
NEURAL_C, GEAR_C, C_C = (575, 610), (845, 478), (628, 606)


def text_path(txt, x, base, size, track=0):
    f = TTFont(str(FONT)); gs = f.getGlyphSet(); cm = f.getBestCmap(); s = size / f["head"].unitsPerEm
    out, cx = [], x
    for ch in txt:
        pen = SVGPathPen(gs); g = cm[ord(ch)]
        gs[g].draw(TransformPen(pen, (s, 0, 0, -s, cx, base))); out.append(pen.getCommands()); cx += gs[g].width * s + track
    return " ".join(out)


def P(c, r, a): return (c[0] + r * math.cos(math.radians(a)), c[1] - r * math.sin(math.radians(a)))


def arc(c, r, a0, a1):
    (x0, y0), (x1, y1) = P(c, r, a0), P(c, r, a1); span = (a1 - a0) % 360
    return f"M{x0:.1f} {y0:.1f} A{r} {r} 0 {1 if span > 180 else 0} 0 {x1:.1f} {y1:.1f}"


def poly(pts): return "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + " Z"


def defs():
    gs = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in GOLD)
    clip = poly([GEAR_C] + [P(GEAR_C, 400, a) for a in range(-44, 176, 4)])
    return (f'<linearGradient id="__P__gold" gradientUnits="userSpaceOnUse" x1="280" y1="260" x2="960" y2="940">{gs}</linearGradient>'
            '<radialGradient id="__P__tile" cx="50%" cy="34%" r="78%"><stop offset="0" stop-color="#23242A"/><stop offset=".6" stop-color="#15161A"/><stop offset="1" stop-color="#0B0C0E"/></radialGradient>'
            '<linearGradient id="__P__rim" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFF0B8" stop-opacity=".95"/><stop offset=".45" stop-color="#E8B637" stop-opacity=".18"/><stop offset="1" stop-color="#B8861E" stop-opacity=".55"/></linearGradient>'
            '<linearGradient id="__P__gloss" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".07"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>'
            '<linearGradient id="__P__tglass" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".10"/><stop offset=".42" stop-color="#fff" stop-opacity=".035"/><stop offset=".43" stop-color="#fff" stop-opacity="0"/></linearGradient>'
            '<linearGradient id="__P__shine" gradientUnits="userSpaceOnUse" x1="0" y1="270" x2="0" y2="700"><stop offset="0" stop-color="#fff" stop-opacity=".55"/><stop offset=".45" stop-color="#fff" stop-opacity=".12"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/></linearGradient>'
            '<linearGradient id="__P__streak" gradientUnits="userSpaceOnUse" x1="300" y1="250" x2="950" y2="900"><stop offset=".33" stop-color="#fff" stop-opacity="0"/><stop offset=".40" stop-color="#fff" stop-opacity=".55"/><stop offset=".44" stop-color="#fff" stop-opacity="0"/><stop offset=".62" stop-color="#fff" stop-opacity="0"/><stop offset=".65" stop-color="#fff" stop-opacity=".3"/><stop offset=".68" stop-color="#fff" stop-opacity="0"/></linearGradient>'
            '<filter id="__P__metal" x="-15%" y="-15%" width="130%" height="130%" color-interpolation-filters="sRGB">'
            '<feGaussianBlur in="SourceAlpha" stdDeviation="5" result="b"/>'
            '<feSpecularLighting in="b" surfaceScale="7" specularConstant="1.5" specularExponent="38" lighting-color="#FFFBEA" result="sp"><feDistantLight azimuth="225" elevation="48"/></feSpecularLighting>'
            '<feComposite in="sp" in2="SourceAlpha" operator="in" result="spi"/>'
            '<feDiffuseLighting in="b" surfaceScale="6" diffuseConstant="1.18" lighting-color="#ffffff" result="df"><feDistantLight azimuth="225" elevation="58"/></feDiffuseLighting>'
            '<feComposite in="SourceGraphic" in2="df" operator="arithmetic" k1="1" result="sh"/>'
            '<feSpecularLighting in="b" surfaceScale="9" specularConstant=".9" specularExponent="70" lighting-color="#ffffff" result="sp2"><feDistantLight azimuth="240" elevation="62"/></feSpecularLighting>'
            '<feComposite in="sp2" in2="SourceAlpha" operator="in" result="sp2i"/>'
            '<feComposite in="spi" in2="sh" operator="arithmetic" k2=".85" k3="1" result="lit0"/>'
            '<feComposite in="sp2i" in2="lit0" operator="arithmetic" k2=".5" k3="1" result="lit"/>'
            '<feComposite in="lit" in2="SourceAlpha" operator="in" result="body"/>'
            '<feGaussianBlur in="SourceAlpha" stdDeviation="9" result="sb"/><feOffset in="sb" dx="0" dy="12" result="so"/>'
            '<feFlood flood-color="#000" flood-opacity=".7"/><feComposite in2="so" operator="in" result="shadow"/>'
            '<feMerge><feMergeNode in="shadow"/><feMergeNode in="body"/></feMerge></filter>'
            '<filter id="__P__tileShadow" x="-10%" y="-10%" width="120%" height="125%"><feDropShadow dx="0" dy="18" stdDeviation="22" flood-color="#000" flood-opacity=".55"/></filter>'
            f'<clipPath id="__P__gearClip"><path d="{clip}"/></clipPath>')


def tile():
    return ('<rect x="40" y="40" width="944" height="944" rx="212" fill="url(#__P__tile)" filter="url(#__P__tileShadow)"/>'
            '<rect x="40" y="40" width="944" height="472" rx="212" fill="url(#__P__gloss)"/>'
            '<rect x="40" y="40" width="944" height="944" rx="212" fill="url(#__P__tglass)"/>'
            '<rect x="43.5" y="43.5" width="937" height="937" rx="209" fill="none" stroke="url(#__P__rim)" stroke-width="7"/>'
            '<rect x="52" y="52" width="920" height="920" rx="200" fill="none" stroke="#fff" stroke-opacity=".06" stroke-width="2"/>')


G = "url(#__P__gold)"


def shapes():
    """Each part's gold shapes (no filter). The keys are the five moving parts."""
    R = 305
    neural = [f'<path d="{arc(NEURAL_C, R, 74, 286)}" fill="none" stroke="{G}" stroke-width="13" stroke-linecap="round"/>']
    outs = [P(NEURAL_C, R, a) for a in (100, 131, 162, 193, 224, 255, 282)]
    ins = []
    for a in (115, 146, 177, 208, 239, 268):
        r = 238
        while math.hypot(P(NEURAL_C, r, a)[0] - C_C[0], P(NEURAL_C, r, a)[1] - C_C[1]) < 268: r += 2
        ins.append(P(NEURAL_C, r, a))
    for i, (x, y) in enumerate(ins):
        for (a, b) in (outs[i], outs[i + 1]):
            neural.append(f'<line x1="{a:.1f}" y1="{b:.1f}" x2="{x:.1f}" y2="{y:.1f}" stroke="{G}" stroke-width="10" stroke-linecap="round"/>')
        if i:
            neural.append(f'<line x1="{ins[i-1][0]:.1f}" y1="{ins[i-1][1]:.1f}" x2="{x:.1f}" y2="{y:.1f}" stroke="{G}" stroke-width="8" stroke-linecap="round"/>')
    neural += [f'<circle cx="{x:.1f}" cy="{y:.1f}" r="25" fill="{G}"/>' for x, y in outs]
    neural += [f'<circle cx="{x:.1f}" cy="{y:.1f}" r="19" fill="{G}"/>' for x, y in ins]
    r_in, r_root, r_tip, n = 106, 150, 186, 12
    pts = []
    for i in range(n):
        a = i * 360 / n
        for da, r in ((-15, r_root), (-9.5, r_tip), (9.5, r_tip), (15, r_root)): pts.append(P(GEAR_C, r, a + da))
    (h0x, h0y), (h1x, h1y) = P(GEAR_C, r_in, 0), P(GEAR_C, r_in, 180)
    gear = [f'<path d="{poly(pts)} M{h0x:.1f} {h0y:.1f} A{r_in} {r_in} 0 1 1 {h1x:.1f} {h1y:.1f} A{r_in} {r_in} 0 1 1 {h0x:.1f} {h0y:.1f} Z" fill="{G}" fill-rule="evenodd"/>']
    cpath = arc(C_C, 182, 37, -36)
    c = [f'<path d="{cpath}" fill="none" stroke="{G}" stroke-width="90" stroke-linecap="butt"/>']
    c_cut = f'<path d="{cpath}" fill="none" stroke="{INK}" stroke-width="120" stroke-linecap="butt"/>'
    line = [(546, 678), (652, 572), (702, 628), (846, 484)]
    ux, uy = 846 - 702, 484 - 628; L = math.hypot(ux, uy); ux, uy = ux / L, uy / L; px, py = -uy, ux
    head = poly([(846 + px * 54, 484 + py * 54), (846 + ux * 70, 484 + uy * 70), (846 - px * 54, 484 - py * 54)])
    lp = "M" + " L".join(f"{x} {y}" for x, y in line)
    arrow = [f'<path d="{lp}" fill="none" stroke="{G}" stroke-width="42" stroke-linejoin="miter" stroke-linecap="butt" class="lg5-line"/>',
             f'<path d="{head}" fill="{G}" class="lg5-head"/>']
    arrow_cut = (f'<path d="{lp}" fill="none" stroke="{INK}" stroke-width="72" stroke-linejoin="miter" stroke-linecap="butt" class="lg5-line"/>'
                 f'<path d="{head}" fill="{INK}" stroke="{INK}" stroke-width="30" stroke-linejoin="round" class="lg5-head"/>')
    ai = [f'<path d="{text_path("AI", 780, 694, 134, 6)}" fill="{G}"/>']
    return {"neural": "".join(neural), "gear": "".join(gear), "c": "".join(c), "arrow": "".join(arrow), "ai": "".join(ai),
            "c_cut": c_cut, "arrow_cut": arrow_cut}


def lit(markup):
    """A part with the 3D metal filter and its two glass shine passes."""
    gloss = "".join(f'<g opacity="{op}">' + markup.replace(G, f"url(#__P__{f})") + "</g>" for f, op in (("shine", ".42"), ("streak", ".7")))
    return f'<g filter="url(#__P__metal)">{markup}</g>{gloss}'


def static_svg(with_tile=True, pfx="l"):
    s = shapes()
    body = (f'<g clip-path="url(#__P__gearClip)">{lit(s["gear"])}</g>' + lit(s["neural"]) + s["c_cut"] + lit(s["c"]) +
            s["arrow_cut"] + lit(s["arrow"]) + lit(s["ai"]))
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024"><defs>{defs()}</defs>'
           + (tile() if with_tile else "") + f'<g transform="{CONTENT}">{body}</g></svg>')
    return svg.replace("__P__", pfx)


if __name__ == "__main__":
    (HERE / "logo-v35.svg").write_text(static_svg(True))
    (HERE / "logo-v35-mark.svg").write_text(static_svg(False))
    s = shapes()
    data = {"defs": defs(), "tile": tile(), "content": CONTENT, "centres": {"neural": NEURAL_C, "gear": GEAR_C, "c": C_C},
            "parts": {k: (lit(v) if k in ("neural", "gear", "c", "arrow", "ai") else v) for k, v in s.items()}}
    out = HERE.parent / "src" / "data" / "logoV35.ts"
    out.write_text("// Generated by brand-source/make_logo_v35.py - do not edit by hand.\n"
                   f"export const LOGO_V35 = {json.dumps(data)} as const;\n")
    print("wrote logo-v35.svg, logo-v35-mark.svg,", out.name)
