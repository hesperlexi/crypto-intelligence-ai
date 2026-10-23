"""Technical indicators. Every function is causal: the value at bar t uses bars <= t only."""
from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rma(s: pd.Series, n: int) -> pd.Series:
    """Wilder's smoothing."""
    return s.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def _div(a, b):
    b = b.where(b != 0) if isinstance(b, pd.Series) else np.where(b == 0, np.nan, b)
    return a / b


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return rma(true_range(df), n)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up, dn = rma(d.clip(lower=0), n), rma((-d).clip(lower=0), n)
    out = 100 - 100 / (1 + _div(up, dn))
    return out.where(dn != 0, 100.0).where(up.notna())


def stoch_rsi(close: pd.Series, n: int = 14, k: int = 3, d: int = 3) -> tuple[pd.Series, pd.Series]:
    r = rsi(close, n)
    lo, hi = r.rolling(n).min(), r.rolling(n).max()
    raw = (_div(r - lo, hi - lo)).fillna(0.5).where(r.notna()) * 100
    kk = sma(raw, k)
    return kk, sma(kk, d)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def adx(df: pd.DataFrame, n: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus_dm = up.where((up > dn) & (up > 0), 0.0)
    minus_dm = dn.where((dn > up) & (dn > 0), 0.0)
    a = atr(df, n)
    plus_di = 100 * _div(rma(plus_dm, n), a)
    minus_di = 100 * _div(rma(minus_dm, n), a)
    dx = 100 * _div((plus_di - minus_di).abs(), plus_di + minus_di)
    return rma(dx.fillna(0.0).where(a.notna()), n), plus_di, minus_di


def cci(df: pd.DataFrame, n: int = 20) -> pd.Series:
    tp = ((df["high"] + df["low"] + df["close"]) / 3).to_numpy()
    out = np.full(len(tp), np.nan)
    if len(tp) >= n:
        w = sliding_window_view(tp, n)
        m = w.mean(axis=1)
        mad = np.abs(w - m[:, None]).mean(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            out[n - 1:] = np.where(mad > 0, (tp[n - 1:] - m) / (0.015 * mad), 0.0)
    return pd.Series(out, index=df.index)


def williams_r(df: pd.DataFrame, n: int = 14) -> pd.Series:
    hh, ll = df["high"].rolling(n).max(), df["low"].rolling(n).min()
    return -100 * _div(hh - df["close"], hh - ll)


def roc(close: pd.Series, n: int = 12) -> pd.Series:
    return (close / close.shift(n) - 1) * 100


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    upper, lower = mid + k * sd, mid - k * sd
    width = _div(upper - lower, mid)
    pct_b = _div(close - lower, upper - lower)
    return mid, upper, lower, width, pct_b


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP anchored at each UTC day open (intraday timeframes)."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    day = df["ts"] // 86_400_000
    pv = (tp * df["volume"]).groupby(day).cumsum()
    vv = df["volume"].groupby(day).cumsum()
    return _div(pv, vv).fillna(tp)


def rolling_vwap(df: pd.DataFrame, n: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    return _div((tp * df["volume"]).rolling(n).sum(), df["volume"].rolling(n).sum())


def anchored_vwap(df: pd.DataFrame, anchor_pos: int) -> pd.Series:
    """VWAP anchored at positional index `anchor_pos` (e.g. the last confirmed swing). NaN before it."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    pv = (tp * df["volume"]).iloc[anchor_pos:].cumsum()
    vv = df["volume"].iloc[anchor_pos:].cumsum()
    return _div(pv, vv).reindex(df.index)


def obv(df: pd.DataFrame) -> pd.Series:
    return (np.sign(df["close"].diff()).fillna(0.0) * df["volume"]).cumsum()


def cmf(df: pd.DataFrame, n: int = 20) -> pd.Series:
    rng = df["high"] - df["low"]
    mfm = _div((df["close"] - df["low"]) - (df["high"] - df["close"]), rng).fillna(0.0)
    return _div((mfm * df["volume"]).rolling(n).sum(), df["volume"].rolling(n).sum())


def mfi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    mf = tp * df["volume"]
    d = tp.diff()
    pos = mf.where(d > 0, 0.0).rolling(n).sum()
    neg = mf.where(d < 0, 0.0).rolling(n).sum()
    out = 100 - 100 / (1 + _div(pos, neg))
    return out.where(neg != 0, 100.0).where(pos.notna())


def ichimoku(df: pd.DataFrame, conv: int = 9, base: int = 26, span: int = 52):
    """Cloud values are the ones plotted AT bar t (i.e. computed `base` bars earlier) - no look-ahead."""
    mid = lambda n: (df["high"].rolling(n).max() + df["low"].rolling(n).min()) / 2  # noqa: E731
    tenkan, kijun = mid(conv), mid(base)
    span_a = ((tenkan + kijun) / 2).shift(base)
    span_b = mid(span).shift(base)
    return tenkan, kijun, span_a, span_b


def pivot_points(df: pd.DataFrame, intraday: bool) -> pd.DataFrame:
    """Classic floor pivots from the PREVIOUS completed period (UTC day for intraday, prior bar otherwise)."""
    if intraday:
        day = df["ts"] // 86_400_000
        agg = df.groupby(day).agg(h=("high", "max"), l=("low", "min"), c=("close", "last")).shift(1)
        h, l, c = (agg[k].reindex(day).to_numpy() for k in ("h", "l", "c"))
    else:
        h, l, c = (df[k].shift(1).to_numpy() for k in ("high", "low", "close"))
    p = (h + l + c) / 3
    return pd.DataFrame({"pivot": p, "r1": 2 * p - l, "s1": 2 * p - h, "r2": p + (h - l), "s2": p - (h - l),
                         "r3": h + 2 * (p - l), "s3": l - 2 * (h - p)}, index=df.index)


def donchian(df: pd.DataFrame, n: int = 20):
    """Channel of the PRIOR n bars (excludes the current bar) so a close beyond it is a breakout."""
    upper = df["high"].rolling(n).max().shift(1)
    lower = df["low"].rolling(n).min().shift(1)
    return upper, lower, (upper + lower) / 2


def keltner(df: pd.DataFrame, n: int = 20, mult: float = 2.0):
    mid = ema(df["close"], n)
    a = atr(df, n)
    return mid, mid + mult * a, mid - mult * a


def compute_indicators(df: pd.DataFrame, timeframe: str = "1h") -> pd.DataFrame:
    """Return a copy of `df` with every indicator column appended."""
    from ..config import TF_SECONDS

    out = df.copy()
    c = out["close"]
    for n in (20, 50, 100, 200):
        out[f"sma_{n}"] = sma(c, n)
    for n in (9, 21, 50, 200):
        out[f"ema_{n}"] = ema(c, n)
    out["rsi"] = rsi(c)
    out["stoch_k"], out["stoch_d"] = stoch_rsi(c)
    out["macd"], out["macd_signal"], out["macd_hist"] = macd(c)
    out["adx"], out["plus_di"], out["minus_di"] = adx(out)
    out["atr"] = atr(out)
    out["cci"] = cci(out)
    out["willr"] = williams_r(out)
    out["roc"] = roc(c, 12)
    out["momentum"] = c - c.shift(10)
    out["bb_mid"], out["bb_upper"], out["bb_lower"], out["bb_width"], out["bb_pctb"] = bollinger(c)
    intraday = TF_SECONDS.get(timeframe, 3600) < 86400
    out["vwap"] = session_vwap(out) if intraday else rolling_vwap(out, 20)
    out["vol_sma"] = sma(out["volume"], 20)
    out["rel_volume"] = _div(out["volume"], out["vol_sma"])
    out["vol_roc"] = (_div(out["volume"], out["volume"].shift(10)) - 1) * 100
    out["obv"] = obv(out)
    out["cmf"] = cmf(out)
    out["mfi"] = mfi(out)
    out["tenkan"], out["kijun"], out["span_a"], out["span_b"] = ichimoku(out)
    piv = pivot_points(out, intraday)
    for col in piv.columns:
        out[col] = piv[col]
    out["dc_upper"], out["dc_lower"], out["dc_mid"] = donchian(out)
    out["kc_mid"], out["kc_upper"], out["kc_lower"] = keltner(out)
    # moving-average crosses (event on the bar the cross completes)
    above = (out["sma_50"] > out["sma_200"]).astype(float).where(out["sma_200"].notna())
    out["golden_cross"] = (above.diff() == 1).astype(int)
    out["death_cross"] = (above.diff() == -1).astype(int)
    return out
