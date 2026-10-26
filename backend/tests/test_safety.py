"""Safety switch: pause a coin/timeframe after bad live signals, resume when its practice trades recover."""
from app.db import Database
from app.services import safety


def _put(db, table, n, status, ret, t0, sym="SOL/USDT", tf="15m"):
    for i in range(n):
        db.execute(f"INSERT INTO {table} (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, status, "
                   "return_pct) VALUES (?, ?, ?, ?, ?, 'BUY', 'BUY', 1.0, 1, ?, ?)",
                   (f"{table}{t0}{i}", t0 + i, sym, tf, t0 + i, status, ret))


def test_pauses_after_a_bad_run_and_resumes_on_recovered_practice_trades():
    db = Database("sqlite:///:memory:")
    _put(db, "signals", 12, "STOPPED", -1.0, 1000)
    assert safety.check(db, "SOL/USDT", "15m", now=5000)["paused"] is False          # too few closed yet
    _put(db, "signals", 9, "STOPPED", -1.0, 2000)
    _put(db, "signals", 4, "TP1", 0.8, 3000)                                          # 25: avg < 0, 16 % reached TP1
    st = safety.check(db, "SOL/USDT", "15m", now=6000)
    assert st["paused"] and "safety switch" in st["reason"]
    assert safety.check(db, "SOL/USDT", "1h", now=6000)["paused"] is False            # other timeframes untouched
    assert [o["timeframe"] for o in safety.overview(db)] == ["15m"]
    _put(db, "shadow_signals", 5, "TP2", 1.2, 7000)                                   # practice trades after the pause
    assert safety.check(db, "SOL/USDT", "15m", now=8000)["paused"] is True            # 5 of 8 needed
    _put(db, "shadow_signals", 3, "STOPPED", -1.0, 9000)
    st = safety.check(db, "SOL/USDT", "15m", now=10_000)
    assert st["paused"] is False and st["resumed_at"] == 10_000                       # 8 closed, avg > 0, 62 % TP1
    # after the resume only new signals count: the old losing run does not pause it again
    assert safety.check(db, "SOL/USDT", "15m", now=11_000)["paused"] is False
    assert safety.overview(db) == []


def test_a_good_record_never_pauses():
    db = Database("sqlite:///:memory:")
    _put(db, "signals", 15, "TP1", 0.5, 1000)
    _put(db, "signals", 10, "STOPPED", -1.0, 2000)                                    # 60 % TP1: fine
    assert safety.check(db, "SOL/USDT", "15m", now=5000)["paused"] is False
