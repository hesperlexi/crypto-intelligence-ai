"""Builds the per-timeframe analysis frame and the leakage-free ML dataset.

Anti-leakage rules enforced here:
  * inputs are CLOSED candles only (callers pass closed_only(...) frames)
  * every feature at bar t is a function of bars <= t (verified by the truncation-invariance test)
  * targets live in a separate `meta` frame and are never part of X
  * no scaling/normalisation is fitted here - that happens inside each model pipeline on training rows only
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import TF_SECONDS, settings
from ..engine.regime import regime_frame
from ..engine.scores import component_scores, decayed_event
from .indicators import compute_indicators
from .liquidity import volume_frame
from .structure import divergences, market_structure
from .volatility import volatility_frame

MIN_BARS = 60
# the higher timeframe whose context is added to each model's features
HTF_OF = {"15m": "1h", "1h": "4h", "4h": "1d", "12h": "1d", "1d": "3d"}


class InsufficientData(Exception):
    pass


@dataclass
class Frame:
    timeframe: str
    df: pd.DataFrame      # closed OHLCV candles
    ind: pd.DataFrame     # OHLCV + indicators + structure + volatility + volume + scores + regime
    swings: list[dict]


def build_frame(df: pd.DataFrame, timeframe: str, swing_k: int = 3) -> Frame:
    if df is None or len(df) < MIN_BARS:
        raise InsufficientData(f"{0 if df is None else len(df)} closed candles; need at least {MIN_BARS}")
    ind = compute_indicators(df, timeframe)
    struct, swings = market_structure(df, swing_k)
    vol = volatility_frame(df, timeframe)
    ind = pd.concat([ind, struct, vol], axis=1)
    ind = pd.concat([ind, volume_frame(df, ind)], axis=1)
    ind["bull_div_rsi"], ind["bear_div_rsi"] = divergences(df, swings, ind["rsi"])
    ind["bull_div_macd"], ind["bear_div_macd"] = divergences(df, swings, ind["macd_hist"])
    scores = component_scores(ind)
    ind = pd.concat([ind, scores], axis=1)
    ind = pd.concat([ind, regime_frame(ind)], axis=1)
    return Frame(timeframe, df, ind, swings)


def htf_features(frame: Frame, htf: Frame) -> pd.DataFrame:
    """Context from the higher timeframe, aligned without look-ahead: a base bar only sees higher-timeframe
    candles that had CLOSED by the time the base bar closed (the forming higher-timeframe candle is never used)."""
    from ..data.base import tf_ms

    h = htf.ind
    a = h["atr"].replace(0, np.nan)
    hl = np.log(h["close"])
    H = pd.DataFrame({
        "close_ts": h["ts"] + tf_ms(htf.timeframe),
        "htf_tech": h["tech_score"], "htf_trend": h["sc_trend"], "htf_momentum": h["sc_momentum"],
        "htf_rsi": h["rsi"] / 100, "htf_adx": h["adx"] / 100,
        "htf_ret_1": hl - hl.shift(1), "htf_ret_3": hl - hl.shift(3),
        "htf_d_ema50": (h["close"] - h["ema_50"]) / a, "htf_regime": h["regime_score"],
    }).dropna(subset=["close_ts"]).sort_values("close_ts")
    base = pd.DataFrame({"close_ts": frame.ind["ts"] + tf_ms(frame.timeframe), "_i": np.arange(len(frame.ind))})
    m = pd.merge_asof(base.sort_values("close_ts"), H, on="close_ts", direction="backward")
    m = m.sort_values("_i")
    out = m.drop(columns=["close_ts", "_i"])
    out.index = frame.ind.index
    return out


DERIV_COLS = ["fund_1h", "fund_8h", "fund_z", "prem", "prem_24h", "prem_chg_8h", "deriv_avail"]
# crowd positioning (Binance archive): open interest, long/short ratios, taker flow. A day's values are used from
# the start of the day after next (the archive publishes after the day ends), in training and live alike.
CROWD_COLS = ["oi_chg_1d", "oi_chg_7d", "ls_top", "ls_top_chg_3d", "ls_acct", "taker_24h", "crowd_avail"]
CROWD_LAG_DAYS = 2


def deriv_features(frame: Frame, d: pd.DataFrame | None) -> pd.DataFrame:
    """Futures positioning from the hourly funding / premium series (data.derivs), without look-ahead: a bar sees
    the last hourly value published by the time it closed, and nothing older than 3 hours (else 'unavailable').
    Bars before the series begins get zeros with deriv_avail = 0, so older training rows are kept."""
    from ..data.base import tf_ms

    out = pd.DataFrame(0.0, index=frame.ind.index, columns=DERIV_COLS)
    if d is None or d.empty:
        return out
    h = d.dropna(subset=["funding"]).sort_values("ts").copy() if "funding" in d else d.iloc[0:0]
    if h.empty:
        return out
    f = h["funding"].astype(float) * 1e4                 # basis points per hour
    p = h["premium"].astype(float) * 1e4
    mean7, std7 = f.rolling(168, min_periods=48).mean(), f.rolling(168, min_periods=48).std()
    H = pd.DataFrame({
        "close_ts": h["ts"].astype("int64"), "fund_1h": f, "fund_8h": f.rolling(8, min_periods=4).sum(),
        "fund_z": ((f.rolling(24, min_periods=8).mean() - mean7) / std7.replace(0, np.nan)).clip(-6, 6),
        "prem": p.clip(-200, 200), "prem_24h": p.rolling(24, min_periods=8).mean().clip(-200, 200),
        "prem_chg_8h": (p - p.shift(8)).clip(-200, 200), "_src_ts": h["ts"].astype("int64"),
    })
    base = pd.DataFrame({"close_ts": (frame.ind["ts"] + tf_ms(frame.timeframe)).astype("int64"), "_i": np.arange(len(frame.ind))})
    m = pd.merge_asof(base.sort_values("close_ts"), H, on="close_ts", direction="backward").sort_values("_i")
    fresh = (m["close_ts"] - m["_src_ts"]) <= 3 * 3_600_000
    cols = DERIV_COLS[:-1]
    vals = m[cols].to_numpy(float).copy()
    vals[~fresh.to_numpy()] = np.nan
    out[cols] = np.nan_to_num(vals, nan=0.0)
    out["deriv_avail"] = (fresh & m["fund_1h"].notna()).astype(float).to_numpy()
    return out


def crowd_features(frame: Frame, d: pd.DataFrame | None) -> pd.DataFrame:
    """Crowd positioning without look-ahead: each bar sees the latest day that was published at least
    CROWD_LAG_DAYS ago (nothing older than CROWD_LAG_DAYS + 2 days, else 'unavailable')."""
    from ..data.base import tf_ms

    out = pd.DataFrame(0.0, index=frame.ind.index, columns=CROWD_COLS)
    if d is None or d.empty or "oi" not in d or d["oi"].notna().sum() < 48:
        return out
    h = d[["ts", "oi", "ls_top", "ls_acct", "taker"]].dropna(subset=["oi"]).sort_values("ts").copy()
    day = 86_400_000
    oi = h["oi"].astype(float)
    lt = np.log(h["ls_top"].astype(float).clip(lower=1e-6))
    la = np.log(h["ls_acct"].astype(float).clip(lower=1e-6))
    tk = np.log(h["taker"].astype(float).clip(lower=1e-6))
    H = pd.DataFrame({
        "known_ts": ((h["ts"].astype("int64") // day + CROWD_LAG_DAYS) * day).astype("int64"),
        "oi_chg_1d": ((oi / oi.shift(24) - 1) * 100).clip(-60, 60),
        "oi_chg_7d": ((oi / oi.shift(168) - 1) * 100).clip(-90, 90),
        "ls_top": lt.clip(-3, 3), "ls_top_chg_3d": (lt - lt.shift(72)).clip(-3, 3),
        "ls_acct": la.clip(-3, 3), "taker_24h": tk.rolling(24, min_periods=12).mean().clip(-3, 3),
    })
    base = pd.DataFrame({"known_ts": (frame.ind["ts"] + tf_ms(frame.timeframe)).astype("int64"), "_i": np.arange(len(frame.ind))})
    m = pd.merge_asof(base.sort_values("known_ts"), H.rename(columns={"known_ts": "_k"}).assign(known_ts=lambda x: x["_k"]),
                      on="known_ts", direction="backward").sort_values("_i")
    fresh = (m["known_ts"] - m["_k"]) <= 2 * day
    cols = CROWD_COLS[:-1]
    vals = m[cols].to_numpy(float).copy()
    vals[~fresh.to_numpy()] = np.nan
    out[cols] = np.nan_to_num(vals, nan=0.0)
    out["crowd_avail"] = (fresh & m["oi_chg_1d"].notna()).astype(float).to_numpy()
    return out


def make_features(frame: Frame, btc: Frame | None = None, htf: Frame | None = None,
                  deriv: pd.DataFrame | None = None) -> pd.DataFrame:
    """Stationary feature matrix (ratios / oscillators / ATR-normalised distances - never raw prices)."""
    i = frame.ind
    c, a = i["close"], i["atr"].replace(0, np.nan)
    lr = np.log(c)
    X = pd.DataFrame(index=i.index)
    for n in (1, 2, 3, 5, 10, 20):
        X[f"ret_{n}"] = lr - lr.shift(n)
    X["ret_1_z"] = X["ret_1"] / i["sigma_bar"]
    for n in (9, 21, 50, 200):
        X[f"d_ema{n}"] = (c - i[f"ema_{n}"]) / a
    X["ema50_slope"] = (i["ema_50"] - i["ema_50"].shift(10)) / a
    X["rsi"] = i["rsi"] / 100
    X["stoch_k"], X["stoch_d"] = i["stoch_k"] / 100, i["stoch_d"] / 100
    X["macd_n"], X["macd_hist_n"] = i["macd"] / a, i["macd_hist"] / a
    X["adx"] = i["adx"] / 100
    X["di_diff"] = (i["plus_di"] - i["minus_di"]) / 100
    X["atr_pct"] = i["atr_pct"]
    X["cci"] = i["cci"].clip(-300, 300) / 100
    X["willr"] = i["willr"] / 100
    X["roc"] = i["roc"] / 100
    X["bb_pctb"], X["bb_width"], X["bb_width_pct"] = i["bb_pctb"], i["bb_width"], i["bb_width_pct"]
    X["d_vwap"] = (c - i["vwap"]) / a
    X["rel_volume"] = np.log(i["rel_volume"].clip(lower=1e-3))
    X["vol_roc"] = i["vol_roc"].clip(-100, 500) / 100
    X["cmf"], X["mfi"] = i["cmf"], i["mfi"] / 100
    X["obv_slope"] = i["obv_slope"].clip(-10, 10)
    X["clv"], X["buy_pressure"], X["vol_confirm"] = i["clv"], i["buy_pressure"], i["vol_confirm"]
    X["cloud_pos"] = (c - (i["span_a"] + i["span_b"]) / 2) / a
    X["tk_diff"] = (i["tenkan"] - i["kijun"]) / a
    X["dc_pos"] = ((c - i["dc_lower"]) / (i["dc_upper"] - i["dc_lower"]).replace(0, np.nan)).clip(-1, 2)
    X["kc_pos"] = ((c - i["kc_lower"]) / (i["kc_upper"] - i["kc_lower"]).replace(0, np.nan)).clip(-1, 2)
    X["struct_trend"], X["sh_label"], X["sl_label"] = i["struct_trend"], i["sh_label"], i["sl_label"]
    X["bos_decay"] = decayed_event(i["bos"] + i["choch"], 10)
    X["false_break_decay"] = decayed_event(i["false_breakout"], 6)
    X["div_decay"] = decayed_event(i["bull_div_rsi"] - i["bear_div_rsi"], 10)
    X["d_last_sh"] = ((i["last_sh"] - c) / a).clip(-20, 20)
    X["d_last_sl"] = ((c - i["last_sl"]) / a).clip(-20, 20)
    X["sigma_bar"], X["rv"], X["vol_pct"] = i["sigma_bar"], i["rv"], i["vol_pct"]
    X["range_ratio"] = i["range_ratio"].clip(0, 10)
    rng = (i["high"] - i["low"]).replace(0, np.nan)
    X["body_ratio"] = ((c - i["open"]) / rng).fillna(0.0)
    X["upper_wick"] = ((i["high"] - i[["open", "close"]].max(axis=1)) / rng).fillna(0.0)
    X["lower_wick"] = ((i[["open", "close"]].min(axis=1) - i["low"]) / rng).fillna(0.0)
    for col in ("sc_trend", "sc_momentum", "sc_volume", "sc_structure", "tech_score", "regime_score"):
        X[col] = i[col]
    if TF_SECONDS[frame.timeframe] < 86400:
        hour = (i["ts"] // 3_600_000 % 24).astype(float)
        X["hour_sin"], X["hour_cos"] = np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24)
    if TF_SECONDS[frame.timeframe] <= 86400:
        dow = ((i["ts"] // 86_400_000 + 3) % 7).astype(float)
        X["dow_sin"], X["dow_cos"] = np.sin(2 * np.pi * dow / 7), np.cos(2 * np.pi * dow / 7)
    if btc is not None:  # cross-asset context: the same closed bar of BTC is known at the same time
        b = btc.ind
        blr = np.log(b["close"])
        X["btc_ret_1"] = (blr - blr.shift(1)).reindex(X.index)
        X["btc_ret_5"] = (blr - blr.shift(5)).reindex(X.index)
        X["btc_tech"] = b["tech_score"].reindex(X.index)
        X["corr_btc_30"] = X["ret_1"].rolling(30).corr(X["btc_ret_1"])
        X["rel_strength_20"] = X["ret_20"] - (blr - blr.shift(20)).reindex(X.index)
    if htf is not None:
        X = pd.concat([X, htf_features(frame, htf)], axis=1)
    if deriv is not None:
        X = pd.concat([X, deriv_features(frame, deriv)], axis=1)
        if "oi" in deriv:
            X = pd.concat([X, crowd_features(frame, deriv)], axis=1)
    return X.replace([np.inf, -np.inf], np.nan)


@dataclass
class Dataset:
    X: pd.DataFrame          # features for every bar (last row = live inference row)
    meta: pd.DataFrame       # ts, close, sigma, thr, fwd_ret, y, mfe, mae, vol_state, regime_group
    feature_names: list[str]
    valid: np.ndarray        # rows with complete features
    trainable: np.ndarray    # valid rows whose outcome is already known


def make_dataset(frame: Frame, btc: Frame | None = None, neutral_band: float | None = None,
                 htf: Frame | None = None, deriv: pd.DataFrame | None = None) -> Dataset:
    """Target A: direction class (0 DOWN / 1 NEUTRAL / 2 UP) of the NEXT bar's close-to-close return.

    The neutral band is +/- neutral_band * sigma_bar, where sigma_bar is known at decision time.
    """
    band = settings.neutral_band_sigma if neutral_band is None else neutral_band
    i = frame.ind
    X = make_features(frame, btc, htf, deriv)
    c = i["close"]
    fwd = c.shift(-1) / c - 1
    thr = band * i["sigma_bar"]
    y = pd.Series(np.where(fwd > thr, 2.0, np.where(fwd < -thr, 0.0, 1.0)), index=i.index).where(fwd.notna() & thr.notna())
    grp = np.where(i["regime"] >= 7, 3.0, np.where(i["regime"] >= 4, 2.0, np.where(i["regime"] <= 2, 0.0, 1.0)))
    meta = pd.DataFrame({
        "ts": i["ts"], "close": c, "sigma": i["sigma_bar"], "thr": thr, "fwd_ret": fwd, "y": y,
        "mfe": i["high"].shift(-1) / c - 1, "mae": i["low"].shift(-1) / c - 1,
        "vol_state": i["vol_state"], "regime": i["regime"],
        "regime_group": np.where(i["regime"].isna(), np.nan, grp),   # 0 bear, 1 neutral, 2 bull, 3 unstable
    }, index=i.index)
    valid = X.notna().all(axis=1).to_numpy() & meta["sigma"].notna().to_numpy()
    trainable = valid & meta["y"].notna().to_numpy()
    return Dataset(X, meta, list(X.columns), valid, trainable)
