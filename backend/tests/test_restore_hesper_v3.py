"""The V3.0 reset is undone for the Hesper Challenge: archived runs / trades and state come back; the run started after
the reset is moved aside (kept)."""
from app import fresh_restart_v3 as R, restore_hesper_v3 as X
from tests.test_fresh_restart_v3 import Sink, _db


def test_restore(tmp_path):
    db = _db(tmp_path)
    cols = [r["name"] for r in db.query("PRAGMA table_info(hesper_runs)")]
    vals = {c: 0 for c in cols}
    vals.update({"run": 7, "started_at": 1, "result": "FAIL"})
    db.execute(f"INSERT INTO hesper_runs ({','.join(vals)}) VALUES ({','.join('?' * len(vals))})", tuple(vals.values()))
    db.set_setting("laststand_state", {"run": 2})
    rt = type("RT", (), {"db": db})()
    R.maybe_run(rt, Sink(), 1000)
    assert db.get_setting("hesper_state") is None and not db.query("SELECT * FROM hesper_runs")
    vals.update({"run": 1, "started_at": 2000})                       # a new run after the reset
    db.execute(f"INSERT INTO hesper_runs ({','.join(vals)}) VALUES ({','.join('?' * len(vals))})", tuple(vals.values()))
    db.set_setting("hesper_state", {"run": 1})
    out = X.maybe_run(rt, 3000)
    assert out["restored"]["hesper_runs"] == 1 and out["moved_aside"]["hesper_runs"] == 1
    assert [r["run"] for r in db.query("SELECT run FROM hesper_runs")] == [7]
    assert db.get_setting("hesper_state") == {"run": 3} and db.get_setting("laststand_state") == {"run": 2}
    assert db.query("SELECT run FROM archive_v3b_hesper_runs")[0]["run"] == 1
    assert X.maybe_run(rt, 4000) is None
