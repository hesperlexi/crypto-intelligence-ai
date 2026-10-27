"""Demo trading bots: fills, partial take-profits, break-even stops, prediction tracking, accounting, resets."""
import time

import pytest

from app.db import Database
from app.services import analysis
from app.services import bots as B
from app.services.runtime import Runtime

STEP = 900_000                     # 15 minutes
H4 = 4 * 3_600_000


class _P:
    name = "test"


def _rt(symbols=("BTC/USDT",)):
    from app.config import settings

    settings.symbols = list(symbols)
    rt = Runtime(Database("sqlite:///:memory:"), _P())
    return rt


def _put(rt, symbol, start_ts, closes, spread=0.2):
    """15m candles at 100-ish prices; each entry is (open, high, low, close) or a close (flat candle)."""
    rows, ts = [], start_ts
    for c in closes:
        o, h, l, cl = c if isinstance(c, tuple) else (c, c + spread, c - spread, c)
        rows.append([ts, o, h, l, cl, 10.0])
        ts += STEP
    rt.store.upsert("test", symbol, "15m", rows)
    return ts


def _now_aligned():
    n = int(time.time() * 1000)
    return n - n % STEP


def _cfg(**kw):
    base = {"id": "b1", "name": "t", "mode": "decision", "timeframe": "4h", "symbols": "all", "starting_balance": 10_000,
            "risk_per_trade_pct": 1.0, "max_position_pct": 100.0, "max_open_positions": 5, "allow_short": True,
            "reset_token": "1"}
    return {**base, **kw}


def _buy(decision="BUY", side=1, entry=100.0, stop=98.0, tps=(102.0, 104.0, 106.0), bar_ts=1):
    return {"status": "OK", "decision": decision, "bar_ts": bar_ts, "confidence": 0.55,
            "signal": {"signal": "BUY" if side > 0 else "SELL"},
            "forecast": {"probabilities": {"up": 0.5, "down": 0.2}, "predicted": "UP", "model_version": "v1",
                         "edge_confirmed": False},
            "setup": {"valid": True, "side_int": side, "ideal_entry": entry, "stop": stop, "risk_reward": 2.0,
                      "targets": [{"price": p} for p in tps]}}


@pytest.fixture
def no_costs(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "fee_rate", 0.0)
    monkeypatch.setattr(settings, "slippage_bps", 0.0)
    monkeypatch.setattr(settings, "spread_bps", 0.0)


def test_long_takes_partial_profits_and_exits_at_breakeven(monkeypatch, no_costs):
    rt = _rt()
    now = _now_aligned()
    t0 = now - 40 * STEP
    _put(rt, "BTC/USDT", t0, [100.0] * 4)                       # history up to the entry
    eng = B.BotEngine(rt)
    eng.sync_configs([_cfg()])
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: _buy())
    entry_time = t0 + 4 * STEP
    eng.run(entry_time)
    (cfg, st), = eng.bots()
    pos = st["positions"][0]
    assert pos["entry"] == 100.0 and abs(pos["qty"] - 50.0) < 1e-9    # 1% of 10k risk / $2 stop distance
    # next candles: one hits TP1 (102), then price returns to the entry -> break-even stop on the rest
    _put(rt, "BTC/USDT", t0 + 4 * STEP, [(100, 102.5, 99.9, 102), (102, 102.2, 99.5, 99.8)])
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: {"status": "OK", "decision": "HOLD"})
    eng.run(entry_time + 3 * STEP)
    (cfg, st), = eng.bots()
    assert st["positions"] == []
    t = rt.db.one("SELECT * FROM bot_trades")
    assert t["exit_reason"] == "breakeven stop" and t["correct"] == 1
    assert abs(t["pnl"] - 50 * 0.5 * 2) < 1e-6                      # half banked at TP1 (+$2), the rest flat
    assert abs(st["cash"] - (10_000 + t["pnl"])) < 1e-6 and abs(st["equity"] - st["cash"]) < 1e-6
    assert abs(t["r_multiple"] - t["pnl"] / 100) < 1e-9


