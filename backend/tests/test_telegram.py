"""Telegram autopilot: posts are due at the right time, sent once, and nothing is sent without a token."""
from datetime import datetime, timezone

from app.db import Database
from app.services import telegram as T
from app.services.runtime import Runtime
from app.sinks import LocalSink


class Fake:
    def __init__(self):
        self.sent = []

    def post(self, url, json=None, timeout=None):
        self.sent.append(json)

        class R:
            status_code = 200

            def json(self_inner):
                return {"ok": True}
        return R()


def ms(y, mo, d, h):
    return int(datetime(y, mo, d, h, tzinfo=timezone.utc).timestamp() * 1000)


WINS = {"period": "today", "wins": [{"symbol": "BTC/USDT", "timeframe": "4h", "side": "LONG", "entry": 67240.0, "status": "TP2",
                                     "return_pct": 4.9}]}


def test_posts_wins_once_at_the_evening_slot(tmp_path):
    rt = Runtime(Database("sqlite:///:memory:"), None)
    sink, fake = LocalSink(tmp_path), Fake()
    assert T.run(rt, sink, WINS, None, ms(2026, 10, 27, 17), fake)["enabled"] is False      # not configured
    sink.set("owner/telegram", {"enabled": True, "token": "x", "channel": "mychannel", "post_teaser": False})
    T.run(rt, sink, WINS, None, ms(2026, 10, 27, 15), fake)                                 # before 16:00 UTC
    assert fake.sent == []
    out = T.run(rt, sink, WINS, None, ms(2026, 10, 27, 17), fake)
    assert out["sent"] == ["wins"] and fake.sent[0]["chat_id"] == "@mychannel" and "+4.9%" in fake.sent[0]["text"]
    T.run(rt, sink, WINS, None, ms(2026, 10, 27, 20), fake)                                 # same day: not again
    assert len(fake.sent) == 1


def test_weekly_on_monday_and_teaser_of_a_grade_a_signal(tmp_path):
    rt = Runtime(Database("sqlite:///:memory:"), None)
    sink, fake = LocalSink(tmp_path), Fake()
    sink.set("owner/telegram", {"enabled": True, "token": "x", "channel": "@c", "post_wins": False})
    now = ms(2026, 10, 26, 8)                                                                # a Monday
    rt.db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, "
                  "tp1, tp2, tp3, status, payload) VALUES ('s', ?, 'SOL/USDT', '1h', 1, 'BUY', 'BUY', 180, 1, 180, 176, 184, 188, "
                  "194, 'OPEN', '{\"grade\": \"A\"}')", (now - 2 * 3_600_000,))
    weekly = {"reports": [{"complete": False}, {"complete": True, "closed": 4, "wins": 3, "losses": 1, "win_rate": 0.75,
                                                  "total_return_pct": 6.2, "week_start": now - 8 * 86_400_000,
                                                  "week_end": now - 86_400_000, "best": WINS["wins"]}]}
    out = T.run(rt, sink, None, weekly, now, fake)
    assert sorted(out["sent"]) == ["teaser", "weekly"]
    texts = " ".join(m["text"] for m in fake.sent)
    assert "3 wins / 1 losses" in texts and "SOL/USDT LONG" in texts and "grade A" in texts
