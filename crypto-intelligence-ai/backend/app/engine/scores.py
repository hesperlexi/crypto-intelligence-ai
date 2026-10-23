"""Vectorised component scores in [-1, +1] (bearish .. bullish) for every bar.

These feed the transparent signal engine, the 'technical rules' model inside the ensemble,
and the rule-based backtest strategy. All inputs are causal, so the scores are too.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TECH_COMPONENTS = ["sc_trend", "sc_momentum", "sc_volume", "sc_structure", "sc_volatility"]


def decayed_event(event: pd.Series | np.ndarray, bars: int) -> np.ndarray:
    """Carry the last non-zero event forward, fading linearly to 0 over `bars` bars."""
    e = np.nan_to_num(np.asarray(event, float))
    idx = np.arange(len(e))
    last = np.maximum.accumulate(np.where(e != 0, idx, -1))
    val = np.where(last >= 0, e[np.maximum(last, 0)], 0.0)
    return val * np.clip(1 - (idx - last) / bars, 0, 1) * (last >= 0)


def _mean(parts: list[pd.Series | np.ndarray], index: pd.Index) -> pd.Series:
    m = pd.concat([pd.Series(np.asarray(p, float), index=index) for p in parts], axis=1)
    return m.mean(axis=1, skipna=True).where(m.notna().sum(axis=1) >= max(2, len(parts) // 2)).clip(-1, 1)


def component_scores(ind: pd.DataFrame) -> pd.DataFrame:
    c, a = ind["close"], ind["atr"].replace(0, np.nan)
    out = pd.DataFrame(index=ind.index)

    cloud_top = ind[["span_a", "span_b"]].max(axis=1)
    cloud_bot = ind[["span_a", "span_b"]].min(axis=1)
    cloud = np.where(c > cloud_top, 1.0, np.where(c < cloud_bot, -1.0, 0.0))
    cloud = np.where(cloud_top.isna(), np.nan, cloud)
    out["sc_trend"] = _mean([
        np.sign(c - ind["ema_200"]), np.sign(ind["ema_50"] - ind["ema_200"]),
        np.sign(ind["ema_21"] - ind["ema_50"]), np.sign(c - ind["ema_21"]),
        np.tanh((ind["ema_50"] - ind["ema_50"].shift(10)) / a), cloud,
    ], ind.index)

    z12 = (c / c.shift(12) - 1) / (ind["sigma_bar"] * np.sqrt(12))
    div = decayed_event(ind["bull_div_rsi"] - ind["bear_div_rsi"] + ind["bull_div_macd"] - ind["bear_div_macd"], 10)
    out["sc_momentum"] = _mean([
        ((ind["rsi"] - 50) / 25).clip(-1, 1), np.tanh(4 * ind["macd_hist"] / a),
        np.sign(ind["macd"] - ind["macd_signal"]), (z12 / 2).clip(-1, 1),
        (ind["stoch_k"] - 50) / 50, np.clip(div, -1, 1) * 0.5,
    ], ind.index)

    out["sc_volume"] = _mean([
        ind["vol_confirm"].clip(-1, 1), (ind["cmf"] * 4).clip(-1, 1), np.tanh(ind["obv_slope"]),
        (ind["mfi"] - 50) / 50, (ind["buy_pressure"] * 2).clip(-1, 1),
    ], ind.index)

    brk = np.where((c > ind["dc_upper"]) & (ind["rel_volume"] > 1.2), 1.0,
                   np.where((c < ind["dc_lower"]) & (ind["rel_volume"] > 1.2), -1.0, 0.0))
    out["breakout"] = brk
    out["sc_structure"] = _mean([
        ind["struct_trend"], 0.5 * (ind["sh_label"] + ind["sl_label"]),
        decayed_event(ind["bos"] + ind["choch"], 10), decayed_event(ind["false_breakout"], 6),
        decayed_event(brk, 5),
    ], ind.index).where(ind["atr"].notna())

    # volatility is not directional: it scales how much the trend reading can be trusted
    quality = ind["vol_state"].map({0.0: 1.0, 1.0: 1.0, 2.0: 0.5, 3.0: 0.0})
    out["vol_quality"] = quality
    out["sc_volatility"] = (out["sc_trend"] * (quality * 2 - 1)).clip(-1, 1)

    w = np.array([0.30, 0.25, 0.15, 0.25, 0.05])
    comp = out[TECH_COMPONENTS]
    out["tech_score"] = (comp.fillna(0) * w).sum(axis=1).where(comp[["sc_trend", "sc_momentum"]].notna().all(axis=1))
    return out
