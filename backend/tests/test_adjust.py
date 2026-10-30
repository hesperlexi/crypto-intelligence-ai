"""v2.7 admin adjustment of an open call's stop-loss / TP1: forward-only in the record, validation, admin-only job,
bots follow the same change."""
import tempfile
import time

import pandas as pd
import pytest

from app import worker
from app.data.base import tf_ms
from app.db import Database, loads
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


# ---- engine/manage.follow -------------------------------------------------------------------------------------

def test_no_adjustment_is_identical_to_before():
    rows = _rows((100, 101, 99.5, 100.5), (100.5, 102.3, 100.2, 102), (102, 102.2, 99.9, 100))
    assert M.follow(1, 100, 98, TPS, rows, complete=True) == M.follow(1, 100, 98, TPS, rows, complete=True, adjust=[])


def test_tighter_stop_applies_only_from_the_first_candle_opened_at_or_after_the_change():
    # candle 0 dips to 99.0 (above the old stop 98); the admin moves the stop to 99.2 during candle 0 (at = ts0 + 5 min)
    rows = _rows((100, 100.4, 99.0, 99.8), (99.8, 100.2, 99.5, 100), (100, 100.3, 99.1, 99.5))
    adj = [{"at": 5 * 60_000, "field": "stop", "new": 99.2}]
    r = M.follow(1, 100, 98, TPS, rows, adjust=adj, complete=True)
    # candle 0 (opened before the change) is NOT stopped by 99.2; candle 1 low 99.5 survives; candle 2 low 99.1 stops
    assert r["status"] == "STOPPED" and r["closed_ts"] == 2 * M15 and r["exit_reason"] == "admin_stop"
    assert r["exit_price"] == pytest.approx(99.2)
    assert r["return_r"] == pytest.approx(-0.4)                       # R stays on the original risk (2.0)


def test_adjustment_after_the_stop_was_hit_changes_nothing():
    rows = _rows((100, 100.4, 97.5, 98.2), (98.2, 99, 98, 98.5))
    base = M.follow(1, 100, 98, TPS, rows, complete=True)
    later = M.follow(1, 100, 98, TPS, rows, complete=True, adjust=[{"at": M15 + 1, "field": "stop", "new": 97.0}])
    assert base["status"] == later["status"] == "STOPPED" and later["exit_reason"] == "stop"
    assert later["return_pct"] == base["return_pct"]


def test_short_mirrored_and_tp1_change():
    # short entry 100, stop 102, TP1 98 -> admin moves TP1 to 99 from candle 1; candle 1 low 98.9 reaches it
    rows = _rows((100, 100.5, 99.5, 99.8), (99.8, 100, 98.9, 99.2), (99.2, 101.5, 99, 101))
    tps = [98.0, 97.0, 96.0]
    r = M.follow(-1, 100, 102, tps, rows, complete=False, adjust=[{"at": M15, "field": "tp1", "new": 99.0}])
    assert r["hits"][0] and not r["hits"][1]
    # after TP1 the stop is break-even (100); candle 2 high 101.5 stops the rest at 100
    assert r["status"] == "TP1" and r["exit_reason"] == "break_even"
    assert r["legs"][0]["price"] == pytest.approx(99.0)
    # admin stop for the short, from candle 1: 100.4; candle 2 high 101.5 hits it (no TP1 in this variant)
    r2 = M.follow(-1, 100, 102, tps, rows, complete=False, adjust=[{"at": M15, "field": "stop", "new": 100.4}])
    assert r2["status"] == "STOPPED" and r2["exit_reason"] == "admin_stop" and r2["exit_price"] == pytest.approx(100.4)


def test_tp1_cannot_change_once_hit_and_after_tp1_the_more_protective_stop_wins():
    rows = _rows((100, 102.5, 99.8, 102), (102, 102.4, 101.0, 101.5), (101.5, 101.6, 99.95, 100.2))
    # TP1 hit in candle 0; admin moves TP1 (ignored) and stop to 99 (looser than break-even 100) from candle 1
    r = M.follow(1, 100, 98, TPS, rows, complete=False,
                 adjust=[{"at": M15, "field": "tp1", "new": 105.0}, {"at": M15, "field": "stop", "new": 99.0}])
    assert r["legs"][0]["price"] == pytest.approx(102.0)              # TP1 leg at the original level
    assert r["status"] == "TP1" and r["exit_reason"] == "break_even"    # break-even (more protective) still applies
    # a tighter admin stop after TP1 (101.2 above break-even) binds from candle 1: candle 1 low 101.0 hits it
    r2 = M.follow(1, 100, 98, TPS, rows, complete=False, adjust=[{"at": M15, "field": "stop", "new": 101.2}])
    assert r2["exit_reason"] == "admin_stop" and r2["closed_ts"] == M15 and r2["exit_price"] == pytest.approx(101.2)


