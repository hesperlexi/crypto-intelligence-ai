"""v2.31 fast price watch: early pushes from the live price, never changes anything, same tag as the engine's push."""
import json

from app import watch
from app.db import Database
from app.services import alerts, hesper as H

NOW = 1_763_000_000_000


def _db():
    db = Database("sqlite:///:memory:")
    alerts.ensure(db)
    return db


def _call(db, sid="c1", side=1, fill="FILLED", tp1_hit=0, entry=100.0, stop=98.0):
    db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, confidence, price, side, "
               "entry, stop, tp1, tp2, tp3, status, payload, fill_status, tp1_hit) VALUES (?, ?, 'BTC/USDT', '1h', ?, 'BUY', "
               "'BUY', 0.6, ?, ?, ?, ?, 102, 103.5, 105, 'OPEN', '{}', ?, ?)",
               (sid, NOW, NOW + hash(sid) % 1000, entry, side, entry, stop, fill, tp1_hit))


def _rule(db, rid="r1", uid="member1", events=("tp1", "tp2", "tp3", "closed", "entry"), state="primed"):
    db.execute("INSERT INTO alerts (id, user_id, type, symbol, timeframe, params, cooldown_s, enabled, created_at, last_state) "
               "VALUES (?, ?, 'SIGNAL_UPDATES', ?, ?, ?, 60, 1, ?, ?)",
               (rid, uid, alerts.ALL_SYMBOLS, alerts.ALL_TFS, json.dumps({"events": list(events)}), NOW, state))


def test_tp_touch_goes_to_the_rule_owner_once_with_the_engines_tag():
    db = _db()
    _call(db)
    _rule(db)
    msgs, sent = watch.once(db, {}, {"BTC/USDT": 102.3}, NOW)
    assert len(msgs) == 1 and msgs[0]["uid"] == "member1" and msgs[0]["tag"] == "c1-tp1"
    assert "touched TP1" in msgs[0]["body"]
    again, _ = watch.once(db, sent, {"BTC/USDT": 102.4}, NOW + 30_000)
    assert again == []                                         # never twice


def test_nothing_when_engine_already_announced_or_event_off_or_price_away():
    db = _db()
    _call(db)
    _rule(db, events=("closed",))
    assert watch.once(db, {}, {"BTC/USDT": 102.3}, NOW)[0] == []      # TP1 not wanted by this rule
    assert watch.once(db, {}, {"BTC/USDT": 99.0}, NOW)[0] == []       # between stop and TP1
    alerts._mark(db, "r1", "c1:closed", NOW)
    assert watch.once(db, {}, {"BTC/USDT": 97.0}, NOW)[0] == []       # the engine already sent it


def test_break_even_stop_after_tp1_and_pending_entry():
    db = _db()
    _call(db, tp1_hit=1)
    _call(db, sid="c2", fill="PENDING", entry=99.0, stop=97.0)
    _rule(db, uid="local")                                     # the admin's rule: no uid
    msgs, _ = watch.once(db, {}, {"BTC/USDT": 98.9}, NOW)
    bodies = {m["tag"]: m["body"] for m in msgs}
    assert "break-even stop" in bodies["c1-closed"] and "reached the entry" in bodies["c2-entry"]
    assert all("uid" not in m for m in msgs)


def test_hesper_touches_admin_and_members():
    db = _db()
    db.set_setting(H.STATE_KEY, {"run": 3, "positions": [{"id": "p1", "symbol": "SOL/USDT", "side": -1, "stop": 210.0,
                                  "targets": [190.0, 185.0, 180.0], "tp_hit": 0}], "pending": []})
    db.set_setting("hesper_push_members", ["m9"])
    msgs, sent = watch.once(db, {}, {"SOL/USDT": 189.5}, NOW)
    assert [m.get("uid") for m in msgs] == [None, "m9"] and msgs[0]["tag"] == "hesper-3-tp-SOL-1"
    assert msgs[0]["url"] == "/rich" and msgs[1]["url"] == "/results?tab=challenge"
    # same tag as the engine's own confirmed push for that event
    assert H.push_messages([{"type": "tp", "symbol": "SOL/USDT", "tp": 1, "run": 3}])[0]["tag"] == msgs[0]["tag"]
    assert watch.once(db, sent, {"SOL/USDT": 189.0}, NOW)[0] == []
    db.set_setting(H.STATE_KEY, {"run": 3, "idle": True, "positions": [], "pending": []})
    assert watch.once(db, {}, {"SOL/USDT": 150.0}, NOW)[0] == []


def test_read_only_connection(tmp_path):
    path = tmp_path / "e.db"
    db = Database(f"sqlite:///{path}")
    alerts.ensure(db)
    _call(db)
    ro = watch.ReadOnlyDB(str(path))
    assert ro.query("SELECT id FROM signals")[0]["id"] == "c1"
    try:
        ro.c.execute("DELETE FROM signals")
        raise AssertionError("must be read-only")
    except Exception as exc:
        assert "readonly" in str(exc).lower()
