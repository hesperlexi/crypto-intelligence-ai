"""v2.69: silver (XAG/USDT, MEXC SILVER_USDT) is watch only; MEXC candles are made consistent; hourly Firestore copies."""
from app import sinks, worker
from app.data import futures_only as F
from app.engine.futures import futures_view, maintenance_rate
from app.services import analysis, autopaper, proof_checks


def test_mexc_rows_widen_high_and_low():
    d = {"time": [1, 2], "open": [10, 10], "high": [9.5, 11], "low": [10.5, 9], "close": [9.8, 10.5], "vol": [3, -1]}
    rows = F.mexc_rows(d, 2.0)
    assert rows[0] == [1000, 10.0, 10.0, 9.8, 9.8, 6.0]          # high below the open / low above the close fixed
    assert rows[1] == [2000, 10.0, 11.0, 9.0, 10.5, 0.0]          # a clean bar unchanged; negative volume -> 0


def test_silver_is_futures_only_and_watch_only():
    assert F.FUT_ONLY["XAG/USDT"] == "SILVER_USDT" and worker.SILVER == "XAG/USDT"
    assert "XAG/USDT" in analysis.WATCH_ONLY_COINS and maintenance_rate("XAG/USDT") == 0.02
    assert "silver_v269" in worker.MIGRATION_FLAGS and "WATCH ONLY" in proof_checks.FLAGS


def test_watch_gate_holds_back_every_trade_call():
    w, (d, g, why) = analysis.watch_gate("XAG/USDT", "BUY", "A")
    assert w == {"decision": "BUY", "grade": "A"} and d == "NO TRADE" and g is None and "watch only" in why
    assert analysis.watch_gate("XAG/USDT", "NO TRADE", None)[0] is None
    assert analysis.watch_gate("BTC/USDT", "SELL", "A") == (None, ("SELL", "A", ""))


def _a(**k):
    setup = {"valid": True, "ideal_entry": 40.0, "stop": 39.0, "side_int": 1, "risk_reward": 1.6,
             "targets": [{"name": "TP1", "price": 41.0, "rr": 1.0}, {"name": "TP2", "price": 41.5, "rr": 1.5},
                         {"name": "TP3", "price": 42.0, "rr": 2.0}]}
    return {"symbol": "XAG/USDT", "timeframe": "4h", "status": "OK", "price": 40.0, "decision": "NO TRADE", "grade": None,
            "setup": setup, "forecast": {"probabilities": {"up": 0.5, "down": 0.3}}, **k}


def test_card_shows_the_watch_call_but_nothing_can_trade_it():
    v = futures_view(_a(watch={"decision": "BUY", "grade": "A"}), None)
    assert v["side"] == 0 and v["watch"] == {"action": "LONG", "side": 1, "grade": "A"} and v["plan"]["valid"]
    assert autopaper.candidates({"4h": [v]}) == []                # auto-trade ignores it
    assert "watch" not in futures_view(_a(), None)


def test_firestore_copy_hourly_while_edge_healthy():
    assert sinks.EDGE_FS_EVERY_S == 3600


def test_clean_mexc_candles_once():
    from app.db import Database
    from app.services.runtime import Runtime

    class _P:
        name = "test"
    rt = Runtime(Database("sqlite:///:memory:"), _P())
    rt.store.upsert("binance", "ANTHROPIC/USDT", "15m", [[0, 10, 9.5, 9.0, 9.8, 1], [900_000, 10, 11, 9, 10.5, 1]])
    rt.store.upsert("binance", "BTC/USDT", "15m", [[0, 10, 9.5, 9.0, 9.8, 1]])     # not a MEXC coin: untouched
    assert worker.clean_mexc_candles(rt) == 1
    df = rt.store.load("binance", "ANTHROPIC/USDT", "15m")
    assert float(df["high"].iloc[0]) == 10.0 and worker.clean_mexc_candles(rt) == 0
    assert float(rt.store.load("binance", "BTC/USDT", "15m")["high"].iloc[0]) == 9.5
