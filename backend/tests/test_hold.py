"""v2.22 admin Hold: withdrawn within the window, moved (not deleted), followed privately, counted publicly."""
import pytest

from app.db import Database, dumps
from app.services import hold as H
from app.services.runtime import Runtime

NOW = 1_800_000_000_000


def _rt():
    rt = Runtime(Database("sqlite:///:memory:"), None)
    rt.db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, "
                  "tp1, tp2, tp3, status, fill_status, payload) VALUES ('s1', ?, 'SOL/USDT', '1h', 1, 'SELL', 'SELL', 100, -1, "
                  "100, 102, 98, 97, 95, 'OPEN', 'FILLED', ?)", (NOW - 5 * 60_000, dumps({"grade": "A"})))
    return rt


class Sink:
    def __init__(self):
        self.pushed = []

    def send_push(self, m):
        self.pushed += m
        return {"sent": len(m)}


def test_hold_moves_the_call_and_tells_members(monkeypatch):
    rt = _rt()
    monkeypatch.setattr("app.services.adjust.latest_price", lambda rt, s: 99.5)
    sink = Sink()
    out = H.hold(rt, {"signal_id": "s1", "note": "news in 10 min"}, "boss@x.com", sink, now=NOW)
    assert out["ok"] and rt.db.one("SELECT id FROM signals WHERE id = 's1'") is None
    h = rt.db.one("SELECT * FROM held_signals WHERE id = 's1'")
    assert h["status"] == "OPEN" and h["held_by"] == "boss@x.com" and h["hold_note"] == "news in 10 min"
    assert sink.pushed and "withdrawn" in sink.pushed[0]["title"]
    assert H.held_open(rt.db, "SOL/USDT", "1h") and H.withdrawn_count(rt.db, 0) == 1


def test_hold_only_inside_the_window_and_with_a_note():
    rt = _rt()
    with pytest.raises(H.HoldError):
        H.hold(rt, {"signal_id": "s1", "note": "late"}, "a", None, now=NOW + 30 * 60_000)
    with pytest.raises(H.HoldError):
        H.hold(rt, {"signal_id": "s1", "note": ""}, "a", None, now=NOW)
    with pytest.raises(H.HoldError):
        H.hold(rt, {"signal_id": "nope", "note": "abc"}, "a", None, now=NOW)


def test_scoreboard_counts_what_held_calls_would_have_made():
    rt = _rt()
    H.hold(rt, {"signal_id": "s1", "note": "abc"}, "a", None, now=NOW)
    rt.db.execute("UPDATE held_signals SET status = 'STOPPED', return_pct = -2.0, return_net_pct = -2.15, closed_at = ? "
                  "WHERE id = 's1'", (NOW + 3_600_000,))
    sb = H.scoreboard(rt.db)
    assert sb["n"] == 1 and sb["closed"] == 1 and sb["would_have_lost"] == 1 and sb["total_r"] < 0
