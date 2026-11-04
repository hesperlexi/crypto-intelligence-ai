"""v2.17 (owner, 4 Nov 2026): AI add-ons that failed the strict holdout test are off by default.

Research: research-results/results/aiv3-final-20261103T204940Z.json (Holm-corrected block bootstrap; none survived
except the higher-timeframe context of SOL/USDT 15m). Each switch is kept; env = 1 turns it back on.
"""
from __future__ import annotations

import os
from unittest import mock

from app.config import Settings, settings
from app.ml import trainer


def test_ai_addon_defaults_are_off():
    env = {k: v for k, v in os.environ.items()
           if k not in ("TRADE_FILTER", "TRADE_FILTER2", "TARGET_MODEL", "RUNNER_MODEL", "USE_DERIV_FEATURES",
                        "HTF_GATES", "HTF_GATE_KEEP", "USE_HTF_FEATURES")}
    with mock.patch.dict(os.environ, env, clear=True):
        s = Settings()
    assert not s.trade_filter_v1 and not s.trade_filter2
    assert not s.target_model and not s.runner_model
    assert not s.use_deriv_features and not s.htf_gates and not s.use_htf_features
    # the one survivor keeps its per-series higher-timeframe gate
    assert s.htf_gate_keep == ["SOL/USDT|15m"]
    assert s.htf_gate_on("SOL/USDT", "15m")
    assert not s.htf_gate_on("SOL/USDT", "1h") and not s.htf_gate_on("BTC/USDT", "15m")
    # what stays: base ensemble, entry rules, edge-for-ML, honest record settings
    assert s.entry_rules and s.require_edge_for_ml and not s.require_edge_for_trade


def test_switches_can_be_turned_back_on():
    on = {"TRADE_FILTER": "1", "TRADE_FILTER2": "1", "TARGET_MODEL": "1", "RUNNER_MODEL": "1",
          "USE_DERIV_FEATURES": "1", "HTF_GATES": "1"}
    with mock.patch.dict(os.environ, on):
        s = Settings()
    assert s.trade_filter_v1 and s.trade_filter2 and s.target_model and s.runner_model
    assert s.use_deriv_features and s.htf_gates and s.htf_gate_on("BTC/USDT", "4h")


def test_switched_off_addons_are_not_trained_or_scored():
    from app.services import analysis
    from app.ml import runner_model, target_model, trade_filter
    from tests.helpers import shared_runtime

    rt, _ = shared_runtime()
    b = trainer.load_bundle("BTC/USDT", "4h", rt.db)
    assert b is not None
    for k in ("trade_filter", "target_model", "runner_model"):
        assert b[k] == {"enabled": False, "reason": trainer.OFF_REASON}

    def boom(*a, **k):
        raise AssertionError("switched-off add-on was called")

    with mock.patch.object(trade_filter, "score", boom), mock.patch.object(target_model, "lifts", boom), \
            mock.patch.object(runner_model, "score", boom):
        fc = analysis.model_forecast(rt, "BTC/USDT", "4h")
    assert fc["available"]
    assert fc["trade_filter"] is None and fc["target_lift"] is None and fc["runner"] is None
    assert "trade_filter_error" not in fc
