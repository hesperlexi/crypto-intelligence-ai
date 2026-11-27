// DEV PREVIEW ONLY. Sample documents shaped like the engine's views (backend/app/views.py, services/scanner.py,
// engine/futures.py, docs/v1-contract.md) and the users / presence collections. Used to look at pages that sit
// behind Google sign-in. These numbers are sample data for the preview and never reach the production bundle.
const NOW = Date.now();
// preview-only sample headlines (illustrative, never shipped to the live app)
function newsHeads() {
  const src = ["CoinDesk", "Cointelegraph", "Decrypt"];
  const t: [string, string[]][] = [
    ["Sample headline: Bitcoin holds above key support as ETF flows turn positive", ["BTC"]],
    ["Sample headline: Ethereum developers set date for next network upgrade", ["ETH"]],
    ["Sample headline: Solana network activity climbs to a monthly high", ["SOL"]],
    ["Sample headline: Traders watch US inflation data due this week", []],
    ["Sample headline: XRP and Dogecoin lead large-cap gains in Asian hours", ["XRP", "DOGE"]],
    ["Sample headline: Gold-backed tokens see record weekly volume", ["GOLD"]],
    ["Sample headline: Avalanche foundation announces developer grants", ["AVAX"]],
    ["Sample headline: Exchange reserves of Bitcoin fall to a multi-year low", ["BTC"]],
    ["Sample headline: Stablecoin supply reaches a new record", []],
    ["Sample headline: Ethereum staking queue shortens ahead of upgrade", ["ETH"]],
    ["Sample headline: Solana memecoin volumes cool after a busy week", ["SOL"]],
    ["Sample headline: Bitcoin miners move coins to exchanges", ["BTC"]],
    ["Sample headline: Chainlink adds new data feeds for tokenized funds", ["LINK"]],
    ["Sample headline: Regulators publish draft rules for crypto custody", []],
    ["Sample headline: Dogecoin open interest rises as price steadies", ["DOGE"]],
    ["Sample headline: BNB Chain fees drop after network update", ["BNB"]],
  ];
  return t.map(([title, coins], i) => ({ title, coins, source: src[i % 3], url: "https://example.com/" + i, ts: NOW - (i * 1.7 + 0.3) * 3_600_000,
    summary: i % 2 ? null : "Sample summary text for the preview only. The live page shows the first lines the news site publishes with each story." }));
}
const H = 3_600_000, D = 86_400_000;
const v = (o: any) => ({ json: JSON.stringify(o), updated_at: NOW });
// ui-probe.yml drops real views into dev/live/<name>.json (never committed) to test a page with live data
const LIVE = import.meta.glob("./live/*.json", { eager: true, import: "default" }) as Record<string, any>;
const liveView = (name: string): any | null => LIVE[`./live/${name}.json`] ?? null;

const COINS: [string, number, number][] = [
  ["BTC/USDT", 68420.5, 1.84], ["ETH/USDT", 2468.12, -0.92], ["BNB/USDT", 587.3, 0.41], ["XRP/USDT", 0.5234, 2.71],
  ["SOL/USDT", 168.42, 3.95], ["DOGE/USDT", 0.13872, -2.15], ["LTC/USDT", 71.84, 0.18], ["AAVE/USDT", 152.6, 4.42],
  ["AVAX/USDT", 27.41, -1.36], ["PAXG/USDT", 2741.2, 0.22],
];
export const PRICES = Object.fromEntries(COINS.map(([s, p, c]) => [s, { p, c }]));

const REG = ["BULL", "BULLISH CONSOLIDATION", "NEUTRAL", "STRONG BULL", "BEAR", "BEARISH CONSOLIDATION", "BULL", "STRONG BULL", "BEAR", "NEUTRAL"];
const SIG = ["BUY", "HOLD", "HOLD", "BUY", "STRONG BUY", "SELL", "HOLD", "BUY", "SELL", "HOLD"];
const DEC = ["BUY", "NO TRADE", "NO TRADE", "BUY ON PULLBACK", "BUY", "SELL", "NO TRADE", "BUY", "SELL", "NO TRADE"];

function plan(price: number, side: 1 | -1, valid = true, runner = false) {
  const r = price * 0.018;
  const entry = price * (1 - side * 0.002);
  const stop = entry - side * r;
  const tps = [1, 1.6, 2.4].map((k) => entry + side * r * k);
  const lev = 8;
  return {
    side: side > 0 ? "LONG" : "SHORT", valid, reason: valid ? null : "waiting for the higher timeframe to agree",
    entry, entry_zone: [entry * (1 - side * 0.003), entry * (1 + side * 0.002)], stop,
    targets: tps.map((p, i) => ({ name: `TP${i + 1}`, price: p, rr: [1, 1.6, 2.4][i], probability: [0.62, 0.44, 0.29][i] })),
    risk_reward: 1.4, risk_pct: 1.8, runner: runner ? { on: true, rr: 4, target: entry + side * r * 4 } : null,
    suggested_leverage: lev, liquidation_at_suggested: entry * (1 - side * (1 / lev - 0.005)),
    margin_loss_at_stop_pct: 1.8 * lev, funding_per_day_pct: -side * 0.03,
  };
}

function futuresRows(tf: string) {
  // vary the sample calls by timeframe so the Signals "All" list looks like a real mix
  const k = Math.max(0, ["4h", "15m", "1h", "12h", "1d", "3d"].indexOf(tf));
  const rows = COINS.map(([symbol, price], i) => {
    const d = DEC[(i + 3 * k) % DEC.length];
    const side = d === "SELL" ? -1 : d.startsWith("BUY") ? 1 : 0;
    const p_up = side > 0 ? 0.58 : side < 0 ? 0.24 : 0.41, p_down = side < 0 ? 0.55 : side > 0 ? 0.21 : 0.37;
    const row: any = {
      symbol, status: "OK", timeframe: tf, price, action: d === "BUY ON PULLBACK" ? "LONG ON PULLBACK" : side > 0 ? "LONG" : side < 0 ? "SHORT" : "NO TRADE",
      side, decision: d, decision_reason: side ? null : "the AI and the trend disagree", lean: p_up > p_down + 0.03 ? "LONG" : p_down > p_up + 0.03 ? "SHORT" : "NEUTRAL",
      p_up, p_down, p_neutral: 1 - p_up - p_down, confidence: side ? 0.66 - ((i + 2 * k) % 9) * 0.012 : 0.52, grade: side ? (i % 3 === 1 && (tf === "4h" || tf === "12h") ? "B" : "A") : null,
      decision_basis: side ? "4H trend and the AI ensemble agree; 1D trend supports it" : null,
      // V3.4 preview: setup checklist + advisory strategy fit
      opportunity: { score: side ? 74 - (i % 5) * 6 : 41, coverage: side ? 1 : 0.83, side: side > 0 ? "LONG" : "SHORT",
        positive: ["trend: BULL, ADX 28", "reward: 1 : 1.90", "liquidity: $412M 24 h, spread 1.1 bps"], negative: side ? ["momentum: RSI 71"] : ["regime: market weak bear"],
        warnings: [], rejection: side ? [] : ["TOO MANY SAME-SIDE CALLS"],
        components: { trend: 85, momentum: 55, relative: 66, volume: 75, liquidity: 85, volatility: 80, regime: side ? 85 : 20, entry: 90, reward: 70, stop: 80, costs: 70, correlation: 62 } },
      strategy_fit: side ? { action: i % 4 === 3 ? "STRATEGY UNSUITABLE" : "TRADE", reason: i % 4 === 3 ? "this strategy has lost in this market (34 past trades in a weak bear market); the call stands, treat it with care" : "not yet proven here (12 past trades in a weak bull market)" }
        : { action: "WAIT", reason: "a setup exists but timing / limits hold it back: TOO MANY SAME-SIDE CALLS" },
      filter_score: side ? 0.61 : null, filter_threshold: 0.55, regime: REG[i], signal: SIG[i], funding_rate: 0.0001,
      record_status: side ? "logged" : "not_logged", stale: false,
      ai: side ? { rationale: "Price is holding above the rising 4H trend after a shallow pullback; momentum is recovering and the stop sits under the last swing low.", regime: "trend", model: "advisor", at: NOW - 20 * 60_000 } : undefined,
      call: side ? { id: `c${i}`, status: "OPEN", fill_status: d === "BUY ON PULLBACK" ? "PENDING" : "FILLED", side: side > 0 ? "LONG" : "SHORT", entry: price * (1 - side * 0.004), stop: price * (1 - side * 0.02), peak_r: 0.42, peak_pct: 0.76, exit_reason: null, managed: 0, created_at: NOW - (1 + ((i * 5 + k * 3) % 11)) * H, leverage: 8 }
        : i === 6 ? { id: `c${i}`, status: "TP2", fill_status: "FILLED", side: "LONG", entry: price * 0.98, stop: price * 0.962, peak_r: 2.1, peak_pct: 3.4, exit_reason: null, managed: 0, created_at: NOW - 9 * H, closed_at: NOW - 2 * H, return_pct: 2.3, leverage: 10, roi_pct: 23 }
        : i === 9 ? { id: `c${i}`, status: "STOPPED", fill_status: "FILLED", side: "SHORT", entry: price * 0.99, stop: price * 1.008, peak_r: 0.3, peak_pct: 0.4, exit_reason: "stop", managed: 0, created_at: NOW - 9 * H, closed_at: NOW - 3 * H, return_pct: -1.8, leverage: 8, roi_pct: -14.4 } : null,
    };
    if (side) row.plan = plan(price, side as 1 | -1, true, i === 4);
    else row.plan = plan(price, 1, false);
    if (row.call) Object.assign(row.call, { tp1: row.call.entry + (row.call.side === "LONG" ? 1 : -1) * Math.abs(row.call.entry - row.call.stop), tp1_hit: 0 });
    if (i === 0 && row.call) {
      // v2.7 sample: the admin moved this open call's stop-loss (public, forward-only)
      Object.assign(row.call, { entry: row.plan.entry, stop: row.plan.stop, tp1: row.plan.targets[0].price });
      const old = row.call.stop, nu = Math.round(price * 0.9905);
      row.call = { ...row.call, stop0: old, tp1_0: row.call.tp1, stop: nu,
        adjustments: [{ at: NOW - 48 * 60_000, field: "stop", old, new: nu, note: "Locking in more of the move before the US CPI release" }] };
    }
    return row;
  });
  // v2.69 silver: watch only - the engine's call is shown, side stays 0 (never traded or counted)
  rows.push({ symbol: "XAG/USDT", status: "OK", timeframe: tf, price: 41.64, action: "NO TRADE", side: 0, decision: "NO TRADE",
    decision_reason: "watch only: this call is shown for study - not traded by the bots and not counted in the results",
    lean: "LONG", p_up: 0.57, p_down: 0.22, p_neutral: 0.21, confidence: 0.6, grade: null, regime: "BULL", signal: "BUY",
    funding_rate: 0.0001, record_status: null, stale: false, call: null, watch: { action: "LONG", side: 1, grade: "A" },
    plan: plan(41.64, 1, true, false) } as any);
  return rows;
}

function dashboard(tf: string) {
  const rows = COINS.map(([symbol, price, ch], i) => ({ symbol, status: "OK", price, change_24h_pct: ch, regime: REG[i], signal: SIG[i], score: 40 + ((i * 17) % 50), decision: DEC[i], confidence: 0.55 + (i % 4) * 0.04, grade: DEC[i] !== "NO TRADE" ? "A" : null }));
  // preview: a full-size watchlist (29 coins) so the dial / sonar can be judged at real density
  const EXTRA = ["PEPE", "ENA", "GALA", "TRX", "UNI", "LINK", "ADA", "SUI", "DOT", "NEAR", "BCH", "HBAR", "SHIB", "BONK", "APT", "RARE", "ANTHROPIC", "MSTR", "ETC", "XAG"];
  EXTRA.forEach((b, j) => rows.push({ symbol: `${b}/USDT`, status: "OK", price: 1 + j, change_24h_pct: ((j * 7) % 13) - 8, regime: j % 6 === 0 ? "BULL" : j % 5 === 0 ? "NEUTRAL" : "BEAR",
    signal: j % 6 === 0 ? "BUY" : j % 5 === 0 ? "HOLD" : j % 3 === 0 ? "SELL" : "HOLD", score: 25 + ((j * 23) % 70), decision: "NO TRADE", confidence: 0.5, grade: null }));
  const HZ = ["15M", "1H", "4H", "12H", "24H", "3D"];
  return {
    timeframe: tf,
    market_status: { status: "BULL", bull: 6, bear: 2, neutral: 2, assets: 10, basis: `share of tracked assets in a bullish / bearish ${tf} regime (60% needed)` },
    regimes: rows.map((r, i) => ({ symbol: r.symbol, regime: r.regime, confidence: 0.5 + ((i * 7) % 5) / 10 })),
    top_signals: rows.slice(0, 6).map((r) => ({ symbol: r.symbol, signal: r.signal, score: r.score, decision: r.decision, confidence: r.confidence })),
    opportunities: rows.filter((r) => r.decision !== "NO TRADE").slice(0, 4).map((r) => ({ symbol: r.symbol, decision: r.decision, signal: r.signal, score: r.score, confidence: r.confidence, risk_reward: 1.4 })),
    risks: [{ symbol: "DOGE/USDT", risk: "HIGH volatility" }, { symbol: "AAVE/USDT", risk: "RSI 77 (overbought)" }],
    heatmap: rows.map((r) => ({ symbol: r.symbol, change_24h_pct: r.change_24h_pct, signal: r.signal, regime: r.regime })),
    forecast_table: rows.map((r, i) => ({ symbol: r.symbol, price: r.price, horizons: Object.fromEntries(HZ.map((h, j) => [h, j === 5 && i > 6 ? { status: "MODEL NOT TRAINED" } : { expected_return: ((i + j) % 5 - 2) * 0.0031, p_up: 0.5 + ((i + j) % 5 - 2) * 0.03, edge_confirmed: (i + j) % 3 !== 0 }])) })),
    rows,
  };
}

function publicRecord() {
  const t: any = trackRecord();
  const closed = (t.live.signals as any[]).filter((x) => x.status !== "OPEN" && x.return_pct != null);
  const daily: any[] = []; let acc = 0;
  for (let i = 20; i >= 0; i--) { acc += Math.sin(i * 1.7) * 0.8 + 0.25; daily.push({ day: new Date(NOW - i * D).toISOString().slice(0, 10), cum: +acc.toFixed(2) }); }
  return { generated_at: NOW, since: t.record_since, restart: t.restart, net: true, summary: t.live.summary, open: 4,
    by_timeframe: { "15m": { closed: 9, win_rate: 0.67, total_return_pct: 2.1 }, "1h": { closed: 6, win_rate: 0.5, total_return_pct: -0.4 }, "4h": { closed: 11, win_rate: 0.64, total_return_pct: 4.9 }, "12h": { closed: 3, win_rate: 0.67, total_return_pct: 1.2 } },
    last_7d: t.last_7d, daily,
    recent: closed.slice(0, 12).map((x) => ({ symbol: x.symbol, timeframe: x.timeframe, side: x.side, status: x.status, net_pct: x.return_pct, closed_at: x.closed_at })),
    method: "Every trade signal the engine published, followed candle by candle; results after fees." };
}

