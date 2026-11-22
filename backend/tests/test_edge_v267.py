"""v2.67 edge views: member views also go to the Cloudflare Worker; Firestore keeps a slower copy only while the edge works."""
import time

from app import sinks
from app.db import Database
from app.sinks import LocalSink


def _sink(tmp_path, monkeypatch, fail=False):
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT", '{"x": 1}')
    db = Database(f"sqlite:///{tmp_path}/t.db")
    s = LocalSink(tmp_path / "out", db)
    posted = []

    def post(rows):
        if fail:
            raise RuntimeError("down")
        posted.extend(rows)
    monkeypatch.setattr(s, "_edge_post", post)
    monkeypatch.setattr(s, "_edge_probe", lambda row: None)
    return s, posted


def test_edge_sends_member_views_only(tmp_path, monkeypatch):
    s, posted = _sink(tmp_path, monkeypatch)
    s.view("dashboard_4h", {"a": 1})
    s.view("analysis_BTCUSDT_4h", {"b": 1})
    s.view("guardian", {"admin": 1})            # admin-only: never to the edge
    s.view("alerts_u_abc", {"mine": 1})          # per person: never to the edge
    s.flush()
    names = {r["name"] for r in posted}
    assert names == {"dashboard_4h", "analysis_BTCUSDT_4h"}
    assert all(set(r) == {"name", "json", "at", "etag"} for r in posted)
    assert s.edge_healthy()
    # unchanged -> not sent again
    posted.clear()
    s.view("dashboard_4h", {"a": 1})
    s.flush()
    assert posted == []


def test_firestore_copy_slower_while_edge_healthy(tmp_path, monkeypatch):
    s, posted = _sink(tmp_path, monkeypatch)
    s.view("track_record", {"v": 1})
    assert s.flush() == 1                        # first publish goes to Firestore too
    s.view("track_record", {"v": 2})
    assert s.flush() == 0                        # within EDGE_FS_EVERY_S: edge only
    assert posted[-1]["name"] == "track_record" and '"v":2' in posted[-1]["json"].replace(" ", "")
    s.view("track_record", {"v": 3}, core={"call": 1})
    assert s.flush() == 1                        # a changed call (core) still goes to Firestore at once


def test_edge_failure_keeps_firestore_live(tmp_path, monkeypatch):
    s, posted = _sink(tmp_path, monkeypatch, fail=True)
    s.view("track_record", {"v": 1})
    s.flush()
    s.view("track_record", {"v": 2})
    assert s.flush() == 1                        # edge down -> every change to Firestore as before
    assert not s.edge_healthy()
    assert s.edge_status().get("last_error")


def test_edge_off_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT", raising=False)
    db = Database(f"sqlite:///{tmp_path}/t.db")
    s = LocalSink(tmp_path / "out", db)
    s.view("dashboard_4h", {"a": 1})
    assert s.edge_pending == {} and s.flush() == 1


def test_edge_re_matches_frontend_and_worker():
    import pathlib, re
    root = pathlib.Path(__file__).resolve().parents[2]
    w = (root / "chat-worker/src/index.ts").read_text()
    f = (root / "frontend/src/lib/edge.ts").read_text()
    pat = sinks.EDGE_RE.pattern
    assert pat in w.replace("\\\\", "\\") or pat.strip("^$") in w
    assert pat.strip("^$") in f
