"""Builds frontend/public/manual.pdf from docs/manual/manual.md in the app's gold / black theme.

    python scripts/build_manual.py [version]

Needs: pip install markdown playwright (Chromium) and the Inter font for the best look.
"""
import base64
import datetime as dt
import pathlib
import sys

import re

import markdown
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "manual" / "manual.md"
OUT = ROOT / "frontend" / "public" / "manual.pdf"
LOGO = ROOT / "frontend" / "public" / "icons" / "icon-512.png"
VERSION = sys.argv[1] if len(sys.argv) > 1 else "2.0.0"
import os
HEAD_MM = float(os.environ.get("HEAD_MM", "22"))

body = markdown.markdown(SRC.read_text(encoding="utf-8"), extensions=["tables", "sane_lists"])
body = body.replace("<li>☐ ", "<li>")
body = re.sub(r"<ul>(\s*<li><strong>Install the app)", r'<ul class="check">\1', body)
logo = base64.b64encode(LOGO.read_bytes()).decode()
date = dt.date.today().strftime("%B %Y")

# contents list from the H2 headings
import re
toc = "".join(f"<li>{re.sub('<[^>]+>', '', h)}</li>" for h in re.findall(r"<h2>(.*?)</h2>", body))
# the first paragraph is the lead
lead, rest = body.split("</p>", 1)
lead = lead.replace("<p>", "")

CSS = """
@page { size: A4; margin: 21mm 0 20mm; }
@page :first { margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; width: 100%; background: #0b0e11; color: #eaecef; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: Inter, "DejaVu Sans", Arial, sans-serif; font-size: 10.6pt; line-height: 1.58; }
.gold { color: #f0b90b; }

/* cover */
.cover { height: 297mm; position: relative; overflow: hidden; padding: 0 22mm;
  display: flex; flex-direction: column; justify-content: center; page-break-after: always;
  background:
    radial-gradient(120mm 90mm at 85% 22%, rgba(240,185,11,.22), transparent 70%),
    radial-gradient(110mm 80mm at 0% 100%, rgba(240,185,11,.12), transparent 70%),
    linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px) 0 0 / 12mm 12mm,
    linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px) 0 0 / 12mm 12mm,
    #0b0e11; }
.cover .logo { width: 44mm; height: 44mm; border-radius: 10mm; box-shadow: 0 0 0 1px rgba(240,185,11,.45), 0 12mm 30mm rgba(240,185,11,.25); }
.cover .kicker { margin-top: 14mm; font-size: 10pt; letter-spacing: .32em; text-transform: uppercase; color: #f0b90b; font-weight: 600; }
.cover h1 { margin: 4mm 0 0; font-size: 38pt; line-height: 1.05; font-weight: 800; letter-spacing: -.02em; color: #fff; }
.cover h1 span { color: #f0b90b; }
.cover .sub { margin-top: 6mm; max-width: 140mm; font-size: 12.5pt; color: #b7bdc6; }
.cover .rule { margin-top: 12mm; height: 1.2mm; width: 40mm; border-radius: 1mm; background: linear-gradient(90deg, #fcd535, #f0b90b, transparent); }
.cover .meta { position: absolute; left: 22mm; right: 22mm; bottom: 26mm; display: flex; justify-content: space-between;
  font-size: 9pt; color: #848e9c; border-top: 1px solid rgba(240,185,11,.25); padding-top: 4mm; }

/* contents */
.toc { padding: 6mm 22mm 0; page-break-after: always; }
.toc h2 { margin-top: 0; }
.toc ol { list-style: none; padding: 0; margin: 8mm 0 0; columns: 1; }
.toc li { counter-increment: t; padding: 2.6mm 4mm; margin-bottom: 1.8mm; border-radius: 3mm;
  background: linear-gradient(180deg, rgba(255,255,255,.05), rgba(255,255,255,.015)); border: 1px solid rgba(255,255,255,.07);
  font-size: 11pt; color: #eaecef; }
.lead { margin: 4mm 0 2mm; break-inside: avoid; padding: 5mm 6mm; border-radius: 3mm; border: 1px solid rgba(240,185,11,.35);
  background: rgba(240,185,11,.07); color: #eaecef; font-size: 11pt; }

/* content */
.content { padding: 0 20mm; }
h2 { font-size: 17pt; font-weight: 750; color: #fff; margin: 0 0 4mm; padding: 9mm 0 3mm; letter-spacing: -.01em;
  border-bottom: 1px solid rgba(240,185,11,.35); break-after: avoid; }
h2::first-letter { color: #f0b90b; }
/* chapters flow on; a heading always stays with its first lines, nothing is cut in half across a page break */
.section { padding-top: 0; break-inside: auto; }
.section + .section h2 { margin-top: 7mm; }
h2 { padding-top: 0; break-after: avoid; page-break-after: avoid; }
h2 + * { break-before: avoid; }
h3 { font-size: 12.5pt; color: #fff; margin: 5mm 0 2mm; break-after: avoid; }
p, li, blockquote, .check li, tr { break-inside: avoid; }
p { orphans: 3; widows: 3; }
table { break-inside: avoid; }
p:has(+ ul), p:has(+ ol), p:has(+ table) { break-after: avoid; }
.content ul li:has(> :first-child) {}
.check { list-style: none; padding-left: 0; }
.check li { padding: 2mm 3mm 2mm 9mm; position: relative; border-radius: 2.5mm; background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.06); }
.check li::before { content: ''; position: absolute; left: 3mm; top: 2.9mm; width: 3.2mm; height: 3.2mm; border-radius: .8mm; border: 1.4px solid #f0b90b; }
p { margin: 0 0 3mm; color: #d5d9de; }
strong { color: #fff; font-weight: 650; }
em { color: #fcd535; font-style: normal; }
ul, ol { margin: 0 0 4mm; padding-left: 6mm; }
li { margin: 0 0 1.8mm; color: #d5d9de; }
li::marker { color: #f0b90b; font-weight: 700; }
blockquote { margin: 4mm 0; padding: 4mm 5mm; border-radius: 3mm; border: 1px solid rgba(240,185,11,.4);
  background: linear-gradient(135deg, rgba(240,185,11,.13), rgba(240,185,11,.04)); break-inside: avoid; }
blockquote p { margin: 0; color: #eaecef; }
table { width: 100%; border-collapse: separate; border-spacing: 0; margin: 2mm 0 5mm; font-size: 9.2pt;
  border: 1px solid rgba(255,255,255,.09); border-radius: 3mm; overflow: hidden; break-inside: auto; }
th { text-align: left; background: rgba(240,185,11,.16); color: #f0b90b; font-weight: 650; padding: 2.4mm 3mm; }
td { padding: 2.4mm 3mm; border-top: 1px solid rgba(255,255,255,.07); vertical-align: top; color: #d5d9de; }
tr { break-inside: avoid; }
tr:nth-child(even) td { background: rgba(255,255,255,.025); }
"""

