// Rasterises the v2.28 logo (brand-source/logo.svg + art.png, from make_logo.py) into every place the app uses a
// logo image: public/brand/logo-{96,192,384}.png, public/icons/*, public/favicon.png, public/brand/og-image.png and
// backend/app/assets/logo.png. WebP copies are made afterwards with Pillow (see the commit / CLAUDE.md).
// Run: node frontend/brand-source/render_logo_assets.cjs   (needs Playwright's Chromium)
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const SRC = __dirname;
const PUB = path.join(SRC, "..", "public");
const art = "data:image/png;base64," + fs.readFileSync(path.join(SRC, "art.png")).toString("base64");
const full = fs.readFileSync(path.join(SRC, "logo.svg"), "utf8").replace(/href="art.png"/g, `href="${art}"`);
const icon = full;
const uri = (s) => `data:image/svg+xml;base64,${Buffer.from(s).toString("base64")}`;
// a square, full-bleed version (no rounded corners, no rim) for maskable / Apple icons: the tile background fills it
const bleed = (s, scale) => s
  .replace(/<rect x="16" y="16" width="480" height="480" fill="url\(#sheen\)"\/>/, "")
  .replace('<clipPath id="tc"><rect x="16" y="16" width="480" height="480" rx="104"/></clipPath>', '<clipPath id="tc"><rect x="-400" y="-400" width="1312" height="1312"/></clipPath>')
  .replace(/<rect x="16" y="16" width="480" height="480" fill="url\(#(bg|sheen)\)"\/>/g, '<rect x="-400" y="-400" width="1312" height="1312" fill="#141519"/>')
  .replace('<g clip-path="url(#tc)">', `<rect width="512" height="512" fill="#141519"/><g transform="translate(256 256) scale(${scale}) translate(-256 -256)"><g clip-path="url(#tc)">`)
  .replace(/<rect x="17.5" y="17.5" width="477" height="477" rx="103" fill="none"[^>]*\/>/, "</g>");

const jobs = [
  [full, 384, "brand/logo-384.png"], [full, 192, "brand/logo-192.png"], [icon, 96, "brand/logo-96.png"],
  [full, 512, "icons/icon-512.png"], [full, 192, "icons/icon-192.png"],
  [bleed(full, 1.0), 180, "icons/apple-touch-icon.png"],
  [bleed(full, 0.8), 512, "icons/maskable-512.png"], [bleed(full, 0.8), 192, "icons/maskable-192.png"],
  [icon, 48, "favicon.png"],
  [full, 256, "../../backend/app/assets/logo.png"],
];

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1200, height: 630 } });
  for (const [svg, size, out] of jobs) {
    await p.setViewportSize({ width: size, height: size });
    await p.setContent(`<html><body style="margin:0;background:transparent"><img src="${uri(svg)}" width="${size}" height="${size}" style="display:block"></body></html>`);
    await p.waitForTimeout(150);
    await p.screenshot({ path: path.join(PUB, out), omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } });
    console.log("wrote", out);
  }
  // social preview card
  await p.setViewportSize({ width: 1200, height: 630 });
  await p.setContent(`<html><body style="margin:0;width:1200px;height:630px;display:flex;align-items:center;gap:56px;padding:0 90px;box-sizing:border-box;
    background:radial-gradient(70% 90% at 78% 10%,#2a2416 0%,#141519 55%,#0e0f12 100%);font-family:Arial,Helvetica,sans-serif;color:#f6ecd0">
    <img src="${uri(full)}" width="380" height="380" style="filter:drop-shadow(0 0 40px rgba(232,182,55,.3))">
    <div><div style="font-size:66px;font-weight:800;line-height:1.05">Crypto Intelligence <span style="color:#E8B637">AI</span></div>
    <div style="margin-top:22px;font-size:30px;color:#c9bfa6">AI trade plans for spot and futures</div>
    <div style="margin-top:34px;font-size:26px;color:#5CF2DF">cryptointelai.com</div></div></body></html>`);
  await p.waitForTimeout(300);
  await p.screenshot({ path: path.join(PUB, "brand/og-image.png") });
  console.log("wrote brand/og-image.png");
  await b.close();
})();
