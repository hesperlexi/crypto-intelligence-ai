"""v2.65: ANT/USDT (added by mistake) is replaced by the Anthropic pre-IPO perpetual, once."""
from app import worker
from app.data.futures_only import FUT_ONLY
from app.db import Database
from app.services.runtime import Runtime
from app.sinks import LocalSink


class _P:
    name = "test"


def test_ant_replaced_by_anthropic_once(tmp_path, monkeypatch):
    monkeypatch.setenv("ADD_MSTR", "1")
    assert FUT_ONLY["ANTHROPIC/USDT"] == "ANTHROPIC_USDT"
    rt = Runtime(Database("sqlite:///:memory:"), _P())
    for f in worker.MIGRATION_FLAGS:
        if f != "anthropic_v265":
            rt.db.set_setting(f, True)
    rt.db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side) "
                  "VALUES ('s1', 1, 'BTC/USDT', '4h', 1, 'BUY', 'BUY', 100, 1)")
    sink = LocalSink(tmp_path)
    sink.set("config/watchlist", {"symbols": [{"symbol": "BTC/USDT", "pinned": True}, {"symbol": "ANT/USDT", "pinned": False}]})
    worker.sync_config(rt, sink)
    syms = [i["symbol"] for i in sink.get("config/watchlist")["symbols"]]
    assert "ANT/USDT" not in syms and "ANTHROPIC/USDT" in syms and "BTC/USDT" in syms
    sink.set("config/watchlist", {"symbols": [{"symbol": "BTC/USDT", "pinned": True}]})     # removing it later sticks
    worker.sync_config(rt, sink)
    assert [i["symbol"] for i in sink.get("config/watchlist")["symbols"]] == ["BTC/USDT"]
