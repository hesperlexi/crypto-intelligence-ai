// V3.5: rasterises logo-v35.svg / logo-v35-mark.svg (make_logo_v35.py) into every logo image the app, the Android app,
// the Telegram cards and the manual use. WebP copies are made by make_webp_v35.py afterwards.
// Run: node frontend/brand-source/render_logo_v35.cjs   (Playwright's Chromium)
const { chromium } = require("playwright");
const fs = require("fs"), path = require("path");
const SRC = __dirname, PUB = path.join(SRC, "..", "public");
const tile = fs.readFileSync(path.join(SRC, "logo-v35.svg"), "utf8");
const mark = fs.readFileSync(path.join(SRC, "logo-v35-mark.svg"), "utf8");
const uri = (s) => `data:image/svg+xml;base64,${Buffer.from(s).toString("base64")}`;
const BG = "radial-gradient(70% 70% at 50% 34%,#23242A 0%,#15161A 60%,#0B0C0E 100%)";
// html for one job: tile image, or the mark on a full-bleed square / a round disc
const page = (kind, size, scale = 1) => kind === "tile"
  ? `<img src="${uri(tile)}" width="${size}" height="${size}" style="display:block">`
  : `<div style="width:${size}px;height:${size}px;background:${BG};${kind === "disc" ? "border-radius:50%;" : ""}display:flex;align-items:center;justify-content:center">
       <img src="${uri(mark)}" width="${size * scale}" height="${size * scale}"></div>`;
const jobs = [
  ["tile", 384, "brand/logo-384.png"], ["tile", 192, "brand/logo-192.png"], ["tile", 96, "brand/logo-96.png"],
  ["tile", 512, "icons/icon-512.png"], ["tile", 192, "icons/icon-192.png"], ["tile", 48, "favicon.png"],
  ["bleed", 180, "icons/apple-touch-icon.png", 1.0], ["bleed", 512, "icons/maskable-512.png", 0.84], ["bleed", 192, "icons/maskable-192.png", 0.84],
  ["disc", 384, "brand/logo-art-384.png", 1.06], ["disc", 192, "brand/logo-art-192.png", 1.06],
  ["tile", 256, "../../backend/app/assets/logo.png"], ["disc", 512, "../../backend/app/assets/logo-art.png", 1.06],
];
(async () => {
  const b = await chromium.launch(); const p = await b.newPage();
  for (const [kind, size, out, scale] of jobs) {
    await p.setViewportSize({ width: size, height: size });
    await p.setContent(`<html><body style="margin:0;background:transparent">${page(kind, size, scale)}</body></html>`);
    await p.waitForTimeout(250);
    await p.screenshot({ path: path.join(PUB, out), omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } });
    console.log("wrote", out);
  }
  await p.setViewportSize({ width: 1200, height: 630 });
  await p.setContent(`<html><head><style>@font-face{font-family:P;src:url(data:font/ttf;base64,${fs.readFileSync(path.join(SRC, "../../backend/app/assets/fonts/IBMPlexSans-SemiBold.ttf")).toString("base64")})}</style></head>
    <body style="margin:0;width:1200px;height:630px;display:flex;align-items:center;gap:56px;padding:0 90px;box-sizing:border-box;
    background:radial-gradient(70% 90% at 78% 10%,#2a2416 0%,#141519 55%,#0e0f12 100%);font-family:P,Arial,sans-serif;color:#f6ecd0">
    <img src="${uri(tile)}" width="380" height="380">
    <div><div style="font-size:64px;font-weight:600;line-height:1.05">Crypto Intelligence <span style="color:#E8B637">AI</span></div>
    <div style="margin-top:22px;font-size:30px;color:#c9bfa6">AI trade plans for spot and futures</div>
    <div style="margin-top:34px;font-size:26px;color:#E8B637">cryptointelai.com</div></div></body></html>`);
  await p.waitForTimeout(400);
  await p.screenshot({ path: path.join(PUB, "brand/og-image.png") });
  console.log("wrote brand/og-image.png");
  await b.close();
})();
