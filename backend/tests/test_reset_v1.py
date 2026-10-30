"""v1.0.0 fresh start: removes trade/performance data once, keeps people, settings and models."""
from app import reset_v1
from app.db import now_ms
from app.db import Database
from app.services.runtime import Runtime
from app.sinks import LocalSink


class _P:
    symbols = ("BTC/USDT",)


def _setup(tmp_path, rt):
    sink = LocalSink(tmp_path / "fs", rt.db)
    sink.set("users/u1", {"status": "approved"})
    sink.set("config/bots", {"bots": [{"id": "b1", "reset_token": "v24"}]})
    sink.set("alerts/a1", {"owner_uid": "u1"})
    sink.set("paper/u1_futures", {"balance": 1})
    sink.set("paper_trades/t1", {"uid": "u1"})
    sink.set("views/bot_b1", {"x": 1})
    sink.set("views/track_record", {"x": 1})
    rt.db.set_setting("safety:BTC/USDT:1h", {"paused": True})
    rt.db.set_setting("risk_profile", {"keep": True})
    return sink


def test_reset_is_gated_and_runs_once(tmp_path, monkeypatch):
    rt = Runtime(Database("sqlite:///:memory:"), _P())
    sink = _setup(tmp_path, rt)
    assert reset_v1.maybe_run(rt, sink, now_ms()) is None           # not approved: nothing happens
    assert sink.get("paper/u1_futures") is not None
    monkeypatch.setattr(reset_v1, "APPROVED", True)
    t = now_ms()
    out = reset_v1.maybe_run(rt, sink, t)
    assert out is not None and out["firestore_docs"]["paper"] == 1
    assert sink.get("paper/u1_futures") is None and sink.get("paper_trades/t1") is None
    assert sink.get("views/bot_b1") is None
    assert sink.get("users/u1") and sink.get("alerts/a1")              # people and alert rules kept
    assert sink.get("config/bots")["bots"][0]["reset_token"] == "v1"
    assert sink.get("config/release")["version"] == "1.0.0"
    assert rt.db.get_setting("record_since") == t
    assert rt.db.get_setting("safety:BTC/USDT:1h") is None
    assert rt.db.get_setting("risk_profile") == {"keep": True}
    assert rt.db.one("SELECT COUNT(*) AS n FROM signals")["n"] == 0
    assert reset_v1.maybe_run(rt, sink, now_ms()) is None           # once only
