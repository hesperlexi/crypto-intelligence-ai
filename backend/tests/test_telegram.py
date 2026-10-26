"""Telegram autopilot: posts are due at the right time, sent once, and nothing is sent without a token."""
from datetime import datetime, timezone

from app.db import Database
from app.services import telegram as T
from app.services.runtime import Runtime
from app.sinks import LocalSink


class Fake:
    def __init__(self):
        self.sent = []

    def post(self, url, json=None, data=None, files=None, timeout=None):
        m = dict(json or data or {})
        m["text"] = m.get("text") or m.get("caption")
        m["photo"] = bool(files)
        self.sent.append(m)

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
    sink.set("owner/telegram", {"enabled": True, "token": "x", "channel": "mychannel", "post_teaser": False,
                                "approve_first": False})
    T.run(rt, sink, WINS, None, ms(2026, 10, 27, 15), fake)                                 # before 16:00 UTC
    assert fake.sent == []
    out = T.run(rt, sink, WINS, None, ms(2026, 10, 27, 17), fake)
    assert out["sent"] == ["wins"] and fake.sent[0]["chat_id"] == "@mychannel" and "+4.9%" in fake.sent[0]["text"]
    T.run(rt, sink, WINS, None, ms(2026, 10, 27, 20), fake)                                 # same day: not again
    assert len(fake.sent) == 1


def test_weekly_on_monday_and_teaser_of_a_grade_a_signal(tmp_path):
    rt = Runtime(Database("sqlite:///:memory:"), None)
    sink, fake = LocalSink(tmp_path), Fake()
    sink.set("owner/telegram", {"enabled": True, "token": "x", "channel": "@c", "post_wins": False,
                                "approve_first": False})
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


def test_every_win_is_posted_once_as_a_picture(tmp_path):
    rt = Runtime(Database("sqlite:///:memory:"), None)
    sink, fake = LocalSink(tmp_path), Fake()
    sink.set("owner/telegram", {"enabled": True, "token": "x", "channel": "@c", "post_wins": False,
                                "post_weekly": False, "post_teaser": False, "approve_first": False})
    t0 = ms(2026, 10, 27, 9)
    T.run(rt, sink, None, None, t0, fake)                              # first run only sets the starting point
    assert fake.sent == []

    def add(i, status, ret, closed):
        rt.db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, "
                      "stop, tp1, tp2, tp3, status, closed_at, return_pct) VALUES (?, ?, 'PAXG/USDT', '1h', ?, 'BUY', 'BUY', "
                      "4000, 1, 4000, 3960, 4040, 4060, 4100, ?, ?, ?)", (f"s{i}", t0 - 3_600_000, i, status, closed, ret))
    add(1, "TP2", 1.6, t0 + 60_000)
    add(2, "STOPPED", -1.0, t0 + 120_000)                              # losses are not announced as wins
    add(3, "TP2", 0.5, t0 - 60_000)                                    # closed before the start point
    add(4, "TP1", 0.4, t0 + 90_000)                                    # target 1 only: not one of the best wins
    out = T.run(rt, sink, None, None, t0 + 300_000, fake)
    assert out["sent"] == ["win"] and fake.sent[0]["photo"] is True
    assert "GOLD LONG" in fake.sent[0]["text"] and "+1.6%" in fake.sent[0]["text"]
    T.run(rt, sink, None, None, t0 + 600_000, fake)                    # not posted twice
    assert len(fake.sent) == 1


def test_cards_render():
    from app.services import cards
    for png in (cards.win_card(T.win_item({"symbol": "BTC/USDT", "timeframe": "4h", "side": 1, "status": "TP3",
                                           "return_pct": 3.3, "entry": 1, "tp3": 2, "created_at": 0, "closed_at": 7_200_000})),
                cards.wins_card(WINS["wins"]), cards.teaser_card({"symbol": "ETH/USDT", "side": -1, "timeframe": "15m",
                                                                   "entry": 1, "stop": 2, "tp1": 0.9, "tp2": 0.8, "tp3": 0.7}, 61)):
        assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 10_000


def test_approve_first_keeps_the_card_until_the_owner_posts_it(tmp_path):
    rt = Runtime(Database("sqlite:///:memory:"), None)
    sink, fake = LocalSink(tmp_path), Fake()
    sink.set("owner/telegram", {"enabled": True, "token": "x", "channel": "@c", "post_teaser": False})   # approve_first by default
    out = T.run(rt, sink, WINS, None, ms(2026, 10, 27, 17), fake)
    assert fake.sent == [] and out["sent"] == ["wins (waiting for approval)"]
    items = sink.get(T.DRAFTS)["items"]
    assert len(items) == 1 and items[0]["png"] and "+4.9%" in items[0]["caption"]
    res = T.post_draft(sink, items[0]["id"], fake)
    assert res["sent"] and fake.sent[0]["photo"] and sink.get(T.DRAFTS)["items"] == []
    assert T.post_draft(sink, items[0]["id"], fake)["sent"] is False                 # not twice
