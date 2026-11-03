"""Perpetual-futures maths and the futures view of an analysis. Pure functions, no I/O, no real orders.

Isolated margin, USDT-margined perpetuals (Binance-style):
* liquidation (v2.13, with the maintenance rate of the coin and the taker fee of closing the position):
      long  = entry * (1 - 1/L) / (1 - mmr - fee)
      short = entry * (1 + 1/L) / (1 + mmr + fee)
  i.e. the price at which margin + P/L only covers the maintenance margin plus the exit fee.
* maintenance margin rates (v2.13): `maintenance_rate(symbol)`, an APPROXIMATION of Binance's tier-1 rates (smallest
  position bracket; the real tables change and are per contract): BTC / ETH 0.4 %, large caps 0.5 %, other alts 1.0 %,
  gold (PAXG) and memecoins 2.0 %, anything unknown 1.0 % - rounded up where unsure, so liquidation is never shown
  later than it would be.
* funding is exchanged every 8 hours (00:00, 08:00, 16:00 UTC): longs pay shorts when the rate is positive
* leverage is never chosen so high that liquidation sits inside the stop: the "safe" leverage keeps the
  liquidation price at least `buffer` times the stop distance away from the entry
"""
from __future__ import annotations

import math
import os
from typing import Any

FUNDING_INTERVAL_MS = 8 * 3_600_000
DEFAULT_FUNDING_RATE = 0.0001        # Binance base rate: 0.01% per 8h
MAINTENANCE_MARGIN = 0.01            # v2.13: the rate for a coin not in MAINTENANCE_TIERS (was a flat 0.5 %)
FUTURES_FEE_RATE = 0.0005            # 0.05% taker
MAX_LEVERAGE = 20                    # futures demo bots' ceiling outside the v2.14 policy timeframes (v2.13)
# v2.14 leverage policy (owner, 3 Nov 2026), ONLY on the timeframes in POLICY_TFS (owner: 15m only): the signal card,
# the record's ROI on margin, the demo bots, Hesper and members' auto-trade use leverage CHOSEN BY THE ENGINE from the
# stop distance, the coin's margin tier and the grade: clamp(safe max x grade factor, 10, 50). A trade whose safe max is
# below 10x (the stop is too wide for 10x without liquidation coming first) is not taken. Every other timeframe keeps
# the v2.13 behaviour exactly (card / record: safe leverage capped at 10x; bots: safe up to their config, 20x; Hesper:
# safe up to 25x; auto-trade: v2.13 rules, cap 20x) - see `leverage_for`.
POLICY_TFS = tuple(t.strip() for t in os.environ.get("LEVERAGE_POLICY_TFS", "15m").split(",") if t.strip())
MIN_LEVERAGE = 10
POLICY_MAX_LEVERAGE = 50
GRADE_FACTOR = {"A": 1.0, "B": 0.75}  # anything else (no grade): 0.75
TOO_WIDE_REASON = "stop too wide for 10x minimum"
SAFE_CAP = 125                       # the safe max is measured up to the exchange's own maximum, then clamped to 10-50
CARD_MAX_LEVERAGE = 10               # the signal card's suggested leverage is capped here outside POLICY_TFS (v2.13)
CARD_BUFFER = 1.5                    # liquidation at least 1.5x the stop distance beyond the entry
MIN_BUFFER = 1.5                     # v2.13: no safe leverage is ever computed with a smaller buffer
# v2.13: approximate Binance USDT-M tier-1 maintenance margin rates (see the module doc)
MAINTENANCE_TIERS = {
    "BTC": 0.004, "ETH": 0.004,
    "BNB": 0.005, "SOL": 0.005, "XRP": 0.005, "LTC": 0.005, "ADA": 0.005, "LINK": 0.005, "DOT": 0.005,
    "AVAX": 0.01, "AAVE": 0.01, "TRX": 0.01, "BCH": 0.01, "ATOM": 0.01, "NEAR": 0.01, "TON": 0.01, "GRAM": 0.01,
    "DOGE": 0.02, "SHIB": 0.02, "PEPE": 0.02, "1000PEPE": 0.02, "1000SHIB": 0.02, "WIF": 0.02, "BONK": 0.02,
    "1000BONK": 0.02, "FLOKI": 0.02, "1000FLOKI": 0.02, "TRUMP": 0.025,
    "PAXG": 0.02, "XAUT": 0.02, "GOLD": 0.02,
}


