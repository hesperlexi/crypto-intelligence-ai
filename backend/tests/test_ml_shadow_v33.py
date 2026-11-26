"""V3.3 Stage 2 phases D + E: performance by regime with intervals, portfolio risk in the Lab, ML shadow report."""
import json

from app.db import Database
from app.services import analysis, ml_shadow, perf_lab

H = 3_600_000
NOW = 1_795_700_000_000


class RT:
    def __init__(self):
        self.db = Database("sqlite:///:memory:")

    def candles(self, s, tf):
        return None


def _call(db, i, ret, payload, tf="4h", status=None):
    created = NOW - (100 - i) * H
    db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, tp1, "
               "status, fill_status, closed_at, return_pct, return_net_pct, payload) VALUES (?, ?, ?, ?, ?, 'BUY', 'BUY', 100, 1, "
               "100, 98, 102, ?, 'FILLED', ?, ?, ?, ?)",
               (f"s{i}", created, f"C{i}/USDT", tf, created - H, status or ("TP1" if ret > 0 else "STOPPED"),
                created + 3 * H, ret, ret, json.dumps(payload)))


def _fill(rt, monkeypatch):
    from app import views
    monkeypatch.setattr(views, "record_since", lambda rt_: 0)
    for i in range(40):
        blocked = i % 4 == 0
        p = {"grade": "A", "risk_shadow": {"state": "NORMAL" if i % 2 else "CAUTION"}}
        if blocked:
            p["filter_shadow"] = [{"filter": "trade_filter", "score": 0.3, "threshold": 0.5, "validated": False}]
        if i % 10 == 0:
            p["runner_shadow"] = {"would_run": True, "score": 0.7, "threshold": 0.6}
        _call(rt.db, i, -2.0 if blocked else (2.0 if i % 3 else -2.0), p, tf="4h" if i % 2 else "1h")


def test_ml_shadow_report_links_shadow_decisions_to_outcomes(monkeypatch):
    rt = RT()
    _fill(rt, monkeypatch)
    m = ml_shadow.build(rt, NOW)
    assert m["counts"] == {"calls": 40, "would_block": 10, "would_run": 4}
    assert m["would_block"]["n"] == 10 and m["would_block"]["avg_r"] == -1.0          # 2 % move / 2 % risk = 1R
    assert m["allowed"]["n"] == 30 and m["by_filter"]["trade_filter"]["n"] == 10
    assert set(m["by_tf"]) == {"1h", "4h"} and set(m["by_regime"]) == {"NORMAL", "CAUTION"}
    assert m["mode"] == {"trade_filter_enforce": analysis.FILTER_ENFORCE, "runner_enforce": analysis.RUNNER_ENFORCE}
    assert m["verdict"] == "too few closed calls to judge"                              # 10 < MIN_N
    assert "not win probabilities" in m["note"]


def test_verdict_needs_enough_calls(monkeypatch):
    monkeypatch.setattr(ml_shadow, "MIN_N", 5)
    rt = RT()
    _fill(rt, monkeypatch)
    assert ml_shadow.build(rt, NOW)["verdict"].startswith("blocked calls did worse")


def test_shadow_kept_share_and_freshness_reported():
    rt = RT()
    rt.db.set_setting("filter_shadow_stats|trade_filter|4h", {"n": 100, "kept_share": 0.47, "keep_fraction": 0.5, "at": NOW})
    rt.db.execute("INSERT INTO model_versions (id, symbol, timeframe, created_at, active, summary) VALUES "
                  "('v1', 'BTC/USDT', '4h', ?, 1, ?)", (NOW - 60 * H, json.dumps({"addons": {
                      "trade_filter": {"enabled": True, "validated": True, "threshold_method": "oof_embargo"},
                      "runner_model": {"enabled": True, "validated": False, "threshold_method": None}}})))
    rt.db.execute("INSERT INTO model_versions (id, symbol, timeframe, created_at, active, summary) VALUES "
                  "('v2', 'ETH/USDT', '4h', ?, 1, '{}')", (NOW - 5 * H,))
    m = ml_shadow.build(rt, NOW)
    assert m["shadow_scored"]["trade_filter|4h"]["kept_share"] == 0.47
    f = m["freshness"]
    assert f["ages"]["4h"]["n"] == 2 and f["ages"]["4h"]["older_than_48h"] == 1
    assert f["addons"]["trade_filter"] == {"enabled": 1, "validated": 1, "in_sample_threshold": 0, "unknown": 1}
    assert f["addons"]["runner_model"]["in_sample_threshold"] == 1


def test_perf_lab_adds_regime_intervals_portfolio_and_shadow(monkeypatch):
    rt = RT()
    _fill(rt, monkeypatch)
    v = perf_lab.build(rt, NOW)
    keys = {r["key"] for r in v["by_regime"]}
    assert keys == {"NORMAL", "CAUTION"}
    assert v["overall"]["ci95_avg_r"] is not None and v["overall"]["max_losing_streak"] >= 1
    assert v["portfolio"]["available"] and v["ml_shadow"]["counts"]["would_block"] == 10
    assert "not verified win probabilities" in v["basis"]["confidence"]
    assert any(r["key"].startswith("4h ") for r in v["by_tf_side"])


def test_bundle_summary_carries_addon_status():
    from app.ml import trainer
    import inspect
    src = inspect.getsource(trainer._summary)
    assert '"addons"' in src and "validated" in src and "threshold_method" in src
