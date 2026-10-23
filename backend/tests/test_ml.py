"""Model pipeline: walk-forward, calibration, ensemble, edge test, distribution, drift, explainability."""
import numpy as np

from app.backtest.benchmarks import NO_EDGE, edge_test
from app.features.dataset import InsufficientData, build_frame, make_dataset
from app.ml import trainer
from app.ml.calibration import Calibrator, fit_calibrator
from app.ml.distribution import confidence_lookup, first_passage_base_rate, forecast_distribution, interval_coverage
from app.ml.drift import performance_drift, psi, reference_bins
from app.ml.metrics import brier, classification_metrics, ece, wilson
from app.ml.models import default_models, model_status
from tests.helpers import synthetic_candles

_cache: dict = {}


def _bundle(predictable: float):
    if predictable not in _cache:
        fr = build_frame(synthetic_candles(5000, "4h", seed=3, predictable=predictable), "4h")
        _cache[predictable] = (fr, trainer.train_bundle("TEST/USDT", "4h", fr, fast=True))
    return _cache[predictable]


def test_random_walk_gets_no_confirmed_edge():
    _, b = _bundle(0.0)
    assert b["edge"]["edge_confirmed"] is False
    assert b["edge"]["verdict"] == NO_EDGE and b["edge"]["failed_checks"]
    assert b["best_model"]["supported"] is False        # no model is named 'best' without statistical support


def test_learnable_structure_is_picked_up_out_of_sample():
    """Returns with planted momentum: the ensemble must beat the class prior on bars it never trained on."""
    _, b = _bundle(0.3)
    e = b["edge"]
    assert b["metrics"]["ensemble"]["brier"] < b["metrics"]["prior_baseline"]["brier"]
    assert e["p_value_accuracy"] < 0.01 and e["p_value_random_timing"] < 0.05
    assert e["model"]["net_return"] > e["benchmarks"]["buy_hold"]["net_return"]
    assert b["weights"]["has_skill"] is True
    # the edge is plain momentum, so the 'previous candle' benchmark is a fair rival: the verdict must be
    # consistent with whether the model really out-earned every benchmark, whichever way that falls
    assert e["edge_confirmed"] == (not e["failed_checks"])
    assert e["checks"]["beats_all_benchmarks_net"] == all(e["beats"].values())


def test_edge_test_confirms_real_skill_and_rejects_noise():
    ind = build_frame(synthetic_candles(3000, "4h", seed=11), "4h").ind
    lo, hi = 1000, 3000
    close = ind["close"].to_numpy()[lo:hi]
    nxt_up = np.r_[close[1:] > close[:-1], False]
    rng = np.random.default_rng(0)
    wrong = rng.random(hi - lo) < 0.35                                   # an oracle that is right 65% of the time
    pos = np.where(nxt_up ^ wrong, 1.0, 0.0)
    y_true, y_pred = np.where(nxt_up, 2.0, 0.0), np.where(pos > 0, 2.0, 0.0)
    prior = max(nxt_up.mean(), 1 - nxt_up.mean())
    good = edge_test(ind, lo, hi, pos, "4h", 0.0015, y_true, y_pred, prior)
    assert good["edge_confirmed"] is True, good["failed_checks"]
    noise = rng.integers(0, 2, hi - lo).astype(float)
    bad = edge_test(ind, lo, hi, noise, "4h", 0.0015, y_true, np.where(noise > 0, 2.0, 0.0), prior)
    assert bad["edge_confirmed"] is False and bad["verdict"] == NO_EDGE
    flat = edge_test(ind, lo, hi, np.zeros(hi - lo), "4h", 0.0015, y_true, np.full(hi - lo, 1.0), prior)
    assert flat["edge_confirmed"] is False and "trades_at_all" in flat["failed_checks"]
    few = edge_test(ind, lo, lo + 100, pos[:100], "4h", 0.0015, y_true[:100], y_pred[:100], prior)
    assert "enough_oos_samples" in few["failed_checks"]


def test_bundle_metrics_cover_every_required_statistic():
    _, b = _bundle(0.3)
    ens = b["metrics"]["ensemble"]
    for k in ("accuracy", "directional_accuracy", "precision", "recall", "f1", "roc_auc", "brier", "ece", "reg_mae",
              "reg_rmse", "reg_mape_price", "net_return", "gross_return", "sharpe", "max_drawdown", "win_rate",
              "profit_factor"):
        assert k in ens, k
    assert ens["gross_return"] >= ens["net_return"]      # costs are always charged
    assert abs(sum(b["weights"]["global"].values()) - 1) < 1e-9
    assert not set(b["weights"]["global"]) & {"prior_baseline", "prev_candle"}   # benchmarks never vote
    assert b["n_oos"] >= 300 and len(b["folds"]) >= 2
    for f in b["folds"]:
        assert f["train"][1] < f["val"][0] and f["val"][1] < f["test"][0]
    assert b["live_fit"]["train"][1] < b["live_fit"]["val"][0]


