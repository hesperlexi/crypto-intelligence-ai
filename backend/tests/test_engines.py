"""Regime, signal, multi-timeframe, entry/exit and risk engines."""
import numpy as np

from app.data.base import to_frame
from app.engine import mtf as mtf_engine
from app.engine.regime import describe_regime, transition_probabilities
from app.engine.risk import RiskProfile, correlated_notional, portfolio_risk, position_size
from app.engine.setup import build_setup
from app.engine.signal import build_signal, label_for, optimise_weights
from app.features.dataset import build_frame
from app.features.liquidity import oi_price_state, order_book_metrics
from app.features.structure import sr_zones
from tests.helpers import synthetic_candles


def _trend(drift: float, n: int = 700, seed: int = 1):
    rng = np.random.default_rng(seed)
    r = drift + 0.006 * rng.standard_normal(n)
    close = 100 * np.exp(np.cumsum(r))
    open_ = np.r_[100.0, close[:-1]]
    high = np.maximum(open_, close) * (1 + 0.002 * rng.random(n))
    low = np.minimum(open_, close) * (1 - 0.002 * rng.random(n))
    return to_frame(np.column_stack([np.arange(n) * 14_400_000, open_, high, low, close, 1000 + 100 * rng.random(n)]))


def test_regime_follows_the_trend():
    up = describe_regime(build_frame(_trend(0.004), "4h").ind)
    down = describe_regime(build_frame(_trend(-0.004), "4h").ind)
    assert up["group"] == "Bull" and up["score"] > 0.5, up["regime"]
    assert down["group"] == "Bear" and down["score"] < -0.5, down["regime"]
    assert 0 <= up["confidence"] <= 1
    probs = up["transition"]["probabilities"]
    assert probs and abs(sum(probs.values()) - 1) < 1e-9 and probs["Bull"] > 0.5


def test_regime_needs_history():
    fr = build_frame(_trend(0.004, n=80), "4h")
    assert describe_regime(fr.ind)["regime"]                       # classified from the inputs that exist
    short = transition_probabilities(fr.ind["regime"].iloc[:30])
    assert short["probabilities"] is None and short["basis"] == "insufficient history"


def test_oversold_rsi_alone_does_not_create_a_buy():
    """A falling market with RSI under 30 must not turn into BUY just because RSI is low."""
    df = _trend(-0.012, n=500, seed=4)
    ind = build_frame(df, "4h").ind
    assert ind["rsi"].iloc[-1] < 35
    sig = build_signal(ind, "4h", None, None, None)
    assert "BUY" not in sig["signal"], sig["signal"]
    assert sig["composite"] < 0


def test_signal_components_and_weight_redistribution():
    ind = build_frame(_trend(0.004), "4h").ind
    sig = build_signal(ind, "4h", None, None, None)
    comps = {c["key"]: c for c in sig["components"]}
    assert not comps["ml"]["available"] and not comps["liquidity"]["available"] and not comps["htf"]["available"]
    assert abs(sum(c["effective_weight"] for c in sig["components"]) - 1) < 1e-9
    assert sig["weights_note"] and "BUY" in sig["signal"] and sig["reasons"]
    full = build_signal(ind, "4h", 0.5, 0.6, 0.3)
    assert all(c["available"] for c in full["components"]) and full["weights_note"] is None
    assert full["composite"] > sig["composite"] - 0.2
    bearish_ml = build_signal(ind, "4h", -0.9, -0.9, -0.9)
    assert bearish_ml["composite"] < full["composite"]
    assert label_for(0.0) == 3 and label_for(0.7) == 6 and label_for(-0.4) == 1


def test_timeframe_disagreement_downgrades_the_signal():
    ind = build_frame(_trend(0.004), "4h").ind
    ok = build_signal(ind, "4h", None, None, None, mtf_alignment=0.9)
    bad = build_signal(ind, "4h", None, None, None, mtf_alignment=0.3)
    assert bad["label_index"] == ok["label_index"] - 1
    assert any("Downgraded" in w for w in bad["warnings"])


def test_mtf_alignment():
    up, down = build_frame(_trend(0.004), "4h"), build_frame(_trend(-0.004), "4h")
    same = mtf_engine.mtf_matrix({"15m": up, "1h": up, "4h": up, "12h": up, "1d": up, "1w": up})
    assert same["alignment"] == 1.0 and same["dominant"] == 1 and not same["conflict"]
    mixed = mtf_engine.mtf_matrix({"15m": down, "1h": down, "4h": up, "12h": up, "1d": up, "1w": up}, {})
    assert 0.5 < mixed["alignment"] < 1.0 and mixed["conflict"]
    assert mtf_engine.alignment_with(mixed, -1) < 0.5
    partial = mtf_engine.mtf_matrix({"4h": up}, {"1w": "only 12 candles"})
    assert partial["timeframes_used"] == 1 and any(not r["available"] for r in partial["rows"])
    assert mtf_engine.higher_tf_score(same, "4h") > 0.3 and mtf_engine.higher_tf_score(same, "1w") is None


def test_long_setup_is_ordered_and_risk_defined():
    fr = build_frame(synthetic_candles(1500, "4h", seed=8), "4h")
    last = fr.ind.iloc[-1]
    zones = sr_zones(fr.swings, float(last["close"]), float(last["atr"]), len(fr.df))
    for side in (1, -1):
        s = build_setup(fr.ind, zones, side, min_rr=1.5)
        tps = [t["price"] for t in s["targets"]]
        if side > 0:
            assert s["stop"] < s["ideal_entry"] <= s["price"] and s["ideal_entry"] < tps[0] < tps[1] < tps[2]
        else:
            assert s["stop"] > s["ideal_entry"] >= s["price"] and s["ideal_entry"] > tps[0] > tps[1] > tps[2]
        assert 1.0 - 1e-9 <= s["stop_distance_atr"] <= 3.0 + 1e-9
        assert s["entry_zone"][0] <= s["ideal_entry"] <= s["entry_zone"][1]
        assert s["valid"] or s["reason"]
        for t in s["targets"]:
            assert t["probability"] is None or 0 <= t["probability"] <= 1
    assert build_setup(fr.ind, zones, 0)["valid"] is False


