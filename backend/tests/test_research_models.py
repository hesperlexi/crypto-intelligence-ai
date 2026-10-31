"""v2.7 model research (python -m app.research models): causality of the trade labels, the per-coin normalisation and
the walk-forward fits, plus a small end-to-end run on the synthetic runtime."""
from types import SimpleNamespace

import numpy as np
import pandas as pd

from app import research_models as RM
from app.data.base import tf_ms
from app.features.dataset import build_frame
from app.ml import series_policy as SP
from tests.helpers import synthetic_candles


def _all_ctx(df, tf="4h"):
    fr = build_frame(df, tf)
    ts = fr.ind["ts"].to_numpy(np.int64)
    n = len(ts)
    b = {"oos": {"ts": ts, "P_ens": np.full((n, 3), 1 / 3), "fwd_ret": np.zeros(n)}, "edge": {}}
    return fr, SP.build_context("X", tf, b, {tf: fr}, None)


def _labels(df, rows):
    fr, c = _all_ctx(df)
    i = fr.ind
    return RM.trade_labels(c, i["high"].to_numpy(float), i["low"].to_numpy(float), i["close"].to_numpy(float), 0.15, rows=rows)


def test_trade_labels_only_use_the_next_horizon_bars():
    df = synthetic_candles(900, "4h", seed=4)
    rows = np.arange(400, 600)
    full = _labels(df, rows)
    assert np.isfinite(full["y_long"][rows]).mean() > 0.9
    assert set(np.unique(full["y_long"][rows][np.isfinite(full["y_long"][rows])])) <= {0.0, 1.0}
    # truncated data invariance: row i's label is the same when the data ends right after bar i + H
    for i in (420, 480, 560):
        cut = _labels(df.iloc[: i + RM.H + 1].reset_index(drop=True), np.array([i]))
        for k in full:
            assert np.allclose(np.nan_to_num(cut[k][i], nan=9), np.nan_to_num(full[k][i], nan=9)), (k, i)
        # ... and unknown (NaN) when even one of those bars is missing
        short = _labels(df.iloc[: i + RM.H].reset_index(drop=True), np.array([i]))
        assert np.isnan(short["y_long"][i]) and np.isnan(short["r_short"][i])


def test_rolling_z_is_truncation_invariant():
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(800, 4)).cumsum(axis=0), columns=list("abcd"))
    z = RM.rolling_z(X)
    z2 = RM.rolling_z(X.iloc[:500])
    assert np.allclose(z.iloc[:500].to_numpy(), z2.to_numpy(), equal_nan=True)
    assert z.iloc[: RM.ZMIN - 1].isna().all().all() and np.isfinite(z.iloc[RM.ZMIN:].to_numpy()).all()


def _fake_series(sym, n=2400, seed=0, tf="4h"):
    rng = np.random.default_rng(seed)
    step = tf_ms(tf)
    ts = 1_600_000_000_000 + step * np.arange(n, dtype=np.int64)
    X = rng.normal(size=(n, 6))
    yl = (X[:, 0] + 0.5 * rng.normal(size=n) > 0).astype(float)
    ys = (X[:, 1] + 0.5 * rng.normal(size=n) > 0).astype(float)
    lab = {"y_long": yl, "y_short": ys, "r_long": 2 * yl - 1, "r_short": 2 * ys - 1}
    rows = np.arange(1200, n)
    ctx = SimpleNamespace(ts=ts[rows], rows=rows, n=len(rows))
    return RM.Series(sym, tf, ctx, None, None, None, 0, ts, X, X.copy(), lab, np.where(X[:, 2] > 0, 2.0, 0.0), 0)


def test_walk_forward_never_sees_future_labels_or_features():
    """Shuffle-future test: for every chunk, its predictions do not change when every label that closed after the
    chunk began, and every feature row after the chunk, is scrambled."""
    for pooled in (False, True):
        items = [_fake_series("A/USDT", seed=1), _fake_series("B/USDT", seed=2)]
        bounds = RM.boundaries(items, 4)
        base = RM.walk_forward(items, bounds, "trade", pooled=pooled)
        assert np.isfinite(base["A/USDT 4h"]["p_long"]).all()
        emb = (RM.H + 1) * tf_ms("4h")
        rng = np.random.default_rng(9)
        for k in range(len(bounds) - 1):
            lo, hi = bounds[k], bounds[k + 1]
            for s in items:
                late = s.ts + emb > lo
                for c in s.labels:
                    v = s.labels[c].copy()
                    v[late] = rng.permutation(v[late]) if c.startswith("r_") else 1 - v[late]
                    s.labels[c] = v
                fut = s.ts >= hi
                s.X[fut] = rng.normal(size=(fut.sum(), s.X.shape[1])) * 5
                s.Xz[fut] = s.X[fut]
            again = RM.walk_forward(items, bounds, "trade", pooled=pooled)
            for s in items:
                m = (s.ctx.ts >= lo) & (s.ctx.ts < hi)
                for c in ("p_long", "p_short", "r_long", "r_short"):
                    assert np.allclose(again[s.key][c][m], base[s.key][c][m]), (pooled, k, c)
            # restore for the next chunk (rebuild the untouched series)
            items = [_fake_series("A/USDT", seed=1), _fake_series("B/USDT", seed=2)]
        # the model learnt something real out of sample (sanity: the fake label is predictable)
        s = items[0]
        p = base[s.key]["p_long"]
        y = s.labels["y_long"][s.ctx.rows]
        assert RM._auc(y, p) > 0.7


def test_trade_side_needs_threshold_and_positive_expected_r():
    pl = np.array([0.7, 0.7, 0.3, 0.6, np.nan])
    ps = np.array([0.2, 0.2, 0.8, 0.65, 0.9])
    rl = np.array([0.1, -0.1, 0.2, 0.3, 0.1])
    rs = np.array([0.1, 0.1, 0.1, 0.2, -0.2])
    assert RM.trade_side(pl, ps, rl, rs, 0.55).tolist() == [1, 0, -1, -1, 0]


def test_bootstrap_paired_share():
    base = {"a": [{"r": -0.2, "ts": 0}] * 20, "b": [{"r": -0.1, "ts": RM.WEEK}] * 20}
    better = {"a": [{"r": 0.3, "ts": 0}] * 20, "b": [{"r": 0.2, "ts": RM.WEEK}] * 20}
    for unit in ("series", "week"):
        assert RM._boot(base, better, unit)["share_better"] == 1.0
        assert RM._boot(better, base, unit)["share_better"] == 0.0


def test_models_research_runs_on_the_synthetic_runtime():
    from tests.helpers import shared_runtime
    import time
    rt, _ = shared_runtime()
    out = RM.evaluate(rt, ["BTC/USDT", "ETH/USDT"], ["4h"], time.time() + 1800, 0.15, diag=False)
    assert set(out["test"]) == {"current", "A", "B", "AB"}
    for v in ("A", "B", "AB"):
        assert set(out["bootstrap_vs_current"][v]) == {"by_series", "by_week"}
        assert set(out["verdict"][v]) >= {"clear_win", "bootstrap_ge_80"}
    assert "4h" in out["test"]["current"]["by_timeframe"]
    # every fit was trained only on rows before its chunk (logged), and no test series lost its predictions
    assert out["fits"] and all(f.get("rows", 0) >= RM.MIN_TRAIN or f.get("skipped") for f in out["fits"])
    for k, s in out["series"].items():
        assert s["no_prediction_rows"]["A"] < s["oos_bars"]