def test_prediction_is_a_probability_distribution_with_intervals():
    fr, b = _bundle(0.3)
    p = trainer.predict(b, make_dataset(fr))
    probs = p["probabilities"]
    assert abs(sum(probs.values()) - 1) < 1e-9 and all(0 <= v <= 1 for v in probs.values())
    iv = p["distribution"]["intervals"]
    assert iv["50"]["low_price"] > iv["80"]["low_price"] > iv["95"]["low_price"]
    assert iv["50"]["high_price"] < iv["80"]["high_price"] < iv["95"]["high_price"]
    assert iv["95"]["low_price"] < p["distribution"]["expected_price"] < iv["95"]["high_price"]
    ups = [u["probability"] for u in p["touch"]["upside"]]
    assert ups == sorted(ups, reverse=True)              # reaching +10% is never likelier than reaching +2%
    assert 0 <= p["model_agreement"] <= 1
    c = p["confidence"]
    assert c["confidence"] is None or (0 <= c["confidence"] <= 1 and c["n"] >= 30)
    cov = b["interval_coverage"]["coverage"]
    assert 0.6 < cov["80"] < 0.95                        # the 80% range really holds roughly 80% of outcomes
    ex = trainer.explain_prediction(b, make_dataset(fr))
    assert ex and (ex["positive"] or ex["negative"])


def test_insufficient_history_refuses_to_train():
    fr = build_frame(synthetic_candles(320, "4h"), "4h")
    try:
        trainer.train_bundle("TEST/USDT", "4h", fr, fast=True)
        raise AssertionError("training on too little data must be refused")
    except InsufficientData:
        pass


def test_calibration_policy():
    rng = np.random.default_rng(0)
    n = 1500
    true_p = rng.uniform(0.05, 0.9, n)
    y = np.where(rng.random(n) < true_p, 2, 0)
    over = np.clip(0.5 + (true_p - 0.5) * 2.2, 0.01, 0.99)       # over-confident model
    P = np.column_stack([1 - over, np.zeros(n), over])
    cal, rep = fit_calibrator(P, y)
    assert cal.method == "isotonic" and rep["holdout_brier"] < rep["holdout_brier_raw"]
    out = cal.transform(P)
    assert np.allclose(out.sum(axis=1), 1) and ece(out, y) < ece(P, y)
    cal_small, rep_small = fit_calibrator(P[:150], y[:150])
    assert cal_small.method == "none" and "not statistically justified" in rep_small["reason"]
    good = np.column_stack([1 - true_p, np.zeros(n), true_p])     # already calibrated: must be left alone or not hurt
    cal_good, rep_good = fit_calibrator(good[:600], y[:600])
    assert cal_good.method in ("none", "platt")
    assert np.array_equal(Calibrator("none").transform(P), P)


def test_metrics_and_intervals():
    y = np.array([2, 2, 0, 0, 1, 2])
    perfect = np.eye(3)[y]
    assert brier(perfect, y) == 0.0 and classification_metrics(perfect, y)["accuracy"] == 1.0
    uniform = np.full((6, 3), 1 / 3)
    assert abs(brier(uniform, y) - 2 / 3) < 1e-12
    lo, hi = wilson(50, 100)
    assert lo < 0.5 < hi and wilson(0, 0) == (0.0, 1.0)
    z = np.random.default_rng(1).standard_normal(4000)
    cov = interval_coverage(z)["coverage"]
    assert abs(cov["50"] - 0.5) < 0.05 and abs(cov["80"] - 0.8) < 0.04 and abs(cov["95"] - 0.95) < 0.03
    d = forecast_distribution(100.0, 0.02, 0.001, z)
    assert abs(d["intervals"]["95"]["high_return"] - (0.001 + 0.02 * 1.96)) < 0.004
    assert forecast_distribution(100.0, 0.02, 0.001, z[:10]) is None       # too few errors -> no range


def test_confidence_lookup_uses_realised_hit_rates():
    n = 400
    oos = {"p_max": np.full(n, 0.52), "pred": np.full(n, 2), "hit": np.r_[np.ones(240), np.zeros(160)],
           "vol_state": np.full(n, 1.0)}
    c = confidence_lookup(0.52, 2, 1.0, oos)
    assert abs(c["confidence"] - 0.6) < 1e-12 and c["n"] == 400 and c["vol_conditioned"]
    assert confidence_lookup(0.52, 0, 1.0, oos)["confidence"] is None       # never predicted DOWN -> no claim


def test_first_passage_base_rate_on_a_trend():
    n = 600
    close = 100 * np.exp(np.cumsum(np.full(n, 0.004)))
    high, low, atr = close * 1.001, close * 0.999, close * 0.01
    up = first_passage_base_rate(high, low, close, atr, 1.0, 1.0, 20)
    assert up["probability"] == 1.0 and up["n"] == n - 20
    assert first_passage_base_rate(high, low, close, atr, 1.0, 1.0, 20, side=-1)["probability"] == 0.0
    assert first_passage_base_rate(high[:10], low[:10], close[:10], atr[:10], 1.0, 1.0, 20)["probability"] is None


def test_drift_detection():
    rng = np.random.default_rng(0)
    ref = reference_bins(rng.normal(size=5000))
    assert psi(ref, rng.normal(size=2000)) < 0.05
    assert psi(ref, rng.normal(loc=1.5, size=2000)) > 0.25
    assert performance_drift(40, 100, 6000, 10000)["degraded"] is True
    assert performance_drift(58, 100, 6000, 10000)["degraded"] is False
    assert performance_drift(5, 10, 6000, 10000)["tested"] is False


def test_unavailable_libraries_are_reported_not_replaced():
    status = {m["name"]: m for m in model_status()}
    for name in ("xgboost", "lightgbm", "lstm", "transformer", "arima"):
        m = status[name]
        assert m["available"] or m["reason"]             # either usable or an explicit reason
    assert set(default_models()) == {k for k, v in status.items() if v["available"]}