def maintenance_rate(symbol: str | None) -> float:
    """Tier-1 maintenance margin rate of a coin (approximation; unknown coins: MAINTENANCE_MARGIN)."""
    if not symbol:
        return MAINTENANCE_MARGIN
    base = str(symbol).upper().split("/")[0].replace("USDT", "") or str(symbol).upper()
    return float(MAINTENANCE_TIERS.get(base, MAINTENANCE_MARGIN))


def liquidation_price(entry: float, side: int, leverage: float, mmr: float | None = None, symbol: str | None = None,
                      fee: float = FUTURES_FEE_RATE) -> float:
    """Isolated-margin liquidation price including the coin's maintenance rate and the fee of closing at that price."""
    lev = max(1.0, float(leverage))
    m = maintenance_rate(symbol) if mmr is None else float(mmr)
    if side > 0:
        return max(0.0, entry * (1 - 1 / lev) / (1 - m - fee))
    return entry * (1 + 1 / lev) / (1 + m + fee)


def safe_leverage(entry: float, stop: float | None, max_leverage: float = MAX_LEVERAGE,
                  mmr: float | None = None, buffer: float = 1.5, symbol: str | None = None,
                  fee: float = FUTURES_FEE_RATE) -> int:
    """Highest whole leverage whose liquidation price (maintenance rate + exit fee) stays at least `buffer` (>= 1.5) x
    the stop distance beyond the entry. Uses the stricter (short-side) form for both sides."""
    if not stop or not entry:
        return 1
    dist = abs(entry - stop) / entry
    if dist <= 0:
        return 1
    m = maintenance_rate(symbol) if mmr is None else float(mmr)
    b = max(MIN_BUFFER, float(buffer))
    # long: (1/L - m - f) / (1 - m - f) >= b*d ; short: (1/L - m - f) / (1 + m + f) >= b*d  -> the short form is stricter
    lev = 1 / (b * dist * (1 + m + fee) + m + fee)
    return int(max(1, min(max_leverage, math.floor(lev))))


def safe_max_leverage(entry: float | None, stop: float | None, symbol: str | None = None) -> int | None:
    """Highest whole leverage (<= SAFE_CAP 125, the exchange's maximum) whose liquidation (coin tier + closing fee) sits >= 1.5x the stop distance beyond
    the entry. None without a usable entry / stop (stop on the wrong side counts as no stop distance)."""
    if not entry or not stop:
        return None
    try:
        e, s = float(entry), float(stop)
    except (TypeError, ValueError):
        return None
    if not (e > 0 and s > 0) or e == s:
        return None
    return safe_leverage(e, s, SAFE_CAP, None, CARD_BUFFER, symbol=symbol)


def engine_leverage(entry: float | None, stop: float | None, symbol: str | None = None,
                    grade: str | None = None, timeframe: str | None = None,
                    cap: float = CARD_MAX_LEVERAGE) -> int | None:
    """v2.14 leverage of a futures trade (card, record, bots, Hesper, auto-trade). On a timeframe in POLICY_TFS (or with
    no timeframe given: the bare rule) it is chosen by the engine from the stop distance, the coin's margin tier and the
    grade: clamp(safe max x grade factor, 10, 50), grade A 100 %, grade B (or none) 75 % of the safe max. None = not
    taken: the safe max is below 10x (`TOO_WIDE_REASON`), so the minimum leverage would put liquidation too close to (or
    before) the stop. Never above the safe max. On any other timeframe: the v2.13 rule (safe leverage capped at `cap`)."""
    if timeframe is not None and not in_policy(timeframe):
        if not entry or not stop:
            return None
        return safe_leverage(float(entry), float(stop), cap, None, CARD_BUFFER, symbol=symbol)
    safe = safe_max_leverage(entry, stop, symbol)
    if safe is None or safe < MIN_LEVERAGE:
        return None
    f = GRADE_FACTOR.get(str(grade or "").upper(), GRADE_FACTOR["B"])
    lev = int(math.floor(safe * f + 1e-9))
    return int(max(MIN_LEVERAGE, min(POLICY_MAX_LEVERAGE, safe, lev)))


def in_policy(timeframe: str | None) -> bool:
    """Does the v2.14 engine-chosen 10-50x leverage policy apply to this timeframe? (owner: 15m only)"""
    return bool(timeframe) and str(timeframe) in POLICY_TFS


