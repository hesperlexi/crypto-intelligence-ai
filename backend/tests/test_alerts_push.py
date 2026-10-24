"""Trade-signal alerts carry the full plan, respect their filters, and reach registered devices."""
import json
import tempfile

from app.db import Database
from app.services import alerts
from app.services.runtime import Runtime
from app.sinks import LocalSink
from app import worker


class _P:
    name = "test"


def _a(decision="SELL", side=-1, conf=0.6, confident=True):
    return {"status": "OK", "symbol": "BTC/USDT", "timeframe": "4h", "price": 100.0, "decision": decision,
            "confidence": conf, "regime": {}, "now": {},
            "forecast": {"probabilities": {"up": 0.2, "down": 0.6, "neutral": 0.2},
                         "confident_call": {"is_confident": confident}},
            "setup": {"valid": True, "side_int": side, "ideal_entry": 100.0, "entry_zone": [99.5, 100.5], "stop": 102.0,
                      "risk_pct": 2.0, "risk_reward": 2.1,
                      "targets": [{"price": 98.0}, {"price": 96.0}, {"price": 94.0}]}}


def test_trade_setup_alert_message_and_filters():
    from app.config import settings

    settings.symbols = ["BTC/USDT"]
    rt = Runtime(Database("sqlite:///:memory:"), _P())
    alerts.create_alert(rt.db, "TRADE_SETUP", "BTC/USDT", "4h", {"side": "any", "market": "futures"}, cooldown_s=1)
    alerts.create_alert(rt.db, "TRADE_SETUP", "BTC/USDT", "4h", {"side": "long"}, cooldown_s=1)
    alerts.create_alert(rt.db, "TRADE_SETUP", "BTC/USDT", "4h", {"side": "any", "min_confidence": 0.7}, cooldown_s=1)
    none = {"status": "OK", "symbol": "BTC/USDT", "timeframe": "4h", "price": 100.0, "decision": "NO TRADE", "regime": {}}
    assert alerts.evaluate(rt.db, none, now=1_000) == []           # first look: records the state, never fires
    fired = alerts.evaluate(rt.db, _a(), now=10_000)
    assert len(fired) == 1                                          # long-only and min-confidence 70% stay quiet
    msg = fired[0]["message"]
    for part in ("BTC/USDT 4h SHORT (futures)", "stop-loss 102", "TP1 98", "TP2 96", "TP3 94", "R:R 1:2.1",
                 "confidence 60%", "suggested leverage", "liquidation"):
        assert part in msg, (part, msg)
    assert alerts.evaluate(rt.db, _a(), now=20_000) == []           # still the same call: no repeat


def test_engine_pushes_fired_alerts_to_devices():
    root = tempfile.mkdtemp()
    db = Database("sqlite:///:memory:")
    sink = LocalSink(root, db)
    sink.set("push_tokens/abc", {"token": "abc"})
    res = sink.send_push([worker.push_message({"id": "e1", "type": "TRADE_SETUP", "symbol": "BTC/USDT", "message": "hello"})])
    assert res == {"sent": 1, "devices": 1}
    line = json.loads(open(f"{root}/push_log.jsonl").read().splitlines()[0])
    assert line["title"] == "Trade signal · BTC/USDT" and line["body"] == "hello" and line["url"] == "/alerts"


def test_member_alerts_are_private_and_pushed_to_their_devices():
    from app.config import settings
    from tests.helpers import ArrayProvider
    import time

    settings.symbols = ["BTC/USDT"]
    root = tempfile.mkdtemp()
    db = Database("sqlite:///:memory:")
    now = int(time.time() * 1000)
    rt = Runtime(db, ArrayProvider(("BTC/USDT",), base_bars=3000, end_ms=now - now % 900_000 + 900_000))
    sink = LocalSink(root, db)
    sink.set("alerts/m1", {"type": "PRICE_ABOVE", "symbol": "BTC/USDT", "timeframe": "4h", "params": {"level": 1e9},
                           "owner_uid": "member1"})
    sink.set("alerts/a1", {"type": "PRICE_ABOVE", "symbol": "BTC/USDT", "timeframe": "4h", "params": {"level": 1e9}})
    worker.sync_config(rt, sink)
    worker.publish(rt, sink, {"ticks": 1}, now, {})
    sink.flush()
    mine = json.loads(sink.get("views/alerts_u_member1")["json"])
    admin = json.loads(sink.get("views/alerts")["json"])
    assert set(mine["state"]) == {"m1"} and set(admin["state"]) == {"a1"}
    sink.set("push_tokens/t1", {"token": "t1", "uid": "member1"})
    sink.set("push_tokens/t2", {"token": "t2", "uid": "someone-else"})
    res = sink.send_push([worker.push_message({"id": "e", "type": "PRICE_ABOVE", "symbol": "BTC/USDT", "message": "x"}, "member1")])
    assert res["sent"] == 1
