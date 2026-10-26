"""AI-chosen take-profits (v2.2): how far can THIS setup run?

The base rates in engine/setup.py say how often price reached 1:1.5, 1:2 ... 1:3 before the stop in similar markets.
This model adds what the current setup itself says: for each distance it learns, from the model's own out-of-sample
calls, the chance of getting there before the stop, given the features and the ensemble's probabilities. At run time
it returns a *lift* per distance (this setup's chance divided by the average chance), which multiplies the base
rate - so geometry stays with the base rate and the setup-specific view comes from the model.

Honesty: each distance's classifier is trained on the first 70 % of the calls and examined on the last 30 %; it is
used only if it beats the plain average (Brier skill of at least 1 %) there. Otherwise its lift is 1 (no opinion).
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from .trade_filter import HORIZON, MIN_MARGIN, STOP_ATR, _features

log = logging.getLogger(__name__)
R_GRID = (1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0)
MIN_SKILL = 0.01
LIFT_CLIP = (0.5, 2.0)


def reach_labels(high: np.ndarray, low: np.ndarray, close: np.ndarray, atr: np.ndarray, i: int, side: int,
                 horizon: int = HORIZON) -> np.ndarray | None:
    """For each distance in R_GRID: 1 if price reached it before the stop (stop counts first in a shared candle)."""
    if i + horizon >= len(close) or not np.isfinite(atr[i]) or atr[i] <= 0:
        return None
    entry, dist = close[i], STOP_ATR * atr[i]
    stop = entry - side * dist
    best = 0.0
    for j in range(i + 1, i + horizon + 1):
        if (low[j] <= stop) if side > 0 else (high[j] >= stop):
            break
        fav = (high[j] - entry) if side > 0 else (entry - low[j])
        best = max(best, fav / dist)
    return np.array([1 if best >= r else 0 for r in R_GRID], int)


def _model():
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(max_iter=150, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=50,
                                          l2_regularization=1.0, random_state=0)


def _brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def train(X: np.ndarray, P: np.ndarray, rows: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray,
          atr: np.ndarray) -> dict[str, Any]:
    side = np.where(P[:, 2] >= P[:, 0], 1, -1)
    margin = np.abs(P[:, 2] - P[:, 0])
    labels, keep = [], []
    for k, (r, s, m) in enumerate(zip(rows, side, margin)):
        if m < MIN_MARGIN or not np.isfinite(X[k]).all():
            continue
        lab = reach_labels(high, low, close, atr, int(r), int(s))
        if lab is not None:
            labels.append(lab)
            keep.append(k)
    n = len(keep)
    if n < 500:
        return {"enabled": False, "reason": f"only {n} labelled calls", "n": n}
    keep = np.array(keep)
    F = _features(X[keep], P[keep], side[keep])
    Y = np.vstack(labels)
    a = int(n * 0.7)
    out: dict[str, Any] = {"enabled": False, "n": n, "per_r": {}}
    models = {}
    for j, r in enumerate(R_GRID):
        y = Y[:, j]
        if len(set(y[:a])) < 2 or y[:a].sum() < 20:
            out["per_r"][str(r)] = {"used": False, "reason": "too few successes"}
            continue
        m = _model().fit(F[:a], y[:a])
        p = m.predict_proba(F[a:])[:, 1]
        base = float(y[:a].mean())
        b_model, b_base = _brier(p, y[a:]), _brier(np.full(len(p), base), y[a:])
        skill = 1 - b_model / b_base if b_base > 0 else 0.0
        used = skill >= MIN_SKILL
        out["per_r"][str(r)] = {"used": used, "skill": round(skill, 4), "base_rate": round(base, 4)}
        if used:
            final = _model().fit(F, y)
            models[r] = {"model": final, "mean": float(final.predict_proba(F)[:, 1].mean())}
    if models:
        out.update(enabled=True, models=models,
                   reason=f"{len(models)} of {len(R_GRID)} distances beat the average on unseen calls")
    else:
        out["reason"] = "no distance beat the plain average on unseen calls"
    return out


def lifts(tm: dict[str, Any] | None, x_row: np.ndarray, probs: dict[str, float]) -> dict[str, dict[float, float]] | None:
    """{'long': {R: lift}, 'short': {R: lift}} for the distances the model is trusted on (others: no entry)."""
    if not tm or not tm.get("enabled") or not np.isfinite(x_row).all():
        return None
    P = np.array([[probs["down"], probs["neutral"], probs["up"]]] * 2, float)
    F = _features(np.vstack([x_row, x_row]), P, np.array([1, -1]))
    out: dict[str, dict[float, float]] = {"long": {}, "short": {}}
    for r, m in tm["models"].items():
        p = m["model"].predict_proba(F)[:, 1]
        for i, side in enumerate(("long", "short")):
            out[side][float(r)] = float(np.clip(p[i] / max(m["mean"], 1e-6), *LIFT_CLIP))
    return out
