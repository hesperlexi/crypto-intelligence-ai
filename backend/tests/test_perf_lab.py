"""v2.25 Performance Lab: record study in net R, splits, curve, histogram; published once, admin only."""
from app.db import Database, dumps
from app.services import perf_lab as PL
from app.services.runtime import Runtime

NOW = 1_800_000_000_000
H = 3_600_000


def _rt():
    rt = Runtime(Database("sqlite:///:memory:"), None)
    rt.db.set_setting("record_since", NOW - 100 * H)
    rows = [("a", "4h", 1, "TP2", 3.0, 3.15), ("b", "1h", -1, "STOPPED", -2.0, -2.15), ("c", "15m", -1, "TP1", 1.0, 0.85),
            ("d", "4h", 1, "OPEN", None, None)]
    for i, (sid, tf, side, st, g, n) in enumerate(rows):
        rt.db.execute(
            "INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, status, "
            "return_pct, return_net_pct, closed_at, fill_status, payload) VALUES (?, ?, 'SOL/USDT', ?, ?, 'x', 'x', 100, ?, 100, ?, "
            "?, ?, ?, ?, 'FILLED', ?)",
            (sid, NOW - (50 - i) * H, tf, i, side, 98 if side > 0 else 102, st, g, n, None if st == "OPEN" else NOW - (40 - i) * H,
             dumps({"grade": "A"})))
    return rt


def test_build_reports_net_r_by_split():
    v = PL.build(_rt(), NOW)
    assert v["calls"] == 4 and v["open"] == 1 and v["overall"]["n"] == 3
    assert v["overall"]["total_r"] == round(1.575 - 1.075 + 0.425, 2)
    assert {x["key"] for x in v["by_tf"]} == {"15m", "1h", "4h"} and v["by_tf"][0]["key"] == "15m"
    assert sum(b["n"] for b in v["histogram"]) == 3 and len(v["curve"]) == 3 and len(v["dots"]) == 3
    assert v["no_admin"]["n"] == 3 and v["admin"]["touched"] == 0


class Sink:
    lean = False

    def __init__(self):
        self.views = []

    def view(self, name, v, **kw):
        self.views.append((name, kw))


def test_publish_one_admin_document_and_skips_in_lean_mode():
    s = Sink()
    out = PL.publish(_rt(), s, NOW)
    assert out["closed"] == 3 and s.views[0][0] == "perf_lab" and s.views[0][1]["min_interval_s"] == PL.EVERY_S
    s2 = Sink()
    s2.lean = True
    assert PL.publish(_rt(), s2, NOW) == {"skipped": "lean"} and not s2.views
