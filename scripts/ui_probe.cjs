// ui-probe.yml: open a page of the preview build (live views copied in) at phone sizes, report errors only (no data).
const { chromium } = require("playwright");
const fs = require("fs");
const path = process.argv[2] || "/results?tab=bots";
(async () => {
  const b = await chromium.launch();
  const report = { path, runs: [] };
  for (const [w, h, n] of [[344, 882, "fold cover"], [673, 841, "fold inner"], [412, 915, "phone"]]) {
    const ctx = await b.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2.625, isMobile: true, hasTouch: true,
      userAgent: "Mozilla/5.0 (Linux; Android 14; SM-F936B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36" });
    const p = await ctx.newPage();
    const errs = [];
    p.on("pageerror", (e) => errs.push("pageerror: " + (e.stack || e.message).slice(0, 600)));
    p.on("console", (m) => { if (m.type() === "error") errs.push("console: " + m.text().slice(0, 300)); });
    p.on("crash", () => errs.push("PAGE CRASHED"));
    const cdp = await ctx.newCDPSession(p);
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
    const t0 = Date.now();
    try { await p.goto(`http://localhost:5197${path}${path.includes("?") ? "&" : "?"}preview=member`, { waitUntil: "domcontentloaded", timeout: 60000 }); } catch (e) { errs.push("goto: " + e.message.slice(0, 200)); }
    await p.waitForTimeout(15000);
    try { await p.evaluate(() => window.scrollTo(0, document.body.scrollHeight)); await p.waitForTimeout(4000); } catch (e) { errs.push("scroll: " + e.message.slice(0, 200)); }
    let info = {};
    try {
      info = await p.evaluate(() => ({ canvases: document.querySelectorAll("canvas").length, nodes: document.querySelectorAll("*").length,
        heap_mb: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1e6) : null,
        error_box: !!document.querySelector('[role="alert"]'), loading: !!document.querySelector(".skeleton"),
        bot_cards: document.querySelectorAll(".ai-card").length,
        text_head: (document.querySelector("main")?.innerText || "").replace(/[0-9.,+$%-]+/g, "#").slice(0, 400) }));
    } catch (e) { errs.push("evaluate: " + e.message.slice(0, 200)); }
    report.runs.push({ screen: n, ms: Date.now() - t0, ...info, errors: errs.slice(0, 15) });
    await ctx.close();
  }
  await b.close();
  fs.writeFileSync("/tmp/ui-probe.json", JSON.stringify(report, null, 1));
  console.log(JSON.stringify(report, null, 1));
})();