function trackRecord() {
  const sigs = [
    ["SOL/USDT", "4h", "LONG", "A", "TP2", 2.31], ["BTC/USDT", "1h", "LONG", "A", "TP1", 0.84], ["ETH/USDT", "4h", "SHORT", "B", "STOPPED", -1.62],
    ["XRP/USDT", "1h", "LONG", "A", "TP3", 3.12], ["AAVE/USDT", "12h", "LONG", "A", "OPEN", null], ["DOGE/USDT", "15m", "SHORT", "B", "STOPPED", -0.94],
    ["BNB/USDT", "4h", "LONG", "A", "TP1", 0.71], ["AVAX/USDT", "1h", "SHORT", "A", "TP2", 1.88], ["LTC/USDT", "1d", "LONG", "B", "EXPIRED", 0.12],
  ].map(([symbol, timeframe, side, grade, status, ret], i) => {
    const px = PRICES[symbol as string].p, s = side === "LONG" ? 1 : -1;
    const leverage = Math.min(10, Math.floor(1 / (1.5 * 0.018 + 0.005)));   // engine/futures.signal_leverage for a 1.8% stop (cap 10x)
    return { id: `seed-${i}`, symbol, timeframe, side, grade, status, return_pct: ret, leverage, roi_pct: ret == null ? null : (ret as number) * leverage, created_at: NOW - (i + 1) * 7 * H, closed_at: status === "OPEN" ? null : NOW - (i + 1) * 5 * H,
      entry: px, stop: px * (1 - s * 0.018), tp1: px * (1 + s * 0.018), tp2: px * (1 + s * 0.029), tp3: px * (1 + s * 0.043),
      fill_status: "FILLED", peak_pct: status === "STOPPED" ? 0.4 : null, managed: 0 } as any;
  });
  // v2.7 sample: a closed call stopped at the level the admin moved
  Object.assign(sigs[2], { exit_reason: "admin_stop", adjustments: [{ at: sigs[2].created_at + 3 * H, field: "stop", old: sigs[2].stop, new: sigs[2].entry * 1.0162, note: "Cutting risk: the trend turned against the short" }] });
  // closed rows: hit flags, time limits (pre-v2.8 calls keep 30), exit reasons, a sealed proof
  const HB: Record<string, number> = { "15m": 250, "1h": 200, "4h": 100 };
  const tfMs: Record<string, number> = { "15m": H / 4, "1h": H, "4h": 4 * H, "12h": 12 * H, "1d": D };
  const hits: Record<string, number[]> = { TP1: [1, 0, 0], TP2: [1, 1, 0], TP3: [1, 1, 1] };
  const reason: Record<string, string> = { TP1: "break_even", TP2: "trail", TP3: "tp3", STOPPED: "stop", EXPIRED: "expired" };
  sigs.forEach((x: any, i: number) => {
    const [a, b, c] = hits[x.status] ?? [0, 0, 0];
    const hb = i < 5 ? HB[x.timeframe] ?? 30 : 30;
    Object.assign(x, { tp1_hit: a, tp2_hit: b, tp3_hit: c, stop_hit: x.status === "STOPPED" || x.status === "TP1" || x.status === "TP2" ? 1 : 0,
      horizon_bars: hb, expires_at: x.created_at + hb * (tfMs[x.timeframe] ?? H), exit_reason: x.exit_reason ?? (x.status === "OPEN" ? null : reason[x.status]),
      proof: { hash: "9f2c4e81d0b7a3f65e1c22d4a8b90e7f3c6d5a1b2e4f8091a7c3d6e5f4b2a190".slice(i) + "0".repeat(i), sealed_at: x.created_at + 5 * 60_000 } });
  });
  Object.assign(sigs[0].proof, { text: "CIA-SEAL-1|sample|SOL/USDT|4h|LONG|levels|published|salt" });
  // open samples: running after TP1 (stop at break-even, admin moved TP1), waiting for a pullback entry, fresh 15m demo-style call
  const lev = sigs[0].leverage;
  const mk = (symbol: string, timeframe: string, side: "LONG" | "SHORT", grade: string, ageH: number, entryOff: number, extra: any = {}) => {
    const px = PRICES[symbol].p, s = side === "LONG" ? 1 : -1, entry = px * (1 - s * entryOff);
    const hb = HB[timeframe] ?? 30;
    return { id: `seed-${symbol}-${timeframe}`, symbol, timeframe, side, grade, status: "OPEN", return_pct: null, roi_pct: null, leverage: lev, created_at: NOW - ageH * H, closed_at: null,
      entry, stop: entry * (1 - s * 0.018), tp1: entry * (1 + s * 0.018), tp2: entry * (1 + s * 0.029), tp3: entry * (1 + s * 0.043),
      fill_status: "FILLED", filled_at: NOW - ageH * H + 15 * 60_000, peak_pct: null, managed: 0, tp1_hit: 0, tp2_hit: 0, tp3_hit: 0, stop_hit: 0,
      horizon_bars: hb, expires_at: NOW - ageH * H + hb * tfMs[timeframe],
      proof: { hash: "4b1d8e2f6a9c3075d1e4b8a2c6f09e3d7b5a1c8e2f4d6b9a0c3e5f7a1b2d4c6e", sealed_at: NOW - ageH * H + 4 * 60_000 }, ...extra };
  };
  const tp1Row = mk("BTC/USDT", "4h", "LONG", "A", 9, 0.021, { tp1_hit: 1, peak_pct: 2.6 });
  tp1Row.adjustments = [{ at: NOW - 6 * H, field: "tp1", old: tp1Row.tp1 * 1.004, new: tp1Row.tp1, note: "Nearer target 1 before the US data" }];
  const pendRow = mk("ETH/USDT", "1h", "SHORT", "A", 1.5, -0.006, { fill_status: "PENDING", filled_at: undefined });
  // v2.21: a "let it run" call past target 3 (stop at TP2, one exit at 1:4)
  const runnerRow = mk("XRP/USDT", "15m", "SHORT", "A", 1, -0.05, { tp1_hit: 1, tp2_hit: 1, tp3_hit: 1, peak_pct: 5.2 });
  runnerRow.runner = { on: true, rr: 4, target: runnerRow.entry * (1 - 4 * 0.018) };
  const runRow = mk("SOL/USDT", "1h", "LONG", "A", 3, 0.008, { peak_pct: 1.1,
    ai: { rationale: "Sample advisor note for the preview: momentum is rising with the 4h trend; the main risk is the resistance just above target 2.", regime: "trending up" } });
  // v2.67 preview: a full board (14 running) so the journeys show 12 + "2 more"
  const extraOpen = [
    mk("BNB/USDT", "4h", "LONG", "A", 5, 0.012, { tp1_hit: 1 }), mk("DOGE/USDT", "15m", "SHORT", "A", 0.6, 0.006), mk("LTC/USDT", "1h", "LONG", "A", 2, -0.009),
    mk("AAVE/USDT", "4h", "SHORT", "A", 7, -0.025, { tp1_hit: 1, tp2_hit: 1 }), mk("AVAX/USDT", "4h", "SHORT", "B", 4, 0.004), mk("PAXG/USDT", "12h", "LONG", "A", 20, 0.003),
    mk("BTC/USDT", "15m", "SHORT", "A", 0.4, -0.002), mk("ETH/USDT", "4h", "LONG", "B", 11, -0.014), mk("SOL/USDT", "15m", "SHORT", "A", 0.8, 0.011), mk("XRP/USDT", "4h", "LONG", "A", 3, 0.016),
  ].map((r, i) => ({ ...r, id: `${r.id}-x${i}` }));
  sigs.unshift(runnerRow, tp1Row, pendRow, runRow, ...extraOpen);
  const closed = sigs.filter((x) => x.status !== "OPEN").map((x) => x.return_pct as number);
  let acc = 0;
  let accRoi = 0;
  const curve = sigs.slice().reverse().filter((x) => x.status !== "OPEN").map((x) => ({ ts: x.closed_at, cum_return_pct: (acc += x.return_pct as number), cum_roi_pct: (accRoi += x.roi_pct as number) }));
  const rois = sigs.filter((x) => x.status !== "OPEN").map((x) => x.roi_pct as number);
  const last7 = { days: 7, net: true, closed: 9, wins: 6, losses: 3, win_rate: 6 / 9, avg_return_pct: 0.41, total_return_pct: 3.69, avg_gross_return_pct: 0.58,
    best: { symbol: "XRP/USDT", timeframe: "1h", side: "LONG", status: "TP3", return_pct: 2.96 }, worst: { symbol: "ETH/USDT", timeframe: "4h", side: "SHORT", status: "STOPPED", return_pct: -1.78 },
    min_sample: 30, sample_note: "Only 9 closed signals: too few to judge the method; results this short swing a lot.",
    basis: "Signals that closed in the last 7 days, after fees (0.15% round trip plus funding), equal size, half at TP1 and a quarter at TP2 and TP3. Unfilled calls are not counted." };
  return {
    last_7d: last7,
    record_since: NOW - 2 * D, testing_since: NOW - 2 * D,
    restart: { at: NOW - 2 * D, text: "Fresh start 3 Nov 2026: real entry prices, after fees." },
    live: { summary: { closed: closed.length, win_rate: closed.filter((r) => r > 0).length / closed.length, avg_return_pct: closed.reduce((a, b) => a + b, 0) / closed.length, total_return_pct: acc,
      avg_roi_pct: accRoi / rois.length, total_roi_pct: accRoi, best_roi_pct: Math.max(...rois), worst_roi_pct: Math.min(...rois) },
      open: sigs.filter((x) => x.status === "OPEN").length, curve, signals: sigs },
    tested: [{ symbol: "BTC/USDT", timeframe: "4h", edge: true, selective_hit_rate: 0.61, selective_ci95: [0.55, 0.67], calls_per_day: 0.8, tested_days: 410 },
      { symbol: "SOL/USDT", timeframe: "1h", edge: true, selective_hit_rate: 0.58, selective_ci95: [0.53, 0.63], calls_per_day: 2.1, tested_days: 380 },
      { symbol: "LTC/USDT", timeframe: "1d", edge: false, selective_hit_rate: 0.5, selective_ci95: [0.41, 0.59], calls_per_day: 0.2, tested_days: 600 }],
    bots: [{ scorecard: true, name: "Futures signals A+B · 4H", trades: 6, win_rate: 0.67, return_pct: 3.4, benchmark_return_pct: 1.2, max_drawdown_pct: 1.9, started_at: NOW - 2 * D },
      { scorecard: true, name: "Futures signals A+B · 1H", trades: 11, win_rate: 0.55, return_pct: 1.1, benchmark_return_pct: 1.2, max_drawdown_pct: 2.6, started_at: NOW - 2 * D }],
    method: { live: "Every trade signal the engine published, followed candle by candle: half the position exits at take-profit 1 (1:1), a quarter at take-profit 2 and a quarter at take-profit 3; after take-profit 1 the stop moves to break-even, after take-profit 2 to take-profit 1. The rest exits at the stop or when the call's time limit runs out (250 candles on 15M, 200 on 1H, 100 on 4H, 30 on the others; calls published before 31 Oct 2026 keep 30). Fees not included.", tested: "Walk-forward test on data the models never saw." },
    achievements: [
      { id: "signals_10", title: "10 signals delivered", unlocked: true, value: "10", detail: "10 trade signals published and followed to the end", achieved_at: NOW - 1 * D },
      { id: "best_trade", title: "Best signal", unlocked: true, value: "+31.2% ROI", detail: "XRP long · 10x margin · price +3.12%", achieved_at: NOW - 2 * H, roi_pct: 31.2, leverage: 10, return_pct: 3.12 },
      { id: "win_streak", title: "Winning streak", unlocked: true, value: "4 in a row", detail: "consecutive winning signals", achieved_at: NOW - 6 * H },
      { id: "all_targets", title: "All targets hit", unlocked: true, value: "1x", detail: "signals that reached take-profit 3", achieved_at: NOW - 2 * H },
      { id: "best_week", title: "Best week", unlocked: true, value: "+58.4% ROI", detail: "total ROI on margin of all signals closed that week", achieved_at: NOW - 3 * D, roi_pct: 58.4 },
      { id: "signals_25", title: "25 signals delivered", unlocked: true, value: "25", detail: "25 trade signals published and followed to the end", achieved_at: NOW - 3 * H },
      { id: "tp1_rate", title: "Target 1 reached often", unlocked: true, value: "62%", detail: "share of closed signals that reached take-profit 1", achieved_at: NOW - 5 * H },
      { id: "best_short", title: "Best short", unlocked: true, value: "+48.8% ROI", detail: "LTC short · 7x margin · price +6.96%", achieved_at: NOW - 4 * H, roi_pct: 48.8, leverage: 7, return_pct: 6.96 },
      { id: "bot_futures-signal-ab-4h", title: "Beat buy & hold · 4H", unlocked: false, value: "+3.4%", detail: "scorecard bot vs +1.2% for holding", progress: 0.6 },
      { id: "live_30", title: "30 days of public results", unlocked: false, value: "2 days", detail: "every signal public since launch", progress: 0.07 },
    ],
  };
}

function weekly() {
  const wk = 7 * D, start = NOW - (NOW - 4 * D) % wk;
  const t = (symbol: string, timeframe: string, side: string, status: string, ret: number, leverage: number | null) =>
    ({ symbol, timeframe, side, status, entry: PRICES[symbol]?.p ?? 1, return_pct: ret, leverage, roi_pct: leverage ? ret * leverage : null, grade: "A", created_at: start - D, closed_at: start - D / 2 });
  const last = [t("XRP/USDT", "1h", "LONG", "TP3", 3.12, 10), t("SOL/USDT", "4h", "LONG", "TP2", 2.31, 10), t("AVAX/USDT", "1h", "SHORT", "TP2", 1.88, 9),
    t("1000PEPE/USDT", "15m", "SHORT", "TP1", 0.71, null), t("BNB/USDT", "4h", "LONG", "TP1", 0.71, 10)];
  const mk = (st: number, best: any[], complete: boolean, wins: number, losses: number, tot: number, totRoi: number) => ({
    week_start: st, week_end: st + wk, complete, issued: wins + losses + 2, closed: wins + losses, wins, losses, win_rate: wins / (wins + losses),
    total_return_pct: tot, total_roi_pct: totRoi, avg_return_pct: tot / (wins + losses), avg_roi_pct: totRoi / (wins + losses),
    best, worst: t("ETH/USDT", "4h", "SHORT", "STOPPED", -1.62, 10), scorecard_bots: [{ name: "Futures signals A+B · 4H", week_return_pct: 2.4, total_return_pct: 3.4 }],
    radar_best: { symbol: "SUI/USDT", ret_7d_pct: 14.2, vs_btc_pct: 9.8 },
    curve: [0, 31.2, 54.3, 38.1, 55.0, 62.1, 46.0, 53.1, 70.2, 58.0, totRoi].slice(0, wins + losses + 1), curve_basis: "roi",
    basis: "Signals that closed this week; each return assumes equal size, half closed at target 1 and a quarter at targets 2 and 3, before fees. ROI is on margin at the leverage each signal card suggested (price return x leverage); losses are multiplied the same way." });
  return { reports: [mk(start, last.slice(0, 2), false, 2, 1, 3.81, 38.1), mk(start - wk, last, true, 7, 3, 6.92, 64.8)] };
}

function users() {
  const u: Record<string, any> = {};
  const add = (id: string, d: any) => { u[`users/${id}`] = { uid: id, photo: "", requested_at: NOW - 10 * D, ...d }; };
  add("u_pend1", { email: "omar.h@example.com", name: "Omar Haddad", username: "omar_h", provider: "google", status: "pending", requested_at: NOW - 2 * H,
    payment: { method: "binance", months: 3, amount: 40, currency: "USDT", txid: "B2610290041887", proof: proofImage(), status: "submitted", submitted_at: NOW - 90 * 60_000 } });
  add("u_pend2", { email: "lina.m@example.com", name: "", username: "lina_trades", provider: "password", status: "pending", requested_at: NOW - 26 * H,
    payment: { method: "mexc", months: 1, amount: 15, currency: "USDT", txid: "MX88120934", proof: null, status: "submitted", submitted_at: NOW - 20 * H } });
  // proofs sent with v2.1+: the screenshot lives in payment_proofs/{uid}; the payment only says has_proof
  add("u_pend3", { email: "karim.b@example.com", name: "Karim Benali", username: "karim_b", provider: "google", status: "pending", requested_at: NOW - 3 * H,
    payment: { method: "binance", months: 6, amount: 70, currency: "USDT", txid: "B2610310077", proof: null, has_proof: true, status: "submitted", submitted_at: NOW - 40 * 60_000 } });
  u["payment_proofs/u_pend3"] = { uid: "u_pend3", proof: proofImage(), submitted_at: NOW - 40 * 60_000 };
  // an old record whose inline "proof" is not an image: the Users page must show "invalid image", never render it
  add("u_badproof", { email: "odd.upload@example.com", name: "Odd Upload", provider: "google", status: "pending", requested_at: NOW - 5 * H,
    payment: { method: "binance", months: 1, amount: 15, currency: "USDT", txid: "B2610319999", proof: "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==", status: "submitted", submitted_at: NOW - 4 * H } });
  add("u_new", { email: "new.person@example.com", name: "New Person", username: "newperson", provider: "password", status: "pending", requested_at: NOW - 30 * 60_000,
    referred_by: "u_member", ref_via: "k7m2p9qx" });
  add("u_member", { email: "sara.k@example.com", name: "Sara Kim", username: "sara_k", provider: "google", status: "approved", expires_at: NOW + 74 * D, plan_months: 3, approved_at: NOW - 16 * D, free: false,
    // v2.16 sample: invite code, two friends joined (one paid -> one free month), last month's leaderboard badge
    ref_code: "k7m2p9qx", referral_stats: { joined: 2, paid: 1, months: 1, updated_at: NOW - H }, badges: ["lb:2026-10"],
    history: [{ months: 3, amount: 40, free: false, granted_at: NOW - 16 * D },
      { months: 1, amount: 0, free: true, kind: "referral", ref_uid: "u_pend3", ref_name: "@dreyes", granted_at: NOW - 2 * D, granted_by: "owner@example.com", from: NOW + 44 * D, to: NOW + 74 * D },
      { months: 1, amount: 0, free: true, kind: "prize", prize_month: "2026-10", prize_label: "October 2026", granted_at: NOW - D, granted_by: "owner@example.com", from: NOW + 44 * D, to: NOW + 74 * D }], payment: { method: "binance", months: 3, amount: 40, currency: "USDT", txid: "B2610140032", proof: null, has_proof: true, status: "accepted", submitted_at: NOW - 16 * D, decided_at: NOW - 16 * D } });
  u["payment_proofs/u_member"] = { uid: "u_member", proof: proofImage(), submitted_at: NOW - 16 * D };   // decided before screenshots were auto-deleted
  add("u_end", { email: "daniel.r@example.com", name: "Daniel Reyes", username: "dreyes", provider: "password", status: "approved", expires_at: NOW + 4 * D, plan_months: 1, approved_at: NOW - 26 * D,
    referred_by: "u_member", ref_via: "k7m2p9qx", referral_reward: { to: "u_member", at: NOW - 2 * D, by: "owner@example.com" },
    history: [{ months: 1, amount: 15, granted_at: NOW - 26 * D }] });
  add("u_free", { email: "tester@example.com", name: "Test Account", status: "approved", expires_at: NOW + 180 * D, plan_months: 6, approved_at: NOW - 3 * D, free: true,
    history: [{ months: 6, amount: 0, free: true, granted_at: NOW - 3 * D }] });
  add("u_exp", { email: "mei.l@example.com", name: "Mei Lin", status: "approved", expires_at: NOW - 5 * D, plan_months: 1, approved_at: NOW - 35 * D,
    history: [{ months: 1, amount: 15, granted_at: NOW - 35 * D }] });
  add("u_old", { email: "early.member@example.com", name: "Early Member", status: "approved", approved_at: NOW - 120 * D });
  add("u_block", { email: "spam@example.com", name: "", status: "blocked" });
  // more varied people so the Users page shows paging, sorting and every state
  const paid = (m: number, amt: number, ago: number) => ({ months: m, amount: amt, free: false, granted_at: NOW - ago * D });
  const price: Record<number, number> = { 1: 15, 3: 40, 6: 70, 12: 130 };
  const people: [string, string, string][] = [
    ["Ahmed Al Mansoori", "ahmed.m", "google"], ["Priya Nair", "priya_n", "password"], ["Lucas Martin", "lucasm", "google"],
    ["Fatima Zahra", "", "google"], ["Yusuf Demir", "ydemir", "password"], ["Hannah Schmidt", "hannah_s", "google"],
    ["Carlos Mendes", "cmendes", "google"], ["Aisha Rahman", "aisha.r", "password"], ["Kenji Watanabe", "kenji_w", "google"],
    ["Olivia Brown", "", "password"], ["Mohammed Al Farsi", "mfarsi", "google"], ["Elena Petrova", "elena_p", "google"],
    ["Ravi Kumar", "ravik", "password"], ["Sophie Laurent", "sophie_l", "google"], ["Noah Williams", "", "google"],
    ["Zainab Hussein", "zainab_h", "password"], ["Marco Rossi", "mrossi", "google"], ["Layla Haddad", "layla", "google"],
    ["Alexander Konstantinopoulos-Smith", "alex_ks", "password"], ["Tariq Aziz", "tariq_a", "google"], ["Grace Lee", "gracelee", "google"],
  ];
  people.forEach(([name, username, provider], i) => {
    const id = `u_x${i}`;
    const email = `${name.toLowerCase().split(" ")[0]}.${(name.split(" ")[1] ?? "x").toLowerCase()}@example.com`;
    const base = { email, name, ...(username ? { username } : {}), provider, requested_at: NOW - (i * 3 + 1) * D };
    const m = [1, 3, 6, 12][i % 4];
    switch (i % 7) {
      case 0: add(id, { ...base, status: "approved", expires_at: NOW + (20 + i * 4) * D, plan_months: m, approved_at: NOW - 10 * D, free: false, history: [paid(m, price[m], 10)],
        payment: { method: i % 2 ? "mexc" : "binance", months: m, amount: price[m], currency: "USDT", txid: `B26100${i}991`, proof: null, ...(i < 10 ? { has_proof: true } : {}), status: "accepted", submitted_at: NOW - 10 * D } });
        if (i < 10) u[`payment_proofs/${id}`] = { uid: id, proof: proofImage(), submitted_at: NOW - 10 * D }; break;
      case 1: add(id, { ...base, status: "approved", expires_at: NOW + (2 + i) * D, plan_months: 1, approved_at: NOW - 25 * D, free: false, history: [paid(1, 15, 25)] }); break;
      case 2: add(id, { ...base, status: "approved", expires_at: NOW + (40 + i * 6) * D, plan_months: m, approved_at: NOW - 4 * D, free: true, history: [{ months: m, amount: 0, free: true, granted_at: NOW - 4 * D }] }); break;
      case 3: add(id, { ...base, status: "pending", requested_at: NOW - (i + 2) * H,
        payment: { method: i % 2 ? "mexc" : "binance", months: m, amount: price[m], currency: "USDT", txid: `MX7712${i}0`, proof: i % 2 ? null : proofImage(), status: "submitted", submitted_at: NOW - (i + 1) * H } }); break;
      case 4: add(id, { ...base, status: "approved", expires_at: NOW - (3 + i) * D, plan_months: 1, approved_at: NOW - 40 * D, free: false, history: [paid(1, 15, 40)] }); break;
      case 5: add(id, { ...base, status: i > 10 ? "blocked" : "pending",
        payment: { method: "binance", months: 1, amount: 10, currency: "USDT", txid: "B000123", proof: null, has_proof: true, status: "rejected", reason: "Payment not found in my Binance history", submitted_at: NOW - 3 * D } }); break;
      default: add(id, { ...base, status: "approved", expires_at: NOW + (3 + (i % 4)) * D, plan_months: 1, approved_at: NOW - 27 * D, free: i % 2 === 0, history: [i % 2 === 0 ? { months: 1, amount: 0, free: true, granted_at: NOW - 27 * D } : paid(1, 15, 27)] });
    }
  });
  add("u_freeold", { email: "friend.tester@example.com", name: "Friend Tester", status: "approved", expires_at: NOW - 2 * D, plan_months: 1, approved_at: NOW - 32 * D, free: true,
    history: [{ months: 1, amount: 0, free: true, granted_at: NOW - 32 * D }] });
  return u;
}

