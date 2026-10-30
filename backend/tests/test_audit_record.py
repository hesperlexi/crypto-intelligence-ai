"""Audit v1 fixes to the live record: look-ahead (A1), entry/fill (A2), stale data (A3), stacked calls (A4),
wins_today losses (A5), wall-clock expiry / void (A7), decisions log and re-entry rules."""
import pandas as pd
import pytest

from app.data.base import tf_ms
from app.db import Database, loads
from app.services import tracking as T

M15 = tf_ms("15m")
H1 = tf_ms("1h")
BAR = 1_700_000_000_000 - (1_700_000_000_000 % tf_ms("4h"))


def _a(decision="BUY", bar=BAR, tf="1h", side=1, entry=100.0, live=101.0, stop=None, tps=(102.0, 103.0, 104.0), **kw):
    stop = stop if stop is not None else entry - side * 2
    if side < 0:
        tps = tuple(entry - (t - entry) for t in tps)
    return {"symbol": "BTC/USDT", "timeframe": tf, "bar_ts": bar, "price": live, "decision": decision, "grade": "A",
            "confidence": 0.6, "regime": {"regime": "BULL"}, "volatility": {"state": "NORMAL"},
            "signal": {"signal": "BUY" if side > 0 else "SELL", "score": 70, "reasons": [], "warnings": []},
            "setup": {"valid": True, "side_int": side, "ideal_entry": entry, "stop": stop, "risk_reward": 1.6, "atr": 1.0,
                      "targets": [{"price": t, "rr": 1.0} for t in tps]}, "flags": [], **kw}


class RT:
    def __init__(self, m15, own=None):
        self.db = Database("sqlite:///:memory:")
        self.m15, self.own = m15, own

    def candles(self, symbol, tf):
        if tf == "15m":
            return self.m15
        return self.own if self.own is not None else self.m15.iloc[0:0]


def _df(rows):
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"])


def test_a2_entry_is_the_plan_entry_and_market_calls_are_filled():
    db = Database("sqlite:///:memory:")
    assert T.log_signal(db, _a(entry=100.0, live=101.3), now=BAR + H1 + 1000)
    s = db.one("SELECT * FROM signals")
    assert s["entry"] == 100.0 and s["price"] == 101.3 and s["fill_status"] == "FILLED"
    assert s["engine_version"] == "2.6.0" and s["app_version"] == "2.0.0"
    assert loads(s["payload"])["live_price"] == 101.3


def test_a1_follows_only_candles_opened_after_publication():
    created = BAR + H1 + 7 * 60_000              # published 7 minutes into a 15m candle
    rt = RT(_df([[BAR + H1, 100, 103.0, 99.5, 101],                 # forming at publication: the TP1 high must not count
                 [BAR + H1 + M15, 101, 101.5, 100.5, 101]]))
    T.log_signal(rt.db, _a(), now=created)
    T.update_signal_outcomes(rt, now=created + 30 * 60_000)
    s = rt.db.one("SELECT * FROM signals")
    assert s["tp1_hit"] == 0 and s["status"] == "OPEN"
    assert s["peak_r"] == pytest.approx(0.75)


def test_a2_pullback_waits_for_fill_then_follows_from_the_fill_candle():
    created = BAR + H1
    rows = [[created, 101, 101.8, 100.4, 101],                       # not through 100 yet
            [created + M15, 101, 103.5, 99.9, 100.5],               # fills at 100; its high (TP1/TP2) came before: ignored
            [created + 2 * M15, 100.5, 102.2, 100.2, 102]]          # TP1 after the fill
    rt = RT(_df(rows))
    T.log_signal(rt.db, _a("BUY ON PULLBACK", entry=100.0, live=101.2), now=created)
    assert rt.db.one("SELECT fill_status FROM signals")["fill_status"] == "PENDING"
    T.update_signal_outcomes(rt, now=created + 3 * M15)
    s = rt.db.one("SELECT * FROM signals")
    assert s["fill_status"] == "FILLED" and s["filled_at"] == created + M15
    assert s["tp1_hit"] == 1 and s["tp2_hit"] == 0 and s["status"] == "OPEN"
    rules = [d["rule"] for d in T.recent_decisions(rt.db)["decisions"]]
    assert "fill" in rules and "logged" in rules


