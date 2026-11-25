"""v2.22 engine combination (owner-approved 14 Nov 2026), proven together on unseen calls
(`research-results/results/combo-latest.json`: test −0.021R → +0.013R per trade, worst drawdown 130R → 31R; fewer calls).

* Volume-profile filter: profile of the last VP_LOOKBACK candles of the call's own timeframe (VP_BINS rows, typical
  price, 70 % value area). A long is skipped when the POC or VAH sits just above the price (within VP_K ATR): heavy
  traded volume right ahead. A short likewise with the POC or VAL just below.
* Fee filter: on FEE_FILTER_TFS a stop closer than FEE_MIN_STOP_PCT % makes fees too large a share of the risk.
  15m is left out (it got worse there in the test).
* Same-side cap: no new call while SAME_SIDE_CAP calls in that direction (all coins, all timeframes) are running.
Pure helpers; analysis.analyze applies them to live calls only (research replays keep measuring everything)."""
from __future__ import annotations

import os
from typing import Any

import numpy as np

VP_ON = os.environ.get("VP_FILTER", "1") != "0"
VP_LOOKBACK, VP_BINS, VP_AREA, VP_K = 200, 50, 0.70, 0.5
FEE_FILTER_TFS = tuple(t.strip() for t in os.environ.get("FEE_FILTER_TFS", "1h,4h").split(",") if t.strip())
FEE_MIN_STOP_PCT = float(os.environ.get("FEE_MIN_STOP_PCT", "1.5"))
SAME_SIDE_CAP = int(os.environ.get("SAME_SIDE_CAP", "12"))         # 0 = off; v2.64: 8 -> 12 (caps study 21 Nov 2026)


def profile(h: np.ndarray, l: np.ndarray, c: np.ndarray, v: np.ndarray) -> dict[str, float] | None:
    """POC / VAH / VAL (row centres) exactly as the research replay (research_ideas._profile)."""
    lo, hi = float(np.min(l)), float(np.max(h))
    if not np.isfinite(lo) or hi <= lo or v.sum() <= 0:
        return None
    tp = (h + l + c) / 3
    bins = np.clip(((tp - lo) / (hi - lo) * VP_BINS).astype(int), 0, VP_BINS - 1)
    vol = np.bincount(bins, weights=v, minlength=VP_BINS)
    centers = lo + (np.arange(VP_BINS) + 0.5) * (hi - lo) / VP_BINS
    p = int(np.argmax(vol))
    a, b, tot = p, p, vol[p]
    while tot < VP_AREA * vol.sum() and (a > 0 or b < VP_BINS - 1):
        up = vol[b + 1] if b < VP_BINS - 1 else -1
        dn = vol[a - 1] if a > 0 else -1
        if up >= dn:
            b += 1
            tot += vol[b]
        else:
            a -= 1
            tot += vol[a]
    return {"poc": float(centers[p]), "vah": float(centers[b]), "val": float(centers[a])}


def vp_block(df: Any, side: int, price: float, atr: float) -> str | None:
    """Reason text when a heavy volume level sits just ahead of the trade, else None."""
    if not VP_ON or df is None or len(df) < VP_LOOKBACK or not (atr and atr > 0) or "volume" not in df:
        return None
    t = df.tail(VP_LOOKBACK)
    p = profile(t["high"].to_numpy(float), t["low"].to_numpy(float), t["close"].to_numpy(float), t["volume"].to_numpy(float))
    if p is None:
        return None
    levels = (("POC", p["poc"]), ("VAH", p["vah"])) if side > 0 else (("POC", p["poc"]), ("VAL", p["val"]))
    for name, lvl in levels:
        if 0 < side * (lvl - price) <= VP_K * atr:
            return (f"heavy traded volume just {'above' if side > 0 else 'below'} the price (volume profile {name} "
                    f"{lvl:.6g}, within {VP_K:g} ATR): little room before it")
    return None


def fee_block(timeframe: str, price: float, stop: float | None) -> str | None:
    if timeframe not in FEE_FILTER_TFS or not stop or not price:
        return None
    pct = abs(price - stop) / price * 100
    if pct < FEE_MIN_STOP_PCT:
        return (f"the stop is only {pct:.2f}% away: on {timeframe.upper()} a stop under {FEE_MIN_STOP_PCT:g}% leaves fees "
                "too large a share of the risk")
    return None


# v2.68 (owner, 22 Nov 2026: "the longer timeframes take the quota - keep a free slot for each timeframe"): a timeframe
# with NO running call on that side may still open one when the limit is full. Slot study (research_slots.py,
# research-results/results/slots-latest.json, 904 unseen calls): +32.8R -> +34.2R, max drawdown unchanged (41.5R), only 27
# calls differ (too few to prove: INCONCLUSIVE); per-timeframe caps (4 or 5 each, total 12 / 16 / 20) FAILED - they
# helped 15m / 1h / 12h but cut 4h, the strongest timeframe, by a third. Env SAME_SIDE_RESERVE=0 turns the reserve off.
SAME_SIDE_RESERVE = os.environ.get("SAME_SIDE_RESERVE", "1") != "0"


def cap_block(db: Any, side: int, timeframe: str | None = None) -> str | None:
    if SAME_SIDE_CAP <= 0:
        return None
    row = db.one("SELECT COUNT(*) AS n FROM signals WHERE status = 'OPEN' AND side = ? "
                 "AND (fill_status IS NULL OR fill_status = 'FILLED')", (int(side),))
    n = int((row or {}).get("n") or 0)
    if n >= SAME_SIDE_CAP:
        if SAME_SIDE_RESERVE and timeframe:
            mine = db.one("SELECT COUNT(*) AS n FROM signals WHERE status = 'OPEN' AND side = ? AND timeframe = ? "
                          "AND (fill_status IS NULL OR fill_status = 'FILLED')", (int(side), timeframe))
            if not int((mine or {}).get("n") or 0):
                return None                      # this timeframe's reserved slot
        return (f"{n} {'long' if side > 0 else 'short'} calls are already running (limit {SAME_SIDE_CAP}): one market "
                "move could hit them all together")
    return None                                  # V3.2 (audit R-18): unreachable duplicate body after this removed