function presence() {
  return {
    "presence/u_member": { last_seen: NOW - 60_000, country: "AE", device: "iPhone app" },
    "presence/u_end": { last_seen: NOW - 3 * H, country: "GB", device: "Desktop browser" },
    "presence/u_pend1": { last_seen: NOW - 80 * 60_000, country: "SA", device: "Android app" },
    "presence/u_free": { last_seen: NOW - 2 * D, country: "DE", device: "Android browser" },
    "presence/u_exp": { last_seen: NOW - 9 * D, country: "SG", device: "Desktop app" },
    "presence/u_old": { last_seen: NOW - 30 * 60_000, country: "AE", device: "Android app (Chrome)" },
    ...Object.fromEntries(Array.from({ length: 21 }, (_, i) => i).filter((i) => i % 5 !== 4).map((i) => [`presence/u_x${i}`, {
      last_seen: NOW - [2, 45, 300, 1500, 4000, 9000, 20000][i % 7] * 60_000,
      country: ["AE", "IN", "FR", "MA", "TR", "DE", "BR", "PK", "JP", "US", "OM", "RU", "IN", "FR", "GB", "NG", "IT", "LB", "GR", "EG", "KR"][i],
      device: ["iPhone app", "Android app", "Desktop browser", "Android browser", "Desktop app", "iPad browser"][i % 6],
    }])),
    "user_state/u_member": { push_ok_at: NOW - 15 * D },
    "user_state/u_end": { push_error: { app: "web", stage: "token", code: "messaging/permission-blocked", message: "Notifications blocked in the browser", at: NOW - 2 * D } },
  };
}

/** A small receipt-like picture drawn on a canvas (a payment screenshot stand-in). */
function proofImage(): string {
  try {
    const c = document.createElement("canvas"); c.width = 360; c.height = 640;
    const g = c.getContext("2d")!;
    g.fillStyle = "#121417"; g.fillRect(0, 0, 360, 640);
    g.fillStyle = "#f0b90b"; g.font = "bold 22px Inter, sans-serif"; g.fillText("Payment sent", 24, 70);
    g.fillStyle = "#eaecef"; g.font = "bold 40px Inter, sans-serif"; g.fillText("40 USDT", 24, 140);
    g.fillStyle = "#848e9c"; g.font = "16px Inter, sans-serif";
    ["To: Crypto Intelligence AI", "Order ID: B2610290041887", "Status: Completed", "Sample image (preview)"].forEach((t, i) => g.fillText(t, 24, 210 + i * 36));
    return c.toDataURL("image/png");
  } catch { return ""; }
}

// shaped like backend/app/services/market_insights.view (sample values for the preview)
function marketContext() {
  const t0 = Math.floor(NOW / H) * H;
  const series: [number, number, number][] = [];
  for (let i = 9 * 6; i >= 0; i--) {            // 9 days at 4-hour steps
    const t = t0 - i * 4 * H;
    const k = 54 - i;
    series.push([t, +(57.1 + 0.012 * k + 0.18 * Math.sin(k / 5)).toFixed(3), +(11.9 - 0.004 * k + 0.08 * Math.cos(k / 6)).toFixed(3)]);
  }
  const last = series[series.length - 1];
  const day = series[series.length - 7], week = series[series.length - 43];
  const c24 = +(last[1] - day[1]).toFixed(3), c7 = +(last[1] - week[1]).toFixed(3);
  return {
    generated_at: NOW - 12 * 60_000,
    dominance: { as_of: t0 + 4 * 60_000, btc: last[1], eth: last[2], btc_change_24h: c24, btc_change_7d: c7,
      eth_change_24h: +(last[2] - day[2]).toFixed(3), eth_change_7d: +(last[2] - week[2]).toFixed(3), series, series_step_h: 4, points: 9 * 24,
      reading: `Bitcoin's share is steady at ${last[1].toFixed(1)}% (${c7 >= 0 ? "+" : "−"}${Math.abs(c7).toFixed(1)} over 7 days): no clear rotation between Bitcoin and the rest.`,
      source: "CoinGecko /global, stored hourly by the engine", tv_symbol: "CRYPTOCAP:BTC.D" },
    altseason: { value: 32, label: "Neither season", n_beat: 16, n_total: 50, window_days: 90, as_of: Math.floor(NOW / D) * D, computed_at: NOW - 3 * H,
      btc_return: 0.084, best: [{ coin: "HYPE", vs_btc: 0.61 }, { coin: "SUI", vs_btc: 0.38 }, { coin: "AAVE", vs_btc: 0.22 }],
      universe: "CoinGecko market-cap ranking (coins listed on Binance spot)", history: [[NOW - 3 * H, 32]], source: "Binance spot daily closes" },
    pulse: { as_of: NOW - 12 * 60_000, total_market_cap_usd: 3.62e12, market_cap_change_24h_pct: -0.84, stablecoin_share: 7.62, source: "CoinGecko" },
    funding: { avg_rate_8h: 0.0000842, read: "neutral", n: 10, as_of: NOW - 12 * 60_000, source: "OKX perpetual", high: "SOL", low: "DOGE" },
    headline: { title: "Fed holds rates steady; Powell says further cuts depend on incoming inflation data", url: "https://example.com/preview-headline", source: "CoinDesk", ts: NOW - 95 * 60_000 },
    errors: [], rules: {},
    // v2.16 AI market briefing (backend/app/services/briefing.py), published inside this document
    briefing: { text: "The market is leaning bullish: 6 of 10 coins are in a bullish 4H regime and 2 in a bearish one. Bitcoin is in a bull 4H regime (+1.8% in 24 hours); Ether is in a bearish consolidation 4H regime (-0.9% in 24 hours). 7 of 10 coins trade above their 4H 50-period average and 6 are up on the day. Fear & Greed reads 64 (Greed) and Bitcoin's dominance is 57.2%. Next high-impact US release: CPI m/m in about 26.0 hours; new entries pause around it.",
      bullets: ["Mood (4H): 6 bullish · 2 neutral · 2 bearish", "BTC +1.8% 24h · ETH -0.9% 24h", "Open calls: 3 long · 1 short · 1 waiting for entry", "24h: strongest AAVE +4.4% · weakest DOGE -2.2%", "Fear & Greed 64 · BTC dominance 57.2%"],
      source: "ai", model: "gemini-flash-lite-latest", at: NOW - 75 * 60_000, reason: "every 4 h", mood: "BULL",
      note: "Written by AI from the engine's own numbers. Context, not advice; it never changes a signal." },
  };
}

/** v2.16 views/coin_reports (backend/app/services/coin_reports.py): one entry per coin, no live price inside. */
function coinReports() {
  const reports: Record<string, any> = {};
  COINS.forEach(([sym, px], i) => {
    const up = REG[i].includes("BULL"), coin = sym === "PAXG/USDT" ? "GOLD" : sym.split("/")[0];
    const trend = REG[i] === "NEUTRAL" ? "Sideways" : up ? "Uptrend" : "Downtrend";
    const sup = [+(px * 0.968).toPrecision(6), +(px * 0.941).toPrecision(6)], res = [+(px * 1.034).toPrecision(6), +(px * 1.071).toPrecision(6)];
    const call = i === 0 ? { timeframe: "4h", side: "LONG", fill_status: "FILLED", entry: +(px * 0.994).toPrecision(6), stop: +(px * 0.976).toPrecision(6), tp1: +(px * 1.012).toPrecision(6), tp2: +(px * 1.024).toPrecision(6), tp3: +(px * 1.036).toPrecision(6), tp1_hit: 0, tp2_hit: 0, created_at: NOW - 3 * H } : null;
    reports[sym] = {
      symbol: sym, coin, trend: { label: trend, regime_4h: REG[i], regime_1d: up ? "BULL" : "BEARISH CONSOLIDATION" },
      levels: { support: sup, resistance: res },
      expects: [{ timeframe: "4h", lean: up ? "up" : "down", confidence: 0.54 + (i % 4) * 0.02, above_threshold: i % 3 !== 2, proven_edge: i % 2 === 0 },
        { timeframe: "12h", lean: i % 4 === 1 ? (up ? "down" : "up") : up ? "up" : "down", confidence: 0.53 + (i % 3) * 0.02, above_threshold: i % 2 === 0, proven_edge: true }],
      call, risk: i === 0 ? "No unusual risk flagged; any trade can still hit its stop." : i % 4 === 1 ? "The 4H and 12H AI leans point different ways." : "Volatility is high on 4H, so stops are hit more easily.",
      invalidation: call ? { price: call.stop, text: `The 4H long call ends if price trades below ${call.stop.toLocaleString("en-US", { maximumFractionDigits: 2 })} (its stop now).` }
        : { price: up ? sup[0] : res[0], text: `A move ${up ? "below the 4H support" : "above the 4H resistance"} near ${(up ? sup[0] : res[0]).toLocaleString("en-US", { maximumFractionDigits: 4 })} would undo the ${up ? "up" : "down"} lean.` },
      summary: `${coin}: ${trend.toLowerCase()} (4H ${REG[i].toLowerCase()}, 1D ${up ? "bull" : "bearish consolidation"}). AI view: 4H leans ${up ? "up" : "down"} (${54 + (i % 4) * 2}% confidence); 12H leans ${up ? "up" : "down"}. Key levels: support ${sup[0]}, resistance ${res[0]}.`,
      ai: i < 3 ? { text: i === 0 ? "BTC sits in an uptrend on both 4H and 1D, and the AI leans up on 4H with 54% confidence. The open 4H long is protected by its stop, which is also the level that would undo this view." : `${coin} keeps a ${trend.toLowerCase()} on 4H; the AI lean matches it, but with modest confidence.`, at: NOW - 40 * 60_000 } : null,
      bar_ts: NOW - 2 * H,
    };
  });
  return { reports, note: "Built from the engine's own analysis; AI lines are written only from these numbers. Context, not advice.", generated_at: NOW - 40 * 60_000 };
}

/** v2.16 smarter alerts: a member's rules (presets) and their fired events (views/alerts_u_<uid>). */
function alertsFor(uid: string) {
  const rules = {
    [`alerts/${uid}_sig`]: { type: "SIGNAL_UPDATES", symbol: "ALL/USDT", timeframe: "all", params: { events: ["entry", "tp1", "tp2", "tp3", "closed"] }, cooldown_s: 60, enabled: true, created_at: NOW - 2 * D, owner_uid: uid, owner_email: null },
    [`alerts/${uid}_mood`]: { type: "MOOD_CHANGE", symbol: "ALL/USDT", timeframe: "4h", params: {}, cooldown_s: 3600, enabled: true, created_at: NOW - 2 * D, owner_uid: uid, owner_email: null },
    [`alerts/${uid}_trade`]: { type: "TRADE_SETUP", symbol: "BTC/USDT", timeframe: "4h", params: { side: "any", market: "futures", min_confidence: 0, confident_only: false, grade: "A" }, cooldown_s: 3600, enabled: true, created_at: NOW - 3 * D, owner_uid: uid, owner_email: null },
  };
  const ev = (i: number, alert: string, type: string, symbol: string, message: string, ago: number) => ({ id: `ev${i}`, alert_id: `${uid}_${alert}`, created_at: NOW - ago, symbol, type, message });
  return {
    ...rules,
    [`views/alerts_u_${uid}`]: v({ state: { [`${uid}_sig`]: { last_fired_at: NOW - 20 * 60_000, last_state: "primed" }, [`${uid}_mood`]: { last_fired_at: NOW - 9 * H, last_state: null } },
      events: [
        ev(1, "sig", "TP2_REACHED", "SOL/USDT", "SOL 4H LONG: TP2 172.31 hit, stop moves to TP1", 20 * 60_000),
        ev(2, "sig", "ENTRY_REACHED", "ETH/USDT", "ETH 1H SHORT: entry reached at 2,471.80, the trade is live. Stop 2,509.00 · TP1 2,434.60", 95 * 60_000),
        ev(3, "sig", "SIGNAL_CLOSED", "DOGE/USDT", "DOGE 15M SHORT: stopped out · -0.94% after fees", 4 * H),
        ev(4, "mood", "MOOD_CHANGE", "ALL/USDT", "Market mood turned bullish (was bearish): 6 of 10 coins in a bullish 4H regime, 2 bearish", 9 * H),
        ev(5, "sig", "TP3_REACHED", "XRP/USDT", "XRP 1H LONG: TP3 0.5292 hit, all targets hit", 11 * H),
      ], types: {} }),
  };
}

/** Signal log rows shaped like tracking.signal_history + views.contract_fields (every real status appears). */
function signalLog() {
  const rows: any[] = [];
  const st: [string, string | null][] = [["OPEN", null], ["TP1", "trail"], ["TP2", "trail"], ["TP3", "tp3"], ["STOPPED", "stop"], ["TP1", "break_even"], ["EXPIRED", "expired"], ["NOT_FILLED", null], ["VOID", null], ["INFO", null]];
  const tfs = ["1h", "4h", "12h", "1d", "1h", "4h", "15m", "3d"];
  for (let i = 0; i < 42; i++) {
    const [symbol, price] = COINS[(i * 7) % COINS.length];
    const [status, exit] = st[i % st.length];
    const side = status === "INFO" ? 0 : i % 3 === 1 ? -1 : 1;
    const ret = status === "TP3" ? 3.1 : status === "TP2" ? 1.9 : status === "TP1" ? (exit === "break_even" ? 0.45 : 0.9) : status === "STOPPED" ? -1.7 : status === "EXPIRED" ? 0.2 : null;
    const lev = side ? 8 : null;
    rows.push({ id: `s${i}`, created_at: NOW - i * 11 * H - (i % 4) * 1_700_000, symbol, timeframe: tfs[i % tfs.length], signal: side > 0 ? "BUY" : side < 0 ? "SELL" : "HOLD",
      decision: side > 0 ? "BUY" : side < 0 ? "SELL" : "NO TRADE", price, confidence: 0.55 + (i % 5) * 0.03, side, stop: side ? price * (1 - side * 0.018) : null,
      status, tp1_hit: ["TP1", "TP2", "TP3"].includes(status) ? 1 : 0, tp2_hit: ["TP2", "TP3"].includes(status) ? 1 : 0, tp3_hit: status === "TP3" ? 1 : 0,
      stop_hit: status === "STOPPED" || exit === "break_even" ? 1 : 0, return_pct: ret, leverage: lev, roi_pct: ret != null && lev ? ret * lev : null,
      exit_reason: exit, fill_status: status === "NOT_FILLED" ? "NOT_FILLED" : side ? (status === "OPEN" && i % 20 === 10 ? "PENDING" : "FILLED") : null,
      payload: { grade: side ? (i % 4 === 3 ? "B" : "A") : null, decision_reason: side ? null : "the AI and the trend disagree" } });
  }
  return { signals: rows, summary: { closed: 18, win_rate: 0.61, avg_return_pct: 0.62, avg_roi_pct: 4.96, by_status: { TP1: 8, TP2: 4, TP3: 4, STOPPED: 4, EXPIRED: 4 }, not_filled: 4, void: 4 } };
}

