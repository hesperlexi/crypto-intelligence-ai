"""Track-record rows carry the small extras the live status / details sheet needs (hit levels, time limit)."""
import json

from app.db import Database
from app.services import tracking as T


def _rt(db):
    class V:
        exchange = "binance"

        def symbols(self):
            return []
    V.db = db
    return V()


def test_track_record_rows_have_hits_and_time_limit():
    from app import views
    db = Database("sqlite:///:memory:")
    now = T.now_ms()
    ins = ("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, tp1, "
           "tp2, tp3, status, return_pct, closed_at, payload, tp1_hit, fill_status, filled_at) VALUES (?, ?, 'BTC/USDT', ?, ?, 'BUY', "
           "'BUY', 100, 1, 100, 98, 102, 103, 104, ?, ?, ?, ?, ?, ?, ?)")
    db.execute(ins, ("o4", now - 5000, "4h", 1, "OPEN", None, None, json.dumps({"horizon_bars": 100}), 1, "FILLED", now - 4000))
    db.execute(ins, ("old", now - 6000, "1h", 2, "TP1", 1.0, now - 1000, "{}", 1, "FILLED", None))     # pre-v2.8 call: 30
    tr = views.track_record(_rt(db))
    rows = {x["timeframe"]: x for x in tr["live"]["signals"]}
    o = rows["4h"]
    assert o["tp1_hit"] == 1 and o["tp2_hit"] == 0 and o["stop_hit"] == 0 and o["filled_at"] == now - 4000
    assert o["horizon_bars"] == 100 and o["expires_at"] == now - 5000 + 100 * 4 * 3_600_000
    assert rows["1h"]["horizon_bars"] == 30 and "filled_at" not in rows["1h"]
    assert "30 candles" not in tr["method"]["live"] and "100 on 4H" in tr["method"]["live"]
    # the extras stay small: 150 rows of this shape are far below Firestore's 1 MB document limit
    assert len(json.dumps(o)) * 150 < 200_000
