"""Research replays on synthetic data (read-only; the source database is never modified)."""
import json
import sqlite3

import numpy as np

from app import research as R
from app.db import Database, dumps

M15 = 900_000
H1 = 3_600_000
T0 = 1_700_000_000_000 - (1_700_000_000_000 % H1)


def _db(path, n_signals=30, seed=3):
    db = Database(f"sqlite:///{path}")
    rng = np.random.default_rng(seed)
    px, rows = 100.0, []
    for i in range(n_signals * 40 + 200):
        op = px
        cl = op * float(np.exp(rng.normal(0.0002, 0.004)))
        rows.append(("test", "BTC/USDT", "15m", T0 + i * M15, op, max(op, cl) * 1.001, min(op, cl) * 0.999, cl, 1.0))
        px = cl
    db.executemany("INSERT INTO market_data VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    closes = {r[3]: r[7] for r in rows}
    for k in range(n_signals):
        created = T0 + k * 40 * M15
        e = closes[created - M15] if created - M15 in closes else 100.0
        side = 1 if k % 3 else -1
        risk = e * 0.006
        db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, "
                   "tp1, tp2, tp3, status, return_pct, closed_at, payload, atr) VALUES (?, ?, 'BTC/USDT', '1h', ?, 'BUY', "
                   "?, ?, ?, ?, ?, ?, ?, ?, 'TP1', 0.1, ?, ?, ?)",
                   (f"s{k}", created, created - H1, "BUY" if side > 0 else "SELL", e, side, e, e - side * risk,
                    e + side * risk, e + side * 1.5 * risk, e + side * 2.5 * risk, created + H1,
                    dumps({"grade": "A" if k % 2 else "B"}), risk / 1.5))
    db.set_setting("record_since", T0 + 10 * 40 * M15)
    return db


def test_giveback_and_compare_reports(tmp_path):
    path = tmp_path / "state.db"
    db = _db(path)
    db._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db._conn.close()                                       # the fixture's own connection flushes its WAL here
    before = path.read_bytes()
    out = tmp_path / "res" / "giveback.json"
    assert R.main(["giveback", "--db", f"sqlite:///{path}", "--out", str(out)]) == 0
    g = json.loads(out.read_text())
    assert g["ok"] and g["ever"]["all"]["n"] > 0
    assert set(g["ever"]["by_timeframe"]) == {"1h"} and set(g["ever"]["by_grade"]) == {"A", "B"}
    assert g["since_record"]["all"]["n"] < g["ever"]["all"]["n"]
    a = g["ever"]["all"]
    assert a["avg_peak_r"] >= a["avg_realised_r"] - 1e-9 and a["total_r_given_back"] >= 0
    for k, v in a["reached_then_stopped_or_break_even"].items():
        assert v["count"] <= v["reached"] <= a["n"]
    out2 = tmp_path / "res" / "compare.json"
    assert R.main(["compare", "--db", f"sqlite:///{path}", "--out", str(out2)]) == 0
    c = json.loads(out2.read_text())
    assert c["split"]["tuning"] == 21 and c["split"]["test"] == 9 and len(c["grid"]) == 27
    for part in ("tuning", "test"):
        for rule in ("old", "new"):
            assert {"n", "win_rate", "expectancy_r", "expectancy_pct", "max_drawdown_r", "profit_factor"} <= set(c[part][rule])
    assert isinstance(c["new_is_better_on_test"], bool) and "test set" in c["verdict"]
    assert path.read_bytes() == before                     # the engine state is never modified
    con = sqlite3.connect(path)
    assert "decisions" in {r[0] for r in con.execute("SELECT name FROM sqlite_master")}


def test_missing_state_writes_a_clear_json(tmp_path, capsys):
    out = tmp_path / "x.json"
    R.main(["compare", "--db", f"sqlite:///{tmp_path}/nope.db", "--out", str(out)])
    j = json.loads(out.read_text())
    assert j["ok"] is False and "not restored" in j["reason"]


def test_stats_drawdown_and_profit_factor():
    s = R.stats([1, -1, -1, 2], [1, -1, -1, 2])
    assert s["max_drawdown_r"] == 2 and s["profit_factor"] == 1.5 and s["win_rate"] == 0.5 and s["expectancy_r"] == 0.25