def leverage_for(entry: float | None, stop: float | None, symbol: str | None = None, grade: str | None = None,
                 timeframe: str | None = None, cap: float = CARD_MAX_LEVERAGE) -> int | None:
    """The leverage of a futures trade on `timeframe`: in POLICY_TFS the v2.14 engine rule (`engine_leverage`, None =
    not taken); elsewhere the v2.13 rule - the safe leverage (liquidation >= 1.5x the stop distance) capped at `cap`
    (card / record 10, bots their config, Hesper 25, auto-trade 20), never refused for a wide stop. None without a stop."""
    return engine_leverage(entry, stop, symbol, grade, timeframe if in_policy(timeframe) else (timeframe or "-"), cap)


def signal_leverage(entry: float | None, stop: float | None, symbol: str | None = None,
                    grade: str | None = None, timeframe: str | None = None) -> int | None:
    """The leverage the signal card shows and the record stores: 15m (POLICY_TFS) the engine's 10-50x (None = not
    tradable), other timeframes the v2.13 suggestion (safe leverage capped at 10x)."""
    return leverage_for(entry, stop, symbol, grade, timeframe, CARD_MAX_LEVERAGE)


def stop_before_liquidation(entry: float, stop: float, side: int, leverage: float, symbol: str | None = None) -> bool:
    """True when the stop is hit strictly before the liquidation price (the rule every leverage choice keeps)."""
    liq = liquidation_price(entry, side, leverage, symbol=symbol)
    return (stop > liq) if side > 0 else (stop < liq)


def roi_on_margin(return_pct: float | None, leverage: float | None) -> float | None:
    """Result on the margin put up: the price return (blended exits) times the leverage. Losses multiply too;
    the sign never changes, so a win stays a win and a loss a loss."""
    if return_pct is None or not leverage:
        return None
    return float(return_pct) * float(leverage)


