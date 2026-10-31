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
  ];
  return t.map(([title, coins], i) => ({ title, coins, source: src[i % 3], url: "https://example.com/" + i, ts: NOW - (i * 1.7 + 0.3) * 3_600_000,
    summary: i % 2 ? null : "Sample summary text for the preview only. The live page shows the first lines the news site publishes with each story." }));
}
const H = 3_600_000, D = 86_400_000;
const v = (o: any) => ({ json: JSON.stringify(o), updated_at: NOW });

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
  return COINS.map(([symbol, price], i) => {
    const d = DEC[i];
    const side = d === "SELL" ? -1 : d.startsWith("BUY") ? 1 : 0;
    const p_up = side > 0 ? 0.58 : side < 0 ? 0.24 : 0.41, p_down = side < 0 ? 0.55 : side > 0 ? 0.21 : 0.37;
    const row: any = {
      symbol, status: "OK", timeframe: tf, price, action: d === "BUY ON PULLBACK" ? "LONG ON PULLBACK" : side > 0 ? "LONG" : side < 0 ? "SHORT" : "NO TRADE",
      side, decision: d, decision_reason: side ? null : "the AI and the trend disagree", lean: p_up > p_down + 0.03 ? "LONG" : p_down > p_up + 0.03 ? "SHORT" : "NEUTRAL",
      p_up, p_down, p_neutral: 1 - p_up - p_down, confidence: side ? 0.64 - i * 0.01 : 0.52, grade: side ? (i % 3 === 1 ? "B" : "A") : null,
      decision_basis: side ? "4H trend and the AI ensemble agree; 1D trend supports it" : null,
      filter_score: side ? 0.61 : null, filter_threshold: 0.55, regime: REG[i], signal: SIG[i], funding_rate: 0.0001,
      record_status: side ? "logged" : "not_logged", stale: false,
      ai: side ? { rationale: "Price is holding above the rising 4H trend after a shallow pullback; momentum is recovering and the stop sits under the last swing low.", regime: "trend", model: "advisor", at: NOW - 20 * 60_000 } : undefined,
      call: side ? { id: `c${i}`, status: "OPEN", fill_status: d === "BUY ON PULLBACK" ? "PENDING" : "FILLED", side: side > 0 ? "LONG" : "SHORT", entry: price * (1 - side * 0.004), stop: price * (1 - side * 0.02), peak_r: 0.42, peak_pct: 0.76, exit_reason: null, managed: 0, created_at: NOW - 3 * H, leverage: 8 }
        : i === 6 ? { id: `c${i}`, status: "TP2", fill_status: "FILLED", side: "LONG", entry: price * 0.98, stop: price * 0.962, peak_r: 2.1, peak_pct: 3.4, exit_reason: null, managed: 0, created_at: NOW - 9 * H, closed_at: NOW - 2 * H, return_pct: 2.3, leverage: 10, roi_pct: 23 }
        : i === 9 ? { id: `c${i}`, status: "STOPPED", fill_status: "FILLED", side: "SHORT", entry: price * 0.99, stop: price * 1.008, peak_r: 0.3, peak_pct: 0.4, exit_reason: "stop", managed: 0, created_at: NOW - 9 * H, closed_at: NOW - 3 * H, return_pct: -1.8, leverage: 8, roi_pct: -14.4 } : null,
    };
    if (side) row.plan = plan(price, side as 1 | -1, true, i === 4);
    else row.plan = plan(price, 1, false);
    if (row.call) Object.assign(row.call, { tp1: row.call.entry + (row.call.side === "LONG" ? 1 : -1) * Math.abs(row.call.entry - row.call.stop), tp1_hit: 0 });
    if (i === 0) {
      // v2.7 sample: the admin moved this open call's stop-loss (public, forward-only)
      Object.assign(row.call, { entry: row.plan.entry, stop: row.plan.stop, tp1: row.plan.targets[0].price });
      const old = row.call.stop, nu = Math.round(price * 0.9905);
      row.call = { ...row.call, stop0: old, tp1_0: row.call.tp1, stop: nu,
        adjustments: [{ at: NOW - 48 * 60_000, field: "stop", old, new: nu, note: "Locking in more of the move before the US CPI release" }] };
    }
    return row;
  });
}

