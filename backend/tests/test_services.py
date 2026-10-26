"""Service layer end to end on an in-memory database: analysis, protection rules, tracking, alerts, paper
trading, backtests, replay, health, and failure handling (missing data, API / model / database failures)."""
import asyncio
import json
import os

import numpy as np

from app.backtest.benchmarks import NO_EDGE
from app.config import settings
from app.data.base import tf_ms
from app.db import Database, dumps
from app.ml import trainer
from app.services import alerts, analysis, backtests, health, market, paper, replay, scanner, tracking, training
from app.services.runtime import Runtime
from tests.helpers import ArrayProvider, make_runtime, shared_runtime


def test_structured_output_has_every_field_of_the_final_signal_format():
    rt, _ = shared_runtime()
    a = analysis.analyze(rt, "BTC/USDT", "4h", use_cache=False)
    assert a["status"] == "OK"
    out = analysis.final_signal(a)
    for k in ("asset", "price", "regime", "regime_confidence", "signal", "signal_score", "bullish", "neutral", "bearish",
              "forecast", "entry", "stop", "tp1", "tp2", "tp3", "risk_reward", "multi_timeframe_alignment",
              "model_agreement", "warnings", "decision"):
        assert k in out, k
    assert set(out["forecast"]) == {"15M", "1H", "4H"}
    assert out["decision"] in ("BUY", "BUY ON PULLBACK", "HOLD", "SELL", "NO TRADE")
    assert abs(out["bullish"] + out["neutral"] + out["bearish"] - 1) < 1e-9
    json.loads(dumps(a))                                   # strict JSON: no NaN, no numpy types
    assert "NaN" not in dumps(a)
    assert a["commentary"] and a["symbol"].split("/")[0] in a["commentary"]


def test_horizons_use_their_own_timeframe_model_and_never_extrapolate():
    rt, _ = shared_runtime()
    hz = {h["horizon"]: h for h in analysis.horizon_forecasts(rt, "BTC/USDT")}
    assert hz["4H"]["available"] and hz["4H"]["timeframe"] == "4h"
    for label in ("15M", "1H"):                            # only the 4h model was trained in this fixture
        assert not hz[label]["available"] and hz[label]["status"] == "MODEL NOT TRAINED"
        assert "expected_return" not in hz[label]
    assert analysis.model_forecast(rt, "BTC/USDT", "1d")["status"] == "NOT MODELLED"     # daily: context only


def test_no_data_and_no_model_protection():
    rt, _ = shared_runtime()
    missing = analysis.analyze(rt, "DOGE/USDT", "4h", use_cache=False)
    assert missing["status"] == "INSUFFICIENT DATA" and missing["decision"] == "INSUFFICIENT DATA"
    assert missing["forecast"]["available"] is False
    weekly = analysis.analyze(rt, "BTC/USDT", "1w", use_cache=False)      # too few weekly candles for a regime
    assert weekly["forecast"]["available"] is False
    assert weekly["decision"] in ("HOLD", "NO TRADE", "INSUFFICIENT DATA")
    untrained = analysis.analyze(rt, "BTC/USDT", "1h", use_cache=False)
    assert "MODEL NOT TRAINED" in untrained["flags"]
    assert untrained["decision"] not in analysis.TRADE_DECISIONS         # no model -> no confidence -> no trade
    assert untrained["confidence"] is None


def test_decision_gates():
    rt, _ = shared_runtime()
    a = analysis.analyze(rt, "ETH/USDT", "4h", use_cache=False)
    fc = a["forecast"]
    assert fc["available"]
    if not fc["edge_confirmed"]:
        assert NO_EDGE in a["flags"]
        ml = next(c for c in a["signal"]["components"] if c["key"] == "ml")
        assert not ml["available"]                         # an unproven model must not drive the score
    old = (settings.min_confidence, settings.min_model_agreement)
    try:
        settings.min_confidence, settings.min_model_agreement = 0.99, 0.0
        strict = analysis.analyze(rt, "ETH/USDT", "4h", use_cache=False)
        assert strict["decision"] not in analysis.TRADE_DECISIONS
        if strict["decision"] == "NO TRADE":
            assert strict["decision_reason"] and "NO TRADE" in strict["flags"]
        settings.min_confidence, settings.min_model_agreement = 0.0, 1.01
        agree = analysis.analyze(rt, "ETH/USDT", "4h", use_cache=False)
        assert "LOW MODEL AGREEMENT" in agree["flags"] and agree["decision"] not in analysis.TRADE_DECISIONS
    finally:
        settings.min_confidence, settings.min_model_agreement = old


