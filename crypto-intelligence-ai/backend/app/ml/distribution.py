"""Forecast distribution: point forecast, empirical intervals, target-touch probabilities, confidence.

Everything here is estimated from walk-forward OUT-OF-SAMPLE predictions:
  * intervals      = quantiles of volatility-standardised OOS forecast errors, rescaled by today's volatility
  * touch probs    = how often the next bar's high/low reached a given move (in volatility units) in OOS bars
  * confidence     = realised hit-rate of past OOS predictions that looked like the current one
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .metrics import wilson

QUANTILES = (0.025, 0.10, 0.25, 0.50, 0.75, 0.90, 0.975)
INTERVALS = {"50": (0.25, 0.75), "80": (0.10, 0.90), "95": (0.025, 0.975)}
CONF_EDGES = (0.0, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70, 1.0001)
MIN_BUCKET = 30


def interval_coverage(z_res: np.ndarray) -> dict[str, Any]:
    """Honest coverage check: quantiles from the first half of OOS errors, coverage measured on the second half."""
    z = z_res[np.isfinite(z_res)]
    if len(z) < 100:
        return {"n": int(len(z)), "coverage": None}
    half = len(z) // 2
    ref, test = z[:half], z[half:]
    cov = {}
    for name, (lo, hi) in INTERVALS.items():
        a, b = np.quantile(ref, [lo, hi])
        cov[name] = float(((test >= a) & (test <= b)).mean())
    return {"n": int(len(test)), "coverage": cov}


def forecast_distribution(price: float, sigma: float, exp_ret: float, z_res: np.ndarray) -> dict[str, Any] | None:
    z = z_res[np.isfinite(z_res)]
    if len(z) < 60 or not np.isfinite(sigma) or not np.isfinite(exp_ret):
        return None
    q = np.quantile(z, QUANTILES)
    rets = exp_ret + sigma * q
    out = {"expected_return": float(exp_ret), "expected_price": float(price * (1 + exp_ret)),
           "median_return": float(rets[3]), "n_residuals": int(len(z)), "intervals": {}}
    for name, (lo, hi) in INTERVALS.items():
        a, b = exp_ret + sigma * np.quantile(z, [lo, hi])
        out["intervals"][name] = {"low_return": float(a), "high_return": float(b),
                                  "low_price": float(price * (1 + a)), "high_price": float(price * (1 + b))}
    return out


def touch_probabilities(sigma: float, z_mfe: np.ndarray, z_mae: np.ndarray, pred_cls: np.ndarray, cls: int,
                        ups: tuple[float, ...] = (0.02, 0.05, 0.10), downs: tuple[float, ...] = (0.02, 0.05),
                        min_n: int = 100) -> dict[str, Any] | None:
    """P(next bar trades through +x% / -x%), from OOS bars; conditioned on the predicted class when there are
    enough matching bars, otherwise unconditional."""
    ok = np.isfinite(z_mfe) & np.isfinite(z_mae)
    if ok.sum() < min_n or not np.isfinite(sigma) or sigma <= 0:
        return None
    cond = ok & (pred_cls == cls)
    basis = "bars where the ensemble predicted the same class"
    if cond.sum() < min_n:
        cond, basis = ok, "all out-of-sample bars"
    up = [{"move": u, "probability": float((z_mfe[cond] >= u / sigma).mean())} for u in ups]
    down = [{"move": -d, "probability": float((z_mae[cond] <= -d / sigma).mean())} for d in downs]
    return {"n": int(cond.sum()), "basis": basis, "upside": up, "downside": down}


def confidence_lookup(p_max: float, cls: int, vol_state: float, oos: dict[str, np.ndarray]) -> dict[str, Any]:
    """Confidence = realised accuracy of comparable past OOS predictions (same class, same probability bin,
    and same volatility state when at least MIN_BUCKET such cases exist)."""
    pm, pc, hit, vs = oos["p_max"], oos["pred"], oos["hit"], oos["vol_state"]
    b = int(np.searchsorted(CONF_EDGES, p_max, side="right") - 1)
    lo, hi = CONF_EDGES[b], CONF_EDGES[b + 1]
    same = (pc == cls) & (pm >= lo) & (pm < hi)
    levels = [
        (same & (vs == vol_state), "same class, probability bin and volatility state"),
        (same, "same class and probability bin"),
        (pc == cls, "same predicted class"),
    ]
    for mask, basis in levels:
        n = int(mask.sum())
        if n >= MIN_BUCKET:
            k = int(hit[mask].sum())
            ci = wilson(k, n)
            return {"confidence": k / n, "n": n, "basis": basis, "ci95": [ci[0], ci[1]],
                    "bin": [lo, min(hi, 1.0)], "vol_conditioned": basis.endswith("volatility state")}
    return {"confidence": None, "n": int(levels[-1][0].sum()), "basis": "insufficient comparable out-of-sample cases",
            "ci95": None, "bin": [lo, min(hi, 1.0)], "vol_conditioned": False}


def first_passage_base_rate(high: np.ndarray, low: np.ndarray, close: np.ndarray, atr: np.ndarray,
                            up_atr: float, down_atr: float, horizon: int, cond: np.ndarray | None = None,
                            side: int = 1) -> dict[str, Any]:
    """Historical base rate that price reaches the target (`up_atr` ATRs in the trade's favour) before the stop
    (`down_atr` ATRs against it) within `horizon` bars, entering at each bar's close.

    Only entries whose full horizon lies inside the data are counted. `cond` restricts entries to similar
    market conditions. Stop is assumed first when both are touched in one bar (pessimistic)."""
    n = len(close)
    last = n - horizon
    if last <= 0:
        return {"probability": None, "n": 0}
    idx = np.arange(last)
    ok = np.isfinite(atr[:last]) & (atr[:last] > 0)
    if cond is not None:
        ok &= cond[:last]
    idx = idx[ok]
    if len(idx) < 50:
        return {"probability": None, "n": int(len(idx))}
    entry, a = close[idx], atr[idx]
    tgt = entry + side * up_atr * a
    stp = entry - side * down_atr * a
    state = np.zeros(len(idx), int)   # 0 open, 1 target, -1 stop
    for h in range(1, horizon + 1):
        hi, lo = high[idx + h], low[idx + h]
        hit_stop = (lo <= stp) if side > 0 else (hi >= stp)
        hit_tgt = (hi >= tgt) if side > 0 else (lo <= tgt)
        open_ = state == 0
        state = np.where(open_ & hit_stop, -1, state)
        state = np.where(open_ & ~hit_stop & hit_tgt, 1, state)
    k, m = int((state == 1).sum()), int(len(idx))
    ci = wilson(k, m)
    return {"probability": k / m, "n": m, "ci95": [ci[0], ci[1]], "stopped_first": float((state == -1).mean()),
            "unresolved": float((state == 0).mean()), "horizon_bars": horizon}
