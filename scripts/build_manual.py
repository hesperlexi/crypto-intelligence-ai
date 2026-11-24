"""Builds frontend/public/manual.pdf from docs/manual/manual.md (v3 design, 21 Nov 2026).

    python scripts/build_manual.py [version]     (default: the version in frontend/package.json)

Needs: pip install markdown pypdf playwright (Chromium). Fonts: Sora (backend/app/assets/fonts) for titles, Inter for text.
Two passes: the first PDF tells on which page each section starts, the second prints those page numbers in the
clickable contents. Every "## Title {#id data-kicker="NN" data-line="..."}" heading starts a section on a new page.
The previous manual is kept in docs/manual/legacy/.
"""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import pathlib
import re
import sys

import markdown
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "manual" / "manual.md"
OUT = ROOT / "frontend" / "public" / "manual.pdf"
ART = ROOT / "frontend" / "public" / "brand" / "logo-art-384.webp"
SORA = ROOT / "backend" / "app" / "assets" / "fonts" / "Sora.ttf"


def app_version() -> str:
    try:
        return str(json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))["version"])
    except Exception:
        return "0.0.0"


VERSION = sys.argv[1] if len(sys.argv) > 1 else app_version()
DATE = dt.date.today().strftime("%d %B %Y").lstrip("0")
MANUAL_ED = "Manual 3.1"


