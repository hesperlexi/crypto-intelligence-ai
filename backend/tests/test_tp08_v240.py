"""v2.40: the 15m TP1-0.8R test bot is added once and keeps its tp1_r through config cleaning."""
from app import worker
from app.db import Database
from app.services import bots
from app.services.runtime import Runtime
from app.sinks import LocalSink


def test_flag_listed_and_config_kept():
    assert "test_tp08_v240" in worker.MIGRATION_FLAGS
    c = bots.clean_config(dict(bots.TEST_TP08_15M))
    assert c["tp1_r"] == 0.8 and c["grades"] == "A" and c["timeframe"] == "15m" and c["market"] == "futures"


def test_added_once(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_BOT_TP08", "1")
    class _P:
        name = "test"
    rt = Runtime(Database("sqlite:///:memory:"), _P())
    sink = LocalSink(tmp_path)
    base = {"id": "futures-signal-ab-15m", "mode": "decision", "timeframe": "15m", "grades": "A", "market": "futures",
            "leverage": 20.0}
    sink.set("config/bots", {"bots": [base]})
    rt.db.set_setting("test_tp08_v240", False)
    flags = [f for f in worker.MIGRATION_FLAGS if f != "test_tp08_v240"]
    for f in flags:
        rt.db.set_setting(f, True)
    worker.sync_config(rt, sink)
    ids = [b["id"] for b in sink.get("config/bots")["bots"]]
    assert ids.count("futures-test-tp08-15m") == 1
    sink.set("config/bots", {"bots": [base]})          # removed by the admin -> stays removed
    worker.sync_config(rt, sink)
    assert "futures-test-tp08-15m" not in [b["id"] for b in sink.get("config/bots")["bots"]]
