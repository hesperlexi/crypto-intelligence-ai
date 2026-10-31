"""v2.8 admin close: an open call closes at the engine's market price; the result is what the price gives."""
import tempfile
import time

import pandas as pd
import pytest

from app import worker
from app.data.base import tf_ms
from app.db import Database
from app.engine import manage as M
from app.services import adjust as A
from app.services import tracking as T
from app.sinks import LocalSink

M15 = tf_ms("15m")
H1 = tf_ms("1h")
BAR = 1_700_000_000_000 - (1_700_000_000_000 % tf_ms("4h"))
TPS = [102.0, 103.0, 104.0]


def _rows(*bars, t0=0):
    return [(t0 + i * M15, *b) for i, b in enumerate(bars)]


def test_follow_closes_at_the_admin_price_after_the_closed_candles():
    rows = _rows((100, 100.5, 99.5, 100.2), (100.2, 101, 100, 100.8), (100.8, 101.5, 97, 97.5))
    # close during candle 1 (at = ts1 + 5 min): candle 0 followed, candle 1 (not closed yet) and 2 ignored
    r = M.follow(1, 100, 98, TPS, rows, adjust=[{"at": M15 + 5 * 60_000, "field": "close", "new": 100.6}])
    assert r["status"] == "EXPIRED" and r["exit_reason"] == "admin_close" and r["closed_ts"] == M15 + 5 * 60_000
    assert r["return_pct"] == pytest.approx(0.6) and r["return_r"] == pytest.approx(0.3)


def test_follow_close_after_tp1_keeps_the_target_leg_and_a_loss_is_a_loss():
    rows = _rows((100, 102.2, 99.9, 101.8), (101.8, 101.9, 100.5, 100.7))
    r = M.follow(1, 100, 98, TPS, rows, adjust=[{"at": 2 * M15, "field": "close", "new": 100.5}])
    assert r["status"] == "TP1" and r["exit_reason"] == "admin_close"
    assert r["return_pct"] == pytest.approx(0.5 * 2 + 0.5 * 0.5)
    short = M.follow(-1, 100, 102, [98, 97, 96], _rows((100, 100.6, 99.6, 100.4)),
                     adjust=[{"at": M15, "field": "close", "new": 100.9}])
    assert short["status"] == "EXPIRED" and short["return_pct"] == pytest.approx(-0.9)


def test_follow_waits_for_late_candles_and_a_stop_before_the_close_wins():
    # only candle 0 stored, close at ts 3 candles later: candles 1-2 missing -> still open (waits for data)
    rows = _rows((100, 100.5, 99.5, 100.2))
    r = M.follow(1, 100, 98, TPS, rows, adjust=[{"at": 3 * M15 + 1, "field": "close", "new": 101}])
    assert r["status"] == "OPEN"
    rows = _rows((100, 100.5, 97.5, 98.2), (98.2, 99, 98, 98.5))
    r = M.follow(1, 100, 98, TPS, rows, adjust=[{"at": 2 * M15, "field": "close", "new": 99}])
    assert r["status"] == "STOPPED" and r["exit_reason"] == "stop"


def test_close_validation():
    sig = {"id": "s", "status": "OPEN", "side": 1, "fill_status": "FILLED"}
    for kw, why in [({"sig": None}, "not found"), ({"sig": {**sig, "status": "TP1"}}, "only an open"),
                    ({"sig": {**sig, "fill_status": "PENDING"}}, "has not filled"), ({"already": True}, "already being"),
                    ({"note": "x"}, "note of 3"), ({"price": None}, "no current price"),
                    ({"still_open": False}, "already reached")]:
        a = {"sig": sig, "price": 100.0, "note": "take profit", "already": False, "still_open": True, **kw}
        with pytest.raises(A.AdjustError, match=why):
            A.close_validate(a["sig"], a["price"], a["note"], a["already"], a["still_open"])


def _a():
    return {"symbol": "BTC/USDT", "timeframe": "1h", "bar_ts": BAR, "price": 100.0, "decision": "BUY", "grade": "A",
            "confidence": 0.6, "regime": {"regime": "BULL"}, "volatility": {"state": "NORMAL"},
            "signal": {"signal": "BUY", "score": 70, "reasons": [], "warnings": []},
            "setup": {"valid": True, "side_int": 1, "ideal_entry": 100.0, "stop": 98.0, "risk_reward": 1.6, "atr": 1.0,
                      "targets": [{"price": t, "rr": 1.0} for t in TPS]}, "flags": []}


class RT:
    def __init__(self, rows):
        self.db = Database("sqlite:///:memory:")
        self.m15 = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"])

    def candles(self, symbol, tf, include_forming=False, **kw):
        return self.m15 if tf == "15m" else self.m15.iloc[0:0]

    def live_price(self, symbol):
        return None