def b64(path: pathlib.Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def image_uri(path: pathlib.Path) -> str:
    """Screenshots shrunk to 1600 px wide JPEG (keeps the PDF small enough for phones)."""
    try:
        from PIL import Image
        im = Image.open(path).convert("RGB")
        if im.width > 1600:
            im = im.resize((1600, round(im.height * 1600 / im.width)))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=74, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return "data:image/jpeg;base64," + b64(path)


# ---- markdown -> sections ------------------------------------------------------------------------------------------
md = markdown.Markdown(extensions=["tables", "sane_lists", "attr_list", "md_in_html"])
body = md.convert(SRC.read_text(encoding="utf-8"))


def _img(m: re.Match) -> str:
    alt, src = m.group(1), m.group(2)
    path = SRC.parent / src
    if not path.exists():
        raise SystemExit(f"missing screenshot: {src}")
    phone = pathlib.Path(src).name.startswith("m-")
    return (f'<figure class="shot{" phone" if phone else ""}"><img src="{image_uri(path)}" alt="{alt}">'
            f'<figcaption>{alt}</figcaption></figure>')


body = re.sub(r'<img alt="([^"]*)" src="([^"]+)" ?/?>', _img, body)
body = re.sub(r"<p>\s*(<figure[\s\S]*?</figure>)\s*</p>", r"\1", body)
# a pair with a phone shot: wide + narrow columns
body = re.sub(r'<div class="pair">(\s*<figure class="shot">[\s\S]*?</figure>\s*<figure class="shot phone">)',
              r'<div class="pair wide">\1', body)

H2 = re.compile(r'<h2 ([^>]*)>(.*?)</h2>')
sections, toc = [], []
parts = H2.split(body)
for i in range(1, len(parts), 3):
    attrs, title, content = parts[i], parts[i + 1], parts[i + 2]
    a = dict(re.findall(r'([\w-]+)="([^"]*)"', attrs))
    sid, kicker, line = a.get("id"), a.get("data-kicker", ""), a.get("data-line", "")
    toc.append((sid, kicker, title, line))
    sections.append(f'<section class="sec" id="{sid}"><header class="sec-head"><div class="num">{kicker}</div>'
                    f'<div><h2>{title}</h2><p class="line">{line}</p></div></header>{content}</section>')

art = b64(ART)
sora = b64(SORA)

CSS = r"""
@font-face { font-family: Sora; src: url(data:font/ttf;base64,__SORA__) format("truetype"); font-weight: 100 900; }
@page { size: A4; margin: 18mm 0 18mm; }
@page :first { margin: 0; }
:root { --ink: #0a0d14; --panel: #121826; --panel2: #161e2e; --line: rgba(255,255,255,.085); --gold: #f0b90b; --gold2: #fcd535;
  --text: #e8ecf2; --soft: #c7ced8; --mute: #8e98a8; --blue: #4da3ff; --warn: #f5a524; }
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--ink); color: var(--text); -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: Inter, "DejaVu Sans", Arial, sans-serif; font-size: 11pt; line-height: 1.55; }
h1, h2, h3, .num, .kicker { font-family: Sora, Inter, sans-serif; }
a { color: inherit; text-decoration: none; }
strong { color: #fff; font-weight: 650; }
em { color: var(--gold2); font-style: normal; }
p { margin: 0 0 3mm; color: var(--soft); }
ul, ol { margin: 0 0 4mm; padding-left: 6mm; }
li { margin: 0 0 1.6mm; color: var(--soft); }
li::marker { color: var(--gold); }

/* ---------- cover ---------- */
.cover { height: 297mm; position: relative; overflow: hidden; padding: 0 20mm; page-break-after: always;
  background:
    radial-gradient(140mm 140mm at 78% 30%, rgba(240,185,11,.16), transparent 62%),
    radial-gradient(120mm 90mm at 10% 95%, rgba(77,163,255,.12), transparent 70%),
    var(--ink); }
.cover .orbit { position: absolute; right: -40mm; top: 22mm; width: 190mm; height: 190mm; border-radius: 50%;
  border: 1px solid rgba(240,185,11,.22); }
.cover .orbit.o2 { right: -10mm; top: 52mm; width: 130mm; height: 130mm; border-color: rgba(77,163,255,.2); border-style: dashed; }
.cover .art { position: absolute; right: 18mm; top: 70mm; width: 74mm; height: 74mm; border-radius: 50%;
  box-shadow: 0 0 0 1.5px rgba(240,185,11,.55), 0 0 30mm rgba(240,185,11,.28); }
.cover .top { position: absolute; left: 20mm; top: 20mm; font-size: 9pt; letter-spacing: .3em; text-transform: uppercase; color: var(--gold); font-weight: 600; }
.cover .block { position: absolute; left: 20mm; right: 20mm; top: 150mm; }
.cover h1 { margin: 0; font-size: 40pt; line-height: 1.02; font-weight: 800; letter-spacing: -.02em; color: #fff; }
.cover h1 span { color: var(--gold); }
.cover .tag { margin-top: 6mm; font-size: 14pt; color: var(--soft); max-width: 150mm; line-height: 1.4; }
.cover .chips { margin-top: 10mm; display: flex; gap: 3mm; flex-wrap: wrap; }
.cover .chips span { padding: 2mm 4mm; border-radius: 20mm; border: 1px solid rgba(240,185,11,.4); color: var(--text); font-size: 9.5pt; background: rgba(240,185,11,.06); }
.cover .meta { position: absolute; left: 20mm; right: 20mm; bottom: 20mm; display: flex; justify-content: space-between;
  font-size: 9pt; color: var(--mute); border-top: 1px solid rgba(240,185,11,.25); padding-top: 4mm; }

/* ---------- start page + contents ---------- */
.start { padding: 0 18mm; page-break-after: always; }
.start .kicker { font-size: 9pt; letter-spacing: .28em; text-transform: uppercase; color: var(--gold); font-weight: 600; }
.start h2 { font-size: 22pt; margin: 1mm 0 5mm; color: #fff; letter-spacing: -.01em; }
.quick { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4mm; margin-bottom: 9mm; }
.quick div { border: 1px solid rgba(240,185,11,.35); border-radius: 4mm; padding: 4mm; background: linear-gradient(160deg, rgba(240,185,11,.1), rgba(240,185,11,.02)); }
.quick b { display: block; font-family: Sora, sans-serif; color: var(--gold); font-size: 18pt; line-height: 1; margin-bottom: 2mm; }
.quick p { margin: 0; font-size: 9.8pt; color: var(--text); }
.toc { list-style: none; padding: 0; margin: 0; columns: 2; column-gap: 6mm; }
.toc li { break-inside: avoid; margin: 0 0 2mm; }
.toc a { display: grid; grid-template-columns: 9mm 1fr auto; gap: 2mm; align-items: baseline; padding: 2.2mm 3mm; border-radius: 2.5mm;
  background: var(--panel); border: 1px solid var(--line); }
.toc .n { font-family: Sora, sans-serif; color: var(--gold); font-weight: 700; font-size: 10pt; }
.toc .t { color: #fff; font-weight: 600; font-size: 10.2pt; }
.toc .l { display: block; color: var(--mute); font-size: 8.4pt; font-weight: 400; }
.toc .p { color: var(--mute); font-size: 9pt; }

/* ---------- sections ---------- */
main { padding: 0 18mm; }
.sec { page-break-before: always; }
.sec-head { display: grid; grid-template-columns: 22mm 1fr; gap: 4mm; align-items: center; margin: 0 0 6mm;
  padding: 5mm 5mm 5mm 0; border-bottom: 1px solid rgba(240,185,11,.3); break-after: avoid; }
.sec-head .num { font-size: 30pt; font-weight: 800; line-height: 1; text-align: center;
  background: linear-gradient(135deg, #9c6f0a, #f0b90b 40%, #fff1c4 55%, #e7ae17 75%); -webkit-background-clip: text; color: transparent; }
.sec-head h2 { margin: 0; font-size: 21pt; line-height: 1.1; color: #fff; letter-spacing: -.01em; }
.sec-head .line { margin: 1.5mm 0 0; color: var(--mute); font-size: 10.5pt; }
h3 { font-size: 12.5pt; color: #fff; margin: 5mm 0 2mm; break-after: avoid; }
p, li, figure, .card, .tip, .note, .pro, tr { break-inside: avoid; }
h3 + * { break-before: avoid; }

/* cards */
.cards { display: grid; gap: 3.5mm; margin: 3mm 0 5mm; }
.cards.two { grid-template-columns: 1fr 1fr; }
.cards.three { grid-template-columns: 1fr 1fr 1fr; }
.card { background: linear-gradient(180deg, var(--panel2), var(--panel)); border: 1px solid var(--line); border-radius: 4mm; padding: 4mm 4.5mm;
  position: relative; }
.card::before { content: ""; position: absolute; left: 4.5mm; top: 0; width: 12mm; height: .8mm; border-radius: 0 0 1mm 1mm; background: var(--gold); }
.card h3 { margin: 1mm 0 1.8mm; font-size: 11.5pt; color: var(--gold2); }
.card p { font-size: 9.8pt; margin: 0 0 1.5mm; }
.card ul { padding-left: 4.5mm; margin: 0; }
.card li { font-size: 9.8pt; }

/* numbered steps */
ol.steps { list-style: none; padding: 0; counter-reset: s; margin: 3mm 0 5mm; }
ol.steps > li { counter-increment: s; position: relative; padding: 2.6mm 3mm 2.6mm 13mm; margin: 0 0 2.2mm; border-radius: 3mm;
  background: var(--panel); border: 1px solid var(--line); color: var(--text); }
ol.steps > li::before { content: counter(s); position: absolute; left: 3mm; top: 2.3mm; width: 7mm; height: 7mm; border-radius: 50%;
  background: var(--gold); color: #1a1405; font-family: Sora, sans-serif; font-weight: 800; font-size: 9.5pt; text-align: center; line-height: 7mm; }
ol.steps > li p { margin: 0; color: var(--text); }

/* callouts */
.tip, .note, .pro { border-radius: 3.5mm; padding: 3.5mm 4.5mm; margin: 4mm 0; }
.tip p, .note p, .pro p { margin: 0; color: var(--text); font-size: 10pt; }
.tip { border: 1px solid rgba(240,185,11,.45); background: rgba(240,185,11,.08); }
.note { border: 1px solid rgba(245,165,36,.4); background: rgba(245,165,36,.07); border-left: 1.2mm solid var(--warn); }
.pro { border: 1px solid rgba(77,163,255,.4); background: rgba(77,163,255,.07); border-left: 1.2mm solid var(--blue); }
.pro strong:first-child { color: var(--blue); }

/* glossary + faq */
.glossary ul { list-style: none; padding: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 2mm 4mm; }
.glossary li { background: var(--panel); border: 1px solid var(--line); border-radius: 3mm; padding: 2.4mm 3mm; margin: 0; font-size: 9.8pt; }
.faq p { background: var(--panel); border: 1px solid var(--line); border-radius: 3mm; padding: 2.2mm 3.5mm; margin: 0 0 2mm; font-size: 9.6pt; line-height: 1.45; }
.faq p strong:first-child { display: block; color: var(--gold2); margin-bottom: .8mm; }

/* tables */
table { width: 100%; border-collapse: separate; border-spacing: 0; margin: 2mm 0 4mm; font-size: 10pt; border: 1px solid var(--line); border-radius: 3mm; overflow: hidden; }
th { text-align: left; background: rgba(240,185,11,.14); color: var(--gold); padding: 2.4mm 3.5mm; font-weight: 650; }
td { padding: 2.4mm 3.5mm; border-top: 1px solid var(--line); color: var(--soft); }

/* screenshots */
.shot { margin: 3mm 0 5mm; }
.shot img { display: block; max-width: 100%; max-height: 98mm; margin: 0 auto; border-radius: 3mm; border: 1px solid rgba(240,185,11,.35); box-shadow: 0 4mm 12mm rgba(0,0,0,.45); }
.shot figcaption { margin-top: 1.5mm; font-size: 8.4pt; color: var(--mute); }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 4mm; align-items: start; }
.pair.wide { grid-template-columns: 3fr 1fr; }
.pair .shot { margin: 2mm 0 4mm; }
.shot.phone img { border-radius: 5mm; }
"""

COVER = f"""<section class="cover">
  <div class="orbit"></div><div class="orbit o2"></div>
  <img class="art" src="data:image/webp;base64,{art}" alt="">
  <div class="top">User manual</div>
  <div class="block">
    <h1>Crypto Intelligence <span>AI</span></h1>
    <div class="tag">Your intelligent companion for crypto market insights, trading signals and smarter practice.</div>
    <div class="chips"><span>AI signals on six timeframes</span><span>Alerts on your phone</span><span>Practice with virtual money</span><span>An honest track record</span></div>
  </div>
  <div class="meta"><span>{MANUAL_ED} · app version {VERSION} · {DATE}</span><span>cryptointelai.com</span></div>
</section>"""


def start_page(pages: dict[str, int]) -> str:
    rows = "".join(
        f'<li><a href="#{sid}"><span class="n">{k}</span><span class="t">{t}<span class="l">{l}</span></span>'
        f'<span class="p">{pages.get(sid, "")}</span></a></li>' for sid, k, t, l in toc)
    return f"""<section class="start">
  <div class="kicker">Start here</div>
  <h2>Three steps to your first signal</h2>
  <div class="quick">
    <div><b>1</b><p>Sign in at <strong>cryptointelai.com</strong> and activate your membership.</p></div>
    <div><b>2</b><p>Open <strong>Signals</strong>, pick a timeframe and read your first signal.</p></div>
    <div><b>3</b><p>Press <strong>Practise this trade</strong> to try it with virtual money.</p></div>
  </div>
  <div class="kicker">Contents</div>
  <h2>Find what you need</h2>
  <ol class="toc">{rows}</ol>
</section>"""


def html_doc(pages: dict[str, int]) -> str:
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS.replace("__SORA__", sora)}</style></head><body>'
            f'{COVER}{start_page(pages)}<main>{"".join(sections)}</main></body></html>')