def test_setup_is_refused_when_reward_does_not_justify_risk():
    fr = build_frame(synthetic_candles(1500, "4h", seed=8), "4h")
    last = fr.ind.iloc[-1]
    price, atr = float(last["close"]), float(last["atr"])
    wall = {"support": [], "resistance": [{"low": price + 0.2 * atr, "high": price + 0.4 * atr, "mid": price + 0.3 * atr}]}
    s = build_setup(fr.ind, wall, 1, min_rr=1.25)
    assert s["valid"] is False and ("Resistance" in s["reason"] or "expectancy" in s["reason"])
    assert build_setup(fr.ind, {"support": [], "resistance": []}, 1, min_rr=50)["valid"] is False


def test_position_sizing_example_from_the_spec():
    r = position_size(RiskProfile(portfolio=25_000, risk_per_trade_pct=1.0), entry=100.0, stop=95.0)
    assert r["risk_amount"] == 250.0 and abs(r["max_loss"] - 250.0) < 1e-9 and abs(r["qty"] - 50.0) < 1e-9
    tight = position_size(RiskProfile(portfolio=25_000, risk_per_trade_pct=1.0, max_position_pct=10), 100.0, 99.9)
    assert tight["binding_constraint"] == "single-position cap" and abs(tight["notional"] - 2500) < 1e-6
    assert tight["max_loss"] < 250
    full = position_size(RiskProfile(portfolio=25_000), 100.0, 95.0, open_exposure=25_000)
    assert full["allowed"] is False
    halted = position_size(RiskProfile(portfolio=25_000, max_daily_loss_pct=3), 100.0, 95.0, realised_today=-800)
    assert halted["allowed"] is False and "daily loss" in halted["reason"]
    vol = position_size(RiskProfile(portfolio=25_000, risk_per_trade_pct=5, target_annual_vol_pct=10), 100.0, 99.0,
                        sigma_bar=0.03, timeframe="4h")
    assert vol["binding_constraint"] == "volatility target"


def test_correlation_exposure_and_portfolio_risk():
    corr = {"ETH/USDT": {"BTC/USDT": 0.9, "XRP/USDT": 0.3}, "BTC/USDT": {"ETH/USDT": 0.9}}
    assert correlated_notional("ETH/USDT", {"BTC/USDT": 4000, "XRP/USDT": 1000}, corr) == 4000
    pr = portfolio_risk({"BTC/USDT": 5000, "ETH/USDT": 5000}, corr, {"BTC/USDT": 0.6, "ETH/USDT": 0.8}, 10_000)
    assert 60 < pr["portfolio_vol_pct"] < 70.1 and pr["gross_exposure_pct"] == 100.0


def test_order_book_and_oi_interpretation():
    book = {"bids": [[99.9, 5], [99.8, 5], [99.0, 400]], "asks": [[100.1, 1], [100.2, 1], [100.5, 1]]}
    m = order_book_metrics(book)
    assert m["imbalance"] > 0.5 and abs(m["spread"] - 0.2) < 1e-9 and m["walls"][0]["side"] == "bid"
    assert order_book_metrics({"bids": [], "asks": []}) is None
    assert oi_price_state(0.02, 0.05)["label"] == "Price ↑ + OI ↑"
    assert oi_price_state(0.02, -0.05)["label"] == "Price ↑ + OI ↓"
    assert oi_price_state(-0.02, 0.05)["label"] == "Price ↓ + OI ↑"
    assert oi_price_state(-0.02, -0.05)["label"] == "Price ↓ + OI ↓"
    assert oi_price_state(0.0, 0.05)["label"] == "Flat"


def test_weight_optimisation_reports_out_of_sample_accuracy():
    ind = build_frame(synthetic_candles(2500, "4h", seed=3, predictable=0.25), "4h").ind
    fwd = ind["close"].shift(-1) / ind["close"] - 1
    out = optimise_weights(ind, fwd)
    assert out["ok"] and out["test_rows"] > 500 and 0 <= out["test_accuracy"] <= 1
    assert abs(sum(out["weights"].values()) - 1) < 1e-9 and min(out["weights"].values()) >= 0
    assert optimise_weights(ind.iloc[:200], fwd.iloc[:200])["ok"] is False


def test_targets_tp1_is_one_to_one_and_the_rest_stay_within_1_to_3():
    fr = build_frame(synthetic_candles(1500, "4h", seed=3), "4h")
    for side in (1, -1):
        s = build_setup(fr.ind, {"support": [], "resistance": []}, side, min_rr=0)
        rr = [t["rr"] for t in s["targets"]]
        assert abs(rr[0] - 1.0) < 1e-6 and 1.25 - 1e-6 <= rr[1] <= 2.0 + 1e-6 and 2.0 - 1e-6 <= rr[2] <= 3.0 + 1e-6
        assert rr[2] >= rr[1] + 0.25 - 1e-6 and s["tp_split"] == [0.5, 0.25, 0.25]
        assert abs(s["risk_reward"] - (0.5 * rr[0] + 0.25 * rr[1] + 0.25 * rr[2])) < 1e-9
