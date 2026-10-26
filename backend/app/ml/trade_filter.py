"""Trade filter (meta-labelling): the question that actually makes money.

The direction models answer "is the next candle up or down?". A trade is decided over many candles: does the price
reach the targets before the stop? For every out-of-sample bar where the ensemble leaned one way, the trade the app
would take is replayed under the bots' own rules (stop ~1.5 ATR, targets at 1.5R / 2.5R / 4R, a third at each,
break-even after target 1, trailing to target 1 after target 2, time exit after `HORIZON` bars, costs included) and
labelled by its result in R. A gradient-boosting classifier learns which setups tend to pay.

Strict honesty about whether it helps (all on data the filter never trained on):
  * A (first 50 %) trains the filter, B (next 25 %) chooses how selective to be, C (last 25 %) is the exam;
  * it is switched on only if, on C, the trades it keeps earn clearly more R than all candidate trades.
At run time a signal whose filter score falls below the threshold becomes NO TRADE.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

log = logging.getLogger(__name__)
HORIZON = 30
STOP_ATR = 1.5
R_MULTIPLES = (1.5, 2.5, 4.0)
MIN_MARGIN = 0.02
KEEP_GRID = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
MIN_GAIN_R = 0.03


def trade_r(high: np.ndarray, low: np.ndarray, close: np.ndarray, atr: np.ndarray, i: int, side: int,
            cost_rate: float, horizon: int = HORIZON) -> float | None:
    """Result in R of a trade opened at close[i] under the bots' rules; None when the future is not known yet."""
    if i + horizon >= len(close) or not np.isfinite(atr[i]) or atr[i] <= 0:
        return None
    entry = close[i]
    dist = STOP_ATR * atr[i]
    stop = entry - side * dist
    tps = [entry + side * m * dist for m in R_MULTIPLES]
    hit, left, r = 0, 1.0, 0.0
    for j in range(i + 1, i + horizon + 1):
        h, lo = high[j], low[j]
        if (lo <= stop) if side > 0 else (h >= stop):       # the stop counts first when a candle touches both
            r += left * side * (stop - entry) / dist
            left = 0.0
            break
        while hit < 3 and ((h >= tps[hit]) if side > 0 else (lo <= tps[hit])):
            r += (1 / 3) * side * (tps[hit] - entry) / dist
            left -= 1 / 3
            hit += 1
            stop = entry if hit == 1 else tps[0] if hit == 2 else stop
        if left <= 1e-9:
            break
    if left > 1e-9:
        r += left * side * (close[i + horizon] - entry) / dist
    return r - 2 * cost_rate * entry / dist


def _features(X: np.ndarray, P: np.ndarray, side: np.ndarray) -> np.ndarray:
    margin = np.abs(P[:, 2] - P[:, 0])
    p_side = np.where(side > 0, P[:, 2], P[:, 0])
    return np.column_stack([X, P, margin, p_side, side])


def _model():
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=40,
                                          l2_regularization=1.0, random_state=0)


def train(X: np.ndarray, P: np.ndarray, rows: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray,
          atr: np.ndarray, cost_rate: float) -> dict[str, Any]:
    """X, P: features and out-of-sample ensemble probabilities of the candidate rows (time order); rows: their
    positions in the price arrays. Returns {'enabled': bool, ...} with the fitted filter when it helps."""
    side = np.where(P[:, 2] >= P[:, 0], 1, -1)
    margin = np.abs(P[:, 2] - P[:, 0])
    R = np.array([trade_r(high, low, close, atr, int(r), int(s), cost_rate) if m >= MIN_MARGIN else None
                  for r, s, m in zip(rows, side, margin)], dtype=object)
    ok = np.array([v is not None for v in R]) & np.isfinite(X).all(axis=1)
    n = int(ok.sum())
    if n < 400:
        return {"enabled": False, "reason": f"only {n} labelled candidate trades", "n": n}
    F = _features(X[ok], P[ok], side[ok])
    R = R[ok].astype(float)
    y = (R > 0).astype(int)
    a, b = int(n * 0.5), int(n * 0.75)
    if len(set(y[:a])) < 2:
        return {"enabled": False, "reason": "no winning and losing trades to learn from", "n": n}
    mA = _model().fit(F[:a], y[:a])
    pB, pC = mA.predict_proba(F[a:b])[:, 1], mA.predict_proba(F[b:])[:, 1]
    best_keep, best_gain = None, -1e9
    for keep in KEEP_GRID:                              # how selective to be, chosen on B only
        thr = np.quantile(pB, 1 - keep)
        sel = pB >= thr
        if sel.sum() >= 30:
            gain = R[a:b][sel].mean() - R[a:b].mean()
            if gain > best_gain:
                best_keep, best_gain = keep, gain
    if best_keep is None:
        return {"enabled": False, "reason": "too few trades to choose a threshold", "n": n}
    thr_c = np.quantile(pB, 1 - best_keep)
    selC = pC >= thr_c
    exam = {"n": int(len(pC)), "kept": int(selC.sum()), "avg_r_all": float(R[b:].mean()),
            "avg_r_kept": float(R[b:][selC].mean()) if selC.any() else None,
            "win_rate_all": float((R[b:] > 0).mean()), "win_rate_kept": float((R[b:][selC] > 0).mean()) if selC.any() else None}
    enabled = bool(selC.sum() >= 25 and exam["avg_r_kept"] is not None and exam["avg_r_kept"] - exam["avg_r_all"] >= MIN_GAIN_R)
    out = {"enabled": enabled, "keep_fraction": best_keep, "n": n, "exam": exam,
           "base_avg_r": float(R.mean()), "base_win_rate": float(y.mean())}
    if not enabled:
        out["reason"] = "the filter did not improve results on unseen trades"
        return out
    final = _model().fit(F, y)
    p_all = final.predict_proba(F)[:, 1]
    out.update(model=final, threshold=float(np.quantile(p_all, 1 - best_keep)),
               reason=f"kept trades earned {exam['avg_r_kept']:+.2f}R vs {exam['avg_r_all']:+.2f}R for all, on unseen data")
    return out


def score(tf: dict[str, Any] | None, x_row: np.ndarray, probs: dict[str, float]) -> dict[str, Any] | None:
    """Filter scores for a long and a short at the current bar (None when the model has no enabled filter)."""
    if not tf or not tf.get("enabled") or tf.get("model") is None or not np.isfinite(x_row).all():
        return None
    P = np.array([[probs["down"], probs["neutral"], probs["up"]]] * 2, float)
    F = _features(np.vstack([x_row, x_row]), P, np.array([1, -1]))
    p = tf["model"].predict_proba(F)[:, 1]
    return {"p_long": float(p[0]), "p_short": float(p[1]), "threshold": tf["threshold"],
            "keep_fraction": tf["keep_fraction"], "exam": tf.get("exam")}