def test_predictions_are_logged_once_and_scored_after_the_fact():
    rt, _ = make_runtime(predictable=0.15)
    assert training.train_one(rt, "BTC/USDT", "4h", fast=True)["state"] == "done"
    b = trainer.load_bundle("BTC/USDT", "4h", rt.db)
    for _ in range(3):                                     # repeated refreshes of the same bar
        analysis.analyze(rt, "BTC/USDT", "4h", use_cache=False)
    rows = rt.db.query("SELECT * FROM predictions")
    assert len(rows) == 1 and rows[0]["model_version_id"] == b["version"]
    assert rows[0]["target_ts"] == rows[0]["bar_ts"] + 2 * tf_ms("4h")
    assert tracking.resolve_outcomes(rt) == 0              # outcome candle does not exist yet: nothing to score
    # replay the model over 60 earlier bars as if they had been live, then let the "next" candles arrive
    df = rt.candles("BTC/USDT", "4h")
    ds = rt.dataset("BTC/USDT", "4h", b["uses_btc"])
    for pos in range(len(df) - 62, len(df) - 2):
        fc = trainer.predict(b, ds, pos=pos)
        tracking.log_prediction(rt.db, "BTC/USDT", "4h", fc)
    assert tracking.resolve_outcomes(rt) == 60
    stats = tracking.live_stats(rt.db, "BTC/USDT", "4h")
    assert stats["resolved"] == 60 and stats["pending"] == 1 and 0 <= stats["overall"]["accuracy"] <= 1
    assert "brier" in stats and stats["reliability"] and len(stats["recent"]) == 60
    r = stats["recent"][0]
    c = df.set_index("ts")["close"]
    assert abs(r["actual_return"] - (c[r["ts"] + tf_ms("4h")] / c[r["ts"]] - 1)) < 1e-12
    mult = tracking.live_multipliers(rt.db, b, min_n=50)
    assert all(v == 0.5 for v in mult.values())            # only ever down-weights
    assert tracking.performance_windows(rt.db, b)["recent_n"] == 60


def test_signal_history_tracks_targets_and_stops():
    rt, _ = make_runtime()
    df = rt.candles("BTC/USDT", "4h")
    bar = df.iloc[-40]
    px = float(bar["close"])
    a = {"symbol": "BTC/USDT", "timeframe": "4h", "bar_ts": int(bar["ts"]), "price": px, "decision": "BUY",
         "confidence": 0.6, "regime": {"regime": "BULL"}, "signal": {"signal": "BUY", "score": 70, "reasons": [], "warnings": []},
         "setup": {"valid": True, "side_int": 1, "stop": px * 0.5, "risk_reward": 2.0,
                   "targets": [{"price": px * 1.0001}, {"price": px * 1.0002}, {"price": px * 1e6}]}, "flags": []}
    assert tracking.log_signal(rt.db, a) is True
    assert tracking.log_signal(rt.db, a) is False          # unchanged signal is not logged twice
    tracking.update_signal_outcomes(rt)
    s = tracking.signal_history(rt.db, "BTC/USDT")[0]
    after = df[df["ts"] > bar["ts"]].iloc[:30]
    assert bool(s["tp1_hit"]) == bool((after["high"] >= px * 1.0001).any())
    assert s["tp3_hit"] == 0 and s["status"] in ("TP1", "TP2", "EXPIRED", "STOPPED")
    info = {**a, "bar_ts": int(df["ts"].iloc[-5]), "decision": "HOLD", "signal": {"signal": "HOLD"}, "setup": None}
    assert tracking.log_signal(rt.db, info) and tracking.signal_history(rt.db)[0]["status"] == "INFO"


def test_alerts_debounce_and_cooldown():
    db = Database("sqlite:///:memory:")
    alerts.create_alert(db, "PRICE_ABOVE", "BTC/USDT", "4h", {"level": 100}, cooldown_s=3600)
    a = {"status": "OK", "symbol": "BTC/USDT", "timeframe": "4h", "price": 90.0}
    t0 = 1_000_000_000
    assert alerts.evaluate(db, a, t0) == []                                       # condition false
    assert len(alerts.evaluate(db, {**a, "price": 101.0}, t0 + 1000)) == 1        # false -> true: fires
    assert alerts.evaluate(db, {**a, "price": 102.0}, t0 + 2000) == []            # stays true: silent
    assert alerts.evaluate(db, {**a, "price": 99.0}, t0 + 3000) == []             # resets
    assert alerts.evaluate(db, {**a, "price": 101.0}, t0 + 4000) == []            # true again but cooling down
    assert len(alerts.evaluate(db, {**a, "price": 101.0}, t0 + 3_700_000)) == 1   # cooldown over: fires once
    assert len(alerts.events(db)) == 2
    armed = alerts.create_alert(db, "PRICE_BELOW", "BTC/USDT", "4h", {"level": 500})
    assert alerts.evaluate(db, a, t0 + 9_000_000) == []    # already true when created: does not fire immediately
    alerts.set_enabled(db, armed["id"], False)
    try:
        alerts.create_alert(db, "NOT_A_TYPE", "BTC/USDT")
        raise AssertionError("unknown alert types must be rejected")
    except ValueError:
        pass


