"""Signal generators. Each returns an array in {-1, 0, +1} where signal[i] uses information up to the close of bar i."""
from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd


def buy_hold(ind: pd.DataFrame, **_: Any) -> np.ndarray:
    return np.ones(len(ind))


def random_direction(ind: pd.DataFrame, seed: int = 0, hold: int = 6, **_: Any) -> np.ndarray:
    rng = np.random.default_rng(seed)
    blocks = rng.choice([-1.0, 0.0, 1.0], size=len(ind) // hold + 1)
    return np.repeat(blocks, hold)[:len(ind)]


def sma_cross(ind: pd.DataFrame, fast: int = 20, slow: int = 50, **_: Any) -> np.ndarray:
    f = ind["close"].rolling(fast).mean()
    s = ind["close"].rolling(slow).mean()
    return np.nan_to_num(np.where(s.isna(), 0.0, np.sign(f - s)))


def rsi_simple(ind: pd.DataFrame, low: float = 30, high: float = 70, exit_long: float = 55,
               exit_short: float = 45, **_: Any) -> np.ndarray:
    r = ind["rsi"].to_numpy(float)
    out = np.zeros(len(r))
    state = 0.0
    for i, v in enumerate(r):
        if np.isfinite(v):
            if state == 0:
                state = 1.0 if v < low else (-1.0 if v > high else 0.0)
            elif (state > 0 and v > exit_long) or (state < 0 and v < exit_short):
                state = 0.0
        out[i] = state
    return out


def prev_candle(ind: pd.DataFrame, **_: Any) -> np.ndarray:
    return np.nan_to_num(np.sign(ind["close"].diff().to_numpy(float)))


def technical_composite(ind: pd.DataFrame, enter: float = 0.35, exit: float = 0.05, **_: Any) -> np.ndarray:
    """Rule-based composite of the transparent component scores, with hysteresis to limit churn."""
    s = ind["tech_score"].to_numpy(float)
    out = np.zeros(len(s))
    state = 0.0
    for i, v in enumerate(s):
        if np.isfinite(v):
            if state == 0:
                state = 1.0 if v >= enter else (-1.0 if v <= -enter else 0.0)
            elif (state > 0 and v < exit) or (state < 0 and v > -exit):
                state = 0.0
        out[i] = state
    return out


def from_probabilities(P: np.ndarray, min_prob: float = 0.40) -> np.ndarray:
    """Ensemble class probabilities (n, 3) -> position. Rows without a prediction (NaN) are flat."""
    P = np.asarray(P, float)
    ok = np.isfinite(P).all(axis=1)
    cls = np.where(ok, np.nan_to_num(P).argmax(axis=1), 1)
    pmax = np.where(ok, np.nan_to_num(P).max(axis=1), 0.0)
    return np.where((cls == 2) & (pmax >= min_prob), 1.0, np.where((cls == 0) & (pmax >= min_prob), -1.0, 0.0))


STRATEGIES: dict[str, dict[str, Any]] = {
    "buy_hold": {"fn": buy_hold, "label": "Buy & Hold", "params": {}},
    "sma_cross": {"fn": sma_cross, "label": "SMA crossover", "params": {"fast": 20, "slow": 50}},
    "rsi_simple": {"fn": rsi_simple, "label": "Simple RSI (30/70)", "params": {"low": 30, "high": 70}},
    "prev_candle": {"fn": prev_candle, "label": "Previous candle direction", "params": {}},
    "random": {"fn": random_direction, "label": "Random direction", "params": {"seed": 0, "hold": 6}},
    "technical": {"fn": technical_composite, "label": "Technical composite score", "params": {"enter": 0.35, "exit": 0.05}},
    "ai_ensemble": {"fn": None, "label": "AI ensemble (walk-forward out-of-sample only)", "params": {"min_prob": 0.40}},
}


def get_strategy(name: str) -> Callable[..., np.ndarray]:
    if name not in STRATEGIES or STRATEGIES[name]["fn"] is None:
        raise KeyError(f"unknown rule strategy '{name}'")
    return STRATEGIES[name]["fn"]