def test_job_closes_the_call_records_it_and_notifies(monkeypatch):
    created = BAR + H1
    rt = RT([[created, 100, 100.6, 99.6, 100.4], [created + M15, 100.4, 101.0, 100.2, 100.8]])
    T.log_signal(rt.db, _a(), now=created)
    sid = rt.db.one("SELECT id FROM signals")["id"]
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    sink = LocalSink(tempfile.mkdtemp(), rt.db)
    sent = []
    sink.send_push = lambda msgs: (sent.extend(msgs), {"sent": len(msgs)})[1]
    sink.uid_for_email = lambda e: None
    now = int(time.time() * 1000)
    sink.set("jobs/m", {"type": "adjust_signal", "status": "queued", "created_at": now, "by": "member@example.com",
                        "params": {"signal_id": sid, "action": "close", "note": "taking profit"}})
    worker.process_jobs(rt, sink, time.time() + 60)
    assert sink.get("jobs/m")["status"] == "failed"
    at = created + M15 + 10 * 60_000                       # during the 2nd candle; engine price = last close 100.8
    out = A.close(rt, {"signal_id": sid, "action": "close", "note": "taking profit"}, "boss@example.com", sink, now=at)
    assert out["ok"] and out["price"] == 100.8 and out["return_pct"] == pytest.approx(0.8) and "as a win" in out["message"]
    assert sent[-1]["title"] == "BTC 1H long closed" and "Closed by the admin at" in sent[-1]["body"]
    with pytest.raises(A.AdjustError, match="already being"):
        A.close(rt, {"signal_id": sid, "note": "again"}, "boss@example.com", sink, now=at + 1)
    with pytest.raises(A.AdjustError, match="being closed"):
        A.apply(rt, {"signal_id": sid, "stop": 99.0, "note": "tighten"}, "boss@example.com", sink, now=at + 1)
    # the record: the 2nd candle had not closed at the click -> needs it in the data (it is), closes at 100.8
    T.update_signal_outcomes(rt, now=at + M15)
    s = rt.db.one("SELECT * FROM signals")
    assert s["status"] == "EXPIRED" and s["exit_reason"] == "admin_close" and s["return_pct"] == pytest.approx(0.8)
    assert s["closed_at"] == at
    view = T.with_adjustments(rt.db, T.call_view(s))
    assert view["stop"] == 98.0 and view["adjustments"][0]["field"] == "close"


def test_bot_position_closes_at_the_admin_price():
    from app.services.bots import BotEngine
    created = BAR + H1
    rows = [[created + i * M15, 100, 100.4, 99.6, 100.2] for i in range(4)]
    rt = RT(rows)
    rt.symbols = lambda: ["BTC/USDT"]
    eng = BotEngine(rt)
    state = eng._fresh_state({"starting_balance": 10_000.0})
    cfg = {"id": "b1", "mode": "decision", "timeframe": "1h", "max_hold_bars": 42}
    pos = eng._open(state, "BTC/USDT", 1, 100.0, 10.0, created, {"bar_ts": BAR}, 98.0, TPS, fill_raw=True, cfg=cfg)
    pos["last_check"] = created - M15
    pos["admin_close"] = {"at": created + 2 * M15 + 1, "price": 101.0}
    eng._reversals = lambda *a, **k: []
    ev = eng._manage_decision(cfg, state, created + 4 * M15)
    assert ev and ev[0]["reason"] == "closed by admin" and not state["positions"]
    tr = rt.db.one("SELECT * FROM bot_trades")
    assert tr["exit_reason"] == "closed by admin" and tr["exit"] == pytest.approx(101.0, rel=2e-3)


def test_close_at_exactly_the_entry_says_break_even():
    created = BAR + H1
    rt = RT([[created, 100, 100.6, 99.6, 100.4], [created + M15, 100.4, 101.0, 99.8, 100.0]])
    T.log_signal(rt.db, _a(), now=created)
    sid = rt.db.one("SELECT id FROM signals")["id"]
    sink = LocalSink(tempfile.mkdtemp(), rt.db)
    sent = []
    sink.send_push = lambda msgs: (sent.extend(msgs), {"sent": len(msgs)})[1]
    out = A.close(rt, {"signal_id": sid, "action": "close", "note": "flat market"}, "boss@example.com", sink,
                  now=created + M15 + 10 * 60_000)
    assert out["return_pct"] == pytest.approx(0.0) and "at break-even" in out["message"] and "loss" not in out["message"]
    assert "break-even" in sent[-1]["body"]
    msg = A.close_message({"id": "x", "symbol": "BTC/USDT", "timeframe": "1h", "side": 1}, 100.0, 0.0, 0.0, "n")
    assert "0.00% (break-even)" in msg["body"]
