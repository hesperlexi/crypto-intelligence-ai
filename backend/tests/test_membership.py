"""Memberships: who is active, alerts of lapsed members pause, admins hear about proofs, members get reminders."""
from app.services import membership as M

DAY = M.DAY_MS
NOW = 1_800_000_000_000


def test_is_active():
    assert M.is_active(None, NOW)                                            # admins have no record
    assert M.is_active({"status": "approved"}, NOW)                          # approved before memberships existed
    assert M.is_active({"status": "approved", "expires_at": NOW + DAY}, NOW)
    assert not M.is_active({"status": "approved", "expires_at": NOW - 1}, NOW)
    assert not M.is_active({"status": "pending"}, NOW)
    assert not M.is_active({"status": "blocked", "expires_at": NOW + DAY}, NOW)


def test_proof_and_reminder_notifications_are_sent_once():
    users = {
        "a": {"status": "pending", "email": "a@x.com", "payment": {"status": "submitted", "submitted_at": NOW - 5, "months": 3, "amount": 30, "currency": "USDT"}},
        "b": {"status": "approved", "email": "b@x.com", "expires_at": NOW + 2.5 * DAY},
        "c": {"status": "approved", "email": "c@x.com", "expires_at": NOW + 20 * DAY},
    }
    msgs, seen = M.notifications(users, {}, NOW)
    assert [m["title"] for m in msgs] == ["Payment proof received", "Membership ending soon"]
    assert "uid" not in msgs[0] and msgs[1]["uid"] == "b"                    # proofs -> admins, reminder -> member
    assert "30 USDT for 3 months" in msgs[0]["body"]
    again, seen = M.notifications(users, seen, NOW + 60_000)
    assert again == []
    last_day, _ = M.notifications(users, seen, NOW + 2 * DAY)                # the last-day reminder comes separately
    assert [m["uid"] for m in last_day] == ["b"]


def test_worker_pauses_alerts_of_lapsed_members(tmp_path):
    from app.db import Database
    from app.services.runtime import Runtime
    from app.sinks import LocalSink
    from app import worker

    class _P:
        name = "test"

    rt = Runtime(Database("sqlite:///:memory:"), _P())
    sink = LocalSink(tmp_path)
    now = worker.now_ms()
    sink.set("users/old", {"status": "approved", "email": "o@x.com", "expires_at": now - DAY})
    sink.set("users/ok", {"status": "approved", "email": "k@x.com", "expires_at": now + 30 * DAY})
    for aid, owner in (("a1", "old"), ("a2", "ok"), ("a3", "admin-uid")):
        sink.set(f"alerts/{aid}", {"type": "TRADE_SETUP", "symbol": "BTC/USDT", "timeframe": "4h", "owner_uid": owner, "enabled": True})
    notes = worker.sync_config(rt, sink)
    enabled = {r["id"]: r["enabled"] for r in rt.db.query("SELECT id, enabled FROM alerts")}
    assert enabled == {"a1": 0, "a2": 1, "a3": 1}
    assert notes["inactive_members"] == 1
