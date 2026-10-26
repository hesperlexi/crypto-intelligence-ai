"""Perpetual-futures maths and the futures view of an analysis. Pure functions, no I/O, no real orders.

Isolated margin, USDT-margined perpetuals (Binance-style):
* liquidation (simplified, ignores fees):  long  = entry * (1 - 1/L + mmr)
                                            short = entry * (1 + 1/L - mmr)
* funding is exchanged every 8 hours (00:00, 08:00, 16:00 UTC): longs pay shorts when the rate is positive
* leverage is never chosen so high that liquidation sits inside the stop: the "safe" leverage keeps the
  liquidation price at least `buffer` times the stop distance away from the entry
"""
from __future__ import annotations

import math
from typing import Any

FUNDING_INTERVAL_MS = 8 * 3_600_000
DEFAULT_FUNDING_RATE = 0.0001        # Binance base rate: 0.01% per 8h
MAINTENANCE_MARGIN = 0.005           # 0.5%: a conservative tier-1 rate for majors (BTC 0.4%, many alts 0.5-1%)
FUTURES_FEE_RATE = 0.0005            # 0.05% taker
MAX_LEVERAGE = 20


def liquidation_price(entry: float, side: int, leverage: float, mmr: float = MAINTENANCE_MARGIN) -> float:
    lev = max(1.0, float(leverage))
    if side > 0:
        return max(0.0, entry * (1 - 1 / lev + mmr))
    return entry * (1 + 1 / lev - mmr)


def safe_leverage(entry: float, stop: float | None, max_leverage: float = MAX_LEVERAGE,
                  mmr: float = MAINTENANCE_MARGIN, buffer: float = 1.5) -> int:
    """Highest whole leverage whose liquidation price stays `buffer` x the stop distance beyond the entry."""
    if not stop or not entry:
        return 1
    dist = abs(entry - stop) / entry
    if dist <= 0:
        return 1
    lev = 1 / (buffer * dist + mmr)
    return int(max(1, min(max_leverage, math.floor(lev))))


def funding_times(after_ms: int, until_ms: int) -> list[int]:
    """Funding timestamps t with after_ms < t <= until_ms."""
    first = (after_ms // FUNDING_INTERVAL_MS + 1) * FUNDING_INTERVAL_MS
    return list(range(first, until_ms + 1, FUNDING_INTERVAL_MS))


def futures_view(a: dict[str, Any], funding: dict[str, Any] | None, max_leverage: int = 10) -> dict[str, Any]:
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
    lev = safe_leverage(entry, stop, max_leverage) if setup.get("stop") else None
    plan_side = setup.get("side_int") or side
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
    }
    if setup.get("stop") and entry:
        risk_pct = abs(entry - stop) / entry * 100
        out["plan"] = {
            "side": "LONG" if plan_side > 0 else "SHORT", "valid": bool(setup.get("valid")),
            "reason": setup.get("reason"), "entry": entry, "entry_zone": setup.get("entry_zone"), "stop": stop,
            "targets": [{"name": t["name"], "price": t["price"], "rr": t["rr"], "probability": t.get("probability")}
                        for t in setup.get("targets") or []],
            "risk_reward": setup.get("risk_reward"), "risk_pct": risk_pct,
            "suggested_leverage": lev,
            "liquidation_at_suggested": liquidation_price(entry, plan_side, lev) if lev else None,
            "margin_loss_at_stop_pct": risk_pct * lev if lev else None,
            # holding cost of the funding rate for this side, per day (3 payments), as % of position notional
            "funding_per_day_pct": -plan_side * rate_used * 3 * 100,
            "liquidation_by_leverage": {str(L): liquidation_price(entry, plan_side, L) for L in (2, 3, 5, 10, 20)},
        }
    return out
