"""Cloudflare price-alert watcher, engine side: the armed list matches watch.py's texts, audiences and tags."""
import json

from app import watch
from app.services import edge_watch as EW, hesper as H
from tests.test_watch import NOW, _call, _db, _rule

DEV = [("tokA", "member1", "a@x.com", "docA"), ("tokB", "member2", "b@x.com", "docB"), ("tokO", None, "owner@x.com", "docO")]


def test_armed_levels_carry_watch_texts_tags_and_the_right_phones():
    db = _db()
    _call(db)
    _rule(db)
    items = {i["key"]: i for i in EW.armed(db, DEV, {"owner@x.com"})}
    assert set(items) == {"c1:tp1", "c1:tp2", "c1:tp3", "c1:closed"}
    tp1 = items["c1:tp1"]
    assert tp1["tokens"] == ["tokA"] and tp1["msg"]["tag"] == "c1-tp1" and tp1["profit"] is True and tp1["level"] == 102
    assert tp1["src"] == "spot" and tp1["pair"] == "BTCUSDT" and tp1["side"] == 1
    # same text as the engine's own 30-second watch would send at that price
    msgs, _ = watch.once(db, {}, {"BTC/USDT": 102.3}, NOW)
    assert msgs[0]["body"] == tp1["msg"]["body"] and msgs[0]["tag"] == tp1["msg"]["tag"]
    assert items["c1:closed"]["profit"] is False and items["c1:closed"]["level"] == 98.0


def test_already_announced_or_unwanted_events_are_not_armed():
    db = _db()
    _call(db)
    _rule(db, events=("closed",))
    from app.services import alerts
    assert [i["key"] for i in EW.armed(db, DEV, set())] == ["c1:closed"]
    alerts._mark(db, "r1", "c1:closed", NOW)
    assert EW.armed(db, DEV, set()) == []


def test_admin_rule_goes_to_admin_phones_only():
    db = _db()
    _call(db, tp1_hit=1)
    _rule(db, uid="local", events=("closed",))
    it = EW.armed(db, DEV, {"owner@x.com"})[0]
    assert it["tokens"] == ["tokO"] and "break-even stop" in it["msg"]["body"] and it["level"] == 100.0


def test_challenge_split_admin_and_members():
    db = _db()
    db.set_setting(H.STATE_KEY, {"run": 3, "positions": [{"id": "p1", "symbol": "SOL/USDT", "side": -1, "stop": 210.0,
                                  "targets": [190.0], "tp_hit": 0}], "pending": []})
    db.set_setting("hesper_push_members", ["member2"])
    items = {i["key"]: i for i in EW.armed(db, DEV, {"owner@x.com"})}
    assert items["h:p1:tp1"]["tokens"] == ["tokO"] and items["h:p1:tp1"]["msg"]["url"] == "/rich"
    assert items["h:p1:tp1|m"]["tokens"] == ["tokB"] and items["h:p1:tp1|m"]["msg"]["url"] == "/results?tab=challenge"
    assert items["h:p1:tp1"]["msg"]["tag"] == "hesper-3-tp-SOL-1"


def test_watch_py_stays_quiet_only_while_the_cloud_watcher_is_fresh_and_error_free():
    db = _db()
    assert not watch.cloud_healthy(db, NOW)
    db.set_setting("edge_watch_status", {"at": NOW - 60_000, "armed_at": NOW - 5 * 60_000, "error": None})
    assert watch.cloud_healthy(db, NOW)
    assert not watch.cloud_healthy(db, NOW + 10 * 60_000)            # watcher silent for > 6 min
    db.set_setting("edge_watch_status", {"at": NOW - 60_000, "armed_at": NOW - 5 * 60_000, "error": "FCM_SENDER_KEY not set"})
    assert not watch.cloud_healthy(db, NOW)


def test_run_is_off_without_the_edge_key(monkeypatch):
    monkeypatch.setattr("app.sinks.edge_key", lambda: "")
    assert EW.run(None, None) == {"skipped": "off"}