def test_a2_pullback_never_filled_is_excluded_from_every_statistic():
    created = BAR + H1
    rows = [[created + i * M15, 101, 101.5, 100.5, 101] for i in range(14)]     # 3 bars of 1h = 12 x 15m: never touches 100
    rt = RT(_df(rows))
    T.log_signal(rt.db, _a("BUY ON PULLBACK", entry=100.0, live=101.2), now=created)
    T.update_signal_outcomes(rt, now=created + 14 * M15)
    s = rt.db.one("SELECT * FROM signals")
    assert s["status"] == "NOT_FILLED" and s["fill_status"] == "NOT_FILLED" and s["return_pct"] is None
    summ = T.signal_summary(rt.db)
    assert summ["closed"] == 0 and summ["not_filled"] == 1
    from app import views

    class V:
        db = rt.db
        symbols = staticmethod(lambda: [])
    tr = views.track_record(V(), {"bots": []})
    assert tr["live"]["summary"]["closed"] == 0 and tr["live"]["not_filled"] == 1
    assert tr["live"]["signals"][0]["status"] == "NOT_FILLED"            # listed, not hidden
    w = views.wins_today(V())
    assert w["closed"] == 0 and w["losses"] == 0


def test_a4_one_open_call_per_pair_and_restart_idempotent():
    db = Database("sqlite:///:memory:")
    a1 = _a(bar=BAR)
    assert T.log_signal(db, a1, now=BAR + H1) and a1["record_status"] == "logged"
    hold = {**_a(bar=BAR + H1), "decision": "HOLD", "setup": None, "signal": {"signal": "HOLD"}}
    T.log_signal(db, hold, now=BAR + 2 * H1)
    again = _a(bar=BAR + 2 * H1)
    assert not T.log_signal(db, again, now=BAR + 3 * H1) and again["record_status"] == "already_open"
    short = _a(bar=BAR + 3 * H1, side=-1, decision="SELL")
    assert not T.log_signal(db, short, now=BAR + 4 * H1) and short["record_status"] == "already_open"
    assert db.one("SELECT COUNT(*) AS n FROM signals WHERE side != 0")["n"] == 1
    # restart (same candle analysed again): nothing new, one skip decision (deduplicated)
    T.log_signal(db, _a(bar=BAR + 2 * H1), now=BAR + 3 * H1 + 60_000)
    skips = [d for d in T.recent_decisions(db)["decisions"] if d["rule"] == "skip_already_open"]
    assert len(skips) == 2                                    # one for the long, one for the short attempt


def test_a4_mid_candle_decision_change_turns_the_info_row_into_the_call():
    db = Database("sqlite:///:memory:")
    hold = {**_a(bar=BAR), "decision": "HOLD", "setup": None, "signal": {"signal": "HOLD"}}
    T.log_signal(db, hold, now=BAR + H1)
    a = _a(bar=BAR)
    assert T.log_signal(db, a, now=BAR + H1 + 600_000) and a["record_status"] == "logged"
    s = db.one("SELECT * FROM signals")
    assert s["status"] == "OPEN" and s["decision"] == "BUY" and s["created_at"] == BAR + H1 + 600_000


