"""v2.8 timeframe policy: 1d/3d paused, 1h grade A only, 15m demo bot only, per-timeframe time limits."""
from app import worker
from app.db import Database, loads
from app.services import analysis, tracking as T
from app.services.bots import DEMO_15M, demo_view


def test_defaults():
    assert analysis.PAUSED_TFS == ("1d", "3d") and analysis.A_ONLY_TFS == ("1h",) and analysis.DEMO_ONLY_TFS == ("15m",)
    assert (T.horizon_for("1h"), T.horizon_for("4h"), T.horizon_for("12h"), T.horizon_for("15m")) == (200, 100, 30, 250)


def test_demo_view_only_for_demo_bots():
    a = {"status": "OK", "decision": "NO TRADE", "grade": None, "demo": {"decision": "SELL", "grade": "A"}}
    assert demo_view(a, {"demo_only": True})["decision"] == "SELL"
    assert demo_view(a, {})["decision"] == "NO TRADE"
    assert DEMO_15M["grades"] == "A" and DEMO_15M["tp1_only"] and DEMO_15M["max_hold_bars"] == 250


def test_horizon_is_stored_on_the_call_and_old_calls_keep_30():
    s = {"timeframe": "4h", "created_at": 0, "payload": None, "side": 1, "entry": 100.0, "stop": 98.0,
         "tp1": 102, "tp2": 103, "tp3": 104, "fill_status": "FILLED"}
    # no data, wall clock just past 30 x 4h: an old call (no horizon stored) is VOID, a v2.8 call is still running
    now = 31 * 4 * 3_600_000
    assert T.evaluate_signal(s, None, None, now)["status"] == "VOID"
    s2 = {**s, "payload": '{"horizon_bars": 100}'}
    assert T.evaluate_signal(s2, None, None, now).get("status") is None


def test_migration_runs_once(tmp_path):
    from app.services.runtime import Runtime
    from app.sinks import LocalSink

    class _P:
        name = "test"
    rt = Runtime(Database("sqlite:///:memory:"), _P())
    for f in ("watchlist_majors_v2", "gold_paxg_v21", "fresh_start_v23", "testing_v24", "testing_v24b", "pause_15m_v26"):
        rt.db.set_setting(f, True)
    sink = LocalSink(tmp_path)
    bots = [{"id": "futures-signal-ab-1h", "name": "Futures signal bot 1H · grades A+B", "mode": "decision",
             "timeframe": "1h", "grades": "AB", "max_hold_bars": 48},
            {"id": "futures-signal-ab-4h", "mode": "decision", "timeframe": "4h", "grades": "AB", "max_hold_bars": 42},
            {"id": "futures-signal-ab-1d", "mode": "decision", "timeframe": "1d"}]
    sink.set("config/bots", {"bots": bots, "defaults_added": [b["id"] for b in bots] + [d["id"] for d in worker.DEFAULT_BOTS]})
    notes = worker.sync_config(rt, sink)
    out = {b["id"]: b for b in sink.get("config/bots")["bots"]}
    assert set(out) == {"futures-signal-ab-1h", "futures-signal-ab-4h", DEMO_15M["id"]}
    assert out["futures-signal-ab-1h"]["grades"] == "A" and out["futures-signal-ab-1h"]["max_hold_bars"] == 200
    assert out["futures-signal-ab-1h"]["name"].endswith("grade A")
    assert out["futures-signal-ab-4h"]["grades"] == "AB" and out["futures-signal-ab-4h"]["max_hold_bars"] == 100
    assert notes["tf_policy_v28"]["added"] == [DEMO_15M["id"]]
    del out[DEMO_15M["id"]]
    sink.set("config/bots", {**sink.get("config/bots"), "bots": list(out.values())})
    worker.sync_config(rt, sink)                                   # once only: removing the demo bot sticks
    assert DEMO_15M["id"] not in {b["id"] for b in sink.get("config/bots")["bots"]}


def test_drop_inline_proofs_keeps_pending_ones(tmp_path):
    from app.sinks import LocalSink
    sink = LocalSink(tmp_path)
    users = {"a": {"payment": {"status": "accepted", "proof": "data:image/png;base64,AAA", "amount": 0}},
             "b": {"payment": {"status": "submitted", "proof": "data:image/png;base64,BBB"}},
             "c": {"payment": {"status": "accepted", "proof": None}}, "d": {}}
    for k, v in users.items():
        sink.set(f"users/{k}", v)
    assert worker.drop_inline_proofs(sink, users, 1) == 1
    a = sink.get("users/a")["payment"]
    assert a["proof"] is None and a["amount"] == 0 and a["status"] == "accepted"
    assert sink.get("users/b")["payment"]["proof"].startswith("data:image")