def test_stop_fills_first_when_a_candle_touches_both(monkeypatch, no_costs):
    rt = _rt()
    now = _now_aligned()
    t0 = now - 40 * STEP
    _put(rt, "BTC/USDT", t0, [100.0] * 4)
    eng = B.BotEngine(rt)
    eng.sync_configs([_cfg()])
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: _buy())
    eng.run(t0 + 4 * STEP)
    _put(rt, "BTC/USDT", t0 + 4 * STEP, [(100, 106.5, 97.0, 100)])   # huge range: TP3 and stop in one candle
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: {"status": "OK", "decision": "HOLD"})
    eng.run(t0 + 6 * STEP)
    t = rt.db.one("SELECT * FROM bot_trades")
    assert t["exit_reason"] == "stop" and abs(t["pnl"] + 100.0) < 1e-6 and t["correct"] == 0


def test_short_and_one_entry_per_signal_bar(monkeypatch, no_costs):
    rt = _rt()
    now = _now_aligned()
    t0 = now - 40 * STEP
    _put(rt, "BTC/USDT", t0, [100.0] * 4)
    eng = B.BotEngine(rt)
    eng.sync_configs([_cfg()])
    sell = _buy("SELL", -1, 100.0, 102.0, (98.0, 96.0, 94.0), bar_ts=7)
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: sell)
    eng.run(t0 + 4 * STEP)
    _put(rt, "BTC/USDT", t0 + 4 * STEP, [(100, 100.1, 93.5, 94)])   # all three targets in one move down
    eng.run(t0 + 6 * STEP)                                          # same signal bar: must not re-enter
    (cfg, st), = eng.bots()
    t = rt.db.one("SELECT * FROM bot_trades")
    assert t["side"] == -1 and t["exit_reason"] == "TP3"
    assert abs(t["pnl"] - 50 * (0.5 * 2 + 0.25 * 4 + 0.25 * 6)) < 1e-6
    assert st["positions"] == [] and rt.db.one("SELECT COUNT(*) AS n FROM bot_trades")["n"] == 1


def test_pullback_limit_fills_only_when_touched_and_expires(monkeypatch, no_costs):
    rt = _rt()
    now = _now_aligned()
    t0 = now - 60 * STEP
    _put(rt, "BTC/USDT", t0, [101.0] * 4)
    eng = B.BotEngine(rt)
    eng.sync_configs([_cfg(pending_bars=1)])
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: _buy("BUY ON PULLBACK"))
    eng.run(t0 + 4 * STEP)
    (cfg, st), = eng.bots()
    assert len(st["pending"]) == 1 and st["positions"] == []
    assert abs(eng.equity(st) - 10_000) < 1e-6                      # reserved cash still counts as equity
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: {"status": "OK", "decision": "HOLD"})
    _put(rt, "BTC/USDT", t0 + 4 * STEP, [(101, 101.5, 100.5, 101)])  # does not reach 100
    eng.run(t0 + 6 * STEP)
    assert len(eng.bots()[0][1]["pending"]) == 1
    _put(rt, "BTC/USDT", t0 + 5 * STEP, [(101, 101.2, 99.9, 100.4)])  # touches the limit
    eng.run(t0 + 7 * STEP)
    (cfg, st), = eng.bots()
    assert st["pending"] == [] and st["positions"][0]["entry"] == 100.0
    # a second pending order that is never touched expires after pending_bars
    rt2 = _rt()
    _put(rt2, "BTC/USDT", t0, [101.0] * 4)
    e2 = B.BotEngine(rt2)
    e2.sync_configs([_cfg(pending_bars=1)])
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: _buy("BUY ON PULLBACK"))
    e2.run(t0 + 4 * STEP)
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: {"status": "OK", "decision": "HOLD"})
    _put(rt2, "BTC/USDT", t0 + 4 * STEP, [101.0] * 20)
    e2.run(t0 + 4 * STEP + H4 + STEP)
    (cfg, st), = e2.bots()
    assert st["pending"] == [] and st["positions"] == [] and abs(st["cash"] - 10_000) < 1e-6


