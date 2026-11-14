"""v2.32: bStocks coins get no new calls and leave the watchlist only once nothing runs on them."""
import json

from app import worker
from app.db import Database
from app.services import analysis, hesper as H
from app.services.runtime import Runtime

NOW = 1_763_000_000_000


class _P:
    name = "test"


class _Sink:
    def __init__(self):
        self.docs = {}

    def set(self, path, doc, merge=False):
        self.docs[path] = doc


def _rt():
    return Runtime(Database("sqlite:///:memory:"), _P())


def _doc():
    return {"symbols": [{"symbol": "BTC/USDT", "pinned": True}, {"symbol": "MSTRB/USDT"}, {"symbol": "SPCXB/USDT"}]}


def _open_call(db, sym):
    db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, confidence, price, side, "
               "entry, stop, tp1, tp2, tp3, status, payload, fill_status) VALUES ('x', ?, ?, '1h', ?, 'BUY', 'BUY', 0.6, "
               "100, 1, 100, 98, 102, 103, 104, 'OPEN', '{}', 'FILLED')", (NOW, sym, NOW))


def test_waits_for_running_trades_then_removes_once():
    rt, sink = _rt(), _Sink()
    _open_call(rt.db, "MSTRB/USDT")
    rt.db.set_setting(H.STATE_KEY, {"positions": [{"symbol": "SPCXB/USDT"}], "pending": []})
    doc, gone = worker.retire_coins(rt, sink, _doc())
    assert gone == [] and len(doc["symbols"]) == 3 and not rt.db.get_setting(analysis.RETIRE_FLAG)
    rt.db.execute("UPDATE signals SET status = 'TP3'")
    doc, gone = worker.retire_coins(rt, sink, doc)
    assert gone == ["MSTRB/USDT"] and [i["symbol"] for i in sink.docs["config/watchlist"]["symbols"]] == ["BTC/USDT", "SPCXB/USDT"]
    rt.db.set_setting(H.STATE_KEY, {"positions": [], "pending": []})
    doc, gone = worker.retire_coins(rt, sink, doc)
    assert gone == ["SPCXB/USDT"] and rt.db.get_setting(analysis.RETIRE_FLAG) is True
    assert worker.retire_coins(rt, sink, _doc()) == (_doc(), [])        # done: an admin may re-add them later


def test_bot_position_keeps_the_coin():
    rt, sink = _rt(), _Sink()
    rt.db.execute("INSERT INTO bots (id, config, state, created_at) VALUES ('b', '{}', ?, ?)",
                  (json.dumps({"positions": [], "pending": [{"symbol": "MSTRB/USDT"}]}), NOW))
    assert worker.coin_busy(rt, "MSTRB/USDT") and not worker.coin_busy(rt, "SPCXB/USDT")


def test_flag_is_a_migration_flag():
    assert analysis.RETIRE_FLAG in worker.MIGRATION_FLAGS
    assert set(analysis.RETIRING_COINS) == {"MSTRB/USDT", "SPCXB/USDT"}
