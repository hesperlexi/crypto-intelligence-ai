"""v2.42: a stopped test (15m grade B) is left out of the record and disclosed with its own figures."""
import json

from app import views
from app.db import Database
from app.services.runtime import Runtime


def _rt():
    class _P:
        name = "test"
    return Runtime(Database("sqlite:///:memory:"), _P())


def _sig(rt, i, tf, grade, t, net):
    rt.db.execute("INSERT INTO signals (id, symbol, timeframe, side, decision, entry, stop, tp1, tp2, tp3, status, "
                  "created_at, closed_at, return_pct, return_net_pct, payload, bar_ts, signal, price, tp1_hit, tp2_hit, tp3_hit, stop_hit) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,0,0)",
                  (i, "BTC/USDT", tf, 1, "BUY", 100, 99, 101, 102, 103, "STOPPED" if net < 0 else "TP1", t, t + 1000,
                   net, net, json.dumps({"grade": grade}), t, "BUY", 100))


def test_excluded_and_disclosed():
    rt = _rt()
    rt.db.set_setting("record_since", 0)
    for i, (tf, g, t, n) in enumerate([("15m", "B", 2000, -1.0), ("15m", "B", 3000, -0.5), ("15m", "A", 2500, 0.8),
                                       ("1h", "B", 2500, -0.3), ("15m", "B", 9000, 0.4)]):
        _sig(rt, f"s{i}", tf, g, t, n)
    rt.db.set_setting("record_excludes", [{"timeframe": "15m", "grade": "B", "from": 1000, "to": 5000}])
    rc, rp = views.record_clause(rt)
    ids = {r["id"] for r in rt.db.query(f"SELECT id FROM signals WHERE {rc}", rp)}
    assert ids == {"s2", "s3", "s4"}                    # 15m A, 1h B and a 15m B outside the window still count
    x = views.excluded_tests(rt)[0]
    assert x["calls"] == 2 and x["losses"] == 2 and x["wins"] == 0 and x["total_net_pct"] == -1.5
