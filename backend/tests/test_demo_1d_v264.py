"""v2.64: 1d demo-only again - its public bots go, one grade-A 1d demo bot comes back, once."""
from app import worker
from app.db import Database
from app.services import analysis
from app.services.runtime import Runtime
from app.sinks import LocalSink


class _P:
    name = "test"


def test_public_1d_bot_swapped_for_demo_once(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis, "DEMO_ONLY_TFS", ("1d",))
    rt = Runtime(Database("sqlite:///:memory:"), _P())
    for f in worker.MIGRATION_FLAGS:
        if f != "demo_1d_v264":
            rt.db.set_setting(f, True)
    rt.db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side) "
                  "VALUES ('s1', 1, 'BTC/USDT', '4h', 1, 'BUY', 'BUY', 100, 1)")
    sink = LocalSink(tmp_path)
    sink.set("config/bots", {"bots": [{"id": "futures-signal-ab-1d", "timeframe": "1d", "market": "futures"},
                                      {"id": "futures-signal-ab-4h", "timeframe": "4h", "market": "futures"}],
                             "defaults_added": [d["id"] for d in worker.DEFAULT_BOTS]})
    worker.sync_config(rt, sink)
    bots = sink.get("config/bots")["bots"]
    ids = [b["id"] for b in bots]
    assert "futures-signal-ab-1d" not in ids and "futures-demo-ab-1d" in ids and "futures-signal-ab-4h" in ids
    demo = next(b for b in bots if b["id"] == "futures-demo-ab-1d")
    assert demo["demo_only"] and demo["grades"] == "A"
    # removing the demo bot later sticks
    sink.set("config/bots", {**sink.get("config/bots"), "bots": [b for b in bots if b["id"] != "futures-demo-ab-1d"]})
    worker.sync_config(rt, sink)
    assert "futures-demo-ab-1d" not in [b["id"] for b in sink.get("config/bots")["bots"]]
