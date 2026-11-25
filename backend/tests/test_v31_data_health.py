"""v3.1: old source holes no longer degrade a fresh series; a coin Binance stopped trading moves to MEXC."""
import pandas as pd

from app.data.quality import check_candles

DAY = 86_400_000


def _df(ts):
    return pd.DataFrame({"ts": ts, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 1.0})


def test_old_gap_is_ok_recent_gap_is_degraded():
    now = 400 * DAY
    full = list(range(0, now, DAY))
    old_gap = [t for t in full if not (10 * DAY <= t < 20 * DAY)]        # a hole a year ago
    q = check_candles(_df(old_gap), "1d", now + DAY)
    assert q["quality_pct"] < 99 and q["recent_missing"] == 0 and q["status"] == "OK"
    recent_gap = [t for t in full if not ((now - 10 * DAY) <= t < (now - 5 * DAY))]
    q = check_candles(_df(recent_gap + [now - DAY]), "1d", now + DAY)
    assert q["recent_missing"] > 0 and q["status"] in ("OK", "DEGRADED")
    q2 = check_candles(_df([t for t in full if not ((now - 40 * DAY) <= t < (now - 5 * DAY))]), "1d", now + DAY)
    assert q2["status"] == "DEGRADED"


def test_delisted_coin_moves_to_mexc(monkeypatch):
    from app import worker
    from app.data import futures_only as F

    class DB:
        def __init__(self):
            self.s = {}
        def get_setting(self, k, d=None):
            return self.s.get(k, d)
        def set_setting(self, k, v):
            self.s[k] = v
        def one(self, sql, params):
            return {"ts": 1} if params[0] == "XMR/USDT" else {"ts": 10**13}

    class RT:
        db = DB()
        store = type("S", (), {"_cache": {}})()
        def symbols(self):
            return ["BTC/USDT", "XMR/USDT"]

    monkeypatch.setattr(F, "mexc_contract_for", lambda s, **k: "XMR_USDT" if s.startswith("XMR") else None)
    rt = RT()
    try:
        assert worker.delisted_to_mexc(rt, now=10**13) == ["XMR/USDT"]
        assert F.FUT_ONLY["XMR/USDT"] == "XMR_USDT"
        assert worker.delisted_to_mexc(rt, now=10**13 + 1000) == []          # checked at most every 6 h
    finally:
        F.FUT_ONLY.pop("XMR/USDT", None)


def test_bot_capital_topped_up_once_books_kept():
    from app.db import Database
    from app.services.bots import BotEngine, BOT_CAPITAL
    import json
    db = Database("sqlite:///:memory:")
    db.execute("INSERT INTO bots (id, config, state, reset_token, created_at) VALUES ('b1', ?, ?, 'v1', 1)",
               (json.dumps({"id": "b1", "starting_balance": 10_000.0}), json.dumps({"cash": 9_500.0, "positions": [], "pending": []})))
    eng = BotEngine.__new__(BotEngine)
    eng.db = db
    assert eng.add_capital(now=1000) == ["b1"]
    st = json.loads(db.one("SELECT state FROM bots WHERE id = 'b1'")["state"])
    assert st["cash"] == 29_500.0 and st["deposited"] == BOT_CAPITAL and st["deposits"] == [{"at": 1000, "amount": 20_000.0}]
    assert eng.add_capital(now=2000) == []                                  # once


def test_admin_close_reaches_a_bot_position_from_an_earlier_candle():
    from app.db import Database
    from app.services.bots import BotEngine
    import json
    db = Database("sqlite:///:memory:")
    pos_old = {"symbol": "ETH/USDT", "side": -1, "qty": 1, "qty_open": 1, "opened_at": 1_000, "info": {"bar_ts": 500}}
    pos_other = {"symbol": "ETH/USDT", "side": 1, "qty": 1, "qty_open": 1, "opened_at": 1_000, "info": {"bar_ts": 500}}
    pos_later = {"symbol": "ETH/USDT", "side": -1, "qty": 1, "qty_open": 1, "opened_at": 9_000, "info": {"bar_ts": 8_000}}
    db.execute("INSERT INTO bots (id, config, state, reset_token, created_at) VALUES ('b', ?, ?, 'v', 1)",
               (json.dumps({"id": "b", "mode": "decision", "timeframe": "1h"}),
                json.dumps({"cash": 1.0, "positions": [pos_old, pos_other], "pending": []})))
    db.execute("INSERT INTO bots (id, config, state, reset_token, created_at) VALUES ('c', ?, ?, 'v', 1)",
               (json.dumps({"id": "c", "mode": "decision", "timeframe": "1h"}),
                json.dumps({"cash": 1.0, "positions": [pos_later], "pending": []})))
    eng = BotEngine.__new__(BotEngine)
    eng.db = db
    sig = {"symbol": "ETH/USDT", "side": -1, "timeframe": "1h", "bar_ts": 2_000}
    assert eng.apply_close(sig, 3000.0, 5_000) == 1
    b = json.loads(db.one("SELECT state FROM bots WHERE id = 'b'")["state"])["positions"]
    assert b[0]["admin_close"] == {"at": 5_000, "price": 3000.0} and "admin_close" not in b[1]      # other side untouched
    c = json.loads(db.one("SELECT state FROM bots WHERE id = 'c'")["state"])["positions"]
    assert "admin_close" not in c[0]                                                               # opened after the close
    assert eng.apply_close(sig, 3000.0, 5_000) == 0                                                # idempotent


