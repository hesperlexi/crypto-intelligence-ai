"""Benchmark comparison and the statistical edge test.

A model is only described as having an edge if, on walk-forward OUT-OF-SAMPLE bars and after costs, it
  1. earns more than Buy & Hold, previous-candle, SMA-cross and simple-RSI strategies,
  2. beats randomly-timed versions of itself (same exposure and turnover) at significance `alpha`,
  3. classifies direction better than the class-prior baseline at significance `alpha`,
  4. has enough out-of-sample observations.
Otherwise the verdict is "NO STATISTICALLY CONFIRMED EDGE".
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sps

from ..data.base import bars_per_year
from . import strategies as S
from .stats import equity_stats

NO_EDGE = "NO STATISTICALLY CONFIRMED EDGE"


def vector_returns(pos: np.ndarray, close: np.ndarray, cost: float) -> np.ndarray:
    """Per-bar net returns of holding pos[t] (decided at close t) over bar t+1; cost charged on position changes."""
    pos = np.nan_to_num(np.asarray(pos, float))
    ret = close[1:] / close[:-1] - 1
    held = pos[:-1]
    turnover = np.abs(np.diff(np.concatenate([[0.0], held])))
    return held * ret - cost * turnover


def _summary(r: np.ndarray, timeframe: str) -> dict[str, Any]:
    eq = np.concatenate([[1.0], np.cumprod(1 + r)])
    st = equity_stats(eq, timeframe)
    return {"net_return": st["net_return"], "sharpe": st["sharpe"], "max_drawdown": st["max_drawdown"]}


def edge_test(ind: pd.DataFrame, lo: int, hi: int, pos: np.ndarray, timeframe: str, cost: float,
              y_true: np.ndarray, y_pred: np.ndarray, prior_accuracy: float, alpha: float = 0.01,
              min_oos: int = 300, n_sims: int = 500, long_only: bool = True, seed: int = 0) -> dict[str, Any]:
    """`ind` is the full frame; rows [lo, hi) are the contiguous out-of-sample bars that `pos`, `y_true`
    and `y_pred` cover. Benchmark signals are computed on the full history (so their indicators are
    warmed up) and then cut to the same bars."""
    close = ind["close"].to_numpy(float)[lo:hi]
    n = len(close)
    clip = (lambda p: np.clip(p, 0, 1)) if long_only else (lambda p: p)
    pos = clip(np.nan_to_num(pos))
    r_model = vector_returns(pos, close, cost)
    model = _summary(r_model, timeframe)
    bench = {
        "buy_hold": vector_returns(S.buy_hold(ind)[lo:hi], close, cost),
        "prev_candle": vector_returns(clip(S.prev_candle(ind))[lo:hi], close, cost),
        "sma_cross": vector_returns(clip(S.sma_cross(ind))[lo:hi], close, cost),
        "rsi_simple": vector_returns(clip(S.rsi_simple(ind))[lo:hi], close, cost),
    }
    benchmarks = {k: _summary(v, timeframe) for k, v in bench.items()}
    # random timing: circular shifts keep the model's exposure and turnover but destroy its timing
    rng = np.random.default_rng(seed)
    sims = np.empty(n_sims)
    for s in range(n_sims):
        shifted = np.roll(pos, int(rng.integers(1, max(2, n - 1))))
        sims[s] = np.prod(1 + vector_returns(shifted, close, cost)) - 1
    p_random = float((1 + (sims >= model["net_return"]).sum()) / (n_sims + 1))
    benchmarks["random_timing"] = {"net_return": float(np.median(sims)), "sharpe": None, "max_drawdown": None,
                                   "p05": float(np.quantile(sims, 0.05)), "p95": float(np.quantile(sims, 0.95))}
    ok = np.isfinite(y_true) & np.isfinite(y_pred)
    n_cls = int(ok.sum())
    hits = int((y_true[ok] == y_pred[ok]).sum())
    acc = hits / n_cls if n_cls else float("nan")
    p_acc = float(sps.binom.sf(hits - 1, n_cls, prior_accuracy)) if n_cls else 1.0
    beats = {k: bool(model["net_return"] > v["net_return"]) for k, v in benchmarks.items()}
    exposure = float(np.mean(pos[:-1] != 0)) if n > 1 else 0.0
    checks = {
        "enough_oos_samples": bool(n_cls >= min_oos),
        "beats_all_benchmarks_net": bool(all(beats.values())),
        "beats_random_timing": bool(p_random < alpha),
        "accuracy_above_prior": bool(p_acc < alpha),
        "positive_net_return": bool(model["net_return"] > 0),
        "trades_at_all": bool(exposure > 0),
    }
    confirmed = all(checks.values())
    failed = [k for k, v in checks.items() if not v]
    return {
        "edge_confirmed": bool(confirmed),
        "verdict": "Out-of-sample edge confirmed after costs" if confirmed else NO_EDGE,
        "failed_checks": failed, "checks": checks, "alpha": alpha,
        "n_oos": n_cls, "oos_years": float(n / bars_per_year(timeframe)),
        "model": {**model, "exposure": exposure, "accuracy": acc, "prior_accuracy": prior_accuracy},
        "benchmarks": benchmarks, "beats": beats,
        "p_value_random_timing": p_random, "p_value_accuracy": p_acc,
        "cost_per_turn": cost, "long_only": long_only,
    }