/** Community posts (posts/{id}) and the usernames they are signed with. */
function community() {
  const out: Record<string, any> = { "owner/profile": { username: "hesper_ai", uid: "owner" } };
  for (const [n, uid] of [["hesper_ai", "owner"], ["sara_k", "u_member"], ["dreyes", "u_end"], ["omar_h", "u_pend1"], ["lina_trades", "u_pend2"], ["newperson", "u_new"]])
    out[`usernames/${n}`] = { uid, created_at: NOW - 5 * D };
  const posts: [string, string, string, number, boolean?][] = [
    ["owner", "hesper_ai", "Welcome to Community! Share how you use the signals, ask questions and help each other. Please keep it friendly, and remember: nothing here is financial advice.", 26 * H, true],
    ["u_end", "dreyes", "The 4H SOL long hit TP2 for me on the practice account. I moved my stop to break-even after TP1 like the bots do and it saved me on the ETH short yesterday.", 5 * H],
    ["u_member", "sara_k", "Question: do you all use the suggested leverage or go lower? I've been using half of it while I learn. Also found a good explainer at https://example.com/risk-basics (copy it, links aren't clickable here).", 3 * H],
    ["u_end", "dreyes", "@sara_k half is what I do too. The liquidation price in the position details panel makes it easy to see how much room you have.", 2 * H + 40 * 60_000],
    ["u_member", "sara_k", "Thanks! 🙏", 25 * 60_000],
  ];
  posts.forEach(([uid, username, text, ago, admin], i) => { out[`posts/p${i}`] = { author_uid: uid, username, text, created_at: NOW - ago, ...(admin ? { admin: true } : {}) }; });
  return out;
}

/** Practice futures + spot accounts of the preview member (and the owner), for the Trade page. */
function practice(uid: string) {
  const px = (s: string) => PRICES[s].p;
  const pos = (key: string, symbol: string, side: 1 | -1, lev: number, margin: number, ago: number, entryK: number, extra: any = {}) => {
    const entry = px(symbol) * entryK, qty = margin * lev / entry;
    return { key, symbol, side, qty, entry, margin, leverage: lev, liq: side > 0 ? entry * (1 - 1 / lev + 0.005) : entry * (1 + 1 / lev - 0.005),
      stop: null, take: null, opened_at: NOW - ago, checked_at: NOW - 60_000, funded_until: NOW - ago, funding: 0.0001 * qty * entry * Math.floor(ago / (8 * H)), fees: qty * entry * 0.0005, ...extra };
  };
  const btc = pos("BTCUSDT", "BTC/USDT", 1, 10, 500, 5 * H + 12 * 60_000, 0.992, { stop: px("BTC/USDT") * 0.975, take: px("BTC/USDT") * 1.03,
    auto: true, signal: { id: "c0", symbol: "BTC/USDT", timeframe: "4h", grade: "A", side: "LONG", at: NOW - 5 * H - 20 * 60_000 } });
  const eth = pos("ETHUSDT", "ETH/USDT", -1, 5, 300, 26 * H, 1.011, { stop: px("ETH/USDT") * 1.03 });
  const sol = pos("SOLUSDT", "SOL/USDT", 1, 20, 150, 40 * 60_000, 0.996);
  const acc = { id: `acc_${uid}`, starting_balance: 1000, deposited: 10000, deposit_count: 2, deposits: [{ amount: 5000, at: NOW - 3 * D + H }, { amount: 4000, at: NOW - 2 * D }],
    wallet: 8890.4, created_at: NOW - 3 * D, position_mode: "oneway",
    positions: { BTCUSDT: btc, ETHUSDT: eth, SOLUSDT: sol },
    orders: { o1: { id: "o1", symbol: "AVAX/USDT", side: 1, price: px("AVAX/USDT") * 0.97, margin: 200, leverage: 5, stop: px("AVAX/USDT") * 0.94, take: null, reserve: 200.2, created_at: NOW - 2 * H, checked_at: NOW - 60_000 } },
    totals: { realized: 142.6, fees: 9.8, funding: 1.2, count: 6, wins: 4, liquidations: 0 } };
  const out: Record<string, any> = { [`paper/${uid}_futures`]: acc,
    [`paper/${uid}_spot`]: { id: `spot_${uid}`, starting_balance: 1000, deposited: 10000, deposit_count: 1, deposits: [{ amount: 9000, at: NOW - 3 * D + H }], cash: 7420.5, created_at: NOW - 3 * D, benchmark_symbol: "BTC/USDT", benchmark_price: px("BTC/USDT") * 0.97,
      positions: { XRPUSDT: { symbol: "XRP/USDT", qty: 2100, avg_price: px("XRP/USDT") * 0.982, opened_at: NOW - 30 * H, fees: 1.08 }, BNBUSDT: { symbol: "BNB/USDT", qty: 2.2, avg_price: px("BNB/USDT") * 1.006, opened_at: NOW - 4 * H, fees: 1.3 } },
      totals: { realized: 18.2, fees: 3.4, slippage: 0.8, count: 4 } } };
  const trades: [string, string, number, number, number, number | null][] = [["CLOSE", "XRP/USDT", 1, 0.5161, 7 * H, 61.2], ["OPEN", "XRP/USDT", 1, 0.5081, 20 * H, null], ["CLOSE", "DOGE/USDT", -1, 0.1401, 30 * H, -24.4],
    ["OPEN", "DOGE/USDT", -1, 0.1392, 40 * H, null], ["OPEN", "ETH/USDT", -1, eth.entry, 26 * H, null], ["OPEN", "BTC/USDT", 1, btc.entry, 5 * H, null]];
  trades.forEach(([type, symbol, side, price, ago, pnl], i) => {
    out[`paper_futures_trades/${uid}_t${i}`] = { account_id: acc.id, uid, type, symbol, side, price, qty: 1000 / price, fee: 0.5, realized_pnl: pnl, reason: type === "CLOSE" ? (pnl! > 0 ? "take-profit" : "stop-loss") : undefined,
      leverage: 10, margin: 100, created_at: NOW - ago, mode: "PAPER FUTURES" };
  });
  return out;
}

export function seed(): Record<string, any> {
  const tfs = ["15m", "1h", "4h", "12h", "1d", "3d"];
  const out: Record<string, any> = {
    "config/watchlist": { symbols: COINS.map(([s], i) => ({ symbol: s, pinned: i < 2 })) },
    "config/limits": { member_coin_limit: 5, member_coins_max: 0 },
    "views/meta": v({ watchlist: COINS.map(([s], i) => ({ symbol: s, pinned: i < 2 ? 1 : 0 })), policy: { min_confidence: 0.55, min_model_agreement: 0.6, min_risk_reward: 1.25, require_edge_for_ml: true, require_edge_for_trade: true, edge_alpha: 0.05 }, costs: { fee_rate: 0.001, slippage_bps: 2, spread_bps: 1 } }),
    "views/track_record": v(trackRecord()),
    "views/public_record": v(publicRecord()),
    "views/wins_today": v({ period: "today", window_hours: 24, closed: 7, losses: 2, wins: [
      { symbol: "XRP/USDT", timeframe: "1h", side: "LONG", entry: 0.5081, status: "TP3", return_pct: 3.12, leverage: 10, roi_pct: 31.2, closed_at: NOW - 2 * H, target: 0.5292 },
      { symbol: "SOL/USDT", timeframe: "4h", side: "LONG", entry: 164.1, status: "TP2", return_pct: 2.31, leverage: 10, roi_pct: 23.1, closed_at: NOW - 5 * H, target: 168.9 },
      { symbol: "AVAX/USDT", timeframe: "1h", side: "SHORT", entry: 27.92, status: "TP2", return_pct: 1.88, leverage: 9, roi_pct: 16.92, closed_at: NOW - 8 * H, target: 27.11 },
      { symbol: "1000PEPE/USDT", timeframe: "15m", side: "SHORT", entry: 0.00001234, status: "TP1", return_pct: 0.71, closed_at: NOW - 9 * H, target: 0.00001225 }] }),
    "views/news": v({ generated_at: NOW - 12 * 60_000, errors: [], calendar: [{ id: "ppi", title: "PPI m/m", ts: NOW - 3 * H, impact: "High", forecast: "0.2%", previous: "0.1%", actual: "0.4%", country: "USD", after: { verdict: "bearish", data_read: "bearish", move_1h: -1.12, move_4h: -1.64, swing_1h: 1.9, summary: "Came in hotter than expected (0.4% vs 0.2% forecast). Hot inflation keeps interest rates high, which usually weighs on crypto. BTC fell 1.12% in the hour after (-1.64% after 4 h)." } }, { id: "cpi", title: "CPI m/m", ts: NOW + 26 * H, impact: "High", forecast: "0.2%", previous: "0.3%", country: "US" }, { id: "nfp", title: "Non-Farm Employment Change", ts: NOW + 50 * H, impact: "High", forecast: "150K", previous: "142K", country: "US" }], headlines: newsHeads(), sources: { calendar: "Forex Factory weekly economic calendar", headlines: "CoinDesk, Cointelegraph, Decrypt" }, next_high: { title: "CPI m/m", ts: NOW + 26 * H }, last_high: { id: "ppi", title: "PPI m/m", ts: NOW - 3 * H, impact: "High", country: "USD", after: { verdict: "bearish", data_read: "bearish", move_1h: -1.12, move_4h: -1.64, summary: "Came in hotter than expected (0.4% vs 0.2% forecast). Hot inflation keeps interest rates high, which usually weighs on crypto. BTC fell 1.12% in the hour after (-1.64% after 4 h)." } },
      sentiment: { latest: { market: { score: 0.28, ts: NOW - 0.4 * H, source: "headlines", headlines: 18 }, BTC: { score: 0.41, ts: NOW - 0.4 * H }, ETH: { score: 0.12, ts: NOW - 0.4 * H }, alts: { score: -0.18, ts: NOW - 0.4 * H } },
        series: Array.from({ length: 48 }, (_, i) => ({ ts: NOW - (47 - i) * H, score: Math.round((0.25 * Math.sin(i / 6) + i / 120) * 100) / 100 })) } }),
    "views/radar": v({ fast: fastRadar(), picks: [{ rank: 1, symbol: "SUI/USDT", price: 1.92, change_24h_pct: 6.1, quote_volume: 4.1e8, rs_7d: 0.142, rs_30d: 0.31, reasons: [] }, { rank: 2, symbol: "INJ/USDT", price: 21.4, change_24h_pct: 3.4, quote_volume: 1.2e8, rs_7d: 0.096, rs_30d: 0.12, reasons: [] }, { rank: 3, symbol: "TIA/USDT", price: 5.2, change_24h_pct: 2.2, quote_volume: 0.9e8, rs_7d: 0.061, rs_30d: -0.02, reasons: [] }], historical: {}, live: {}, scorecard: {
      since: Date.now() - 10 * 864e5, days: 10, counts: {}, suggest_remove: ["GALA/USDT", "BARD/USDT", "UNI/USDT"],
      labels: { best: "Best results", working: "Making money", early: "Too early to judge", losing: "Losing after fees", quiet: "No signals" },
      method: "From the real record only, after fees (sample data in preview).",
      study: { stamp: "x", method: "Sample study in preview.", baseline: { expectancy_r: -0.044 }, candidates: [
        { symbol: "HBAR/USDT", trades: 81, avg_r: 0.19, win_rate: 0.65, trades_per_week: 15.2, listings: { binance_futures: true, mexc_futures: true }, verdict: "add" },
        { symbol: "SHIB/USDT", trades: 45, avg_r: 0.09, win_rate: 0.51, trades_per_week: 3.6, listings: { binance_futures: true, mexc_futures: true }, verdict: "add" },
        { symbol: "ETC/USDT", trades: 19, avg_r: 0.33, win_rate: 0.58, trades_per_week: 1.2, listings: { binance_futures: true, mexc_futures: true }, verdict: "promising" },
        { symbol: "FIL/USDT", trades: 52, avg_r: 0.08, win_rate: 0.54, trades_per_week: 13.5, listings: { binance_futures: true, mexc_futures: false }, verdict: "no_mexc" },
        { symbol: "OP/USDT", trades: 19, avg_r: -0.47, win_rate: 0.32, trades_per_week: 2.8, listings: { binance_futures: true, mexc_futures: true }, verdict: "avoid" } ] },
      coins: [
        { symbol: "ETH/USDT", pinned: false, calls: 9, closed: 7, wins: 5, win_rate: 0.71, avg_net_pct: 0.62, total_net_pct: 4.3, open: 1, blocked: 4, last_call_at: Date.now() - 3 * 36e5, category: "best", suggest_remove: false, why: null, watched_days: 10 },
        { symbol: "SOL/USDT", pinned: false, calls: 6, closed: 5, wins: 3, win_rate: 0.6, avg_net_pct: 0.41, total_net_pct: 2.1, open: 0, blocked: 2, last_call_at: Date.now() - 20 * 36e5, category: "best", suggest_remove: false, why: null, watched_days: 10 },
        { symbol: "LINK/USDT", pinned: false, calls: 5, closed: 4, wins: 1, win_rate: 0.25, avg_net_pct: 0.12, total_net_pct: 0.5, open: 0, blocked: 1, last_call_at: Date.now() - 50 * 36e5, category: "working", suggest_remove: false, why: null, watched_days: 10 },
        { symbol: "BTC/USDT", pinned: true, calls: 2, closed: 1, wins: 1, win_rate: 1, avg_net_pct: 0.8, total_net_pct: 0.8, open: 1, blocked: 3, last_call_at: Date.now() - 6 * 36e5, category: "early", suggest_remove: false, why: null, watched_days: 10 },
        { symbol: "DOGE/USDT", pinned: false, calls: 6, closed: 5, wins: 1, win_rate: 0.2, avg_net_pct: -0.55, total_net_pct: -2.8, open: 0, blocked: 0, last_call_at: Date.now() - 30 * 36e5, category: "losing", suggest_remove: false, why: null, watched_days: 10 },
        { symbol: "UNI/USDT", pinned: false, calls: 3, closed: 2, wins: 0, win_rate: 0, avg_net_pct: -0.4, total_net_pct: -0.8, open: 0, blocked: 2, last_call_at: Date.now() - 40 * 36e5, category: "early", suggest_remove: true, why: "past test: -0.20R per trade over 74 trades (losing after fees)", watched_days: 10, past_test: { avg_r: -0.2, trades: 74, win_rate: 0.39 } },
        { symbol: "GALA/USDT", pinned: false, calls: 0, closed: 0, wins: 0, win_rate: null, avg_net_pct: null, total_net_pct: null, open: 0, blocked: 5, last_call_at: null, category: "quiet", suggest_remove: true, why: "no public signal in 10 days", watched_days: 10 },
        { symbol: "BARD/USDT", pinned: false, calls: 0, closed: 0, wins: 0, win_rate: null, avg_net_pct: null, total_net_pct: null, open: 0, blocked: 0, last_call_at: null, category: "quiet", suggest_remove: true, why: "no public signal in 10 days", watched_days: 10 },
      ] } }),
    "views/context": v({ market: { total_market_cap_usd: 2.41e12, market_cap_change_24h_pct: 1.21, btc_dominance: 56.4 }, sentiment: { value: 64, label: "Greed", change_7d: 9, history: Array.from({ length: 30 }, (_, i) => ({ ts: NOW - (29 - i) * D, value: 45 + Math.round(15 * Math.sin(i / 4)) + i / 2 })) } }),
    "views/market_context": v(marketContext()),
    "views/coin_reports": v(coinReports()),
    "views/analysis_BTCUSDT_4h": v(assetAnalysis()),
    "views/derivs": v(derivs()),
    ...alertsFor("u_member"),
    ...alertsFor("owner"),
    "views/cross_asset_1d": v({ observations: ["BTC dominance rising: large caps lead, altcoins lag.", "7 of 10 tracked coins are above their 50-day average."] }),
    "views/health": v(health()),
    "views/bots": v(liveView("bots") ?? botsView()),
    "owner/telegram_status": { ok: true, checked_at: NOW - 6 * 60_000, errors: [], last_post_at: NOW - 2 * H, last_sent: ["win"] },
    "views/health_errors": v({ generated_at: NOW, recent_errors: [{ ts: NOW - 2 * H, where: "engine news_publish", error: "TimeoutError: calendar feed did not answer" }], exchange_last_error: null, market_data_last_error: null, model_messages: [] }),
    "views/settings": v({ risk_profile: { portfolio: 10000, risk_per_trade_pct: 1, max_daily_loss_pct: 3, max_exposure_pct: 50, max_position_pct: 20, target_annual_vol_pct: 40 }, signal_weights: { trend: 0.3, momentum: 0.2, volume: 0.1, structure: 0.15, volatility: 0.05, ml: 0.15, htf: 0.05 } }),
    "views/signals": v(signalLog()),
    "views/weekly_report": v(weekly()),
    "views/scalping": v(scalping()),
    "views/hesper": v(hesper()),
    "views/guardian": v(guardian()),
    "views/market_turn": v(marketTurn()),
    "views/risk_state": v(riskState()),
    "views/market_regime": v(marketRegime()),
    "views/model_registry": v(modelRegistry()),
    "views/perf_lab": v(perfLab()),
    ...leaderboard(),
    "config/hesper": { visibility: "members", updated_at: Date.now(), by: "owner" },   // preview: members see the challenge tab
    "users/u_member_self": undefined,
    ...users(),
    ...presence(),
    ...community(),
    ...practice("u_member"),
    ...practice("owner"),
  };
  for (const tf of tfs) {
    out[`views/dashboard_${tf}`] = v(dashboard(tf));
    out[`views/futures_${tf}`] = v({ timeframe: tf, rows: futuresRows(tf) });
  }
  // v2.20 Home: the admin's Trade Guardian card reads views/guardian (shape of backend services/guardian.view)
  out["views/guardian"] = out["views/guardian"] ?? v({ generated_at: NOW - 4 * 60_000, enabled: true,
    status: { last_check: NOW - 4 * 60_000, watched: { coins: ["BTC/USDT", "SOL/USDT"], calls: 3 }, today: {}, day: null, last_error: null },
    live: [{ id: "g1", signal_id: "seed-BTC/USDT-4h", symbol: "BTC/USDT", timeframe: "4h", side: 1, level: "TIGHTEN", rules_level: "TIGHTEN", severity: 0.62, created_at: NOW - 30 * 60_000, expires_at: NOW + 60 * 60_000, status: "live" }],
    history: [], scoreboard: { n: 4, saved_r: 0.9, cost_r: -0.3, net_r: 0.6, helped: 3, hurt: 1, pending: 1 }, config: {}, note: "Recommend-only." });
  delete out["users/u_member_self"];
  return out;
}