def test_prediction_tracker_measures_one_bar(monkeypatch, no_costs):
    rt = _rt()
    now = _now_aligned()
    bar_ts = now - now % H4 - 3 * H4                               # a 4h bar whose next bar has also closed
    bar_close = bar_ts + H4
    _put(rt, "BTC/USDT", bar_close - 8 * STEP, [100.0] * 8)
    eng = B.BotEngine(rt)
    eng.sync_configs([{"id": "p", "mode": "prediction", "timeframe": "4h", "position_pct": 10, "reset_token": "1"}])
    fc = {"available": True, "bar_ts": bar_ts, "predicted_class": 2, "predicted": "UP", "p_max": 0.5,
          "probabilities": {"up": 0.5, "down": 0.3}, "confidence": {"confidence": 0.47}, "model_version": "v",
          "edge_confirmed": False, "expected_return": 0.002}
    monkeypatch.setattr(analysis, "model_forecast", lambda *a, **k: fc)
    eng.run(bar_close + STEP)
    (cfg, st), = eng.bots()
    pos = st["positions"][0]
    assert pos["side"] == 1 and pos["exit_at"] == bar_close + H4 and abs(pos["qty"] - 10.0) < 1e-9
    eng.run(bar_close + 2 * STEP)                                   # same bar: nothing new, still open
    assert len(eng.bots()[0][1]["positions"]) == 1
    _put(rt, "BTC/USDT", bar_close, [100.0] * 15 + [103.0])         # the bar ends at 103
    eng.run(bar_close + H4 + 2 * STEP)
    t = rt.db.one("SELECT * FROM bot_trades")
    assert t["exit_reason"] == "bar closed" and t["exit"] == 103.0 and t["correct"] == 1
    assert abs(t["pnl"] - 30.0) < 1e-6
    rep = eng.report()["bots"][0]
    assert rep["stats"]["direction_accuracy"] == 1.0 and rep["stats"]["by_confidence"][0]["n"] == 1


def test_costs_are_charged_and_reset_wipes_history(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "fee_rate", 0.001)
    rt = _rt()
    now = _now_aligned()
    t0 = now - 40 * STEP
    _put(rt, "BTC/USDT", t0, [100.0] * 4)
    eng = B.BotEngine(rt)
    eng.sync_configs([_cfg()])
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: _buy())
    eng.run(t0 + 4 * STEP)
    (cfg, st), = eng.bots()
    assert st["positions"][0]["entry"] > 100.0 and st["fees_paid"] > 0
    assert st["equity"] < 10_000                                    # entering costs money immediately
    eng.sync_configs([_cfg(name="renamed")])                        # a plain edit keeps the book
    assert eng.bots()[0][1]["positions"]
    eng.sync_configs([_cfg(reset_token="2")])                       # a reset starts over
    (cfg, st), = eng.bots()
    assert st["positions"] == [] and st["cash"] == 10_000
    eng.sync_configs([])
    assert eng.bots() == []


def test_config_validation():
    c = B.clean_config({"mode": "evil", "timeframe": "1m", "starting_balance": "-5", "risk_per_trade_pct": 99,
                        "max_open_positions": "x"})
    assert c["mode"] == "decision" and c["timeframe"] == "4h" and c["starting_balance"] == 100.0
    assert c["risk_per_trade_pct"] == 10 and c["max_open_positions"] == B.DEFAULT_BOTS[0]["max_open_positions"]


