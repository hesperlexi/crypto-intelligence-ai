"""Entry / exit engine: turns a directional signal into a concrete, risk-defined trade plan - or refuses to.

Levels come from market structure (support / resistance zones, swings) with ATR bounds. Target
probabilities are historical first-passage base rates, not model promises.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..ml.distribution import first_passage_base_rate

R_MULTIPLES = (1.5, 2.5, 4.0)


def build_setup(ind: pd.DataFrame, zones: dict[str, list[dict]], side: int, min_rr: float = 1.5,
                horizon: int = 30, live_price: float | None = None) -> dict[str, Any]:
    """side = +1 (long) or -1 (short). Returns {'valid': False, 'reason': ...} when reward does not justify risk."""
    last = ind.iloc[-1]
    price = float(live_price if live_price else last["close"])
    atr = float(last["atr"])
    if not np.isfinite(atr) or atr <= 0 or side == 0:
        return {"valid": False, "reason": "ATR unavailable" if side else "no directional signal"}
    behind = zones["support"] if side > 0 else zones["resistance"]      # levels protecting the trade
    ahead = zones["resistance"] if side > 0 else zones["support"]       # levels in the way of the target
    ema21 = float(last["ema_21"]) if np.isfinite(last["ema_21"]) else None

    # --- entries -------------------------------------------------------------------------------------
    aggressive = price
    near = behind[0] if behind else None
    edge = (near["high"] if side > 0 else near["low"]) if near else None
    if edge is not None and abs(price - edge) <= 2.0 * atr:
        conservative = edge
    else:
        conservative = price - side * 1.0 * atr
    ideal = price - side * 0.5 * atr
    if ema21 is not None and side * (price - ema21) > 0 and abs(price - ema21) <= 1.5 * atr:
        ideal = side * max(side * ideal, side * ema21)       # shallower of the two pullback levels
    ideal = side * max(side * ideal, side * conservative)    # never beyond the conservative entry
    ideal = side * min(side * ideal, side * price)

    # --- stop: beyond structure, bounded to 1-3 ATR from the ideal entry --------------------------------
    struct = []
    if near:
        struct.append(near["low"] if side > 0 else near["high"])
    swing = last["last_sl"] if side > 0 else last["last_sh"]
    if np.isfinite(swing) and side * (ideal - swing) > 0:
        struct.append(float(swing))
    raw_stop = (min(struct) if side > 0 else max(struct)) - side * 0.25 * atr if struct else ideal - side * 1.5 * atr
    dist = float(np.clip(side * (ideal - raw_stop), 1.0 * atr, 3.0 * atr))
    stop = ideal - side * dist
    stop_basis = "structure" if struct and 1.0 * atr <= side * (ideal - raw_stop) <= 3.0 * atr else "ATR bound"

    # --- targets: structure levels ahead, filled with R-multiples -----------------------------------------
    levels = sorted({(z["low"] if side > 0 else z["high"]) for z in ahead}, reverse=side < 0)
    levels = [lv for lv in levels if side * (lv - ideal) >= 1.0 * dist]
    targets: list[tuple[float, str]] = []
    for i, mult in enumerate(R_MULTIPLES):
        floor = ideal + side * mult * dist
        prev = targets[-1][0] if targets else ideal
        if targets and side * (floor - prev) < 0.75 * dist:      # keep targets strictly ordered and spaced
            floor = prev + side * 0.75 * dist
        pick = next((lv for lv in levels if side * (lv - prev) > 0.5 * dist
                     and -0.5 * dist <= side * (lv - floor) <= 1.5 * dist), None)
        if pick is not None:
            targets.append((float(pick), "structure level"))
            levels = [lv for lv in levels if side * (lv - pick) > 0]
        else:
            targets.append((float(floor), f"{side * (floor - ideal) / dist:.1f}R"))
    tps = [t[0] for t in targets]
    rr = [side * (tp - ideal) / dist for tp in tps]

    # --- base-rate probabilities of reaching each target before the stop ---------------------------------
    high, low, close, a = (ind[c].to_numpy(float) for c in ("high", "low", "close", "atr"))
    cond = (np.sign(ind["regime_score"].to_numpy(float)) == side)
    probs = []
    for tp in tps:
        br = first_passage_base_rate(high, low, close, a, side * (tp - ideal) / atr, dist / atr, horizon, cond, side)
        if br["probability"] is None:    # too few similar-regime entries: fall back to all history
            br = first_passage_base_rate(high, low, close, a, side * (tp - ideal) / atr, dist / atr, horizon, None, side)
            br["basis"] = "all historical bars"
        else:
            br["basis"] = "historical bars in a same-direction regime"
        probs.append(br)

    blocker = None
    if ahead:
        first = ahead[0]["low"] if side > 0 else ahead[0]["high"]
        gap = side * (first - price)
        if gap < 1.0 * dist:
            blocker = {"level": float(first), "distance_pct": float(gap / price * 100),
                       "note": f"{'Resistance' if side > 0 else 'Support'} {abs(gap / price * 100):.1f}% away, "
                               f"closer than 1R"}
    main_rr = float(rr[1])
    out = {
        "side": "LONG" if side > 0 else "SHORT", "side_int": side, "price": price, "atr": atr,
        "entry_zone": [float(min(conservative, aggressive)), float(max(conservative, aggressive))],
        "ideal_entry": float(ideal), "aggressive_entry": float(aggressive), "conservative_entry": float(conservative),
        "stop": float(stop), "stop_basis": stop_basis, "stop_distance_atr": float(dist / atr),
        "risk_pct": float(dist / ideal * 100),
        "targets": [{"name": f"TP{i + 1}", "price": tps[i], "basis": targets[i][1], "rr": float(rr[i]),
                     "move_pct": float(side * (tps[i] / ideal - 1) * 100),
                     "probability": probs[i]["probability"], "probability_n": probs[i]["n"],
                     "probability_basis": probs[i].get("basis"), "ci95": probs[i].get("ci95")} for i in range(3)],
        "risk_reward": main_rr, "risk_reward_basis": "TP2 vs stop, from the ideal entry",
        "horizon_bars": horizon, "blocker": blocker,
        "extended": bool(abs(price - ideal) >= 0.4 * atr),
    }
    # expected value per unit risk using the base rates (target before stop within the horizon)
    p2 = probs[1]["probability"]
    out["expectancy_r"] = float(p2 * rr[1] - probs[1]["stopped_first"]) if p2 is not None else None
    if out["expectancy_r"] is not None and out["expectancy_r"] < -0.15:
        return {**out, "valid": False,
                "reason": f"historical base rate implies negative expectancy ({out['expectancy_r']:+.2f}R at TP2)"}
    if main_rr < min_rr:
        return {**out, "valid": False, "reason": f"risk/reward 1:{main_rr:.1f} is below the minimum 1:{min_rr:g}"}
    if blocker is not None:
        return {**out, "valid": False, "reason": blocker["note"] + ": reward does not justify the risk"}
    return {**out, "valid": True, "reason": None}