# ---- validation ---------------------------------------------------------------------------------------------

SIG = {"id": "s1", "symbol": "BTC/USDT", "timeframe": "4h", "side": 1, "entry": 100.0, "stop": 98.0, "tp1": 102.0,
       "status": "OPEN", "fill_status": "FILLED", "tp1_hit": 0, "bar_ts": BAR}
CUR = {"stop": 98.0, "tp1": 102.0}


@pytest.mark.parametrize("sig,price,stop,tp1,note,why", [
    (None, 100, 99, None, "tighten", "not found"),
    ({**SIG, "status": "STOPPED"}, 100, 99, None, "tighten", "only an open or pending"),
    (SIG, 100, 99, None, "ok", "note of 3 to 200"),
    (SIG, 100, 100.5, None, "tighten", "below the current price"),
    (SIG, 101, None, 100.5, "move tp", "above the current price"),
    ({**SIG, "tp1_hit": 1}, 103, None, 105, "move tp", "already hit"),
    (SIG, 100, 40, None, "widen a lot", "more than 50%"),
    (SIG, 99, None, 99.5, "move tp", "profit side of the entry"),
    (SIG, 100, 98, 102, "same", "nothing to change"),
    (SIG, None, 99, None, "tighten", "no current price"),
])
def test_validation_reasons(sig, price, stop, tp1, note, why):
    with pytest.raises(A.AdjustError, match=why):
        A.validate(sig, CUR, price, stop, tp1, note)


def test_validation_short_and_pending_and_ok():
    short = {**SIG, "side": -1, "stop": 102.0, "tp1": 98.0}
    with pytest.raises(A.AdjustError, match="above the current price"):
        A.validate(short, {"stop": 102.0, "tp1": 98.0}, 100, 99.5, None, "tighten")
    with pytest.raises(A.AdjustError, match="profit side of the entry"):
        A.validate(short, {"stop": 102.0, "tp1": 98.0}, 101, None, 100.5, "move tp")
    pend = {**SIG, "fill_status": "PENDING"}
    with pytest.raises(A.AdjustError, match="has not filled yet"):
        A.validate(pend, CUR, 101, 100.5, None, "tighten")
    assert A.validate(SIG, CUR, 100.5, 99.0, 102.5, "lock in") == [("stop", 98.0, 99.0), ("tp1", 102.0, 102.5)]


# ---- job + record + publication ----------------------------------------------------------------------------------

def _a(entry=100.0, live=100.0):
    return {"symbol": "BTC/USDT", "timeframe": "1h", "bar_ts": BAR, "price": live, "decision": "BUY", "grade": "A",
            "confidence": 0.6, "regime": {"regime": "BULL"}, "volatility": {"state": "NORMAL"},
            "signal": {"signal": "BUY", "score": 70, "reasons": [], "warnings": []},
            "setup": {"valid": True, "side_int": 1, "ideal_entry": entry, "stop": 98.0, "risk_reward": 1.6, "atr": 1.0,
                      "targets": [{"price": t, "rr": 1.0} for t in TPS]}, "flags": []}


class RT:
    def __init__(self, rows):
        self.db = Database("sqlite:///:memory:")
        self.m15 = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"])

    def candles(self, symbol, tf, include_forming=False, **kw):
        return self.m15 if tf == "15m" else self.m15.iloc[0:0]

    def live_price(self, symbol):
        return None


def _job_env(monkeypatch, rt):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    sink = LocalSink(tempfile.mkdtemp(), rt.db)
    sent = []
    sink.send_push = lambda msgs: (sent.extend(msgs), {"sent": len(msgs)})[1]
    sink.uid_for_email = lambda e: None
    return sink, sent