FOOT = """<style>html,body{margin:0;padding:0}</style><div style="-webkit-print-color-adjust:exact;print-color-adjust:exact;background:#0a0d14;
width:100%;height:22mm;margin-bottom:-6mm;box-sizing:border-box;padding:5mm 18mm 0;font-family:Inter,Arial,sans-serif;font-size:7.6pt;
color:#8e98a8;display:flex;justify-content:space-between;"><span><span style="color:#f0b90b;font-weight:600">Crypto Intelligence AI</span>
 · User manual</span><span>Analysis and practice only · not financial advice · page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>"""
HEAD = """<style>html,body{margin:0;padding:0}</style><div style="-webkit-print-color-adjust:exact;print-color-adjust:exact;background:#0a0d14;
width:100%;height:22mm;margin-top:-4mm"></div>"""


def render(html: str, out: pathlib.Path) -> None:
    tmp = out.with_suffix(".tmp.html")
    tmp.write_text(html, encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(tmp.as_uri())
        pg.wait_for_timeout(300)
        pg.emulate_media(media="print")
        pg.pdf(path=str(out), format="A4", print_background=True, display_header_footer=True, header_template=HEAD,
               footer_template=FOOT, prefer_css_page_size=True, tagged=True, outline=True)
        b.close()
    tmp.unlink()


def section_pages(pdf: pathlib.Path) -> dict[str, int]:
    from pypdf import PdfReader
    r = PdfReader(str(pdf))
    texts = [(pg.extract_text() or "") for pg in r.pages]
    found: dict[str, int] = {}
    for sid, k, title, line in toc:
        plain = re.sub("<[^>]+>", "", line)[:30]
        for n, t in enumerate(texts[2:], start=3):
            if plain and plain in t.replace("\n", " "):
                found[sid] = n
                break
    return found


if __name__ == "__main__":
    first = OUT.with_name("manual.pass1.pdf")
    render(html_doc({}), first)
    pages = section_pages(first)
    first.unlink()
    render(html_doc(pages), OUT)
    print("wrote", OUT, OUT.stat().st_size // 1024, "KB; sections", pages)
