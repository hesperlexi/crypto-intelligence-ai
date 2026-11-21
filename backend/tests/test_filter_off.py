"""v2.64 safety net: the 15m trade filters stay off only while the calls they would have blocked do not lose."""
import json

from app.services import analysis as A
from .test_hesper import _rt


def _closed(db, i, win, since):
    p = {"grade": "A", "filter_bypassed": True}
    db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, confidence, price, side, entry, stop, "
               "tp1, tp2, tp3, status, payload, fill_status, return_pct) VALUES (?, ?, 'BTC/USDT', '15m', ?, 'BUY', 'BUY', 0.6, 100, 1, "
               "100, 99, 101, 102, 103, ?, ?, 'FILLED', ?)",
               (f"s{i}", since + 1000 + i, since + i * 900_000, "TP1" if win else "STOPPED", json.dumps(p), 1.0 if win else -1.0))


def test_off_until_bypassed_calls_lose(monkeypatch):
    rt = _rt()
    assert A.filter_off(rt, "15m") is True and not A.filter_off(rt, "1h")
    since = rt.db.get_setting("filter_off_since|15m")
    for i in range(12):
        _closed(rt.db, i, win=(i % 4 == 0), since=since)      # mostly losers
    rt.db.set_setting("filter_off_check|15m", {"at": 0})
    assert A.filter_off(rt, "15m") is False
    assert rt.db.get_setting("filter_off_revoked|15m")["closed"] >= 10
    assert A.filter_off(rt, "15m") is False                    # stays on for good


def test_stays_off_while_winning():
    rt = _rt()
    A.filter_off(rt, "15m")
    since = rt.db.get_setting("filter_off_since|15m")
    for i in range(12):
        _closed(rt.db, i, win=(i % 4 != 0), since=since)
    rt.db.set_setting("filter_off_check|15m", {"at": 0})
    assert A.filter_off(rt, "15m") is True
