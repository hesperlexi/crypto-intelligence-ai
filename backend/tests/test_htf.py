"""Higher-timeframe features are leak-free and the confident-call threshold is computed out-of-sample."""
import numpy as np

from app.features.dataset import build_frame, make_dataset
from app.data.base import resample_ohlcv
from app.ml.trainer import selective_threshold

from .helpers import synthetic_candles


def test_htf_features_use_only_closed_higher_timeframe_bars():
    base = synthetic_candles(4000, "1h", seed=3)
    h4 = resample_ohlcv(base, "1h", "4h")
    full = make_dataset(build_frame(base, "1h"), htf=build_frame(h4, "4h"))
    assert "htf_tech" in full.feature_names and "htf_ret_3" in full.feature_names
    # truncation invariance: cutting the future (base and 4h alike) must not change any earlier feature row
    cut = 3000
    end_ts = int(base["ts"].iloc[cut - 1]) + 3_600_000
    b2 = base.iloc[:cut]
    h2 = h4[h4["ts"] + 4 * 3_600_000 <= end_ts]
    part = make_dataset(build_frame(b2, "1h"), htf=build_frame(h2, "4h"))
    cols = [c for c in full.feature_names if c.startswith("htf_")]
    A = full.X[cols].iloc[:cut].to_numpy(float)
    B = part.X[cols].to_numpy(float)
    ok = np.isfinite(A) & np.isfinite(B)
    assert ok.sum() > 1000 and np.allclose(A[ok], B[ok]) and (np.isfinite(A) == np.isfinite(B)).all()
    # a 1h bar closing at 03:00 must see the 4h bar that closed at 00:00, not the one still forming
    ts = base["ts"].to_numpy()
    k = int(np.where(ts % (4 * 3_600_000) == 2 * 3_600_000)[0][100])     # bar 02:00-03:00
    h4_close_known = h4[h4["ts"] + 4 * 3_600_000 <= ts[k] + 3_600_000].iloc[-1]
    fr4 = build_frame(h4, "4h").ind.set_index("ts")
    assert np.isclose(full.X["htf_rsi"].iloc[k], fr4.loc[h4_close_known["ts"], "rsi"] / 100)


def test_selective_threshold_prefers_reliable_calls():
    rng = np.random.default_rng(0)
    n = 3000
    p_up = rng.uniform(0.2, 0.8, n)
    y = np.where(rng.uniform(size=n) < p_up, 2, 0)          # higher p_up -> more often really up
    P = np.column_stack([1 - p_up - 0.05, np.full(n, 0.05), p_up])
    P = np.clip(P, 0.01, None); P /= P.sum(axis=1, keepdims=True)
    sel = selective_threshold(P, y)
    assert sel["threshold"] is not None and sel["hit_rate"] > sel["base"]["hit_rate"]
    assert sel["n"] >= 30 and 0 < sel["coverage"] <= 1