/** views/bots: the shape backend/app/services/bots.report publishes (six futures signal bots, trades left out). */
function botsView() {
  const line: [string, string, number, number, number][] = [["15m", "A", 1.8, 14, 1], ["1h", "A", -0.9, 9, 1], ["4h", "A+B", 3.4, 6, 2], ["12h", "A+B", 0.6, 3, 1], ["1d", "A", 0, 1, 0], ["3d", "A", -0.4, 1, 0]];
  const bots = line.map(([tf, g, ret, trades, open]) => {
    const start = 10_000, eq = start * (1 + ret / 100);
    const positions = Array.from({ length: open }, (_, i) => {
      const sym = ["BTC/USDT", "SOL/USDT", "ETH/USDT"][i % 3], px = PRICES[sym].p;
      return { id: `${tf}-p${i}`, symbol: sym, side: i % 2 ? -1 : 1, qty_open: 1500 / px, entry: px * (i % 2 ? 1.004 : 0.996), lev: 12, liq: px * (i % 2 ? 1.07 : 0.93), stop: px * (i % 2 ? 1.018 : 0.982), tp_hit: i };
    });
    return { config: { id: `futures-signal-ab-${tf}`, name: `Futures signals ${g} · ${tf.toUpperCase()}`, mode: "signal", market: "futures", timeframe: tf, grades: g === "A" ? ["A"] : ["A", "B"], leverage: 20, safe_leverage: true, enabled: true, starting_balance: start },
      state: { cash: eq * 0.8, equity: eq, benchmark: start, started_at: NOW - 30 * H, updated_at: NOW - 3 * 60_000, fees_paid: trades * 3.1, funding_paid: trades * 0.4, liquidations: 0 },
      positions, pending: [],
      stats: { trades, return_pct: ret, equity: eq, benchmark_return_pct: 0.8, open_positions: open, win_rate: trades ? 0.56 : null, profit_factor: 1.2, max_drawdown_pct: -1.4, fees_paid: trades * 3.1, funding_paid: trades * 0.4, liquidations: 0, by_exit: {} },
      trades: [], equity_curve: Array.from({ length: 40 }, (_, k) => ({ ts: NOW - (30 - k * 0.75) * H, equity: start * (1 + (ret / 100) * (k / 39) + Math.sin(k * 0.7 + ret) * 0.004), benchmark: start * (1 + 0.008 * k / 39) })) };
  });
  const funding = Object.fromEntries(COINS.slice(0, 8).map(([s], i) => [s, { rate: 0.0001 * (1 + (i % 3)), source: "OKX" }]));
  return { bots, defaults: [], path_timeframe: "15m", funding, generated_at: NOW - 3 * 60_000 };
}

/** views/health: the same shape backend/app/services/health.report + worker.engine_info publish. */
function health() {
  const tfs = ["15m", "1h", "4h", "12h", "1d", "3d"];
  const syms = COINS.slice(0, 4).map(([s]) => s);
  return {
    status: "LIVE", generated_at: NOW, uptime_s: 18_000,
    engine: { last_tick_started: NOW - 4 * 60_000, last_tick_finished: NOW - 3 * 60_000, last_tick_seconds: 61.4, schedule_minutes: 5, ticks: 412,
      data_host: "https://data-api.binance.vision", failed_steps: [], last_train: { finished_at: NOW - 9 * H },
      firestore_writes_today: 8_430, firestore_write_budget: 15_000, firestore_reads_today: 6_120, firestore_read_limit: 50_000, firestore_lean: false, firestore_members_active: 23,
      firestore_member_reserve: 1_380, firestore_engine_budget: 13_620, firestore_free_limit: 20_000 },
    market_data: { status: "LIVE", transport: "REST", last_update_ms: NOW - 3 * 60_000, age_s: 180, reconnects: 0, last_error: null, quality_pct: 99.97, stale_series: 0 },
    exchange: { errors: 0, clock_skew_ms: 42, last_error: null },
    database: { ok: true, engine: "sqlite" },
    series: syms.flatMap((s) => tfs.map((tf) => ({ symbol: s, timeframe: tf, status: "OK", candles: 30_000, missing: 0, duplicates: 0, malformed: 0, quality_pct: 100, age_s: 240 }))),
    models: syms.flatMap((s) => tfs.map((tf, i) => ({ symbol: s, timeframe: tf, version: `v-${s.slice(0, 3)}-${tf}`, trained_at: NOW - 9 * H, age_h: 9, edge_confirmed: i % 2 === 0, state: "active", progress: null, message: null }))),
    model_libraries: [{ name: "lightgbm", label: "LightGBM", available: true }, { name: "torch", label: "Deep models (PyTorch)", available: false, reason: "not installed on the engine" }],
    recent_errors: [{ ts: NOW - 2 * H, where: "engine news_publish", error: "TimeoutError: calendar feed did not answer" }],
    safety: [],
    config: { exchange: "binance", background_jobs: false, websocket_feed: false, deep_models: false, forecast_refresh_s: 300, retrain_interval_h: 24, mode: "ANALYSIS ONLY - no real orders are ever placed" },
  };
}

/** views/scalping: the shape backend/app/views.scalping publishes (15m grade-A demo calls, admin scorecard). */
function scalping() {
  const M15 = 900_000;
  const since = NOW - 9 * D;
  const coins = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT", "DOGE/USDT", "AVAX/USDT", "LTC/USDT"];
  // [status, return %, tp1, tp2, tp3, hold minutes]
  const outcomes: [string, number, number, number, number, number][] = [
    ["TP1", 0.31, 1, 0, 0, 95], ["STOPPED", -0.62, 0, 0, 0, 40], ["TP3", 1.18, 1, 1, 1, 210], ["TP2", 0.74, 1, 1, 0, 160],
    ["STOPPED", -0.55, 0, 0, 0, 25], ["TP1", 0.28, 1, 0, 0, 130], ["EXPIRED", -0.12, 0, 0, 0, 3750], ["TP2", 0.69, 1, 1, 0, 185],
    ["STOPPED", -0.58, 0, 0, 0, 55], ["TP1", 0.33, 1, 0, 0, 70], ["TP3", 1.06, 1, 1, 1, 240], ["STOPPED", -0.6, 0, 0, 0, 35],
    ["TP1", 0.3, 1, 0, 0, 120], ["TP2", 0.71, 1, 1, 0, 175],
  ];
  const lev = 20;
  const closed = outcomes.map(([status, ret, t1, t2, t3, hold], i) => {
    const symbol = coins[i % coins.length], px = PRICES[symbol].p, side = i % 3 === 1 ? "SHORT" : "LONG", k = side === "LONG" ? 1 : -1;
    const created = since + (i + 1) * 14 * H, entry = px * (1 - 0.01 * Math.sin(i)), risk = entry * 0.006;
    return { id: `sc${i}`, symbol, timeframe: "15m", side, decision: side === "LONG" ? "BUY" : "SELL", grade: "A", created_at: created, entry, stop: entry - k * risk,
      tp1: entry + k * risk, tp2: entry + k * risk * 1.5, tp3: entry + k * risk * 2, status, closed_at: created + hold * 60_000, return_pct: ret, leverage: lev, rebuilt: i < 6,
      fill_status: "FILLED", peak_r: null, peak_pct: null, exit_reason: status === "STOPPED" ? "stop" : status === "EXPIRED" ? "expired" : status === "TP3" ? "tp3" : "break_even",
      managed: 0, tp1_hit: t1, tp2_hit: t2, tp3_hit: t3, stop_hit: status === "STOPPED" ? 1 : 0, horizon_bars: 250, expires_at: created + 250 * M15, filled_at: created, hold_min: hold };
  });
  const missed = { ...closed[0], id: "scm", symbol: "BTC/USDT", status: "NOT_FILLED", fill_status: "NOT_FILLED", return_pct: null, rebuilt: false, created_at: NOW - 30 * H, closed_at: NOW - 28 * H, tp1_hit: 0, tp2_hit: 0, tp3_hit: 0, stop_hit: 0, exit_reason: null, hold_min: undefined };
  const openRow = (id: string, symbol: string, side: "LONG" | "SHORT", ago: number, tp1: number, pending = false) => {
    const px = PRICES[symbol].p, k = side === "LONG" ? 1 : -1, entry = px * (1 - k * 0.0015), risk = entry * 0.005, created = NOW - ago;
    return { id, symbol, timeframe: "15m", side, decision: pending ? "BUY ON PULLBACK" : side === "LONG" ? "BUY" : "SELL", grade: "A", created_at: created, entry, stop: entry - k * risk,
      tp1: entry + k * risk, tp2: entry + k * risk * 1.5, tp3: entry + k * risk * 2, status: "OPEN", closed_at: null, return_pct: null, leverage: lev, rebuilt: false,
      fill_status: pending ? "PENDING" : "FILLED", peak_r: 0.6, peak_pct: 0.3, exit_reason: null, managed: 0, tp1_hit: tp1, tp2_hit: 0, tp3_hit: 0, stop_hit: 0,
      horizon_bars: 250, expires_at: created + 250 * M15, ...(pending ? {} : { filled_at: created }) };
  };
  const open = [openRow("so1", "SOL/USDT", "LONG", 50 * 60_000, 1), openRow("so2", "ETH/USDT", "SHORT", 20 * 60_000, 0), openRow("so3", "AVAX/USDT", "LONG", 10 * 60_000, 0, true)];
  const rets = closed.map((x) => x.return_pct);
  let acc = 0, peak = 0, dd = 0;
  const curve = closed.map((x) => { acc += x.return_pct; peak = Math.max(peak, acc); dd = Math.max(dd, peak - acc); return { ts: x.closed_at, cum_return_pct: acc, rebuilt: x.rebuilt }; });
  const wins = rets.filter((r) => r > 0), losses = rets.filter((r) => r <= 0);
  const best = closed.reduce((a, b) => (b.return_pct > a.return_pct ? b : a)), worst = closed.reduce((a, b) => (b.return_pct < a.return_pct ? b : a));
  const pick = (x: any) => ({ id: x.id, symbol: x.symbol, side: x.side, status: x.status, return_pct: x.return_pct, closed_at: x.closed_at, rebuilt: x.rebuilt });
  const mean = (a: number[]) => a.reduce((p, q) => p + q, 0) / a.length;
  const part = (xs: any[]) => { const r = xs.map((x) => x.return_pct), w = r.filter((q) => q > 0); return xs.length ? { closed: xs.length, wins: w.length, losses: xs.length - w.length, win_rate: w.length / xs.length, avg_return_pct: mean(r), total_return_pct: r.reduce((a, b) => a + b, 0) } : { closed: 0 }; };
  return {
    generated_at: NOW, since, timeframe: "15m", grades: ["A"], started: true, logged: closed.length + open.length + 1,
    label: "Demo results · 15m scalping · not public · before fees",
    method: "Every live 15m grade-A call the engine issues to the demo bots, logged the moment it is issued (it is never a public signal) and followed candle by candle with the track record's rules: entry at the card's entry, half closes at target 1 (stop to break-even), a quarter at target 2 (stop to target 1), a quarter at target 3, or the stop; time limit 250 candles. One call per coin at a time. Return = the trade's price return (no leverage), before fees.",
    summary: { closed: closed.length, wins: wins.length, losses: losses.length, win_rate: wins.length / closed.length, avg_return_pct: mean(rets), total_return_pct: acc,
      profit_factor: wins.reduce((a, b) => a + b, 0) / -losses.reduce((a, b) => a + b, 0), best: pick(best), worst: pick(worst), avg_hold_min: mean(closed.map((x) => x.hold_min)),
      hit_rates: { tp1: mean(closed.map((x) => x.tp1_hit)), tp2: mean(closed.map((x) => x.tp2_hit)), tp3: mean(closed.map((x) => x.tp3_hit)) },
      stop_rate: mean(closed.map((x) => (x.status === "STOPPED" ? 1 : 0))), streak: { kind: "win", n: 2, best_win: 2, best_loss: 1 },
      max_drawdown_pct: dd },
    open, recent: [missed, ...closed].sort((a, b) => (b.closed_at ?? 0) - (a.closed_at ?? 0)), curve, not_filled: 1, void: 0,
    split: { rebuilt: part(closed.filter((x) => x.rebuilt)), live: part(closed.filter((x) => !x.rebuilt)) },
    counts: { rebuilt: 6, live: closed.length - 6 + open.length + 1 },
    backfill: { state: "done", window_start: since, live_since: closed[6].created_at - 20 * 60_000, progress: 1, rebuilt: 6, replayed: 214,
      skipped: { already_open: 380, ai_below_threshold: 812, no_grade_a_call: 208, cooldown: 12 }, finished_at: NOW - 20 * H,
      note: "1-2 Nov rebuilt by replaying the engine's decisions on the candles of the time (the 15m model it used then, candles up to each call); from 02 Nov 10:30 UTC logged live." },
    bot: { id: "futures-demo-a-15m", name: "Futures demo bot 15M · grade A · TP1", enabled: true, starting_balance: 10000, equity: 10412.6, cash: 9310.2, return_pct: 4.13,
      trades: 19, win_rate: 0.63, profit_factor: 1.42, max_drawdown_pct: -2.4, open_positions: 2, fees_paid: 61.3, started_at: NOW - 12 * D,
      recent: closed.slice(-6).reverse().map((x) => ({ symbol: x.symbol, side: x.side, opened_at: x.created_at, closed_at: x.closed_at, entry: x.entry, exit: x.tp1, pnl: x.return_pct * 20,
        return_pct: x.return_pct > 0 ? 0.31 : -0.6, exit_reason: x.return_pct > 0 ? "take profit 1" : "stop loss" })) },
  };
}

/** views/hesper: the shape backend/app/services/hesper.view publishes (Road to Rich, admin only). Sample runs. */
function hesper() {
  const v = hesperBase();
  extraTrades(v.current, 10);
  extraTrades(v.laststand.current, 15);
  return v;
}

