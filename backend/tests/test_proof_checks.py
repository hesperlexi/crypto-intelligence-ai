"""v2.24 proof checks: blocked calls logged + followed privately; live AI calibration per timeframe."""
from app.db import Database, dumps, new_id
from app.services import proof_checks as P

NOW = 1_800_000_000_000
DAY = 86_400_000


def _db():
    return Database("sqlite:///:memory:")


def _a(sym="SOL/USDT", tf="4h", bar=1, price=100.0):
    setup = {"valid": True, "side_int": -1, "ideal_entry": 100.0, "stop": 102.0, "atr": 1.0, "risk_reward": 1.6,
             "expectancy_r": 0.1,
             "targets": [{"price": 98.0, "rr": 1.0, "probability": 0.55}, {"price": 96.5, "rr": 1.75, "probability": 0.4},
                         {"price": 95.0, "rr": 2.5, "probability": 0.3}]}
    return {"symbol": sym, "timeframe": tf, "bar_ts": bar, "price": price, "signal": {"signal": "SELL"},
            "decision": "NO TRADE", "forecast": {}}, setup


def test_blocking_flag_is_the_first_measured_filter():
    assert P.blocking_flag(["NEWS RISK"]) == "NEWS RISK"
    assert P.blocking_flag(["AGAINST BIGGER TREND", "NEWS RISK"]) == "AGAINST BIGGER TREND"
    assert P.blocking_flag(["CHECK UNAVAILABLE", "GRADE A ONLY"]) is None      # fail-safe, not a filter
    assert P.blocking_flag(["PAUSED"]) is None                                 # safety switch has its own shadow log
    assert P.blocking_flag([]) is None


def test_rejected_call_is_logged_once_and_never_in_signals():
    db = _db()
    a, setup = _a()
    assert P.log_rejected(db, a, "SELL", setup, "B", "GRADE A ONLY", "grade A only", now=NOW)
    assert not P.log_rejected(db, {**a, "bar_ts": 2}, "SELL", setup, "B", "GRADE A ONLY", "x", now=NOW)   # one open
    r = db.one("SELECT * FROM rejected_signals")
    assert r["reject_flag"] == "GRADE A ONLY" and r["status"] == "OPEN" and r["side"] == -1 and r["entry"] == 100.0
    assert db.one("SELECT COUNT(*) AS n FROM signals")["n"] == 0


def test_not_logged_while_the_record_has_a_call_running():
    db = _db()
    db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, status) "
               "VALUES ('s1', ?, 'SOL/USDT', '4h', 0, 'SELL', 'SELL', 100, -1, 'OPEN')", (NOW,))
    a, setup = _a()
    assert not P.log_rejected(db, a, "SELL", setup, "A", "NEWS RISK", "news", now=NOW)


def test_board_says_whether_a_filter_saved_money():
    db = _db()
    for i in range(12):
        a, setup = _a(sym=f"C{i}/USDT")
        P.log_rejected(db, a, "SELL", setup, "A", "VOLUME WALL AHEAD", "wall", now=NOW)
    # 12 blocked calls, all would have been stopped out (-2 % on a 2 % risk = -1R gross)
    db.execute("UPDATE rejected_signals SET status = 'STOPPED', return_pct = -2.0, return_net_pct = -2.15, closed_at = ?",
               (NOW + DAY,))
    b = P.rejected_board(db)
    f = b["by_flag"][0]
    assert f["flag"] == "VOLUME WALL AHEAD" and f["closed"] == 12 and f["verdict"] == "saving money"
    assert round(f["avg_r"], 3) == -1.075 and b["would_have_lost"] == 12


def _pred(db, tf, created, p, actual, pred_cls):
    pid = new_id()
    db.execute("INSERT INTO predictions (id, created_at, symbol, timeframe, bar_ts, target_ts, model_version_id, price, "
               "p_down, p_neutral, p_up, predicted_class, neutral_band) VALUES (?, ?, 'BTC/USDT', ?, ?, ?, 'm', 1, ?, ?, ?, ?, 0.001)",
               (pid, created, tf, created, created, p[0], p[1], p[2], pred_cls))
    db.execute("INSERT INTO prediction_outcomes (prediction_id, resolved_at, actual_return, actual_class, correct) "
               "VALUES (?, ?, 0, ?, ?)", (pid, created, actual, int(actual == pred_cls)))


def test_calibration_flags_drift_when_the_last_week_is_worse():
    db = _db()
    # month before: confident and right; last week: confident and wrong
    for i in range(300):
        up = bool(i % 4)
        _pred(db, "1h", NOW - 20 * DAY + i * 60_000, (0.05, 0.05, 0.9) if up else (0.6, 0.1, 0.3), 2 if up else 0, 2 if up else 0)
    for i in range(200):
        _pred(db, "1h", NOW - 2 * DAY + i * 60_000, (0.1, 0.2, 0.7), 0 if i % 4 else 2, 2)
    c = P.calibration(db, NOW)
    tf = c["timeframes"][0]
    assert tf["timeframe"] == "1h" and tf["state"] == "drift" and tf["last7"]["skill"] < 0 < tf["prior30"]["skill"]
    assert c["warnings"] and c["warnings"][0].startswith("1h")


def test_tp1_expected_vs_actual_and_cached_checks():
    db = _db()
    for i in range(4):
        db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, status, "
                   "tp1_hit, return_pct, payload) VALUES (?, ?, 'SOL/USDT', '4h', ?, 'SELL', 'SELL', 100, -1, ?, ?, 1, ?)",
                   (f"s{i}", NOW, i, "TP1" if i < 2 else "STOPPED", 1 if i < 2 else 0, dumps({"expect": {"p_tp": [0.6, 0.4, 0.3]}})))
    t = P.tp1_check(db)["timeframes"][0]
    assert t["n"] == 4 and t["expected"] == 0.6 and t["actual"] == 0.5
    v1 = P.checks(db, NOW)
    v2 = P.checks(db, NOW + 60_000)
    assert v1["at"] == v2["at"] == NOW and "rejected" in v1 and "calibration" in v1