def test_paper_trading_accounting():
    rt, prov = make_runtime()
    acc = paper.reset(rt, 10_000)
    px = rt.candles("BTC/USDT", "15m", include_forming=True)["close"].iloc[-1]
    buy = paper.order(rt, "BTC/USDT", "BUY", notional=4000)
    assert buy["mode"] == "PAPER" and buy["price"] > px and buy["fee"] > 0 and buy["slippage_cost"] > 0
    st = paper.state(rt)
    assert st["mode"] == "PAPER TRADING" and len(st["positions"]) == 1
    assert abs(st["cash"] + buy["qty"] * buy["price"] + buy["fee"] - 10_000) < 1e-6
    assert st["equity"] < 10_000                           # costs are paid immediately
    try:
        paper.order(rt, "BTC/USDT", "SELL", qty=buy["qty"] * 2)
        raise AssertionError("selling more than the position must be rejected")
    except paper.PaperError:
        pass
    try:
        paper.order(rt, "BTC/USDT", "BUY", notional=1e9)
        raise AssertionError("buying beyond the virtual cash must be rejected")
    except paper.PaperError:
        pass
    sell = paper.order(rt, "BTC/USDT", "SELL", qty=buy["qty"])
    st = paper.state(rt)
    assert not st["positions"] and sell["realized_pnl"] < 0          # round trip at one price loses the costs
    assert abs(st["equity"] - (10_000 - st["fees"] - st["slippage"])) < 1e-6
    assert acc["id"] != paper.reset(rt, 5000)["id"] and paper.state(rt)["equity"] == 5000


def test_backtest_service_and_ai_strategy_only_uses_out_of_sample_bars():
    rt, _ = shared_runtime()
    r = backtests.run(rt, {"symbol": "BTC/USDT", "timeframe": "4h", "strategy": "sma_cross", "stop_atr": 2.0})
    assert r["status"] == "done"
    s = r["result"]["summary"]
    assert s["gross_return"] >= s["net_return"] and s["fees"] > 0 and s["trades"] > 0
    assert set(r["result"]["benchmarks"]) == {"buy_hold", "sma_cross", "random"}
    assert backtests.get(rt, r["id"])["result"]["summary"]["trades"] == s["trades"]
    b = trainer.load_bundle("BTC/USDT", "4h", rt.db)
    ai = backtests.run(rt, {"symbol": "BTC/USDT", "timeframe": "4h", "strategy": "ai_ensemble", "stop_atr": None})
    assert ai["status"] == "done"
    assert ai["result"]["summary"]["start_ts"] >= int(b["oos"]["ts"][0])          # clipped to the OOS range
    assert ai["result"]["summary"]["start_ts"] > b["folds"][0]["train"][1]
    assert ai["result"]["walk_forward"]["folds"]
    bad = backtests.run(rt, {"symbol": "NOPE/USDT", "timeframe": "4h", "strategy": "sma_cross"})
    assert bad["status"] == "failed" and bad["result"]["error"]


def test_replay_uses_no_future_data():
    rt, prov = shared_runtime()
    df = rt.candles("BTC/USDT", "4h")
    as_of = int(df["ts"].iloc[-120]) + tf_ms("4h") + 5_000
    rp = replay.replay(rt, "BTC/USDT", "4h", as_of, bars_after=20)
    assert rp["status"] == "OK" and rp["audit"]["no_future_data"] is True
    assert rp["audit"]["newest_candle_close_used"] <= as_of and rp["audit"]["model_trained_through"] <= as_of
    assert rp["reveal"]["bars"] == 20 and rp["chart"]["future"][0]["ts"] > rp["audit"]["last_closed_bar_open"]
    # the decisive check: a world in which the future never happened must give the identical analysis
    past = Runtime(Database("sqlite:///:memory:"), prov)
    for (sym, tf), frame in prov.data.items():
        rows = frame[frame["ts"] + tf_ms(tf) <= as_of][["ts", "open", "high", "low", "close", "volume"]].values.tolist()
        past.store.upsert("test", sym, tf, rows)
    rp2 = replay.replay(past, "BTC/USDT", "4h", as_of, bars_after=20)
    a1, a2 = rp["analysis"], rp2["analysis"]
    assert a1["signal"]["composite"] == a2["signal"]["composite"] and a1["decision"] == a2["decision"]
    assert a1["regime"]["score"] == a2["regime"]["score"] and a1["mtf"]["alignment"] == a2["mtf"]["alignment"]
    assert np.allclose(list(a1["forecast"]["probabilities"].values()), list(a2["forecast"]["probabilities"].values()), atol=1e-9)
    assert rp2["reveal"]["bars"] == 0
    assert replay.replay(rt, "BTC/USDT", "4h", int(df["ts"].iloc[10]))["status"] == "INSUFFICIENT DATA"