def test_job_admin_only_records_forward_only_and_publishes(monkeypatch):
    created = BAR + H1
    rows = [[created, 100, 100.4, 99.0, 99.8], [created + M15, 99.8, 100.2, 99.5, 100.0]]
    rt = RT(rows)
    T.log_signal(rt.db, _a(), now=created)
    sid = rt.db.one("SELECT id FROM signals")["id"]
    sink, sent = _job_env(monkeypatch, rt)
    now = int(time.time() * 1000)
    params = {"signal_id": sid, "stop": 99.2, "note": "Tighten before CPI"}
    sink.set("jobs/m", {"type": "adjust_signal", "status": "queued", "created_at": now, "by": "member@example.com",
                        "params": params})
    worker.process_jobs(rt, sink, time.time() + 60)
    assert sink.get("jobs/m")["status"] == "failed" and "only the admin" in sink.get("jobs/m")["error"]
    assert rt.db.one("SELECT COUNT(*) AS n FROM signal_adjustments")["n"] == 0
    # admin, with a bad value: plain reason
    sink.set("jobs/b", {"type": "adjust_signal", "status": "queued", "created_at": now, "by": "boss@example.com",
                        "params": {**params, "stop": 100.5}})
    worker.process_jobs(rt, sink, time.time() + 60)
    assert sink.get("jobs/b")["error"].startswith("for a long, the stop-loss must be below the current price")
    # admin, valid (the engine's latest price = last 15m close 100.0); change made during the 2nd candle
    at = created + M15 + 60_000
    out = A.apply(rt, params, "boss@example.com", sink, now=at)
    assert out["ok"] and out["changes"] == [{"field": "stop", "old": 98.0, "new": 99.2}]
    row = rt.db.one("SELECT * FROM signal_adjustments")
    assert row["by"] == "boss@example.com" and row["price_at_change"] == 100.0 and row["note"] == "Tighten before CPI"
    assert sent and sent[-1]["broadcast"] == "1"
    assert "Stop-loss moved 98.0000 → 99.2000" in sent[-1]["body"] and "BTC 1H long update" == sent[-1]["title"]
    assert any(d["rule"] == "admin_adjust" for d in T.recent_decisions(rt.db)["decisions"])
    # the record: both existing candles opened before the change -> still open, original stop kept in the row
    T.update_signal_outcomes(rt, now=created + 2 * M15)
    s = rt.db.one("SELECT * FROM signals")
    assert s["status"] == "OPEN" and s["stop"] == 98.0
    # a later candle dipping to 99.1 stops it at the admin level
    rt.m15.loc[len(rt.m15)] = [created + 2 * M15, 100.0, 100.1, 99.1, 99.4]
    T.update_signal_outcomes(rt, now=created + 3 * M15)
    s = rt.db.one("SELECT * FROM signals")
    assert s["status"] == "STOPPED" and s["exit_reason"] == "admin_stop" and s["stop"] == 98.0
    # publication: call view and history rows carry the history; the levels in force are on the call
    call = T.with_adjustments(rt.db, T.call_view(s))
    assert call["stop"] == 99.2 and call["stop0"] == 98.0 and call["adjustments"][0]["note"] == "Tighten before CPI"
    assert T.signal_history(rt.db)[0]["adjustments"][0]["new"] == 99.2
    # closed now: a further change is refused
    with pytest.raises(A.AdjustError, match="only an open or pending"):
        A.apply(rt, {**params, "stop": 99.3}, "boss@example.com", sink)


def test_bots_holding_the_call_apply_the_change_forward_only():
    from app.services.bots import BotEngine

    created = BAR + H1
    rows = [[created + i * M15, 100, 100.2, 99.6, 100] for i in range(3)] + [[created + 3 * M15, 100, 100.1, 99.3, 99.5]]
    rt = RT(rows)
    rt.symbols = lambda: ["BTC/USDT"]
    eng = BotEngine(rt)
    state = eng._fresh_state({"starting_balance": 10_000.0})
    pos = eng._open(state, "BTC/USDT", 1, 100.0, 10.0, created - M15, {"bar_ts": BAR}, 98.0, list(TPS), fill_raw=True)
    pos["last_check"] = created - M15
    cfg = {"id": "b", "mode": "decision", "timeframe": "1h", "market": "spot", "starting_balance": 10_000.0}
    rt.db.execute("INSERT INTO bots (id, config, state, reset_token, created_at) VALUES (?, ?, ?, ?, ?)",
                  ("b", __import__("json").dumps(cfg), __import__("json").dumps(state), "x", 0))
    sig = {"symbol": "BTC/USDT", "timeframe": "1h", "side": 1, "bar_ts": BAR}
    assert eng.apply_adjustment(sig, [("stop", 99.5)], created + 2 * M15) == 1
    st = loads(rt.db.one("SELECT state FROM bots")["state"])
    eng._manage_decision = BotEngine._manage_decision.__get__(eng)
    eng._reversals = lambda cfg, state, now: []
    ev = eng._manage_decision({**cfg, "max_hold_bars": 99}, st, created + 4 * M15)
    # candles 0-2 (low 99.6) never touch 99.5; candle 3 (low 99.3) does -> closed by the admin stop, not before
    assert [e["reason"] for e in ev if e["type"] == "close"] == ["admin stop"]
