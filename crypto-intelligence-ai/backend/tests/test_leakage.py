"""Anti-leakage guarantees: nothing computed at bar t may depend on bars after t."""
import numpy as np
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.features.dataset import build_frame, make_dataset
from app.ml.models import make_model
from app.ml.walkforward import make_folds
from tests.helpers import synthetic_candles


def test_features_are_truncation_invariant():
    """Recomputing everything on a shortened history must reproduce the same past values exactly."""
    df = synthetic_candles(2500, "4h", seed=5)
    full = build_frame(df, "4h")
    ds_full = make_dataset(full)
    for cut in (900, 1700, 2499):
        part = build_frame(df.iloc[:cut], "4h")
        ds = make_dataset(part)
        a, b = ds_full.X.iloc[:cut].to_numpy(float), ds.X.to_numpy(float)
        assert np.array_equal(np.isnan(a), np.isnan(b)), f"NaN pattern differs at cut {cut}"
        assert np.nanmax(np.abs(a - b)) < 1e-9, f"feature values changed when the future was removed (cut {cut})"
        ia = full.ind.iloc[:cut].select_dtypes("number").to_numpy(float)
        ib = part.ind.select_dtypes("number").to_numpy(float)
        assert np.nanmax(np.abs(ia - ib)) < 1e-9, f"indicator/structure values changed (cut {cut})"


def test_cross_asset_features_are_truncation_invariant():
    a = build_frame(synthetic_candles(1500, "4h", seed=1), "4h")
    b = build_frame(synthetic_candles(1500, "4h", seed=2), "4h")
    full = make_dataset(a, btc=b).X
    cut = 1100
    part = make_dataset(build_frame(a.df.iloc[:cut], "4h"), btc=build_frame(b.df.iloc[:cut], "4h")).X
    assert np.nanmax(np.abs(full.iloc[:cut].to_numpy(float) - part.to_numpy(float))) < 1e-9


def test_targets_never_enter_the_feature_matrix():
    ds = make_dataset(build_frame(synthetic_candles(800, "4h"), "4h"))
    assert not {"fwd_ret", "y", "mfe", "mae"} & set(ds.X.columns)
    assert np.isnan(ds.meta["fwd_ret"].iloc[-1]) and not ds.trainable[-1]     # the newest bar has no outcome yet
    c = ds.meta["close"].to_numpy()                                           # label of bar t = return of bar t+1
    assert abs(ds.meta["fwd_ret"].iloc[100] - (c[101] / c[100] - 1)) < 1e-12


def test_swings_are_only_known_after_confirmation():
    fr = build_frame(synthetic_candles(600, "4h"), "4h")
    assert fr.swings and all(s["confirm_pos"] == s["pos"] + 3 for s in fr.swings)
    s = fr.swings[10]
    before, after = fr.ind.iloc[s["confirm_pos"] - 1], fr.ind.iloc[s["confirm_pos"]]
    col = "last_sh" if s["kind"] == "high" else "last_sl"
    assert after[col] == s["price"] and before[col] != s["price"]


def test_folds_are_chronological_disjoint_and_purged():
    folds = make_folds(5000, (2000, 300, 300), gap=1)
    assert len(folds) >= 5 and folds[-1].test[1] == 5000
    for f in folds:
        assert f.train[0] < f.train[1] < f.val[0] < f.val[1] < f.test[0] < f.test[1]
        assert f.val[0] - f.train[1] == 1 and f.test[0] - f.val[1] == 1       # purge gap
    for a, b in zip(folds, folds[1:]):
        assert b.test[0] == a.test[1]                                           # test windows tile, never overlap
    assert make_folds(100, (2000, 300, 300)) == []                              # too short -> no folds, no forecast


def test_scaling_is_fitted_inside_the_model_pipeline():
    model = make_model("logistic", ["a", "b"])
    assert isinstance(model, Pipeline) and isinstance(model.steps[0][1], StandardScaler)
    rng = np.random.default_rng(0)
    X = rng.normal(size=(300, 2))
    y = rng.integers(0, 3, 300)
    model.fit(X[:200], y[:200])
    assert np.allclose(model.steps[0][1].mean_, X[:200].mean(axis=0))          # statistics from training rows only