def test_signal_reversal_closes_the_trade_and_flips(monkeypatch, no_costs):
    rt = _rt()
    now = _now_aligned()
    t0 = now - 40 * STEP
    _put(rt, "BTC/USDT", t0, [100.0] * 4)
    eng = B.BotEngine(rt)
    eng.sync_configs([_cfg()])
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: _buy())
    eng.run(t0 + 4 * STEP)
    _put(rt, "BTC/USDT", t0 + 4 * STEP, [(100, 101.5, 99.8, 101.0)])      # in profit, no target yet
    sell = _buy("SELL", -1, 101.0, 103.0, (99.0, 97.0, 95.0), bar_ts=9)
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: sell)
    eng.run(t0 + 6 * STEP)
    t = rt.db.one("SELECT * FROM bot_trades")
    assert t["exit_reason"] == "signal reversed (profit taken)" and t["pnl"] > 0
    (cfg, st), = eng.bots()
    assert len(st["positions"]) == 1 and st["positions"][0]["side"] == -1      # flipped short, never both at once


def test_bots_cap_same_direction_trades(monkeypatch, no_costs):
    rt = _rt(("BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"))
    for sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"):
        rt.add_symbol(sym)
    now = _now_aligned()
    t0 = now - 40 * STEP
    for sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"):
        _put(rt, sym, t0, [100.0] * 4)
    eng = B.BotEngine(rt)
    eng.sync_configs([_cfg(max_same_side=2, max_position_pct=30.0)])
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: _buy())
    eng.run(t0 + 4 * STEP)
    (cfg, st), = eng.bots()
    assert len(st["positions"]) == 2 and all(p["side"] == 1 for p in st["positions"])


def test_bot_cleanup_removes_copies_fixes_timeframes_and_tightens_trackers():
    from app import worker

    base = {"enabled": True, "mode": "prediction", "timeframe": "4h", "symbols": "all", "position_pct": 10.0}
    bots = [{"id": "prediction-a", "name": "P", **base}, {"id": "prediction-b", "name": "P copy", **base},
            {"id": "signal-1h", "name": "S", "mode": "decision", "timeframe": "4h", "reset_token": "1"},
            {"id": "futures-predict-1h", "name": "F", "mode": "prediction", "timeframe": "12h"}]
    out, notes = worker.cleanup_bots(bots)
    ids = [b["id"] for b in out]
    assert ids == ["prediction-a", "signal-1h", "futures-predict-1h"] and notes["removed_duplicates"] == ["prediction-b"]
    by = {b["id"]: b for b in out}
    assert by["signal-1h"]["timeframe"] == "1h" and by["signal-1h"]["reset_token"] == "tf-1"
    assert by["futures-predict-1h"]["timeframe"] == "1h" and by["futures-predict-1h"]["confident_only"] is True
    assert by["prediction-a"]["confident_only"] is True


def test_trades_must_beat_trading_costs():
    from app.services import analysis
    rt = analysis.round_trip_cost(True)
    assert 0.001 < rt < 0.003                                       # futures: about 0.15 % in and out
    assert analysis.round_trip_cost(False) > rt                     # spot fees are higher
    assert not analysis.beats_costs(100.0, 99.76)                   # a 0.24 % stop: target 1 barely covers costs
    assert analysis.beats_costs(100.0, 99.0)                        # a 1 % stop is fine
    assert not analysis.beats_costs(100.0, 99.5, futures=False)     # 0.5 % is too tight for spot fees


def test_a_trade_the_cap_would_shrink_below_half_its_risk_is_skipped(monkeypatch, no_costs):
    rt = _rt(("BTC/USDT",))
    rt.add_symbol("BTC/USDT")
    now = _now_aligned()
    t0 = now - 40 * STEP
    _put(rt, "BTC/USDT", t0, [100.0] * 4)
    eng = B.BotEngine(rt)
    eng.sync_configs([_cfg(max_position_pct=10.0)])           # 2 % stop, 1 % risk -> 50 % planned; cap 10 % = a fifth
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: _buy())
    eng.run(t0 + 4 * STEP)
    (cfg, st), = eng.bots()
    assert st["positions"] == []
