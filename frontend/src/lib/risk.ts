// Port of the engine's position sizing (independent of every model: stop distance, volatility and limits only).
const TF_S: Record<string, number> = { "15m": 900, "1h": 3600, "4h": 14400, "12h": 43200, "1d": 86400, "3d": 259200, "1w": 604800 };
export const DEFAULT_RISK = { portfolio: 25000, risk_per_trade_pct: 1, max_daily_loss_pct: 3, max_exposure_pct: 100, max_position_pct: 50, target_annual_vol_pct: 40 };

export function positionSize(profile: typeof DEFAULT_RISK, entry: number, stop: number, sigmaBar: number | null | undefined,
  timeframe = "4h", openExposure = 0, realisedToday = 0) {
  const p = { ...DEFAULT_RISK, ...Object.fromEntries(Object.entries(profile ?? {}).map(([k, v]) => [k, Number(v)])) };
  const risk = (p.portfolio * p.risk_per_trade_pct) / 100;
  const per = Math.abs(entry - stop);
  if (per <= 0 || entry <= 0) return { allowed: false, reason: "stop equals entry", qty: 0, notional: 0 };
  const daily = (p.portfolio * p.max_daily_loss_pct) / 100;
  if (realisedToday <= -daily) return { allowed: false, qty: 0, notional: 0, reason: `daily loss limit reached (${realisedToday.toFixed(2)} vs -${daily.toFixed(2)})` };
  let qty = risk / per;
  let binding = "risk per trade";
  const caps: Record<string, number> = {
    "single-position cap": (p.portfolio * p.max_position_pct) / 100 / entry,
    "portfolio exposure cap": Math.max(0, (p.portfolio * p.max_exposure_pct) / 100 - openExposure) / entry,
  };
  let volQty: number | null = null;
  if (sigmaBar && sigmaBar > 0) {
    const ann = sigmaBar * Math.sqrt((365.25 * 86400) / (TF_S[timeframe] ?? 14400));
    volQty = (p.portfolio * (p.target_annual_vol_pct / 100)) / ann / entry;
    caps["volatility target"] = volQty;
  }
  for (const [name, cap] of Object.entries(caps)) if (cap < qty) { qty = cap; binding = name; }
  const notional = qty * entry;
  return {
    allowed: qty > 0, reason: qty > 0 ? null : "no exposure budget left", qty, notional, notional_pct: (notional / p.portfolio) * 100,
    risk_amount: risk, max_loss: qty * per, max_loss_pct: ((qty * per) / p.portfolio) * 100, stop_distance_pct: (per / entry) * 100,
    binding_constraint: binding, volatility_adjusted_qty: volQty, daily_loss_limit: daily, daily_loss_remaining: daily + Math.min(realisedToday, 0),
    notes: binding !== "risk per trade" ? [`Size reduced by the ${binding}`] : [], profile: p,
  };
}
