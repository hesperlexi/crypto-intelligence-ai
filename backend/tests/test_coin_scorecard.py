"""v2.33 coin scorecard: categories from the real record (net), suggestions never for pinned coins."""
from app.db import Database
from app.services import coin_scorecard as CS
from app.services.runtime import Runtime

DAY = 86_400_000
NOW = 1_763_000_000_000


class _P:
    name = "test"


def _rt():
    rt = Runtime(Database("sqlite:///:memory:"), _P())
    rt.db.set_setting("record_since", NOW - 20 * DAY)
    return rt


_n = [0]


def _sig(db, sym, ret, status="TP1", fill="FILLED", tf="1h"):
    _n[0] += 1
    db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, confidence, price, side, "
               "entry, stop, tp1, tp2, tp3, status, payload, fill_status, return_pct, return_net_pct) VALUES "
               "(?, ?, ?, ?, ?, 'BUY', 'BUY', 0.6, 100, 1, 100, 98, 102, 103, 104, ?, '{}', ?, ?, ?)",
               (f"s{_n[0]}", NOW - 5 * DAY + _n[0], sym, tf, NOW - 5 * DAY + _n[0], status, fill, ret, ret))


def test_categories_and_suggestions():
    rt = _rt()
    for r in (1.0, 0.8, -0.5):
        _sig(rt.db, "ETH/USDT", r)
    for r in (-1.0, -0.9, -1.1, 0.2, -0.7, -0.8):
        _sig(rt.db, "DOGE/USDT", r, status="STOPPED")
    _sig(rt.db, "LTC/USDT", 0.5)
    wl = [{"symbol": "BTC/USDT", "pinned": 1, "added_at": 0}, {"symbol": "ETH/USDT", "pinned": 0, "added_at": 0},
          {"symbol": "DOGE/USDT", "pinned": 0, "added_at": 0}, {"symbol": "LTC/USDT", "pinned": 0, "added_at": 0},
          {"symbol": "ADA/USDT", "pinned": 0, "added_at": 0}, {"symbol": "NEW/USDT", "pinned": 0, "added_at": NOW - DAY}]
    out = CS.build(rt, wl, NOW)
    cat = {c["symbol"]: c["category"] for c in out["coins"]}
    assert cat == {"ETH/USDT": "best", "DOGE/USDT": "losing", "LTC/USDT": "early", "BTC/USDT": "quiet",
                   "ADA/USDT": "quiet", "NEW/USDT": "early"}
    assert set(out["suggest_remove"]) == {"ADA/USDT", "DOGE/USDT"}          # BTC pinned, NEW too new
    eth = next(c for c in out["coins"] if c["symbol"] == "ETH/USDT")
    assert eth["closed"] == 3 and eth["wins"] == 2 and eth["total_net_pct"] == 1.3
    assert out["coins"][0]["symbol"] == "ETH/USDT"


def test_outside_the_record_is_ignored():
    rt = _rt()
    rt.db.set_setting("record_since", NOW)                    # record restarted after these calls
    _sig(rt.db, "ETH/USDT", 1.0)
    out = CS.build(rt, [{"symbol": "ETH/USDT", "pinned": 0, "added_at": 0}], NOW)
    assert out["coins"][0]["calls"] == 0