function hesperBase(): any {
  const coins = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT", "DOGE/USDT", "AVAX/USDT", "LTC/USDT", "AAVE/USDT", "PAXG/USDT"];
  const tfs = ["15m", "1h", "4h", "12h", "1h", "4h", "1d", "1h"];
  const reasons: Record<string, string> = { w1: "TP1", w2: "TP2", w3: "TP3", be: "breakeven stop", tr: "trailing stop", l: "stop", t: "time exit", liq: "liquidated" };
  // per run: [result, reason, [roi %, exit key][]]
  const plan: [string, string | null, [number, string][]][] = [
    ["FAIL", "busted", [[38, "w2"], [-61, "l"], [24, "w1"], [-58, "l"], [-63, "l"], [12, "be"], [-60, "l"], [-62, "l"], [-64, "l"]]],
    ["FAIL", "liquidated", [[44, "w3"], [-100, "liq"]]],
    ["SUCCESS", "goal", [[52, "w3"], [21, "be"], [-55, "l"], [64, "w3"], [33, "tr"], [-49, "l"], [71, "w3"], [26, "w1"], [58, "w3"], [41, "w2"], [47, "w3"]]],
    ["FAIL", "busted", [[-57, "l"], [29, "w1"], [-62, "l"], [-60, "l"], [8, "t"], [-59, "l"], [-61, "l"], [-63, "l"]]],
    ["SUCCESS", "goal", [[66, "w3"], [48, "w3"], [-52, "l"], [73, "w3"], [39, "w2"], [55, "w3"], [62, "w3"]]],
    ["FAIL", "liquidated", [[31, "w2"], [-54, "l"], [-100, "liq"]]],
    // v2.22: open-ended run that passed $1,000 and was ended by the admin
    ["STOPPED", "stopped", [[68, "w3"], [57, "w3"], [-40, "l"], [72, "w3"], [61, "w3"], [49, "w3"], [-35, "l"], [44, "w2"], [30, "w2"]]],
    ["RUNNING", null, [[46, "w3"], [-51, "l"], [58, "w3"], [27, "be"], [36, "w2"]]],
  ];
  const runs: any[] = [], trades: any[] = [], curves: Record<string, number[][]> = {};
  let t = NOW - 21 * D, k = 0;
  plan.forEach(([result, reason, seq], ri) => {
    const run = ri + 1, start = t;
    let bal = 100, peak = 100, wins = 0, best: any = null;
    const pts: number[][] = [[start, 100]];
    for (const [roi, ex] of seq) {
      const symbol = coins[k % coins.length], tf = tfs[k % tfs.length], px = PRICES[symbol].p, side = k % 3 === 1 ? -1 : 1;
      const lev = [25, 22, 18, 25, 14, 20, 25, 11][k % 8], margin = bal * 0.995, pnl = margin * roi / 100;
      const opened = t + 1 * H, closed = opened + (2 + (k % 5) * 2) * H, move = roi / lev / 100;
      const tr = { id: `h${k}`, run, symbol, timeframe: tf, side, leverage: lev, opened_at: opened, closed_at: closed, entry: px * (1 - 0.01 * Math.sin(k)),
        exit: px * (1 - 0.01 * Math.sin(k)) * (1 + side * move), margin, pnl, roi_pct: roi, exit_reason: reasons[ex], tp_hit: ex.startsWith("w") ? Number(ex[1]) : ex === "be" ? 1 : ex === "tr" ? 2 : 0,
        balance_before: bal, balance_after: bal + pnl, fees: margin * lev * 0.001, funding: margin * lev * 0.0001 };
      bal += pnl; peak = Math.max(peak, bal); if (pnl > 0) wins += 1;
      if (!best || pnl > best.pnl) best = { id: tr.id, symbol, timeframe: tf, pnl, roi_pct: roi };
      trades.push(tr); pts.push([closed, bal]); t = closed; k += 1;
    }
    if (result === "SUCCESS" && bal < 1000) {             // the winning trade that crossed $1,000
      const symbol = coins[k % coins.length], px = PRICES[symbol].p, margin = bal * 0.995, pnl = 1000 * 1.04 - bal, roi = (pnl / margin) * 100;
      const opened = t + H, closed = opened + 6 * H;
      trades.push({ id: `h${k}`, run, symbol, timeframe: "4h", side: 1, leverage: 25, opened_at: opened, closed_at: closed, entry: px, exit: px * (1 + roi / 2500),
        margin, pnl, roi_pct: roi, exit_reason: "TP3", tp_hit: 3, balance_before: bal, balance_after: bal + pnl, fees: margin * 0.025, funding: margin * 0.002 });
      bal += pnl; peak = Math.max(peak, bal); wins += 1; if (pnl > best.pnl) best = { id: `h${k}`, symbol, timeframe: "4h", pnl, roi_pct: roi };
      pts.push([closed, bal]); t = closed; k += 1;
    }
    t += 3 * H;
    const hit = pts.find((p) => p[1] >= 1000);
    runs.push({ run, started_at: start, ended_at: result === "RUNNING" ? null : t - 3 * H, result, reason, start_balance: 100, end_balance: result === "RUNNING" ? null : bal,
      peak, trades: pts.length - 1, wins, best_trade: best, goal_reached_at: result === "STOPPED" && hit ? hit[0] : null });
    curves[String(run)] = pts;
  });
  const done = runs.filter((r) => r.result !== "RUNNING"), succ = done.filter((r) => r.result === "SUCCESS"), fails = done.filter((r) => r.result === "FAIL");
  const cur = runs[runs.length - 1];
  const fastest = succ.reduce((a, b) => (b.ended_at - b.started_at < a.ended_at - a.started_at ? b : a));
  const bestRun = runs.reduce((a, b) => (b.peak > a.peak ? b : a));
  const cash = cur.peak > 0 ? trades[trades.length - 1].balance_after : 100;
  const sol = PRICES["SOL/USDT"].p, entry = sol * 0.996, margin = cash * 0.995, lev = 22, qty = margin * lev / entry;
  return {
    name: "Hesper", since: runs[0].started_at, start: 100, goal: 1000, max_leverage: 25, min_balance: 1, started: true, generated_at: NOW,
    current: { run: cur.run, started_at: cur.started_at, cash: cash - margin / 2 + margin * 0.5 * 0.025 * lev, balance: cash * 1.06, peak: cur.peak, trades: cur.trades, wins: cur.wins, updated_at: NOW - 4 * 60_000,
      open: { id: "hopen", symbol: "SOL/USDT", timeframe: "4h", side: 1, entry, stop: entry, stop0: entry * 0.975, targets: [entry * 1.025, entry * 1.044, entry * 1.06], tp_hit: 1,
        leverage: lev, qty, qty_open: qty / 2, margin, coll: entry / lev, liq: entry * (1 - 1 / lev + 0.005), realized: margin * 0.5 * 0.025 * lev, opened_at: NOW - 7 * H,
        signal_id: "s-sol", confidence: 0.64, horizon_bars: 100, run_target: null, balance_before: cash, risk_pct: 10 }, pending: null,
      slots: 5, risk_pct: 10, pause_until: null, loss_streak: 0 },
    score: { successes: succ.length, failures: fails.length, stopped: done.filter((r) => r.result === "STOPPED").length,
      milestones: runs.filter((r) => r.result === "SUCCESS" || r.goal_reached_at).length, liquidations: fails.filter((r) => r.reason === "liquidated").length, busted: fails.filter((r) => r.reason === "busted").length,
      runs: runs.length, finished: done.length, best_peak: { run: bestRun.run, peak: bestRun.peak }, all_time_peak: bestRun.peak,
      avg_trades_per_run: done.reduce((a, r) => a + r.trades, 0) / done.length, fastest_success: { run: fastest.run, ms: fastest.ended_at - fastest.started_at, trades: fastest.trades },
      fewest_trades_success: { run: fastest.run, trades: fastest.trades }, trades: trades.length, wins: trades.filter((x) => x.pnl > 0).length, streak: { kind: "win", n: 3 } },
    runs: [...runs].reverse(), trades: [...trades].reverse(), curves, label: "Demo · virtual money · not financial advice",
    laststand: laststand(),
  };
}


/** v3.2: several open trades per challenge (up to 5): the seed's first trade + two more and a waiting order. */
function extraTrades(cur: any, risk: number) {
  const mk = (id: string, symbol: string, tf: string, side: number, move: number, lev: number, hours: number) => {
    const px = PRICES[symbol].p, entry = px * (1 - side * move), stop = entry * (1 - side * 0.02), margin = 12 * (risk / 10), qty = margin * lev / entry;
    return { id, symbol, timeframe: tf, side, entry, stop, stop0: stop, targets: [entry * (1 + side * 0.02), entry * (1 + side * 0.03), entry * (1 + side * 0.045)], tp_hit: 0,
      leverage: lev, qty, qty_open: qty, margin, coll: entry / lev, liq: entry * (1 - side / lev + side * 0.005), realized: -margin * 0.01, opened_at: NOW - hours * H,
      signal_id: `s-${id}`, horizon_bars: 200, run_target: null, risk_pct: risk, admin_partials: 0 };
  };
  cur.opens = [cur.open, mk(`${cur.open.id}-b`, "BTC/USDT", "1h", -1, -0.004, 20, 2), mk(`${cur.open.id}-x`, "XRP/USDT", "15m", 1, 0.006, 25, 1)];
  cur.pendings = [{ id: `${cur.open.id}-p`, symbol: "DOGE/USDT", timeframe: "4h", side: 1, limit: PRICES["DOGE/USDT"].p * 0.985, stop: PRICES["DOGE/USDT"].p * 0.96, leverage: 15, reserved: 10, placed_at: NOW - 30 * 60_000, expires_at: NOW + 20 * H }];
  return cur;
}

/** v2.63 Last Stand inside views/hesper: two liquidated runs and a live one that started from $10. */
function laststand() {
  const coins = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT", "DOGE/USDT"];
  const plan: [string, string | null, number, [number, string][]][] = [
    ["FAIL", "liquidated", 10, [[48, "TP3"], [31, "TP2"], [-100, "liquidated"]]],
    ["FAIL", "liquidated", 25, [[-52, "stop"], [64, "TP3"], [22, "closed by admin"], [-100, "liquidated"]]],
    ["RUNNING", null, 10, [[57, "TP3"], [41, "TP2"], [-38, "stop"], [62, "TP3"], [18, "closed by admin"]]],
  ];
  const runs: any[] = [], trades: any[] = [], curves: Record<string, number[][]> = {};
  let t = NOW - 6 * D, k = 0;
  plan.forEach(([result, reason, start, seq], ri) => {
    const run = ri + 1, t0 = t;
    let bal = start, peak = start, wins = 0;
    const pts: number[][] = [[t0, start]];
    for (const [roi, ex] of seq) {
      const symbol = coins[k % coins.length], px = PRICES[symbol].p, side = k % 3 === 1 ? -1 : 1, lev = [25, 20, 25, 18][k % 4];
      const margin = bal * 0.995, pnl = margin * roi / 100, opened = t + H, closed = opened + (3 + (k % 4) * 3) * H;
      trades.push({ id: `ls${k}`, run, symbol, timeframe: ["1h", "4h", "15m"][k % 3], side, leverage: lev, opened_at: opened, closed_at: closed, entry: px,
        exit: px * (1 + side * roi / lev / 100), margin, pnl, roi_pct: roi, exit_reason: ex, tp_hit: ex.startsWith("TP") ? Number(ex[2]) : 0,
        balance_before: bal, balance_after: bal + pnl, fees: margin * lev * 0.001, funding: 0 });
      bal += pnl; peak = Math.max(peak, bal); if (pnl > 0) wins += 1; pts.push([closed, bal]); t = closed; k += 1;
    }
    runs.push({ run, started_at: t0, ended_at: result === "RUNNING" ? null : t, result, reason, start_balance: start, end_balance: result === "RUNNING" ? null : bal,
      peak, trades: seq.length, wins, best_trade: null, goal_reached_at: null });
    curves[String(run)] = pts; t += 5 * H;
  });
  const cur = runs[runs.length - 1], cash = trades[trades.length - 1].balance_after;
  const eth = PRICES["ETH/USDT"].p, entry = eth * 0.994, lev = 25, margin = cash * 0.995, qty = margin * lev / entry;
  return {
    id: "laststand", name: "Last Stand", title: "Last Stand", auto_restart: false, min_start: 5, since: runs[0].started_at, start: 10, goal: 100,
    max_leverage: 25, min_balance: 1, started: true, idle: false, generated_at: NOW, open_ended: true,
    current: { run: cur.run, started_at: cur.started_at, cash: cash - margin, balance: cash * 1.07, peak: cur.peak, trades: cur.trades, wins: cur.wins, updated_at: NOW - 3 * 60_000,
      start_balance: 10, goal: 100, goal_reached_at: null, pending: null,
      open: { id: "lsopen", symbol: "ETH/USDT", timeframe: "1h", side: 1, entry, stop: entry * 0.985, stop0: entry * 0.985, targets: [entry * 1.015, entry * 1.025, entry * 1.035], tp_hit: 0,
        leverage: lev, qty, qty_open: qty, margin, coll: entry / lev, liq: entry * (1 - 1 / lev + 0.005), realized: -margin * 0.012, opened_at: NOW - 3 * H,
        signal_id: "s-eth", confidence: 0.66, horizon_bars: 200, run_target: null, balance_before: cash, admin_partials: 0, risk_pct: 15 },
      slots: 5, risk_pct: 15, pause_until: null, loss_streak: 1 },
    score: { runs: 3, finished: 2, failures: 2, liquidations: 2, busted: 0, stopped: 0, successes: 0, milestones: 0, trades: trades.length,
      wins: trades.filter((x) => x.pnl > 0).length, streak: { kind: "win", n: 2 }, best_peak: { run: 3, peak: cur.peak }, all_time_peak: cur.peak },
    runs: [...runs].reverse(), trades: [...trades].reverse(), curves, label: "Demo · virtual money · not financial advice",
  };
}

/** v2.16 practice leaderboard: views/leaderboard (members), admin/leaderboard (admin JSON), owner/leaderboard (prizes). */
function leaderboard(): Record<string, any> {
  const d = new Date(NOW + 4 * H);                 // Dubai month
  const mk = (y: number, m: number) => `${y}-${String(m + 1).padStart(2, "0")}`;
  const month = mk(d.getUTCFullYear(), d.getUTCMonth());
  const pm = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() - 1, 1));
  const prev = mk(pm.getUTCFullYear(), pm.getUTCMonth());
  const label = (k: string) => new Date(`${k}-01T00:00:00Z`).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
  const names: [string, string, number, number][] = [["kenji_w", "u_x8", 38.42, 14], ["sara_k", "u_member", 21.07, 9], ["mrossi", "u_x16", 12.9, 22],
    ["priya_n", "u_x1", 8.35, 6], ["dreyes", "u_end", 4.1, 11], ["elena_p", "u_x11", 1.02, 5], ["lucasm", "u_x2", -3.6, 8], ["aisha.r", "u_x7", -11.25, 17]];
  const rows = names.map(([username, , r, t], i) => ({ rank: i + 1, username, return_pct: r, trades: t }));
  const adminRows = names.map(([username, uid, r, t], i) => ({ uid, username, rank: i + 1, return_pct: r, trades: t, start_equity: 1000 + i * 250, deposits: i === 2 ? 5000 : 0,
    equity: (1000 + i * 250 + (i === 2 ? 5000 : 0)) * (1 + r / 100), unexplained: 0, flags: [] as string[], qualified: true }))
    .concat([{ uid: "u_x4", username: "ydemir", rank: null as any, return_pct: 64.2, trades: 3, start_equity: 1000, deposits: 0, equity: 1642, unexplained: 600, flags: ["balance changed without trades"], qualified: false }]);
  const winners = [{ month: prev, label: label(prev), uid: "u_member", username: "sara_k", return_pct: 27.4, trades: 12, decided_at: NOW - 2 * D }];
  return {
    "views/leaderboard": v({ month, label: label(month), since: NOW - 3 * D, generated_at: NOW - 20 * 60_000, min_trades: 5,
      rules: "Virtual money. Ranked by % return after deposits. Min 5 closed trades.", every_s: 3600, rows, ranked: rows.length, taking_part: 14,
      last_winner: { month: prev, label: label(prev), winners: [{ username: "sara_k", return_pct: 27.4, trades: 12 }] }, badges: { sara_k: [prev] } }),
    "admin/leaderboard": { json: JSON.stringify({ month, label: label(month), generated_at: NOW - 20 * 60_000, min_trades: 5, rows: adminRows, winners, excluded: [] }), updated_at: NOW },
    "owner/leaderboard": { awarded: {}, excluded: [] },
  };
}

