"""Volatility engine: realized volatility, percentile rank, compression/expansion, state label."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.base import bars_per_year
from .indicators import atr, bollinger, true_range

VOL_STATES = ["LOW", "NORMAL", "HIGH", "EXTREME"]


def volatility_frame(df: pd.DataFrame, timeframe: str, window: int = 20, rank_window: int = 365) -> pd.DataFrame:
    """Per-bar volatility measures (all causal).

    sigma_bar   : EW std of 1-bar log returns - the scale used for labels and forecast intervals
    rv / hv     : realized (window) and historical (5x window) annualised volatility
    vol_pct     : percentile rank of rv within the trailing `rank_window` bars (0-1)
    vol_state   : 0 LOW (<20th pct), 1 NORMAL, 2 HIGH (>80th), 3 EXTREME (>95th)
    """
    lr = np.log(df["close"]).diff()
    ann = np.sqrt(bars_per_year(timeframe))
    out = pd.DataFrame(index=df.index)
    out["sigma_bar"] = lr.ewm(span=50, adjust=False, min_periods=20).std()
    out["rv"] = lr.rolling(window, min_periods=window).std() * ann
    out["hv"] = lr.rolling(window * 5, min_periods=window * 2).std() * ann
    out["vol_pct"] = out["rv"].rolling(rank_window, min_periods=60).rank(pct=True)
    a = atr(df, 14)
    out["atr_pct"] = a / df["close"]
    *_, width, _pctb = bollinger(df["close"])
    out["bb_width_pct"] = width.rolling(rank_window, min_periods=60).rank(pct=True)
    tr = true_range(df)
    out["range_ratio"] = tr / a.shift(1)                      # >1.5 expansion, <0.6 compression
    out["range_expansion"] = (out["range_ratio"] > 1.5).astype(int)
    rng = df["high"] - df["low"]
    out["range_compression"] = ((rng <= rng.rolling(7).min()) | (out["bb_width_pct"] < 0.1)).astype(int)
    p = out["vol_pct"]
    state = np.select([p > 0.95, p > 0.80, p < 0.20], [3, 2, 0], default=1).astype(float)
    out["vol_state"] = np.where(p.isna(), np.nan, state)
    return out


def vol_state_name(code: float | None) -> str:
    if code is None or not np.isfinite(code):
        return "UNKNOWN"
    return VOL_STATES[int(code)]