def test_scanner_dashboard_and_cross_asset():
    rt, _ = shared_runtime()
    rows = scanner.scan(rt, "4h")
    assert {r["symbol"] for r in rows} == {"BTC/USDT", "ETH/USDT"}
    for r in rows:
        assert r["status"] == "OK" and r["signal"] and r["regime"] and r["decision"]
        assert r["breakout_base_rate"] is None or 0 <= r["breakout_base_rate"] <= 1
    d = scanner.dashboard(rt, "4h")
    assert d["market_status"]["status"] in ("BULL", "BEAR", "NEUTRAL") and len(d["forecast_table"]) == 2
    for o in d["opportunities"]:
        assert o["decision"] in analysis.TRADE_DECISIONS
    ca = scanner.cross_asset(rt, "1d")
    assert ca["available"] and abs(ca["correlation"]["BTC/USDT"]["BTC/USDT"] - 1) < 1e-9
    json.loads(dumps(d))


def test_api_failure_is_contained():
    class Flaky(ArrayProvider):
        async def fetch_ohlcv(self, symbol, timeframe, since=None, limit=1000):
            if symbol == "ETH/USDT":
                raise ConnectionError("exchange unreachable")
            return await super().fetch_ohlcv(symbol, timeframe, since, limit)

        async def fetch_order_book(self, symbol, limit=100):
            raise TimeoutError("timeout")

    prov = Flaky()
    rt = Runtime(Database("sqlite:///:memory:"), prov)
    asyncio.run(market.sync_all(rt, ["4h"]))
    assert rt.store.count("test", "BTC/USDT", "4h") > 1000 and rt.store.count("test", "ETH/USDT", "4h") == 0
    assert any("exchange unreachable" in e["error"] for e in rt.errors)
    assert asyncio.run(market.refresh_order_book(rt, "BTC/USDT")) is None
    assert analysis.analyze(rt, "ETH/USDT", "4h")["status"] == "INSUFFICIENT DATA"
    assert analysis.analyze(rt, "BTC/USDT", "4h")["status"] == "OK"               # the healthy asset keeps working
    assert asyncio.run(market.derivatives_snapshot(rt, "BTC/USDT"))["available"] is False


def test_model_failure_is_reported_not_papered_over():
    rt, _ = make_runtime()
    assert training.train_one(rt, "BTC/USDT", "4h", fast=True)["state"] == "done"
    row = trainer.active_version("BTC/USDT", "4h", rt.db)
    trainer._cache.clear()
    os.remove(row["path"])                                                        # model file lost
    fc = analysis.model_forecast(rt, "BTC/USDT", "4h")
    assert fc["available"] is False and fc["reason"]
    a = analysis.analyze(rt, "BTC/USDT", "4h", use_cache=False)
    assert a["status"] == "OK" and a["decision"] not in analysis.TRADE_DECISIONS
    skipped = training.train_one(rt, "BTC/USDT", "1w", fast=True)                 # too little weekly history
    assert skipped["state"] == "skipped" and skipped["insufficient"]
    assert ("BTC/USDT", "1w") not in training.due_for_training(rt)                # not retried in a tight loop


def test_database_failure_shows_up_in_health():
    rt, _ = make_runtime()
    h = health.report(rt)
    assert h["database"]["ok"] and h["market_data"]["quality_pct"] == 100.0
    assert h["status"] in ("DEGRADED", "LIVE") and len(h["series"]) == 8 and len(h["models"]) == 6
    health.snapshot(rt)
    assert rt.db.one("SELECT COUNT(*) AS n FROM system_health")["n"] == 3
    rt.db._conn.close()
    assert rt.db.ping() is False
    broken = Runtime.__new__(Runtime)
    broken.__dict__.update(rt.__dict__)
    assert broken.db.ping() is False


def test_external_context_can_be_disabled_without_inventing_values():
    rt, _ = make_runtime()
    old = settings.enable_external_context
    try:
        settings.enable_external_context = False
        ctx = asyncio.run(market.external_context(rt))
        assert ctx["enabled"] is False and "market" not in ctx and "sentiment" not in ctx
    finally:
        settings.enable_external_context = old