def test_only_calls_in_the_record_are_tradable():
    from app.db import Database
    from app.services import analysis
    db = Database("sqlite:///:memory:")
    base = {"symbol": "ETH/USDT", "timeframe": "1h", "decision": "SELL", "grade": "A", "flags": [], "setup": {"side_int": -1}}
    a = {**base, "record_status": "logged"}
    analysis.only_recorded(db, a)
    assert a["decision"] == "SELL"
    a = {**base, "record_status": "not_logged", "record_reason": "re-entry pause after a closed call"}
    analysis.only_recorded(db, a)
    assert a["decision"] == "NO TRADE" and a["grade"] is None and "NOT IN RECORD" in a["flags"] and "re-entry" in a["decision_reason"]
    a = {**base, "record_status": "already_open"}
    analysis.only_recorded(db, a)                                    # no open call on that side -> not tradable
    assert a["decision"] == "NO TRADE"
    db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, status) "
               "VALUES ('s1', 1, 'ETH/USDT', '1h', 1, 'SELL', 'SELL', 1.0, -1, 'OPEN')")
    a = {**base, "record_status": "already_open"}
    analysis.only_recorded(db, a)                                    # the record's running call: still tradable
    assert a["decision"] == "SELL"
    a = {**base, "setup": {"side_int": 1}, "decision": "BUY", "record_status": "already_open"}
    analysis.only_recorded(db, a)                                    # opposite side of the running call
    assert a["decision"] == "NO TRADE"


def test_bot_trades_not_in_the_record_close_once(monkeypatch):
    from app.db import Database
    from app.services import analysis
    monkeypatch.setattr(analysis, "DEMO_ONLY_TFS", ("1d",))
    from app.services.bots import BotEngine
    import json
    db = Database("sqlite:///:memory:")
    keep = {"symbol": "ETH/USDT", "side": -1, "qty": 1, "qty_open": 1, "opened_at": 1_000, "info": {}}
    orphan = {"symbol": "SOL/USDT", "side": -1, "qty": 1, "qty_open": 1, "opened_at": 1_000, "info": {}}
    for bid, tf, extra in (("b", "1h", {}), ("d", "1d", {}), ("e", "15m", {"demo_only": True})):
        db.execute("INSERT INTO bots (id, config, state, reset_token, created_at) VALUES (?, ?, ?, 'v', 1)",
                   (bid, json.dumps({"id": bid, "mode": "decision", "timeframe": tf, **extra}),
                    json.dumps({"cash": 1.0, "positions": [dict(keep), dict(orphan)], "pending": []})))
    db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, status) "
               "VALUES ('s1', 1, 'ETH/USDT', '1h', 1, 'SELL', 'SELL', 1.0, -1, 'OPEN')")
    eng = BotEngine.__new__(BotEngine)
    eng.db = db
    eng._price = lambda s: 100.0
    assert eng.close_unrecorded(now=5_000) == 1
    b = json.loads(db.one("SELECT state FROM bots WHERE id = 'b'")["state"])["positions"]
    assert "admin_close" not in b[0] and b[1]["admin_close"]["price"] == 100.0
    for bid in ("d", "e"):                                               # demo timeframe / demo bot untouched
        assert not any("admin_close" in x for x in json.loads(db.one("SELECT state FROM bots WHERE id = ?", (bid,))["state"])["positions"])


def test_live_forecast_is_computed_once_per_cycle(monkeypatch):
    from app.services import analysis
    calls = []
    monkeypatch.setattr(analysis.trainer, "load_bundle", lambda s, tf, db: {"created_at": 5, "version": "v1"})
    monkeypatch.setattr(analysis, "_model_forecast", lambda rt, s, tf, *a: calls.append((s, tf)) or {"available": True, "p": [1, 2]})
    class RT:
        db = None
    rt = RT()
    a = analysis.model_forecast(rt, "BTC/USDT", "1h")
    a["p"].append(3)                                     # a caller changing its copy does not change the memo
    b = analysis.model_forecast(rt, "BTC/USDT", "1h")
    assert calls == [("BTC/USDT", "1h")] and b["p"] == [1, 2]
    analysis.model_forecast(rt, "BTC/USDT", "1h", as_of=1)    # replays never use the memo
    assert len(calls) == 2


def test_slow_horizons_reuse_the_stored_forecast_until_a_new_candle_or_model():
    import pandas as pd
    from app.db import Database
    from app.services import analysis
    db = Database("sqlite:///:memory:")
    db.execute("INSERT INTO model_versions (id, symbol, timeframe, created_at, active) VALUES ('m1', 'BTC/USDT', '1d', 1, 1)")
    class RT:
        pass
    rt = RT(); rt.db = db; rt.record_error = lambda *a: None
    last = {"ts": 100}
    rt.candles = lambda s, tf: pd.DataFrame({"ts": [50, last["ts"]]})
    fc = {"available": True, "expected_return": 0.01, "distribution": {}, "probabilities": {"up": .5, "down": .3, "neutral": .2},
          "predicted": "up", "confidence": {"confidence": .6}, "edge_confirmed": True, "bar_ts": 100, "model_version": "m1"}
    analysis._fc_store_put(rt, "BTC/USDT", "1d", fc)
    assert analysis._fc_store_get(rt, "BTC/USDT", "1d")["probabilities"]["up"] == .5
    last["ts"] = 200                                              # a new daily candle closed -> computed again
    assert analysis._fc_store_get(rt, "BTC/USDT", "1d") is None
    last["ts"] = 100
    db.execute("UPDATE model_versions SET active = 0")
    db.execute("INSERT INTO model_versions (id, symbol, timeframe, created_at, active) VALUES ('m2', 'BTC/USDT', '1d', 2, 1)")
    assert analysis._fc_store_get(rt, "BTC/USDT", "1d") is None   # retrained -> computed again
    assert analysis._fc_store_get(rt, "BTC/USDT", "1h") is None    # quick timeframes are never reused
