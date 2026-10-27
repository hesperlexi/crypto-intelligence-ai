"""Let winners run (v2.3): at take-profit 1, should this trade bank half or keep the whole position running?

Standard exit (bots' rules): 50% at TP1 (1R), 25% at TP2, 25% at TP3; stop to break-even after TP1, to TP1 after TP2.
Runner exit: nothing is closed at TP1; the stop follows the price up the ladder instead - break-even after TP1, TP1
after TP2, TP2 after TP3 - and the whole position closes at the runner target (RUN_R = 1:4), at the trailing stop,
or at the time limit. A runner earns more when the move keeps going and gives back the TP1 half when it turns.

The model learns, from the AI's own out-of-sample calls, which setups did better as runners. It is used only if,
on the last quarter of those calls (never seen while fitting or choosing the threshold), "runner when the model says
so, standard otherwise" beat "always standard" by at least MIN_GAIN_R per trade, with enough runner trades to trust
it. Otherwise it stays off for that coin/timeframe and every trade uses the standard exit.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from .trade_filter import HORIZON, MIN_MARGIN, R_MULTIPLES, STOP_ATR, TP_SPLIT, _features

log = logging.getLogger(__name__)
RUN_R = 4.0
MIN_GAIN_R = 0.04
KEEP_GRID = (0.2, 0.3, 0.4, 0.5, 0.7, 1.0)


def exits_r(high: np.ndarray, low: np.ndarray, close: np.ndarray, entry: float, dist: float, side: int, start: int,
            horizon: int, tps_r: tuple[float, ...] = R_MULTIPLES, run: bool = False) -> tuple[float, bool]:
    """Result in R (before costs) of one trade opened at `entry` after bar `start`, and whether TP1 was reached.
    The stop counts first when a candle touches both."""
    stop = entry - side * dist
    tps = [entry + side * m * dist for m in tps_r]
    final = entry + side * RUN_R * dist
    hit, left, r = 0, 1.0, 0.0
    end = min(start + horizon, len(close) - 1)
    for j in range(start + 1, end + 1):
        h, lo = high[j], low[j]
        if (lo <= stop) if side > 0 else (h >= stop):
            return r + left * side * (stop - entry) / dist, hit > 0
        if run:
            while hit < 3 and ((h >= tps[hit]) if side > 0 else (lo <= tps[hit])):
                hit += 1
                stop = entry if hit == 1 else tps[hit - 2]
            if (h >= final) if side > 0 else (lo <= final):
                return RUN_R, True
        else:
            while hit < 3 and ((h >= tps[hit]) if side > 0 else (lo <= tps[hit])):
                part = TP_SPLIT[hit] if hit < 2 else left
                r += part * side * (tps[hit] - entry) / dist
                left -= part
                hit += 1
                stop = entry if hit == 1 else tps[0] if hit == 2 else stop
            if left <= 1e-9:
                return r, True
    return r + left * side * (close[end] - entry) / dist, hit > 0


def _model():
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=40,
                                          l2_regularization=1.0, random_state=0)


def train(X: np.ndarray, P: np.ndarray, rows: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray,
          atr: np.ndarray, cost_rate: float, horizon: int = HORIZON) -> dict[str, Any]:
    side = np.where(P[:, 2] >= P[:, 0], 1, -1)
    margin = np.abs(P[:, 2] - P[:, 0])
    std, run, reach, keep = [], [], [], []
    for k, (i, s, m) in enumerate(zip(rows, side, margin)):
        i = int(i)
        if m < MIN_MARGIN or i + horizon >= len(close) or not np.isfinite(atr[i]) or atr[i] <= 0 or not np.isfinite(X[k]).all():
            continue
        entry, dist = close[i], STOP_ATR * atr[i]
        cost = 2 * cost_rate * entry / dist
        a, hit = exits_r(high, low, close, entry, dist, int(s), i, horizon)
        b, _ = exits_r(high, low, close, entry, dist, int(s), i, horizon, run=True)
        std.append(a - cost)
        run.append(b - cost)
        reach.append(hit)
        keep.append(k)
    n = len(keep)
    if n < 400:
        return {"enabled": False, "reason": f"only {n} labelled trades", "n": n}
    keep = np.array(keep)
    F = _features(X[keep], P[keep], side[keep])
    S, R, T = np.array(std), np.array(run), np.array(reach)
    y = (R > S).astype(int)                   # trades that never reached TP1 have R == S: label 0, no effect
    a, b = int(n * 0.5), int(n * 0.75)
    if len(set(y[:a])) < 2 or y[:a].sum() < 20:
        return {"enabled": False, "reason": "too few trades did better as runners to learn from", "n": n}
    mA = _model().fit(F[:a], y[:a])
    pB, pC = mA.predict_proba(F[a:b])[:, 1], mA.predict_proba(F[b:])[:, 1]
    best_keep, best_gain = None, -1e9
    for kf in KEEP_GRID:                       # how often to run, chosen on the middle quarter only
        thr = np.quantile(pB, 1 - kf) if kf < 1 else -1.0
        sel = pB >= thr
        if sel.sum() >= 30:
            gain = float(np.where(sel, R[a:b], S[a:b]).mean() - S[a:b].mean())
            if gain > best_gain:
                best_keep, best_gain = kf, gain
    if best_keep is None:
        return {"enabled": False, "reason": "too few trades to choose a threshold", "n": n}
    thr_b = np.quantile(pB, 1 - best_keep) if best_keep < 1 else -1.0
    selC = pC >= thr_b
    mixed, base = float(np.where(selC, R[b:], S[b:]).mean()), float(S[b:].mean())
    exam = {"n": int(len(pC)), "runners": int(selC.sum()), "runners_reaching_tp1": int((selC & T[b:]).sum()),
            "avg_r_standard": base, "avg_r_with_runners": mixed,
            "avg_r_runner_trades_as_runner": float(R[b:][selC].mean()) if selC.any() else None,
            "avg_r_runner_trades_as_standard": float(S[b:][selC].mean()) if selC.any() else None}
    enabled = bool((selC & T[b:]).sum() >= 25 and mixed - base >= MIN_GAIN_R)
    out = {"enabled": enabled, "keep_fraction": best_keep, "n": n, "exam": exam, "run_r": RUN_R}
    if not enabled:
        out["reason"] = (f"letting trades run did not beat taking half at TP1 on unseen trades "
                         f"({mixed:+.2f}R vs {base:+.2f}R)")
        return out
    final = _model().fit(F, y)
    p_all = final.predict_proba(F)[:, 1]
    out.update(model=final, threshold=float(np.quantile(p_all, 1 - best_keep)) if best_keep < 1 else 0.0,
               reason=f"on unseen trades: {mixed:+.2f}R per trade with runners vs {base:+.2f}R always taking half at TP1")
    return out


def score(rm: dict[str, Any] | None, x_row: np.ndarray, probs: dict[str, float]) -> dict[str, Any] | None:
    """Runner scores for a long and a short at the current bar (None when the model is off for this coin/timeframe)."""
    if not rm or not rm.get("enabled") or rm.get("model") is None or not np.isfinite(x_row).all():
        return None
    P = np.array([[probs["down"], probs["neutral"], probs["up"]]] * 2, float)
    F = _features(np.vstack([x_row, x_row]), P, np.array([1, -1]))
    p = rm["model"].predict_proba(F)[:, 1]
    return {"p_long": float(p[0]), "p_short": float(p[1]), "threshold": rm["threshold"], "run_r": rm.get("run_r", RUN_R),
            "exam": rm.get("exam")}
