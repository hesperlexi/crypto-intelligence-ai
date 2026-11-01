"""Free plan: 50,000 Firestore reads a day. The engine counts its reads (Health) and keeps them low: users re-read
every USERS_EVERY_S with a narrow query in between, jobs by query, auto-trade settings only where switched on."""
from app import worker
from app.db import Database
from app.services import autopaper
from app.services.runtime import Runtime
from app.sinks import LocalSink


def _sink(tmp_path):
    return LocalSink(tmp_path / "out", Database(str(tmp_path / "x.db")))


def test_reads_are_counted_per_quota_day(tmp_path):
    s = _sink(tmp_path)
    assert s.reads_today() == 0
    s.set("users/a", {"status": "approved"})
    s.set("users/b", {"status": "pending"})
    s.get("users/a")                                   # 1
    s.list("users")                                    # 2 documents
    s.list("nothing")                                  # an empty result still costs 1
    s.query("users", "status", "==", "nobody")         # (filters a listing of 2 here; Firestore: 1 for no match)
    assert s.reads_today() == 1 + 2 + 1 + 2
    s.db.set_setting("fs_reads", {"day": "2000-01-01", "n": 999})
    assert s.reads_today() == 0                        # a new quota day starts from zero
    s.get("users/a")
    assert s.reads_today() == 1
    assert LocalSink(tmp_path / "o2").reads_today() == 0   # no database: nothing counted, never raises


def test_query_ops_and_dotted_fields(tmp_path):
    s = _sink(tmp_path)
    s.set("jobs/old", {"status": "done", "created_at": 10})
    s.set("jobs/new", {"status": "queued", "created_at": 500})
    s.set("users/p", {"payment": {"status": "submitted"}})
    s.set("users/q", {"payment": {"status": "accepted"}})
    assert [i for i, _ in s.query("jobs", "created_at", "<", 100)] == ["old"]
    assert [i for i, _ in s.query("jobs", "created_at", ">=", 100)] == ["new"]
    assert [i for i, _ in s.queued_jobs()] == ["new"]
    assert [i for i, _ in s.query("users", "payment.status", "==", "submitted")] == ["p"]


def test_users_are_reread_every_30_min_with_new_proofs_in_between(tmp_path):
    s = _sink(tmp_path)
    rt = Runtime(s.db, None)
    s.set("users/a", {"status": "approved", "payment": {"status": "accepted", "proof": "data:image/png;base64,AAAA"}})
    users, full = worker.load_users(rt, s)
    assert full and users["a"]["status"] == "approved"
    assert rt.db.get_setting("users_cache")["users"]["a"]["payment"]["proof"] == "inline"   # no image in the cache
    s.set("users/b", {"status": "pending", "payment": {"status": "submitted", "submitted_at": 5}})
    s.set("users/a", {"status": "blocked"})
    users, full = worker.load_users(rt, s)
    assert not full and "b" in users and users["a"]["status"] == "approved"      # new proof seen; the rest cached
    cache = rt.db.get_setting("users_cache")
    rt.db.set_setting("users_cache", {**cache, "at": cache["at"] - worker.USERS_EVERY_S * 1000})
    users, full = worker.load_users(rt, s)
    assert full and users["a"]["status"] == "blocked"


def test_auto_paper_reads_only_switched_on_settings_and_checks_unknown_members(tmp_path):
    s = _sink(tmp_path)
    now = 1_793_000_000_000
    s.set("users/m1", {"status": "approved", "expires_at": now + 86_400_000})
    s.set("users/late", {"status": "pending"})                         # joined after the cached list
    s.set("auto_paper/m1", {"enabled": True, "timeframes": ["1h"]})
    s.set("auto_paper/late", {"enabled": True, "timeframes": ["1h"]})
    s.set("auto_paper/off", {"enabled": False})
    row = {"symbol": "BTC/USDT", "side": 1, "price": 100.0, "grade": "A",
           "plan": {"valid": True, "entry": 100.0, "entry_zone": [99.0, 101.0], "stop": 96.0,
                    "targets": [{"price": 104.0}, {"price": 108.0}, {"price": 112.0}], "suggested_leverage": 5}}
    r = autopaper.run(s, {"1h": [row]}, now, users={"m1": {"status": "approved", "expires_at": now + 86_400_000}})
    assert r["members"] == 1 and r["opened"] == 1                       # 'late' looked up (pending): not traded
    assert s.get("paper/late_futures") is None and s.get("paper/off_futures") is None
