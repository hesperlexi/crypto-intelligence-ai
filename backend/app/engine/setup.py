"""Entry / exit engine: turns a directional signal into a concrete, risk-defined trade plan - or refuses to.

Levels come from market structure (support / resistance zones, swings) with ATR bounds. Target
probabilities are historical first-passage base rates, not model promises.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..ml.distribution import first_passage_base_rate

# v2.2 targets (every timeframe): TP1 at exactly 1:1 closes half the position (then the stop moves to
# break-even); TP2 (between 1:1.25 and 1:2) and TP3 (between 1:2 and 1:3) are chosen from the data - how often
# price historically reached each level before the stop in similar conditions - and capped by support /
# resistance in the way. A quarter of the position closes at each of them.
TP1_R = 1.0
TP2_RANGE = (1.25, 1.5, 1.75, 2.0)
TP3_RANGE = (2.0, 2.25, 2.5, 2.75, 3.0)
TP_SPLIT = (0.5, 0.25, 0.25)
R_MULTIPLES = (1.0, 1.75, 2.5)        # typical levels, used where a fixed ladder is needed (trade-filter labels)


def build_setup(ind: pd.DataFrame, zones: dict[str, list[dict]], side: int, min_rr: float = 1.25,
                horizon: int = 30, live_price: float | None = None,
                lift: dict[float, float] | None = None) -> dict[str, Any]:
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

    # --- targets: TP1 at 1:1 (50%), TP2 / TP3 chosen from the data up to 1:2 / 1:3 -------------------------
    high, low, close, a = (ind[c].to_numpy(float) for c in ("high", "low", "close", "atr"))
    cond = (np.sign(ind["regime_score"].to_numpy(float)) == side)

    def base_rate(r_mult: float) -> dict[str, Any]:
        br = first_passage_base_rate(high, low, close, a, r_mult * dist / atr, dist / atr, horizon, cond, side)
        if br["probability"] is None:    # too few similar-regime entries: fall back to all history
            br = first_passage_base_rate(high, low, close, a, r_mult * dist / atr, dist / atr, horizon, None, side)
            br["basis"] = "all historical bars"
        else:
            br["basis"] = "historical bars in a same-direction regime"
        return br

    # support / resistance ahead caps how far a target may reach
    walls = sorted(side * ((z["low"] if side > 0 else z["high"]) - ideal) / dist for z in ahead)
    walls = [w for w in walls if w > TP1_R]

    def pick(options: tuple[float, ...], floor: float) -> tuple[float, str, dict[str, Any]]:
        cands = [m for m in options if m >= floor - 1e-9]
        wall = next((w for w in walls if w > floor), None)
        if wall is not None:
            capped = [m for m in cands if m <= wall + 1e-9]
            cands = capped or cands[:1]
        best = None
        for m in cands:
            br = dict(base_rate(m))
            k = (lift or {}).get(float(m))
            if k is not None and br.get("probability") is not None:      # the AI's view of THIS setup
                br["probability"] = float(min(0.99, br["probability"] * k))
                br["ai_lift"] = round(k, 3)
                br["basis"] = f"{br.get('basis')}, adjusted by the AI for this setup (x{k:.2f})"
            score = (br["probability"] or 0.0) * m          # expected R of this leg (it runs at break-even)
            if best is None or score > best[0] + 1e-9:
                best = (score, m, br)
        ai = best[2].get("ai_lift") is not None
        basis = ("AI-chosen" if ai else "data-chosen") + (", capped by " + ("resistance" if side > 0 else "support") if wall is not None and best[1] <= wall else "")
        return best[1], basis, best[2]

    br1 = base_rate(TP1_R)
    m2, basis2, br2 = pick(TP2_RANGE, TP2_RANGE[0])
    m3, basis3, br3 = pick(TP3_RANGE, max(TP3_RANGE[0], m2 + 0.25))
    mults = [TP1_R, m2, m3]
    targets: list[tuple[float, str]] = [(float(ideal + side * TP1_R * dist), "1:1, closes 50%"),
                                        (float(ideal + side * m2 * dist), f"1:{m2:g}, {basis2}"),
                                        (float(ideal + side * m3 * dist), f"1:{m3:g}, {basis3}")]
    tps = [t[0] for t in targets]
    rr = [float(m) for m in mults]
    probs = [br1, br2, br3]

    blocker = None
    if ahead:
        first = ahead[0]["low"] if side > 0 else ahead[0]["high"]
        gap = side * (first - price)
        if gap < 1.0 * dist:
            blocker = {"level": float(first), "distance_pct": float(gap / price * 100),
                       "note": f"{'Resistance' if side > 0 else 'Support'} {abs(gap / price * 100):.1f}% away, "
                               f"closer than 1R"}
    main_rr = float(sum(w * r for w, r in zip(TP_SPLIT, rr)))      # blended: 50% at 1R, 25% at TP2, 25% at TP3
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
        "risk_reward": main_rr, "risk_reward_basis": "blended over the exits (50% at TP1, 25% at TP2, 25% at TP3) vs the stop",
        "tp_split": list(TP_SPLIT),
        "horizon_bars": horizon, "blocker": blocker,
        "extended": bool(abs(price - ideal) >= 0.4 * atr),
    }
    # expected value per unit risk using the base rates (target before stop within the horizon)
    p1 = probs[0]["probability"]
    out["expectancy_r"] = float(p1 * rr[0] - probs[0]["stopped_first"]) if p1 is not None else None
    if out["expectancy_r"] is not None and out["expectancy_r"] < -0.15:
        return {**out, "valid": False,
                "reason": f"historical base rate implies negative expectancy ({out['expectancy_r']:+.2f}R at TP1, 1:1)"}
    if main_rr < min_rr - 1e-6:          # tolerance: a 1:1 target computes as 0.9999999
        return {**out, "valid": False, "reason": f"risk/reward 1:{main_rr:.1f} is below the minimum 1:{min_rr:g}"}
    if blocker is not None:
        return {**out, "valid": False, "reason": blocker["note"] + ": reward does not justify the risk"}
    return {**out, "valid": True, "reason": None}
