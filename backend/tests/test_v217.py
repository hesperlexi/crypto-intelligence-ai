"""v2.17 AI add-on switches (owner, 4 Nov 2026).

The strict holdout test (research-results/results/aiv3-final-20261103T204940Z.json) passed none of the add-ons except the
higher-timeframe context of SOL/USDT 15m, but they stay ON (current live behaviour) pending a crash / volatility-regime
study. Each has a switch; env = 0 turns it off (then it is neither trained nor scored).
"""
from __future__ import annotations

import os
from unittest import mock

from app.config import Settings
from app.ml import trainer

SWITCHES = ("TRADE_FILTER", "TRADE_FILTER2", "TARGET_MODEL", "RUNNER_MODEL", "USE_DERIV_FEATURES", "HTF_GATES",
            "HTF_GATE_KEEP", "USE_HTF_FEATURES")


def _clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in SWITCHES}


def test_ai_addon_defaults_stay_on():
    with mock.patch.dict(os.environ, _clean_env(), clear=True):
        s = Settings()
    assert s.trade_filter_v1 and s.trade_filter2 and s.target_model and s.runner_model
    assert s.use_deriv_features and s.htf_gates and not s.use_htf_features
    # every series runs its higher-timeframe gate (as on release-v216)
    assert s.htf_gate_on("BTC/USDT", "4h") and s.htf_gate_on("SOL/USDT", "15m")
    assert s.htf_gate_keep == ["SOL/USDT|15m"]
    assert s.entry_rules and s.require_edge_for_ml and not s.require_edge_for_trade


def test_switches_turn_each_addon_off():
    off = {**_clean_env(), "TRADE_FILTER": "0", "TRADE_FILTER2": "0", "TARGET_MODEL": "0", "RUNNER_MODEL": "0",
           "USE_DERIV_FEATURES": "0", "HTF_GATES": "0"}
    with mock.patch.dict(os.environ, off, clear=True):
        s = Settings()
    assert not (s.trade_filter_v1 or s.trade_filter2 or s.target_model or s.runner_model)
    assert not s.use_deriv_features and not s.htf_gates
    # with the gates off only the survivor keeps its higher-timeframe gate
    assert s.htf_gate_on("SOL/USDT", "15m")
    assert not s.htf_gate_on("SOL/USDT", "1h") and not s.htf_gate_on("BTC/USDT", "15m")


def test_switched_off_addons_are_not_trained_or_scored():
    from app.config import settings
    from app.ml import runner_model, target_model, trade_filter
    from app.services import analysis
    from tests.helpers import make_runtime

    def boom(*a, **k):
        raise AssertionError("switched-off add-on was called")

    old = (settings.trade_filter_v1, settings.target_model, settings.runner_model)
    settings.trade_filter_v1 = settings.target_model = settings.runner_model = False
    try:
        rt, _ = make_runtime(symbols=("BTC/USDT",), predictable=0.15)
        b = trainer.train_bundle("BTC/USDT", "4h", rt.frame("BTC/USDT", "4h"), None, fast=True)
        for k in ("trade_filter", "target_model", "runner_model"):
            assert b[k] == {"enabled": False, "reason": trainer.OFF_REASON}
        trainer.save_bundle(b, rt.db)
        with mock.patch.object(trade_filter, "score", boom), mock.patch.object(target_model, "lifts", boom), \
                mock.patch.object(runner_model, "score", boom):
            fc = analysis.model_forecast(rt, "BTC/USDT", "4h")
        assert fc["available"]
        assert fc["trade_filter"] is None and fc["target_lift"] is None and fc["runner"] is None
        assert "trade_filter_error" not in fc
    finally:
        settings.trade_filter_v1, settings.target_model, settings.runner_model = old


def test_addons_are_scored_by_default():
    from app.ml import runner_model, target_model, trade_filter
    from app.services import analysis
    from tests.helpers import shared_runtime

    rt, _ = shared_runtime()
    calls = []
    with mock.patch.object(trade_filter, "score", lambda *a, **k: calls.append("filter")), \
            mock.patch.object(target_model, "lifts", lambda *a, **k: calls.append("target")), \
            mock.patch.object(runner_model, "score", lambda *a, **k: calls.append("runner")):
        fc = analysis.model_forecast(rt, "BTC/USDT", "4h")
    assert fc["available"] and sorted(calls) == ["filter", "runner", "target"]
