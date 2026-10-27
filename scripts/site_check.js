// Opens the live site like a visitor (phone and desktop), records JS errors, failed files and what renders.
const { chromium } = require("playwright");
const SITE = "https://crypapp-6a9b9.web.app";
(async () => {
  const b = await chromium.launch();
  const out = {};
  for (const [w, h, tag] of [[390, 844, "phone"], [1440, 900, "desktop"]]) {
    const p = await b.newPage({ viewport: { width: w, height: h } });
    const errs = [], failed = [], files = new Set();
    p.on("pageerror", (e) => errs.push(e.message.slice(0, 200)));
    p.on("console", (m) => { if (m.type() === "error") errs.push("console: " + m.text().slice(0, 200)); });
    p.on("response", (r) => { const u = r.url(); if (u.startsWith(SITE)) { files.add(u.replace(SITE, "")); if (r.status() >= 400) failed.push(`${r.status()} ${u.replace(SITE, "")}`); } });
    const t0 = Date.now();
    await p.goto(SITE + "/", { waitUntil: "networkidle", timeout: 60000 }).catch((e) => errs.push("goto: " + e.message));
    const loadMs = Date.now() - t0;
    await p.waitForTimeout(2500);
    const text = await p.evaluate(() => document.body.innerText.slice(0, 300));
    const over = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    out[tag] = { load_ms: loadMs, errors: errs.slice(0, 8), failed: failed.slice(0, 8), js_files: [...files].filter((f) => f.endsWith(".js")),
                 overflow_px: over, text: text.replace(/\n+/g, " | ") };
    await p.close();
  }
  // every page chunk referenced by the app must exist
  const html = await (await fetch(SITE + "/")).text();
  const main = (html.match(/\/assets\/[^"']+\.js/g) || [])[0];
  let chunks = [];
  if (main) {
    const js = await (await fetch(SITE + main)).text();
    chunks = [...new Set((js.match(/assets\/[A-Za-z0-9_.-]+\.js/g) || []))];
  }
  const missing = [];
  for (const c of chunks) { const r = await fetch(`${SITE}/${c}`, { method: "HEAD" }); if (!r.ok) missing.push(`${r.status} ${c}`); }
  out.chunks = { main, referenced: chunks.length, missing };
  console.log(JSON.stringify(out, null, 1));
  await b.close();
})();