function dashboard(tf: string) {
  const rows = COINS.map(([symbol, price, ch], i) => ({ symbol, status: "OK", price, change_24h_pct: ch, regime: REG[i], signal: SIG[i], score: 40 + ((i * 17) % 50), decision: DEC[i], confidence: 0.55 + (i % 4) * 0.04, grade: DEC[i] !== "NO TRADE" ? "A" : null }));
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

function trackRecord() {
  const sigs = [
    ["SOL/USDT", "4h", "LONG", "A", "TP2", 2.31], ["BTC/USDT", "1h", "LONG", "A", "TP1", 0.84], ["ETH/USDT", "4h", "SHORT", "B", "STOPPED", -1.62],
    ["XRP/USDT", "1h", "LONG", "A", "TP3", 3.12], ["AAVE/USDT", "12h", "LONG", "A", "OPEN", null], ["DOGE/USDT", "15m", "SHORT", "B", "STOPPED", -0.94],
    ["BNB/USDT", "4h", "LONG", "A", "TP1", 0.71], ["AVAX/USDT", "1h", "SHORT", "A", "TP2", 1.88], ["LTC/USDT", "1d", "LONG", "B", "EXPIRED", 0.12],
  ].map(([symbol, timeframe, side, grade, status, ret], i) => {
    const px = PRICES[symbol as string].p, s = side === "LONG" ? 1 : -1;
    const leverage = Math.min(10, Math.floor(1 / (1.5 * 0.018 + 0.005)));   // engine/futures.signal_leverage for a 1.8% stop (cap 10x)
    return { symbol, timeframe, side, grade, status, return_pct: ret, leverage, roi_pct: ret == null ? null : (ret as number) * leverage, created_at: NOW - (i + 1) * 7 * H, closed_at: status === "OPEN" ? null : NOW - (i + 1) * 5 * H,
      entry: px, stop: px * (1 - s * 0.018), tp1: px * (1 + s * 0.018), tp2: px * (1 + s * 0.029), tp3: px * (1 + s * 0.043),
      fill_status: "FILLED", peak_pct: status === "STOPPED" ? 0.4 : null, managed: 0 } as any;
  });
  // v2.7 sample: a closed call stopped at the level the admin moved
  Object.assign(sigs[2], { exit_reason: "admin_stop", adjustments: [{ at: sigs[2].created_at + 3 * H, field: "stop", old: sigs[2].stop, new: sigs[2].entry * 1.0162, note: "Cutting risk: the trend turned against the short" }] });
  const closed = sigs.filter((x) => x.status !== "OPEN").map((x) => x.return_pct as number);
  let acc = 0;
  let accRoi = 0;
  const curve = sigs.slice().reverse().filter((x) => x.status !== "OPEN").map((x) => ({ ts: x.closed_at, cum_return_pct: (acc += x.return_pct as number), cum_roi_pct: (accRoi += x.roi_pct as number) }));
  const rois = sigs.filter((x) => x.status !== "OPEN").map((x) => x.roi_pct as number);
  return {
    record_since: NOW - 2 * D, testing_since: NOW - 2 * D,
    live: { summary: { closed: closed.length, win_rate: closed.filter((r) => r > 0).length / closed.length, avg_return_pct: closed.reduce((a, b) => a + b, 0) / closed.length, total_return_pct: acc,
      avg_roi_pct: accRoi / rois.length, total_roi_pct: accRoi, best_roi_pct: Math.max(...rois), worst_roi_pct: Math.min(...rois) },
      open: 1, curve, signals: sigs },
    tested: [{ symbol: "BTC/USDT", timeframe: "4h", edge: true, selective_hit_rate: 0.61, selective_ci95: [0.55, 0.67], calls_per_day: 0.8, tested_days: 410 },
      { symbol: "SOL/USDT", timeframe: "1h", edge: true, selective_hit_rate: 0.58, selective_ci95: [0.53, 0.63], calls_per_day: 2.1, tested_days: 380 },
      { symbol: "LTC/USDT", timeframe: "1d", edge: false, selective_hit_rate: 0.5, selective_ci95: [0.41, 0.59], calls_per_day: 0.2, tested_days: 600 }],
    bots: [{ scorecard: true, name: "Futures signals A+B · 4H", trades: 6, win_rate: 0.67, return_pct: 3.4, benchmark_return_pct: 1.2, max_drawdown_pct: 1.9, started_at: NOW - 2 * D },
      { scorecard: true, name: "Futures signals A+B · 1H", trades: 11, win_rate: 0.55, return_pct: 1.1, benchmark_return_pct: 1.2, max_drawdown_pct: 2.6, started_at: NOW - 2 * D }],
    method: { live: "Every trade signal the engine published, followed candle by candle.", tested: "Walk-forward test on data the models never saw." },
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
  add("u_new", { email: "new.person@example.com", name: "New Person", username: "newperson", provider: "password", status: "pending", requested_at: NOW - 30 * 60_000 });
  add("u_member", { email: "sara.k@example.com", name: "Sara Kim", username: "sara_k", provider: "google", status: "approved", expires_at: NOW + 74 * D, plan_months: 3, approved_at: NOW - 16 * D, free: false,
    history: [{ months: 3, amount: 40, free: false, granted_at: NOW - 16 * D }], payment: { method: "binance", months: 3, amount: 40, currency: "USDT", txid: "B2610140032", proof: null, status: "accepted", submitted_at: NOW - 16 * D } });
  add("u_end", { email: "daniel.r@example.com", name: "Daniel Reyes", username: "dreyes", provider: "password", status: "approved", expires_at: NOW + 4 * D, plan_months: 1, approved_at: NOW - 26 * D,
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
        payment: { method: i % 2 ? "mexc" : "binance", months: m, amount: price[m], currency: "USDT", txid: `B26100${i}991`, proof: null, status: "accepted", submitted_at: NOW - 10 * D } }); break;
      case 1: add(id, { ...base, status: "approved", expires_at: NOW + (2 + i) * D, plan_months: 1, approved_at: NOW - 25 * D, free: false, history: [paid(1, 15, 25)] }); break;
      case 2: add(id, { ...base, status: "approved", expires_at: NOW + (40 + i * 6) * D, plan_months: m, approved_at: NOW - 4 * D, free: true, history: [{ months: m, amount: 0, free: true, granted_at: NOW - 4 * D }] }); break;
      case 3: add(id, { ...base, status: "pending", requested_at: NOW - (i + 2) * H,
        payment: { method: i % 2 ? "mexc" : "binance", months: m, amount: price[m], currency: "USDT", txid: `MX7712${i}0`, proof: i % 2 ? null : proofImage(), status: "submitted", submitted_at: NOW - (i + 1) * H } }); break;
      case 4: add(id, { ...base, status: "approved", expires_at: NOW - (3 + i) * D, plan_months: 1, approved_at: NOW - 40 * D, free: false, history: [paid(1, 15, 40)] }); break;
      case 5: add(id, { ...base, status: i > 10 ? "blocked" : "pending",
        payment: { method: "binance", months: 1, amount: 10, currency: "USDT", txid: "B000123", proof: null, status: "rejected", reason: "Payment not found in my Binance history", submitted_at: NOW - 3 * D } }); break;
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
  const acc = { id: `acc_${uid}`, starting_balance: 10000, wallet: 8890.4, created_at: NOW - 3 * D, position_mode: "oneway",
    positions: { BTCUSDT: btc, ETHUSDT: eth, SOLUSDT: sol },
    orders: { o1: { id: "o1", symbol: "AVAX/USDT", side: 1, price: px("AVAX/USDT") * 0.97, margin: 200, leverage: 5, stop: px("AVAX/USDT") * 0.94, take: null, reserve: 200.2, created_at: NOW - 2 * H, checked_at: NOW - 60_000 } },
    totals: { realized: 142.6, fees: 9.8, funding: 1.2, count: 6, wins: 4, liquidations: 0 } };
  const out: Record<string, any> = { [`paper/${uid}_futures`]: acc,
    [`paper/${uid}_spot`]: { id: `spot_${uid}`, starting_balance: 10000, cash: 7420.5, created_at: NOW - 3 * D, benchmark_symbol: "BTC/USDT", benchmark_price: px("BTC/USDT") * 0.97,
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
    "views/wins_today": v({ period: "today", window_hours: 24, closed: 7, losses: 2, wins: [
      { symbol: "XRP/USDT", timeframe: "1h", side: "LONG", entry: 0.5081, status: "TP3", return_pct: 3.12, leverage: 10, roi_pct: 31.2, closed_at: NOW - 2 * H, target: 0.5292 },
      { symbol: "SOL/USDT", timeframe: "4h", side: "LONG", entry: 164.1, status: "TP2", return_pct: 2.31, leverage: 10, roi_pct: 23.1, closed_at: NOW - 5 * H, target: 168.9 },
      { symbol: "AVAX/USDT", timeframe: "1h", side: "SHORT", entry: 27.92, status: "TP2", return_pct: 1.88, leverage: 9, roi_pct: 16.92, closed_at: NOW - 8 * H, target: 27.11 },
      { symbol: "1000PEPE/USDT", timeframe: "15m", side: "SHORT", entry: 0.00001234, status: "TP1", return_pct: 0.71, closed_at: NOW - 9 * H, target: 0.00001225 }] }),
    "views/news": v({ calendar: [{ id: "cpi", title: "CPI m/m", ts: NOW + 26 * H, impact: "High", forecast: "0.2%", previous: "0.3%", country: "US" }, { id: "nfp", title: "Non-Farm Employment Change", ts: NOW + 50 * H, impact: "High", forecast: "150K", previous: "142K", country: "US" }], headlines: newsHeads(), sources: { calendar: "Forex Factory weekly economic calendar", headlines: "CoinDesk, Cointelegraph, Decrypt" }, next_high: { title: "CPI m/m", ts: NOW + 26 * H },
      sentiment: { latest: { market: { score: 0.28, ts: NOW - 0.4 * H, source: "headlines", headlines: 18 }, BTC: { score: 0.41, ts: NOW - 0.4 * H }, ETH: { score: 0.12, ts: NOW - 0.4 * H }, alts: { score: -0.18, ts: NOW - 0.4 * H } },
        series: Array.from({ length: 48 }, (_, i) => ({ ts: NOW - (47 - i) * H, score: Math.round((0.25 * Math.sin(i / 6) + i / 120) * 100) / 100 })) } }),
    "views/radar": v({ picks: [{ rank: 1, symbol: "SUI/USDT", price: 1.92, change_24h_pct: 6.1, quote_volume: 4.1e8, rs_7d: 0.142, rs_30d: 0.31, reasons: [] }, { rank: 2, symbol: "INJ/USDT", price: 21.4, change_24h_pct: 3.4, quote_volume: 1.2e8, rs_7d: 0.096, rs_30d: 0.12, reasons: [] }, { rank: 3, symbol: "TIA/USDT", price: 5.2, change_24h_pct: 2.2, quote_volume: 0.9e8, rs_7d: 0.061, rs_30d: -0.02, reasons: [] }], historical: {}, live: {} }),
    "views/context": v({ market: { total_market_cap_usd: 2.41e12, market_cap_change_24h_pct: 1.21, btc_dominance: 56.4 }, sentiment: { value: 64, label: "Greed", change_7d: 9, history: Array.from({ length: 30 }, (_, i) => ({ ts: NOW - (29 - i) * D, value: 45 + Math.round(15 * Math.sin(i / 4)) + i / 2 })) } }),
    "views/market_context": v(marketContext()),
    "views/cross_asset_1d": v({ observations: ["BTC dominance rising: large caps lead, altcoins lag.", "7 of 10 tracked coins are above their 50-day average."] }),
    "views/health": v({ status: "OK", engine: { last_tick_finished: NOW - 3 * 60_000, schedule_minutes: 5, ticks: 412 }, market_data: {}, exchange: {}, database: {}, config: {} }),
    "views/settings": v({ risk_profile: { portfolio: 10000, risk_per_trade_pct: 1, max_daily_loss_pct: 3, max_exposure_pct: 50, max_position_pct: 20, target_annual_vol_pct: 40 }, signal_weights: { trend: 0.3, momentum: 0.2, volume: 0.1, structure: 0.15, volatility: 0.05, ml: 0.15, htf: 0.05 } }),
    "views/signals": v(signalLog()),
    "views/weekly_report": v(weekly()),
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
  delete out["users/u_member_self"];
  return out;
}