html = f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<section class="cover">
  <img class="logo" src="data:image/png;base64,{logo}">
  <div class="kicker">User manual</div>
  <h1>Crypto Intelligence <span>AI</span></h1>
  <div class="sub">How to get the most out of the predictions, futures signals, alerts, paper trading and demo bots — step by step.</div>
  <div class="rule"></div>
  <div class="meta"><span>Version {VERSION} · {date}</span><span>© 2026 Hesper. All rights reserved.</span></div>
</section>
<section class="toc">
  <div class="lead">{lead}</div>
  <h2>Contents</h2>
  <ol>{toc}</ol>
</section>
<main class="content">{"".join(f'<div class="section"><h2>{part}' for part in rest.split('<h2>')[1:])}</main>
</body></html>"""
# close each section div at the start of the next: simplest is to wrap via split above and close here
html = html.replace('<div class="section">', '</div><div class="section">').replace('<main class="content"></div>', '<main class="content">').replace("</main>", "</div></main>")

BAR = "-webkit-print-color-adjust:exact;print-color-adjust:exact;background:#0b0e11;width:100%;margin:0;"
HEAD = f"""<style>html,body{{margin:0;padding:0}}</style><div style="{BAR}height:{HEAD_MM}mm;margin-top:-6mm"></div>"""
FOOT = f"""<style>html,body{{margin:0;padding:0}}</style><div style="{BAR}height:24mm;margin-bottom:-7.5mm;box-sizing:border-box;padding:5mm 20mm 0;
font-family:Inter,Arial,sans-serif;font-size:7.5pt;color:#848e9c;display:flex;justify-content:space-between;align-items:flex-start;">
<span><span style="color:#f0b90b;font-weight:600">Crypto Intelligence AI</span> · User manual</span>
<span>© 2026 Hesper · page <span class="pageNumber"></span> / <span class="totalPages"></span></span></div>"""

tmp = OUT.with_suffix(".html")
tmp.write_text(html, encoding="utf-8")
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.goto(tmp.as_uri())
    pg.emulate_media(media="print")
    pg.pdf(path=str(OUT), format="A4", print_background=True, display_header_footer=True,
           header_template=HEAD, footer_template=FOOT,
           prefer_css_page_size=True)
    b.close()
tmp.unlink()
print("wrote", OUT, OUT.stat().st_size // 1024, "KB")