def funding_times(after_ms: int, until_ms: int) -> list[int]:
    """Funding timestamps t with after_ms < t <= until_ms."""
    first = (after_ms // FUNDING_INTERVAL_MS + 1) * FUNDING_INTERVAL_MS
    return list(range(first, until_ms + 1, FUNDING_INTERVAL_MS))


def futures_view(a: dict[str, Any], funding: dict[str, Any] | None, max_leverage: int | None = None) -> dict[str, Any]:
    """Long / short call for one symbol and timeframe, built from the regular analysis."""
    sym = a.get("symbol")
    if a.get("status") != "OK":
        return {"symbol": sym, "status": a.get("status"), "reason": a.get("reason") or a.get("decision_reason")}
    fc = a.get("forecast") or {}
    probs = fc.get("probabilities") or {}
    p_up, p_down = probs.get("up"), probs.get("down")
    setup = a.get("setup") or {}
    decision = a.get("decision")
    side = 1 if decision in ("BUY", "BUY ON PULLBACK") else -1 if decision == "SELL" else 0
    action = {1: "LONG", -1: "SHORT", 0: "NO TRADE"}[side]
    if decision == "BUY ON PULLBACK":
        action = "LONG ON PULLBACK"
    # lean: what the probabilities alone favour, shown even when there is no trade
    lean = None
    if p_up is not None and p_down is not None:
        lean = "LONG" if p_up > p_down + 0.03 else "SHORT" if p_down > p_up + 0.03 else "NEUTRAL"
    price = a.get("price")
    entry = setup.get("ideal_entry") or price
    stop = setup.get("stop")
    plan_side = setup.get("side_int") or side
    targets = [{"name": t["name"], "price": t["price"], "rr": t["rr"], "probability": t.get("probability")}
               for t in setup.get("targets") or []]
    runner = setup.get("runner")
    # v2.13: while the call is in the record (open, same side), the card shows the RECORDED levels - the entry the
    # record counts from (the market price for a call entered at publication), its stop and its targets - so members
    # see exactly the trade the results are computed on
    call = a.get("call") or {}
    recorded = bool(call and call.get("status") == "OPEN" and call.get("entry") and call.get("stop")
                    and (1 if call.get("side") == "LONG" else -1) == (1 if plan_side > 0 else -1) and side)
    if recorded:
        entry, stop = float(call["entry"]), float(call.get("stop0") or call["stop"])
        d = abs(entry - stop)
        targets = [{"name": f"TP{i + 1}", "price": float(p), "rr": abs(float(p) - entry) / d if d else None,
                    "probability": (targets[i].get("probability") if i < len(targets) else None)}
                   for i, p in enumerate((call.get("tp1_0") or call.get("tp1"), call.get("tp2"), call.get("tp3"))) if p is not None]
        if runner and runner.get("on"):
            rr = float(runner.get("rr") or 4.0)
            tgt = entry + (1 if plan_side > 0 else -1) * rr * d
            runner = {**runner, "target": tgt, "move_pct": abs(tgt / entry - 1) * 100}
    # v2.14: the engine's leverage (10-50x from stop distance, coin tier and grade); a recorded call shows the leverage
    # stored with it (same function, decided at publication)
    tf = a.get("timeframe")
    policy = in_policy(tf)
    if max_leverage is None:
        max_leverage = POLICY_MAX_LEVERAGE if policy else CARD_MAX_LEVERAGE
    lev = (call.get("leverage") if recorded else None) or (leverage_for(entry, stop, sym, a.get("grade"), tf, max_leverage)
                                                           if stop else None)
    if lev:
        lev = int(min(lev, max_leverage))
    rate = (funding or {}).get("rate")
    rate_used = rate if rate is not None else DEFAULT_FUNDING_RATE
    out = {
        "symbol": sym, "status": "OK", "timeframe": a.get("timeframe"), "price": price, "bar_ts": a.get("bar_ts"),
        "action": action, "side": side, "decision": decision, "decision_reason": a.get("decision_reason"),
        "lean": lean, "p_up": p_up, "p_down": p_down, "p_neutral": probs.get("neutral"),
        "confidence": a.get("confidence"), "model_agreement": a.get("model_agreement"),
        "confident_call": fc.get("confident_call"), "grade": a.get("grade"), "decision_basis": a.get("decision_basis"),
        "news_risk": a.get("news_risk"), "filter_score": a.get("filter_score"), "filter_threshold": a.get("filter_threshold"),
        "policy_margin": (a.get("direction_view") or {}).get("policy_margin"), "margin": (a.get("direction_view") or {}).get("margin"),
        "edge_confirmed": fc.get("edge_confirmed"), "expected_return": fc.get("expected_return"),
        "regime": (a.get("regime") or {}).get("regime"), "volatility": (a.get("volatility") or {}).get("state"),
        "atr_pct": (a.get("volatility") or {}).get("atr_pct"), "signal": (a.get("signal") or {}).get("signal"),
        "funding_rate": rate, "funding_source": (funding or {}).get("source"),
        "funding_rate_used": rate_used,
        # v1 contract: the tracked call, whether this call is in the record, stale data, the advisor note
        "call": a.get("call"), "record_status": a.get("record_status"), "stale": bool(a.get("stale")),
    }
    if a.get("ai"):
        out["ai"] = a["ai"]
    if stop and entry:
        risk_pct = abs(entry - stop) / entry * 100
        out["plan"] = {
            "side": "LONG" if plan_side > 0 else "SHORT", "valid": bool(setup.get("valid")),
            "reason": setup.get("reason"), "entry": entry, "entry_zone": setup.get("entry_zone"), "stop": stop,
            "recorded": recorded, "ideal_entry": setup.get("ideal_entry"),
            "targets": targets,
            "risk_reward": setup.get("risk_reward"), "risk_pct": risk_pct,
            "runner": runner,
            "suggested_leverage": lev,
            "leverage_policy": ({"min": MIN_LEVERAGE, "max": POLICY_MAX_LEVERAGE, "chosen_by": "engine",
                                 "safe_max": safe_max_leverage(entry, stop, sym)} if policy else None),
            "maintenance_rate": maintenance_rate(sym),
            "liquidation_at_suggested": liquidation_price(entry, plan_side, lev, symbol=sym) if lev else None,
            "margin_loss_at_stop_pct": risk_pct * lev if lev else None,
            # holding cost of the funding rate for this side, per day (3 payments), as % of position notional
            "funding_per_day_pct": -plan_side * rate_used * 3 * 100,
            "liquidation_by_leverage": {str(L): liquidation_price(entry, plan_side, L, symbol=sym) for L in ((10, 20, 30, 50) if policy else (2, 3, 5, 10, 20))},
        }
    return out
