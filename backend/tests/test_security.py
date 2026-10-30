"""Rules template renders; job limits per person / per cycle; a member's test notification goes only to them."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app import worker
from app.config import settings
from app.db import Database
from app.services.runtime import Runtime
from app.sinks import LocalSink

ROOT = Path(__file__).resolve().parents[2]


def test_rules_template_renders_and_keeps_the_hardened_checks(tmp_path):
    import shutil
    work = tmp_path / "repo"
    (work / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "make_rules.py", work / "scripts" / "make_rules.py")
    shutil.copy(ROOT / "firestore.rules.template", work / "firestore.rules.template")
    env = {**os.environ, "ADMIN_EMAILS": "owner@example.com"}
    r = subprocess.run([sys.executable, str(work / "scripts" / "make_rules.py")], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    text = (work / "firestore.rules").read_text()
    assert "__ADMIN_EMAILS__" not in text and "'owner@example.com'" in text
    assert text.count("{") == text.count("}") and text.count("(") == text.count(")")
    assert "request.resource.data.params.uid == me()" in text                       # test_push only to yourself
    assert "request.resource.data.created_at is number" in text
    assert "resource.data.uid == me()" in text.split("match /push_tokens/{id}")[1]   # update needs existing owner
    assert "hasOnly(['uid', 'email', 'name', 'photo', 'status', 'requested_at', 'payment'])" in text
    assert "shortText(request.resource.data, 'device')" in text


class _P:
    name = "test"


def _setup(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    db = Database("sqlite:///:memory:")
    rt = Runtime(db, _P())
    sink = LocalSink(tempfile.mkdtemp(), db)
    sent = []
    sink.send_push = lambda msgs: (sent.extend(msgs), {"sent": len(msgs)})[1]
    sink.uid_for_email = lambda e: {"member@example.com": "U_MEMBER"}.get(e)
    return rt, sink, sent


def test_member_test_push_goes_to_the_job_owner_not_params_uid(monkeypatch):
    rt, sink, sent = _setup(monkeypatch)
    now = int(time.time() * 1000)
    sink.set("jobs/a", {"type": "test_push", "status": "queued", "created_at": now, "by": "member@example.com",
                        "params": {"uid": "SOMEONE_ELSE"}})
    sink.set("jobs/b", {"type": "test_push", "status": "queued", "created_at": now + 1, "by": "boss@example.com",
                        "params": {"uid": "ANY"}})
    worker.process_jobs(rt, sink, time.time() + 60)
    assert [m["uid"] for m in sent] == ["U_MEMBER", "ANY"]                     # admin may target anyone
    assert sink.get("jobs/a")["status"] == "done"


def test_job_limits_per_person_and_per_cycle(monkeypatch):
    rt, sink, sent = _setup(monkeypatch)
    monkeypatch.setattr(settings, "jobs_per_user_per_day", 3)
    monkeypatch.setattr(settings, "jobs_per_tick", 2)
    now = int(time.time() * 1000)
    for i in range(4):
        sink.set(f"jobs/m{i}", {"type": "test_push", "status": "queued", "created_at": now + i, "by": "member@example.com",
                                "params": {"uid": "U_MEMBER"}})
    for i in range(3):
        sink.set(f"jobs/x{i}", {"type": "test_push", "status": "queued", "created_at": now + 10 + i, "by": "boss@example.com",
                                "params": {}})
    worker.process_jobs(rt, sink, time.time() + 60)
    st = {f"m{i}": sink.get(f"jobs/m{i}")["status"] for i in range(4)}
    assert st == {"m0": "done", "m1": "done", "m2": "failed", "m3": "failed"}      # 2 per cycle
    assert "per run" in sink.get("jobs/m2")["error"]
    assert all(sink.get(f"jobs/x{i}")["status"] == "done" for i in range(3))       # admin exempt
    sink.set("jobs/m2", {**sink.get("jobs/m2"), "status": "queued"})
    sink.set("jobs/m3", {**sink.get("jobs/m3"), "status": "queued"})
    worker.process_jobs(rt, sink, time.time() + 60)
    assert sink.get("jobs/m2")["status"] == "done"
    assert sink.get("jobs/m3")["status"] == "failed" and "daily limit" in sink.get("jobs/m3")["error"]