/** views/guardian: the shape backend/app/services/guardian.Guardian.view publishes (v2.19 Trade Guardian, admin only). */
function guardian() {
  const M = 60_000;
  const rec = (o: any) => ({ rules_level: o.level, status: "live", status_at: null, status_reason: null, tp1_hit: false, ...o });
  const live = [
    rec({ id: "g1", signal_id: "s-sol", symbol: "SOL/USDT", timeframe: "1h", side: 1, level: "CLOSE", severity: 86,
      created_at: NOW - 4 * M, expires_at: NOW + 26 * M, price: 166.9, entry: 168.1, stop_in_force: 165.8, proposed_stop: null, atr: 0.82,
      reasons: [{ code: "move", label: "Moved 1.52 ATR against in 15 min", points: 30 }, { code: "flip", label: "1H analysis flipped to SELL", points: 25 },
        { code: "btc", label: "BTC -1.74% in 15 min", points: 20 }, { code: "volatility", label: "Volatility 2.9x normal", points: 10 }, { code: "near_stop", label: "0.47R from the stop", points: 15 }],
      ai: { path: "ai_agreed", model: "gemini-flash-lite-latest", text: "Solana dropped sharply against the long trade in the last 15 minutes while Bitcoin fell over the same window. The 1H analysis now points the other way, so the rules see more risk than reward in staying in." } }),
    rec({ id: "g2", signal_id: "s-avax", symbol: "AVAX/USDT", timeframe: "4h", side: -1, level: "TIGHTEN", rules_level: "CLOSE", severity: 77,
      created_at: NOW - 11 * M, expires_at: NOW + 19 * M, price: 27.58, entry: 27.2, stop_in_force: 27.95, proposed_stop: 27.81, atr: 0.19, tp1_hit: false,
      reasons: [{ code: "move", label: "Moved 1.10 ATR against in 60 min", points: 22 }, { code: "near_stop", label: "0.49R from the stop", points: 15 },
        { code: "volatility", label: "Volatility 4.2x normal", points: 15 }, { code: "grade_lost", label: "4H grade A no longer confirmed", points: 8 },
        { code: "funding", label: "Funding 3.4 sd against (estimate)", points: 5, estimate: true }],
      ai: { path: "ai_downgraded", model: "gemini-flash-lite-latest", text: "Avalanche rose against the short trade over the last hour and volatility jumped. The 4H call is no longer confirmed, but the move is not yet decisive, so tightening fits the facts better than closing." } }),
    rec({ id: "g3", signal_id: "s-eth", symbol: "ETH/USDT", timeframe: "15m", side: 1, level: "TIGHTEN", severity: 58, tp1_hit: true,
      created_at: NOW - 27 * M, expires_at: NOW + 3 * M, price: 2471.4, entry: 2452.0, stop_in_force: 2452.0, proposed_stop: 2463.9, atr: 6.1,
      reasons: [{ code: "giveback", label: "Gave back 62% of the 1.48R peak", points: 15 }, { code: "move", label: "Moved 0.71 ATR against in 5 min", points: 13 },
        { code: "flip", label: "15M analysis flipped to SELL", points: 25 }, { code: "near_stop", label: "0.55R from the protected stop", points: 2 }],
      ai: { path: "rules_only", model: null, text: "Severity 58 of 100 from the rules: 15M analysis flipped to SELL; Gave back 62% of the 1.48R peak; Moved 0.71 ATR against in 5 min. The rules suggest to tighten the stop to 2,463.9. Nothing changes unless you apply it." } }),
  ];
  const h = (o: any) => ({ rules_level: o.level, reasons: [], tp1_hit: false, ...o });
  const history = [
    h({ id: "h1", signal_id: "x1", symbol: "XRP/USDT", timeframe: "1h", side: 1, level: "TIGHTEN", severity: 63, created_at: NOW - 3 * H, expires_at: NOW - 2.5 * H,
      status: "applied", status_at: NOW - 2.9 * H, status_reason: "applied by the admin at 0.5198", proposed_stop: 0.5176, shadow: { action: "TIGHTEN", applied: true, with_r: -0.42, without_r: -1.08, delta_r: 0.66 } }),
    h({ id: "h2", signal_id: "x2", symbol: "DOGE/USDT", timeframe: "4h", side: -1, level: "CLOSE", severity: 81, created_at: NOW - 7 * H, expires_at: NOW - 6.5 * H,
      status: "dismissed", status_at: NOW - 6.8 * H, status_reason: "dismissed by owner", shadow: { action: "CLOSE", applied: false, with_r: -0.31, without_r: 1.12, delta_r: -1.43 } }),
    h({ id: "h3", signal_id: "x3", symbol: "BNB/USDT", timeframe: "1h", side: 1, level: "TIGHTEN", severity: 54, created_at: NOW - 9 * H, expires_at: NOW - 8.5 * H,
      status: "expired", status_at: NOW - 8.3 * H, status_reason: "not applied within 30 minutes", proposed_stop: 583.1, shadow: { action: "TIGHTEN", applied: false, with_r: -0.55, without_r: -1.07, delta_r: 0.52 } }),
    h({ id: "h4", signal_id: "x4", symbol: "LTC/USDT", timeframe: "12h", side: 1, level: "TIGHTEN", severity: 57, created_at: NOW - 20 * H, expires_at: NOW - 19.5 * H,
      status: "rejected", status_at: NOW - 19.8 * H, status_reason: "no longer valid at the price now (71.40): the proposed stop is closer than 0.2 ATR to the price", proposed_stop: 71.32, shadow: null }),
    h({ id: "h5", signal_id: "x5", symbol: "AAVE/USDT", timeframe: "4h", side: 1, level: "NONE", rules_level: "TIGHTEN", severity: 52, created_at: NOW - 26 * H, expires_at: NOW - 25.5 * H,
      status: "downgraded", status_at: NOW - 26 * H, status_reason: "AI downgraded the rules' recommendation to no action", shadow: { action: "TIGHTEN", applied: false, with_r: 0.31, without_r: 0.85, delta_r: -0.54 } }),
  ];
  const agg = (n: number, saved: number, cost: number, helped: number, hurt: number) => ({ n, saved_r: saved, cost_r: cost, net_r: Math.round((saved + cost) * 100) / 100, helped, hurt });
  return {
    generated_at: NOW, enabled: true,
    status: { last_check: NOW - 2 * M, watched: { coins: ["SOL", "AVAX", "ETH", "BTC"], calls: 3 }, day: new Date(NOW).toISOString().slice(0, 10),
      today: { checks: 214, skipped_stale: 2, skipped_price: 0, errors: 0, created: 6, ai_calls: 4, no_valid_stop: 1 }, last_error: null },
    live, history,
    checks: {
      at: NOW - 20 * 60_000,
      rejected: { n: 31, open: 4, closed: 24, would_have_won: 9, would_have_lost: 15, total_r: -6.4, avg_r: -0.267, verdict: "saving money", min_judge: 10,
        by_flag: [
          { flag: "AGAINST BIGGER TREND", n: 12, open: 1, missed: 1, closed: 10, would_have_won: 3, would_have_lost: 7, total_r: -4.1, avg_r: -0.41, verdict: "saving money" },
          { flag: "GRADE A ONLY", n: 9, open: 2, missed: 0, closed: 7, would_have_won: 4, would_have_lost: 3, total_r: 0.8, avg_r: 0.114, verdict: null },
          { flag: "VOLUME WALL AHEAD", n: 6, open: 1, missed: 0, closed: 5, would_have_won: 1, would_have_lost: 4, total_r: -2.6, avg_r: -0.52, verdict: null },
          { flag: "NEWS RISK", n: 4, open: 0, missed: 2, closed: 2, would_have_won: 1, would_have_lost: 1, total_r: -0.5, avg_r: -0.25, verdict: null },
        ],
        items: [
          { id: "rj1", symbol: "SOL/USDT", timeframe: "1h", side: "LONG", flag: "GRADE A ONLY", created_at: NOW - 3_600_000, status: "OPEN", net_r: null },
          { id: "rj2", symbol: "ETH/USDT", timeframe: "4h", side: "SHORT", flag: "AGAINST BIGGER TREND", created_at: NOW - 9 * 3_600_000, status: "STOPPED", net_r: -1.08 },
          { id: "rj3", symbol: "AVAX/USDT", timeframe: "15m", side: "LONG", flag: "VOLUME WALL AHEAD", created_at: NOW - 20 * 3_600_000, status: "TP2", net_r: 0.62 },
        ] },
      calibration: { warnings: ["15m: the AI did worse than plain base rates this week (skill -1.8%) and worse than the month before"],
        timeframes: [
          { timeframe: "15m", state: "drift", overconfidence: 0.061, last7: { n: 16100, skill: -0.018, hit_rate: 0.41 }, prior30: { n: 64000, skill: 0.004 } },
          { timeframe: "1h", state: "ok", overconfidence: 0.032, last7: { n: 4020, skill: 0.006, hit_rate: 0.44 }, prior30: { n: 17000, skill: 0.005 } },
          { timeframe: "4h", state: "ok", overconfidence: 0.021, last7: { n: 1000, skill: 0.011, hit_rate: 0.47 }, prior30: { n: 4300, skill: 0.009 } },
          { timeframe: "12h", state: "too few", overconfidence: null, last7: { n: 140, skill: 0.002, hit_rate: 0.45 }, prior30: { n: 600, skill: 0.003 } },
        ] },
      tp1: { timeframes: [{ timeframe: "1h", n: 6, expected: 0.58, actual: 0.5 }, { timeframe: "4h", n: 4, expected: 0.55, actual: 0.75 }] },
    },
    scoreboard: { ...agg(4, 1.18, -1.97, 2, 2), applied: agg(1, 0.66, 0, 1, 0), not_applied: agg(3, 0.52, -1.97, 1, 2),
      by_level: { TIGHTEN: agg(3, 1.18, -0.54, 2, 1), CLOSE: agg(1, 0, -1.43, 0, 1) }, pending: 4, skipped: 0 },
    config: { tighten_at: 50, close_at: 75, expires_min: 30, min_gap_atr: 0.2, fresh_m1_min: 3, persist_ticks: 3 },
    note: "Recommend-only: nothing changes unless the admin applies it. Shadow results are net R estimates (same fees on both sides, funding ignored), from the record's own exit rules.",
  };
}


/** v2.22 market turn detector sample (admin only) */
function riskState() {
  const now = Date.now();
  const f = (key: string, label: string, points: number, status: string, detail: string, source: string, critical = false) =>
    ({ key, label, points, status, detail, source, critical, value: null });
  return {
    generated_at: now - 3 * 60_000, state: "CAUTION", label: "Caution", score: 2, since: now - 5 * H,
    policy: "Be selective: prefer grade A calls and smaller size.",
    why: "BTC +3.1% last 4 hours; 11 short and 0 long signals running",
    factors: [
      f("data", "Data freshness", 0, "ok", "newest closed 15m candle 2 min old", "engine", true),
      f("btc_vol", "BTC volatility", 0, "ok", "recent 4h range is 1.12x its 100-candle normal", "Binance 4h", true),
      f("btc_move", "Sudden BTC move", 1, "warn", "BTC +0.8% last hour, +3.1% last 4 hours", "Binance 1h", true),
      f("breadth_vol", "Market-wide volatility", 0, "ok", "4 of 29 coins far above their normal volatility", "Binance 4h"),
      f("turn", "Trend turning", 0, "ok", "market trend down: weakening", "OKX + Binance"),
      f("sweep", "Stop run on BTC", 0, "ok", "no stop run in the last 6 hours", "Binance 1h"),
      f("liq", "Liquidation wave", 0, "ok", "BTC forced closes last 4h: $38M (1.4x normal)", "Coinalyze"),
      f("funding", "Funding extreme", 0, "ok", "longs paying a normal amount (z +0.6)", "Hyperliquid / OKX"),
      f("news", "Major US data", 0, "ok", "no high-impact release within the pause window", "economic calendar"),
      f("record", "Signal losses", 0, "ok", "closed signals +0.4R today, +0.4R this week (after fees)", "track record"),
      f("streak", "Losing streak", 0, "ok", "1 losing signals in a row", "track record"),
      f("exposure", "One-sided exposure", 1, "warn", "0 long and 11 short signals running", "track record"),
    ],
    unavailable: [],
    log: [{ at: now - 5 * H, from: "NORMAL", to: "CAUTION", score: 2, why: "BTC +3.1% last 4 hours" },
          { at: now - 30 * H, from: "RECOVERY", to: "NORMAL", score: 1, why: "no risk factor is raised" }],
    series: Array.from({ length: 48 }, (_, i) => [now - (47 - i) * H, i > 42 ? 2 : i > 30 ? 1 : 0, i > 42 ? "CAUTION" : "NORMAL"]),
    levels: [], method: "",
  };
}

function marketTurn() {
  const now = Date.now();
  return {
    generated_at: now - 12 * 60_000,
    market: { state: "weakening", trend: "down", score: 38, btc_points: 45, btc_state: "weakening",
      breadth: { trending: 18, turning: 3, weakening: 5 },
      reasons: [{ code: "structure_4h", points: 30, text: "4h closed above the last swing high 69120" },
                { code: "taker_flow", points: 15, text: "24h taker buy/sell 1.17 (OKX) against the downtrend" }] },
    stablecoins: { usd: 2.31e11, chg_7d_pct: 0.42, day: now - 86_400_000 },
    data: { at: now - 15 * 60_000, rows_total: 18240, supported: 22, errors: [] },
    coins: [
      { symbol: "SOL/USDT", state: "turning up", trend: "down", points: 60, reasons: [
        { code: "structure_4h", points: 30, text: "4h closed above the last swing high 171.2" },
        { code: "value_area", points: 15, text: "4h closed above the value-area high 170.4 (POC 163.9)" },
        { code: "liquidations", points: 10, text: "short liquidations $4,120,000 in 24 h = 3.6x the daily average" }] },
      { symbol: "BTC/USDT", state: "weakening", trend: "down", points: 45, reasons: [
        { code: "structure_4h", points: 30, text: "4h closed above the last swing high 69120" },
        { code: "taker_flow", points: 15, text: "24h taker buy/sell 1.17 (OKX) against the downtrend" }] },
      { symbol: "ETH/USDT", state: "trend intact", trend: "down", points: 10, reasons: [
        { code: "open_interest", points: 10, text: "price +2.1% with open interest +4.0% in 24 h (new positions behind the move)" }] },
    ],
    note: "Recommend-only context for the admin. It never changes a call; it is not proven to predict turns yet.",
  };
}

// v2.25 Performance Lab sample (deterministic pseudo-random calls)
function perfLab() {
  const H = 3_600_000;
  let seed = 7;
  const rnd = () => ((seed = (seed * 9301 + 49297) % 233280) / 233280);
  const tfs = ["15m", "1h", "4h", "1d"], coins = ["BTC", "ETH", "SOL", "XRP", "AVAX", "DOGE", "LINK"];
  const dots: any[] = [];
  for (let i = 0; i < 64; i++) {
    const tf = tfs[Math.floor(rnd() * 4)];
    const win = rnd() < (tf === "4h" ? 0.62 : tf === "1h" ? 0.45 : 0.55);
    const r = win ? +(0.4 + rnd() * 2.2).toFixed(2) : +(-0.3 - rnd() * 0.85).toFixed(2);
    dots.push({ t: NOW - (64 - i) * 5 * H, tf, side: rnd() < 0.75 ? "S" : "L", r, coin: coins[Math.floor(rnd() * coins.length)], g: rnd() < 0.7 ? "A" : "B", a: rnd() < 0.15 ? 1 : 0 });
  }
  const st = (v: number[]) => {
    if (!v.length) return { n: 0 };
    let c = 0, p = 0, dd = 0; for (const x of v) { c += x; p = Math.max(p, c); dd = Math.max(dd, p - c); }
    const g = v.filter((x) => x > 0).reduce((a, b) => a + b, 0), l = -v.filter((x) => x < 0).reduce((a, b) => a + b, 0);
    return { n: v.length, win_rate: v.filter((x) => x > 0).length / v.length, avg_r: c / v.length, total_r: +c.toFixed(2), profit_factor: l ? +(g / l).toFixed(2) : null, max_dd_r: +dd.toFixed(2), best_r: Math.max(...v), worst_r: Math.min(...v) };
  };
  const grp = (fn: (d: any) => string) => { const m: Record<string, number[]> = {}; dots.forEach((d) => (m[fn(d)] ??= []).push(d.r)); return Object.entries(m).map(([key, v]) => ({ key, ...st(v) })); };
  let c = 0, p = 0;
  const curve = dots.map((d) => { c += d.r; p = Math.max(p, c); return { t: d.t, r: +c.toFixed(3), dd: +(p - c).toFixed(3) }; });
  const edges = [-1e9, -1.5, -1, -0.75, -0.5, -0.25, 0, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 1e9];
  const histogram = edges.slice(0, -1).map((a, i) => ({ lo: a < -1e8 ? null : a, hi: edges[i + 1] > 1e8 ? null : edges[i + 1], n: dots.filter((d) => d.r >= a && d.r < edges[i + 1]).length }));
  const WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], SS = ["Asia", "Europe", "US", "Late"];
  const heat = WD.map((wd, i) => ({ wd, cells: SS.map((s, j) => ({ s, ...st(dots.filter((_, k) => k % 7 === i && Math.floor(k / 7) % 4 === j).map((d) => d.r)) })) }));
  const all = dots.map((d) => d.r);
  const stage2 = {
    portfolio: { available: true, mode: "enforce", positions: 5, pending: 1, open_r: 3.5, by_side_r: { long: 1, short: 2.5 },
      btc_correlated_r: { long: 1, short: 2 }, risk_per_trade_pct_ref: 0.25, equity_at_risk_pct_ref: 0.875,
      limits: { max_open_r: 8, max_side_r: 6, max_corr_r: 5, max_coin_r: 1, dd_limit_r: 10 },
      drawdown_state: { state: "NORMAL" }, drawdown: { dd_r: 3.2 } },
    by_regime: [{ key: "NORMAL", n: 41, avg_r: 0.08, total_r: 3.3, ci95_avg_r: [-0.21, 0.37] },
      { key: "CAUTION", n: 18, avg_r: -0.05, total_r: -0.9, ci95_avg_r: [-0.52, 0.42] }, { key: "unknown", n: 6, avg_r: 0.2, total_r: 1.2 }],
    ml_shadow: { mode: { trade_filter_enforce: false }, verdict: "too few closed calls to judge",
      would_block: { n: 9, avg_r: 0.12, total_r: 1.1 }, allowed: { n: 56, avg_r: 0.04, total_r: 2.2, ci95_avg_r: [-0.18, 0.26] },
      would_run: { n: 3, avg_r: 0.4, total_r: 1.2 }, shadow_scored: { "trade_filter|4h": { n: 212, kept_share: 0.44, keep_fraction: 0.5 } },
      freshness: { ages: { "15m": { n: 35, median_h: 9.5, older_than_48h: 0 }, "4h": { n: 35, median_h: 9.1, older_than_48h: 1 } },
        addons: { trade_filter: { enabled: 12, validated: 7, unknown: 4 }, runner_model: { enabled: 3, validated: 2, unknown: 4 } } },
      note: "Net R after the record's costs. Model scores are rankings, not win probabilities." },
  };
  return {
    ...stage2,
    by_market_regime: [{ key: "weak_bull", n: 31, avg_r: 0.11, total_r: 3.4, ci95_avg_r: [-0.2, 0.42] }, { key: "sideways", n: 22, avg_r: -0.06, total_r: -1.3 }, { key: "not recorded", n: 12, avg_r: 0.05, total_r: 0.6 }],
    opportunity_check: { all: { n: 64, score: { n: 64, enough: false, top_third_avg_r: 0.21, bottom_third_avg_r: -0.12, spread_r: 0.33 },
      reward: { n: 64, enough: false, top_third_avg_r: 0.18, bottom_third_avg_r: -0.02, spread_r: 0.2 }, regime: { n: 58, enough: false, top_third_avg_r: 0.09, bottom_third_avg_r: 0.03, spread_r: 0.06 } } },
    fast_strategy: { config: { risk_pct: 0.25 }, stats: { overall: { n: 23, win_rate: 0.43, avg_r: -0.04, profit_factor: 0.93, max_dd_r: 4.1 }, open: 2, net_pnl: -18.4, fees: 31.2,
      basis: "paper only; net of fee, slippage and half spread; R = P/L / planned risk" },
      promotion: { eligible: false, requirements: { min_closed: 300 }, failed: ["23 of 300 closed paper trades under the current rules", "net expectancy not shown above zero (95 % interval)", "protected forward holdout verdict not yet run (owner step: research_verdict.read_holdout_once)"] },
      authority: "isolated paper strategy: never a signal, never in the record, bots or members' accounts" },
    generated_at: NOW - 25 * 60_000, since: NOW - 14 * 24 * H, calls: 71, open: 5, missed: 2, overall: st(all),
    no_admin: st(all.map((x, i) => (dots[i].a ? x * 0.6 : x))), admin: { touched: dots.filter((d) => d.a).length, stored: st([]), without: st([]) },
    by_tf: grp((d) => d.tf), by_side: grp((d) => (d.side === "L" ? "LONG" : "SHORT")), by_grade: grp((d) => d.g), by_coin: grp((d) => d.coin),
    by_session: grp((d) => SS[Math.floor(d.t / H) % 4]), by_entry: grp(() => "market"), by_runner: grp((d) => (d.r > 2 ? "let it run" : "standard")),
    heat, histogram, streaks: { wins: 6, losses: 4, current: 2 }, curve, dots,
    losers: { n: all.filter((x) => x < 0).length, reached_profit: { "0.3": 14, "0.5": 9, "0.75": 5, "1.0": 2 } },
    hold_h: { median: 9.5, max: 71 }, exits: { stop: 18, target: 30, breakeven: 9, time_limit: 4, admin_close: 3 },
    proof: { rejected: { n: 31, closed: 24, total_r: -6.4, avg_r: -0.27, verdict: "saving money" }, calibration: { warnings: [] } },
  };
}