def test_reentry_cooldown_and_cap():
    from app.config import settings
    db = Database("sqlite:///:memory:")
    T.log_signal(db, _a(bar=BAR), now=BAR + H1)
    closed = BAR + 2 * H1
    db.execute("UPDATE signals SET status = 'STOPPED', return_pct = -2, closed_at = ?, exit_reason = 'stop'", (closed,))
    a = _a(bar=BAR + 2 * H1)
    assert not T.log_signal(db, a, now=closed + H1) and a["record_status"] == "not_logged" and "waiting" in a["record_reason"]
    for k in range(settings.reentry_max):
        b = _a(bar=BAR + (5 + k) * H1)
        t = closed + (4 + k * 3) * H1
        assert T.log_signal(db, b, now=t), k
        db.execute("UPDATE signals SET status = 'EXPIRED', return_pct = 0, closed_at = ?, exit_reason = 'expired' "
                   "WHERE status = 'OPEN'", (t + H1 // 2,))
    c = _a(bar=BAR + 20 * H1)
    assert not T.log_signal(db, c, now=closed + 15 * H1) and "re-entries" in c["record_reason"]
    vol = _a(bar=BAR + 21 * H1, regime={"regime": "HIGH-VOLATILITY / UNSTABLE"})
    db.execute("DELETE FROM signals WHERE status = 'EXPIRED'")
    assert not T.log_signal(db, vol, now=closed + 16 * H1) and "volatility" in vol["record_reason"]


def test_a7_wall_clock_expiry_and_void():
    created = BAR + H1
    end = created + 30 * H1
    rt = RT(_df([[created, 100, 100.5, 99.5, 100.4]]))          # data stops after the first candle
    T.log_signal(rt.db, _a(), now=created)
    T.update_signal_outcomes(rt, now=created + 5 * H1)
    assert rt.db.one("SELECT status FROM signals")["status"] == "OPEN"
    T.update_signal_outcomes(rt, now=end + H1)
    s = rt.db.one("SELECT * FROM signals")
    assert s["status"] == "EXPIRED" and s["return_pct"] == pytest.approx(0.4) and s["exit_reason"] == "expired"
    rt2 = RT(_df([[created - M15, 100, 100.5, 99.5, 100.4]]))   # nothing at all after publication
    T.log_signal(rt2.db, _a(), now=created)
    T.update_signal_outcomes(rt2, now=end + H1)
    s = rt2.db.one("SELECT * FROM signals")
    assert s["status"] == "VOID" and s["return_pct"] is None
    summ = T.signal_summary(rt2.db)
    assert summ["void"] == 1 and summ["closed"] == 0


def test_a5_wins_today_shows_losses_and_closed():
    from app import views
    db = Database("sqlite:///:memory:")
    now = T.now_ms()
    ins = ("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, tp1, "
           "tp2, tp3, status, return_pct, closed_at) VALUES (?, ?, 'BTC/USDT', '1h', ?, 'BUY', 'BUY', 100, 1, 100, 98, 102, "
           "103, 104, ?, ?, ?)")
    db.execute(ins, ("w", now - 5000, 1, "TP2", 2.0, now - 1000))
    db.execute(ins, ("l", now - 5000, 2, "STOPPED", -2.0, now - 1000))
    db.execute(ins, ("l2", now - 5000, 3, "STOPPED", -1.0, now - 2000))

    class V:
        pass
    V.db = db
    w = views.wins_today(V())
    assert len(w["wins"]) == 1 and w["closed"] == 3 and w["losses"] == 2


def test_a3_stale_candles_mean_no_trade():
    from app.services.analysis import is_stale
    now = 1_700_000_000_000
    q = {"status": "OK", "quality_pct": 100.0}
    assert not is_stale(q, now - 2 * H1, "1h", now)                  # closed an hour ago: fresh
    assert is_stale(q, now - 4 * H1, "1h", now)                      # closed 3 bars ago: stale
    assert is_stale({"status": "DEGRADED", "quality_pct": 80.0}, now - 2 * H1, "1h", now)


def test_a3_engine_analysis_on_stale_store_is_no_trade_and_not_logged():
    from tests.helpers import make_runtime
    from app.services import analysis
    rt, _ = make_runtime(symbols=("BTC/USDT",))          # synthetic candles end in 2025: stale today
    a = analysis.analyze(rt, "BTC/USDT", "4h", use_cache=False)
    assert a["stale"] is True and a["decision"] in ("NO TRADE", "INSUFFICIENT DATA")
    assert "market data is stale" in (a["decision_reason"] or "")
    assert rt.db.one("SELECT COUNT(*) AS n FROM signals WHERE side != 0")["n"] == 0
    assert "call" in a
