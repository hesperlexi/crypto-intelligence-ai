"""Explainability.

Per-prediction: occlusion attribution on the ensemble - each feature is replaced by its training-window
median and the change in (P_up - P_down) is recorded. Model-agnostic, so it explains the ensemble that
actually produced the forecast. Global: permutation importance on the most recent validation window.
When `shap` is installed, SHAP values for the tree model are reported alongside.
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np

FEATURE_LABELS = {
    "ret_1": "last bar return", "ret_1_z": "last bar return (vol-adjusted)", "ret_5": "5-bar return",
    "ret_10": "10-bar return", "ret_20": "20-bar return", "d_ema9": "distance to EMA 9",
    "d_ema21": "distance to EMA 21", "d_ema50": "distance to EMA 50", "d_ema200": "distance to EMA 200",
    "ema50_slope": "EMA 50 slope", "rsi": "RSI", "stoch_k": "Stochastic RSI %K", "stoch_d": "Stochastic RSI %D",
    "macd_n": "MACD line", "macd_hist_n": "MACD histogram", "adx": "ADX trend strength",
    "di_diff": "+DI minus -DI", "atr_pct": "ATR % of price", "cci": "CCI", "willr": "Williams %R", "roc": "ROC",
    "bb_pctb": "Bollinger %B", "bb_width": "Bollinger band width", "bb_width_pct": "band-width percentile",
    "d_vwap": "distance to VWAP", "rel_volume": "relative volume", "vol_roc": "volume ROC", "cmf": "Chaikin money flow",
    "mfi": "Money flow index", "obv_slope": "OBV slope", "clv": "close location in bar", "buy_pressure": "buy pressure",
    "vol_confirm": "volume confirmation", "cloud_pos": "position vs Ichimoku cloud", "tk_diff": "Tenkan-Kijun spread",
    "dc_pos": "position in Donchian channel", "kc_pos": "position in Keltner channel",
    "struct_trend": "market structure trend", "sh_label": "last swing high (HH/LH)", "sl_label": "last swing low (HL/LL)",
    "bos_decay": "recent break of structure", "false_break_decay": "recent failed breakout",
    "div_decay": "recent RSI divergence", "d_last_sh": "distance to last swing high",
    "d_last_sl": "distance to last swing low", "sigma_bar": "bar volatility", "rv": "realized volatility",
    "vol_pct": "volatility percentile", "range_ratio": "range expansion", "body_ratio": "candle body",
    "upper_wick": "upper wick", "lower_wick": "lower wick", "sc_trend": "trend score", "sc_momentum": "momentum score",
    "sc_volume": "volume score", "sc_structure": "structure score", "tech_score": "technical composite",
    "regime_score": "regime score", "btc_ret_1": "BTC last bar return", "btc_ret_5": "BTC 5-bar return",
    "btc_tech": "BTC technical composite", "corr_btc_30": "correlation with BTC", "rel_strength_20": "strength vs BTC",
}


def label(name: str) -> str:
    return FEATURE_LABELS.get(name, name.replace("_", " "))


def occlusion_attribution(predict: Callable[[np.ndarray], np.ndarray], x: np.ndarray, medians: np.ndarray,
                          feature_names: list[str], top: int = 8) -> dict[str, Any]:
    """`predict` maps (n, F) -> ensemble probabilities (n, 3). One batched call covers every feature."""
    F = len(x)
    batch = np.tile(x, (F + 1, 1))
    batch[np.arange(F), np.arange(F)] = medians
    P = predict(batch)
    base = P[-1, 2] - P[-1, 0]
    contrib = base - (P[:-1, 2] - P[:-1, 0])     # >0: the feature's actual value pushes towards UP
    order = np.argsort(-np.abs(contrib))
    items = [{"feature": feature_names[j], "label": label(feature_names[j]), "value": float(x[j]),
              "contribution": float(contrib[j])} for j in order if abs(contrib[j]) > 1e-4]
    return {
        "method": "occlusion (feature replaced by its training median; change in P(up) - P(down))",
        "base": float(base),
        "positive": [i for i in items if i["contribution"] > 0][:top],
        "negative": [i for i in items if i["contribution"] < 0][:top],
    }


def permutation_importance(predict: Callable[[np.ndarray], np.ndarray], X: np.ndarray, y: np.ndarray,
                           feature_names: list[str], seed: int = 0, top: int = 15) -> list[dict[str, Any]]:
    """Increase in ensemble Brier score when one feature is shuffled (higher = the ensemble relies on it more)."""
    from .metrics import brier

    rng = np.random.default_rng(seed)
    base = brier(predict(X), y)
    out = []
    for j, name in enumerate(feature_names):
        Xp = X.copy()
        Xp[:, j] = rng.permutation(Xp[:, j])
        out.append({"feature": name, "label": label(name), "importance": float(brier(predict(Xp), y) - base)})
    out.sort(key=lambda d: -d["importance"])
    return out[:top]


def shap_tree(model: Any, x: np.ndarray, feature_names: list[str], top: int = 8) -> dict[str, Any] | None:
    """Optional SHAP values (UP class) for a fitted tree model. Returns None if shap is unavailable or fails."""
    try:
        import shap

        vals = shap.TreeExplainer(model).shap_values(x.reshape(1, -1))
        arr = np.asarray(vals)
        v = arr[2][0] if arr.ndim == 3 and arr.shape[0] == 3 else arr[0, :, 2] if arr.ndim == 3 else arr[0]
        order = np.argsort(-np.abs(v))[:top]
        return {"method": "SHAP TreeExplainer (UP class)",
                "items": [{"feature": feature_names[j], "label": label(feature_names[j]), "shap": float(v[j])}
                          for j in order]}
    except Exception:
        return None