// v2.75 views/derivs sample (open interest, funding, liquidation map estimate, options / volatility, macro, unlocks)
function derivs() {
  const H = 3_600_000, D = 86_400_000;
  const coins: any = {};
  COINS.forEach(([symbol, price, ch], i) => {
    coins[symbol] = { oi_usd: [9.8e9, 5.1e9, 6.2e8, 1.1e9, 2.4e9, 9.5e8, 1.6e8, 2.2e8, 3.1e8, 1.2e8][i] ?? 1e8, oi_chg_24h: ((i * 7) % 11) - 4 + ch / 2,
      oi_series: Array.from({ length: 48 }, (_, k) => 1e9 * (1 + 0.04 * Math.sin(k / 6 + i) + k * 0.001)),
      ls_ratio: 1 + ((i * 3) % 7) / 10, long_pct: 50 + ((i * 9) % 25) - 8, taker_buy_pct: 50 + ((i * 7) % 15) - 6,
      liq_24h: { long: 2e6 * (i + 1), short: 1.4e6 * (10 - i) }, funding_8h_pct: [0.0102, 0.0087, -0.0031, 0.0141, 0.031, 0.0063, 0.0098, -0.0012, 0.0055, 0.0011][i] ?? 0.01,
      funding_days: Array.from({ length: 7 }, (_, k) => [NOW - (7 - k) * D, 0.004 + 0.008 * Math.sin(k + i) ]) };
  });
  const map = (price: number) => {
    const longs = Array.from({ length: 40 }, (_, k) => (k < 20 ? Math.round(4e6 * Math.exp(-((k - 13) ** 2) / 8) + 6e5 * ((k * 7) % 5)) : 0));
    const shorts = Array.from({ length: 40 }, (_, k) => (k >= 20 ? Math.round(3.2e6 * Math.exp(-((k - 27) ** 2) / 10) + 5e5 * ((k * 3) % 4)) : 0));
    return { price, low: price * 0.85, high: price * 1.15, longs, shorts, note: "estimate" };
  };
  return { generated_at: NOW, coins, liq_maps: { "BTC/USDT": map(68420.5), "ETH/USDT": map(2468.12), "SOL/USDT": map(168.42) },
    volatility: { source: "Deribit", dvol: { BTC: { value: 56.4, chg_24h: 2.1, series: [51, 52.4, 50.8, 53.1, 54.6, 54.3, 55.0, 56.4] }, ETH: { value: 71.2, chg_24h: -1.3, series: [68, 70.1, 72.5, 73.0, 72.1, 71.6, 72.5, 71.2] } },
      options: { BTC: { put_call: 0.71, oi_coins: 412000, max_pain: 66000, expiry: NOW + 5 * D, underlying: 68420 }, ETH: { put_call: 0.86, oi_coins: 3100000, max_pain: 2500, expiry: NOW + 5 * D, underlying: 2468 } } },
    macro: { source: "Yahoo Finance (delayed)",
      SPX: { name: "S&P 500", value: 6910.4, chg_1d: 0.42, series: Array.from({ length: 22 }, (_, k) => 6700 + k * 9 + 30 * Math.sin(k)), btc_corr_30d: 0.54 },
      NDX: { name: "Nasdaq", value: 23810.2, chg_1d: 0.71, series: Array.from({ length: 22 }, (_, k) => 23000 + k * 35 + 90 * Math.sin(k / 2)) },
      DXY: { name: "Dollar index", value: 104.21, chg_1d: -0.18, series: Array.from({ length: 22 }, (_, k) => 105 - k * 0.04 + 0.2 * Math.sin(k)) },
      GOLD: { name: "Gold", value: 2741.2, chg_1d: 0.22, series: Array.from({ length: 22 }, (_, k) => 2650 + k * 4 + 15 * Math.sin(k / 3)) },
      US10Y: { name: "US 10-year yield", value: 4.31, chg_1d: -0.6, series: Array.from({ length: 22 }, (_, k) => 4.45 - k * 0.006 + 0.03 * Math.sin(k)) } },
    unlocks: [{ coin: "SUI", tokens_30d: 6.4e7, pct_of_unlocked: 2.1, next_at: NOW + 9 * D }, { coin: "APT", tokens_30d: 1.13e7, pct_of_unlocked: 1.4, next_at: NOW + 12 * D },
      { coin: "ENA", tokens_30d: 1.7e8, pct_of_unlocked: 0.9, next_at: NOW + 3 * D }, { coin: "AVAX", tokens_30d: 1.6e6, pct_of_unlocked: 0.4, next_at: NOW + 20 * D }],
    core: { coins: 10, maps: 3 } };
}


/** Coin page sample (BTC 4h): enough of the engine's analysis row for every card, incl. the AI opportunity card. */
function assetAnalysis() {
  const px = 68420.5;
  const pm = (name: string, label: string, cal: number[], w: number) => ({ name, label, baseline: false, raw: cal, calibrated: cal, weight: w,
    calibration: "isotonic", predicted: ["down", "neutral", "up"][cal.indexOf(Math.max(...cal))], oos_accuracy: 0.41, oos_brier: 0.62 });
  return {
    status: "OK", symbol: "BTC/USDT", timeframe: "4h", price: px, last_close: px, decision: "WAIT", grade: null,
    decision_reason: "the setup's entry zone is below the price", confidence: 0.57, flags: [],
    regime: { regime: "TRENDING_UP", score: 0.46, confidence: 0.72, trend_strength: "strong", momentum: "rising",
      transition: { horizon_bars: 6, n: 412, from_group: "up", probabilities: { up: 0.71, range: 0.22, down: 0.07 } } },
    volatility: { state: "NORMAL" },
    signal: { signal: "BUY", score: 64, components: [
      { key: "trend", label: "Trend", effective_weight: 0.3, available: true, score: 0.62 },
      { key: "momentum", label: "Momentum", effective_weight: 0.25, available: true, score: 0.35 },
      { key: "volume", label: "Volume", effective_weight: 0.2, available: true, score: 0.12 },
      { key: "structure", label: "Structure", effective_weight: 0.25, available: true, score: 0.4 } ],
      reasons: ["Price above the 50 and 200 averages", "Higher lows on 4H", "MACD above its signal line"],
      warnings: ["RSI 68: close to overbought"] },
    forecast: { available: true, model_version: "BTCUSDT-4h-20261124", trained_at: NOW - 5 * 36e5, bar_ts: NOW - 36e5, price: px,
      sigma: 0.011, neutral_band: 0.0025, probabilities: { down: 0.21, neutral: 0.15, up: 0.64 },
      raw_probabilities: { down: 0.23, neutral: 0.14, up: 0.63 }, predicted_class: 2, predicted: "up", p_max: 0.64,
      model_agreement: 0.83, models_agreeing: 4, models_total: 5,
      per_model: [pm("random_forest", "Random forest", [0.18, 0.14, 0.68], 0.4), pm("xgboost", "XGBoost", [0.24, 0.16, 0.6], 0.15),
        pm("lightgbm", "LightGBM", [0.22, 0.17, 0.61], 0.15), pm("logistic", "Logistic", [0.27, 0.2, 0.53], 0.12), pm("arima", "ARIMA", [0.4, 0.31, 0.29], 0.08)],
      expected_return: 0.0041, edge_confirmed: false, edge_failed_checks: ["bootstrap"],
      confidence: { confidence: 0.57, n: 214, basis: "comparable out-of-sample calls" },
      interval_coverage: { coverage: { "80": 0.79 }, n: 300 },
      distribution: { expected_price: px * 1.0041, intervals: Object.fromEntries([["50", 0.006], ["80", 0.013], ["95", 0.022]].map(([k, w]) =>
        [k, { low_price: px * (1 - (w as number)), high_price: px * (1 + (w as number)), low_return: -(w as number), high_return: w as number }])) },
      explanation: { positive: [{ feature: "ret_20", label: "20-bar momentum", contribution: 0.031 }, { feature: "btc_oi", label: "Open interest rising", contribution: 0.018 }],
        negative: [{ feature: "rsi", label: "RSI high", contribution: -0.012 }] } },
    horizons: [], mtf: { alignment: 0.8, conflict: false, rows: [
      { timeframe: "1h", available: true, direction: 1, direction_label: "Up", regime_score: 0.3 },
      { timeframe: "4h", available: true, direction: 1, direction_label: "Up", regime_score: 0.46 },
      { timeframe: "12h", available: true, direction: 1, direction_label: "Up", regime_score: 0.38 },
      { timeframe: "1d", available: true, direction: 0, direction_label: "Range", regime_score: 0.05 } ] },
    levels: { zones: { support: [{ mid: 66180 }, { mid: 64200 }], resistance: [{ mid: 70100 }] }, liquidity: [], supply_demand: { demand: [], supply: [] } },
    setup: null, risk: null, indicators: {}, events: [],
    liquidity: { relative_volume: 1.2, buy_pressure: 0.14, volume_spike: false },
    commentary: "BTC is in a 4H uptrend; the AI ensemble leans up but has no proven edge on this timeframe yet.",
  };
}


// V3.3 Fast Opportunity Radar sample (display only)
function fastRadar() {
  const at = Date.now() - 20 * 60_000;
  const c = (rank: number, coin: string, price: number, r24: number, rs24: number, rs7: number, rsi: number, qv: number, vx: number,
    spread: number, reasons: string[], warnings: string[]) => ({ rank, coin, symbol: `${coin}/USDT`, status: "ok", price, ret_24h_pct: r24,
    rs_24h_pct: rs24, rs_7d_pct: rs7, rsi14: rsi, quote_volume_24h: qv, volume_expansion: vx, spread_bps: spread,
    score: 0.6 - rank * 0.08, points: {}, reasons, warnings, regime_compatibility: "compatible",
    category: ["SUI", "INJ", "SOL", "TIA"].includes(coin) ? "alt" : "meme", category_rank: rank });
  return {
    available: true, display_only: true, generated_at: at, regime: "CAUTION",
    coins: [
      c(1, "SUI", 1.92, 7.4, 5.1, 18.2, 66, 4.1e8, 2.1, 1.2, ["+18.2% vs BTC over 7 days", "+5.1% vs BTC in 24 h", "1h uptrend: above EMA20 and EMA50, EMA20 rising", "volume 2.1x its recent daily average"], []),
      c(2, "WIF", 1.31, 11.8, 9.6, 12.4, 74, 2.6e8, 2.8, 3.4, ["+12.4% vs BTC over 7 days", "+9.6% vs BTC in 24 h", "volume 2.8x its recent daily average"], ["wick-heavy candles: stop hunting / manipulation risk"]),
      c(3, "PEPE", 0.0000124, 28.5, 26.1, 31.0, 86, 9.8e8, 4.4, 2.1, ["+31.0% vs BTC over 7 days", "+26.1% vs BTC in 24 h"], ["parabolic: chasing this move is the classic way to buy the top", "one-candle pump: most of the day's move came in a single hour"]),
      c(4, "INJ", 21.4, 1.2, -0.8, 6.3, 54, 1.2e8, 1.1, 2.8, ["+6.3% vs BTC over 7 days"], []),
      c(5, "FLOKI", 0.000142, 3.1, 1.0, -2.4, 58, 9.0e6, 3.2, 26.0, [], ["thin liquidity: under $15M traded in 24 h", "wide spread: 26 bps just to get in and out"]),
    ],
    not_covered: ["HYPE", "SPX", "FARTCOIN"],
    tf_4h: { available: true, generated_at: at, timeframe: "4h", coins: [
      { ...c(1, "INJ", 21.4, 1.2, -0.8, 6.3, 61, 1.2e8, 1.4, 2.8, ["+6.3% vs BTC over 7 days", "4h uptrend: above EMA20 and EMA50, EMA20 rising"], []), tf: "4h" },
      { ...c(2, "SUI", 1.92, 7.4, 5.1, 18.2, 71, 4.1e8, 2.1, 1.2, ["+18.2% vs BTC over 7 days", "+5.1% vs BTC in 24 h"], ["one-candle pump: most of the move came in a single candle"]), tf: "4h" },
      { ...c(1, "PEPE", 0.0000124, 28.5, 26.1, 31.0, 79, 9.8e8, 4.4, 2.1, ["+31.0% vs BTC over 7 days", "4h uptrend: above EMA20 and EMA50, EMA20 rising"], ["parabolic: chasing this move is the classic way to buy the top"]), tf: "4h" },
      { ...c(2, "WIF", 1.31, 11.8, 9.6, 12.4, 66, 2.6e8, 2.8, 3.4, ["+12.4% vs BTC over 7 days"], []), tf: "4h" },
    ] },
    tracking: { basis: "price move after the coin first appeared, vs BTC, before costs; not a trade result", tracking: 4,
      meme: { n: 11, worked_share: 0.45, avg_rs_24h_pct: -0.8, ci95: [-4.1, 2.5], enough: false },
      alt: { n: 9, worked_share: 0.56, avg_rs_24h_pct: 0.9, ci95: [-1.7, 3.5], enough: false },
      all: { n: 20, worked_share: 0.5, avg_rs_24h_pct: -0.04, ci95: [-2.1, 2.0], enough: false },
      recent: [{ coin: "WIF", category: "meme", first_seen: at - 26 * 3_600_000, rs_4h: 2.1, rs_24h: -3.4, rs_72h: null },
        { coin: "SUI", category: "alt", first_seen: at - 50 * 3_600_000, rs_4h: 0.8, rs_24h: 2.6, rs_72h: 4.9 },
        { coin: "PEPE", category: "meme", first_seen: at - 80 * 3_600_000, rs_4h: 4.2, rs_24h: 1.1, rs_72h: -6.3 }] },
  };
}

function marketRegime() {
  const at = Date.now() - 6 * 60_000;
  const e = (input: string, reading: string, supports: string, status = "confirmed") => ({ input, reading, supports, status, source: "engine" });
  return {
    generated_at: at, primary: "weak_bull", regime: "weak_bull", regime_word: "Weak uptrend", word: "Weak uptrend", labels: ["weak_bull", "high_volatility"],
    volatility: "high", confidence: "medium", agreement: 0.67, data_quality: "good", inputs: { confirmed: 10, unavailable: 1, total: 12 },
    reasons: ["BTC 4h BULL, 1d BULLISH CONSOLIDATION, breadth 58%"], risk_flags: ["BTC volatility"],
    evidence: [e("BTC regime 4h", "BULL", "bull"), e("BTC regime 1d", "BULLISH CONSOLIDATION", "bull"), e("BTC 4h structure", "inside range", "neutral"),
      e("BTC volatility", "high", "risk"), e("Breadth (above 4h EMA50)", "58%", "neutral"), e("ETH vs BTC, 7 d", "+2.4%", "bull"),
      e("Altcoins vs BTC, 7 d (median)", "-1.2%", "neutral"), e("BTC dominance, 7 d", "-0.40 pts", "neutral"), e("BTC funding per 8 h", "+0.012%", "neutral"),
      e("BTC open interest, 24 h", "+3.1%", "neutral"), e("BTC liquidations, 24 h", "62% longs", "neutral", "delayed"), e("BTC spot volume vs 30 d", "unavailable", "none", "unavailable")],
    transition: { confirmed: "weak_bull", since: at - 19 * 3_600_000, previous: "sideways", pending: null },
    log: [{ at: at - 19 * 3_600_000, from: "sideways", to: "weak_bull", confidence: "medium", data_quality: "good" },
      { at: at - 3 * 86_400_000, from: "weak_bear", to: "sideways", confidence: "low", data_quality: "partial" }],
    authority: "context only - never blocks, approves or sizes a trade",
  };
}

function modelRegistry() {
  const now = Date.now();
  const m = (s: string, tf: string, status: string, age: number, reasons: string[] = [], drift = false) => ({ symbol: s, timeframe: tf, status, age_h: age, n_oos: 640,
    validation: { brier: 0.648, directional_accuracy: 0.54 }, live: { recent: { n: 100, hit: drift ? 0.44 : 0.53 }, drift: { drifting: drift } }, reasons });
  return { generated_at: now - 40 * 60_000, counts: { active: 176, stale: 3, held: 4, invalid: 1 }, drifting: 2,
    training: { finished_at: now - 6 * 3_600_000, status: "warn", outcome: { completed: 88, held: 4, failed_validation: 1, not_reached: 2 } },
    models: [m("ANTHROPIC/USDT", "15m", "invalid", 30, ["newest version failed validation: only 12 out-of-sample predictions (< 30)"]),
      m("XRP/USDT", "1d", "stale", 61, ["trained 61 h ago (> 48 h)"]), m("SOL/USDT", "4h", "held", 9, ["newer version held: the live model was better on shared unseen bars"]),
      m("DOGE/USDT", "1h", "active", 8, ["live hit rate 44% vs 54% out-of-sample"], true), m("BTC/USDT", "4h", "active", 7)],
    trade_quality: { overall: { n: 64, avg_r: 0.06 }, by_confidence: { "0.55-0.60": { n: 21, avg_r: -0.04 }, "0.60-0.65": { n: 30, avg_r: 0.09 }, "0.65-1.00": { n: 13, avg_r: 0.15 } } },
    rule: "a model goes live only after its file loads, it has >= MODEL_MIN_OOS out-of-sample predictions and (with the champion check on) it is not clearly worse than the live one" };
}
