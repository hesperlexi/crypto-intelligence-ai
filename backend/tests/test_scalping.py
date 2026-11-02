"""Admin scalping log (15m grade-A demo calls in `scalp_signals`): logged when issued, followed with the record's exit
engine, summarised in views/scalping - and the public outputs (track record, wins today, weekly reports, achievements)
stay byte-identical whatever the scalping log holds."""
import json

import pandas as pd
import pytest

from app import views
from app.data.base import tf_ms
from app.db import Database, dumps, loads
from app.services import tracking as T

M15 = tf_ms("15m")
H1 = tf_ms("1h")
DAY = 86_400_000
NOW = 1_762_000_000_000 - (1_762_000_000_000 % M15)       # a fixed clock (2025-11), 15m aligned


def _demo(symbol="BTC/USDT", bar=NOW - 4 * M15, side=1, entry=100.0, live=100.0, grade="A", decision=None, tf="15m",
          stale=False, valid=True):
    stop = entry - side * 1.0
    tps = [entry + side * m for m in (1.0, 1.5, 2.0)]
    decision = decision or ("BUY" if side > 0 else "SELL")
    return {"symbol": symbol, "timeframe": tf, "bar_ts": bar, "price": live, "last_close": live,
            "decision": "NO TRADE", "grade": None, "demo": {"decision": decision, "grade": grade}, "stale": stale,
            "decision_reason": "15M calls go to the demo bots only while they are tested", "confidence": 0.62,
            "regime": {"regime": "BULL"}, "volatility": {"state": "NORMAL"},
            "signal": {"signal": "BUY" if side > 0 else "SELL", "score": 70, "reasons": [], "warnings": []},
            "setup": {"valid": valid, "side_int": side, "ideal_entry": entry, "stop": stop, "risk_reward": 1.4, "atr": 0.5,
                      "risk_pct": 1.0, "targets": [{"price": t, "rr": r} for t, r in zip(tps, (1.0, 1.5, 2.0))]},
            "flags": ["DEMO BOTS ONLY", "NO TRADE"]}


class RT:
    exchange = "binance"

    def __init__(self, db=None, paths=None):
        self.db = db or Database("sqlite:///:memory:")
        self.paths = paths or {}
        self.errors = []

    def symbols(self):
        return []                       # no trained bundles in these fixtures: the 'tested' block stays empty

    def candles(self, symbol, tf):
        df = self.paths.get(symbol)
        if df is None:
            return pd.DataFrame(columns=["ts", "open", "high", "low", "close"])
        return df if tf == "15m" else df.iloc[0:0]

    def record_error(self, where, exc):
        self.errors.append((where, str(exc)))


def _df(rows):
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"])


@pytest.fixture
def frozen(monkeypatch):
    """One fixed clock for the views and the tracker, so two builds can be compared byte for byte."""
    monkeypatch.setattr(views, "now_ms", lambda: NOW)
    monkeypatch.setattr(T, "now_ms", lambda: NOW)
    return NOW


def _record_fixture(db):
    """A small real-looking record: closed wins and losses on 1h / 4h, one open call, one never-filled pullback."""
    db.set_setting("record_since", NOW - 30 * DAY)
    ins = ("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, tp1, "
           "tp2, tp3, status, return_pct, closed_at, payload, tp1_hit, tp2_hit, tp3_hit, fill_status, filled_at) "
           "VALUES (?, ?, ?, ?, ?, 'BUY', 'BUY', 100, ?, 100, ?, ?, 103, 104, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
    pay = json.dumps({"grade": "A", "horizon_bars": 200, "leverage": 10})
    rows = [("w1", NOW - 9 * DAY, "BTC/USDT", "1h", 1, 1, 98, 102, "TP3", 2.5, NOW - 8 * DAY, pay, 1, 1, 1, "FILLED", NOW - 9 * DAY),
            ("l1", NOW - 8 * DAY, "ETH/USDT", "4h", 2, 1, 98, 102, "STOPPED", -2.0, NOW - 7 * DAY, pay, 0, 0, 0, "FILLED", NOW - 8 * DAY),
            ("w2", NOW - 3 * DAY, "SOL/USDT", "1h", 3, -1, 102, 98, "TP1", 0.5, NOW - 2 * 3_600_000, pay, 1, 0, 0, "FILLED", NOW - 3 * DAY),
            ("o1", NOW - 5 * 3_600_000, "XRP/USDT", "4h", 4, 1, 98, 102, "OPEN", None, None, pay, 0, 0, 0, "FILLED", NOW - 5 * 3_600_000),
            ("n1", NOW - 6 * DAY, "BNB/USDT", "1h", 5, 1, 98, 102, "NOT_FILLED", None, NOW - 5 * DAY, pay, 0, 0, 0, "NOT_FILLED", None)]
    for r in rows:
        db.execute(ins, r)
    db.execute("INSERT INTO shadow_signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, "
               "stop, tp1, tp2, tp3, status) VALUES ('s1', ?, 'BTC/USDT', '1h', 9, 'BUY', 'BUY', 100, 1, 100, 98, 102, 103, "
               "104, 'OPEN')", (NOW - DAY,))


def _public(rt):
    track = views.track_record(rt)
    return {"track_record": dumps(track), "wins_today": dumps(views.wins_today(rt)),
            "weekly_reports": dumps(views.weekly_reports(rt)), "achievements": dumps(views.achievements(rt, track))}


def _counts(db):
    return {t: db.one(f"SELECT COUNT(*) AS n FROM {t}")["n"] for t in ("signals", "shadow_signals", "decisions", "signal_proofs")}


def test_public_outputs_are_byte_identical_with_scalp_calls(frozen):
    rt = RT()
    _record_fixture(rt.db)
    before, counts0 = _public(rt), _counts(rt.db)
    shadow0 = dumps(rt.db.query("SELECT * FROM shadow_signals ORDER BY id"))
    signals0 = dumps(rt.db.query("SELECT * FROM signals ORDER BY id"))

    rt.db.set_setting("scalping_since", NOW - 2 * DAY)
    # an open call logged now, plus a call that runs to TP1 then back to break-even, plus a stopped one
    created = NOW - 12 * M15
    rt.paths = {"BTC/USDT": _df([[created + i * M15, 100, 100.4, 99.8, 100.1] for i in range(12)]),
                "ETH/USDT": _df([[created, 100, 101.2, 99.9, 101], [created + M15, 101, 101.1, 99.5, 99.6]]
                                + [[created + i * M15, 99.6, 99.8, 99.4, 99.6] for i in range(2, 12)]),
                "SOL/USDT": _df([[created, 100, 100.2, 98.8, 99]] + [[created + i * M15, 99, 99.2, 98.9, 99] for i in range(1, 12)])}
    assert T.log_scalp(rt.db, _demo("BTC/USDT", bar=created - M15), now=created)["status"] == "logged"
    assert T.log_scalp(rt.db, _demo("ETH/USDT", bar=created - M15), now=created)["status"] == "logged"
    assert T.log_scalp(rt.db, _demo("SOL/USDT", bar=created - M15), now=created)["status"] == "logged"
    T.update_signal_outcomes(rt, table=T.SCALP_TABLE, now=NOW)
    st = {r["symbol"]: r for r in rt.db.query("SELECT * FROM scalp_signals")}
    assert st["BTC/USDT"]["status"] == "OPEN"
    assert st["ETH/USDT"]["tp1_hit"] == 1 and st["ETH/USDT"]["status"] == "TP1"       # half at TP1, rest at break-even
    assert st["SOL/USDT"]["status"] == "STOPPED" and st["SOL/USDT"]["return_pct"] < 0

    after = _public(rt)
    for k in before:
        assert after[k] == before[k], k
    assert _counts(rt.db) == counts0
    assert dumps(rt.db.query("SELECT * FROM shadow_signals ORDER BY id")) == shadow0
    assert dumps(rt.db.query("SELECT * FROM signals ORDER BY id")) == signals0
    # the safety switch reads only the record / shadow tables: same answer with and without scalp calls
    from app.services import safety
    assert safety.check(rt.db, "SOL/USDT", "15m", 0) == safety.check(Database("sqlite:///:memory:"), "SOL/USDT", "15m", 0)


def test_log_scalp_rules(frozen):
    db = Database("sqlite:///:memory:")
    a = _demo()
    snap = json.dumps(a, sort_keys=True)
    assert T.log_scalp(db, a, now=NOW)["status"] == "not_logged"                 # not started yet
    db.set_setting("scalping_since", NOW - DAY)
    assert T.log_scalp(db, _demo(grade="B"), now=NOW)["status"] is None           # grade A only
    assert T.log_scalp(db, _demo(tf="1h"), now=NOW)["status"] is None             # 15m only
    assert T.log_scalp(db, _demo(stale=True), now=NOW)["status"] is None
    assert T.log_scalp(db, _demo(valid=False), now=NOW)["status"] is None
    assert T.log_scalp(db, {**_demo(), "demo": None}, now=NOW)["status"] is None
    res = T.log_scalp(db, a, now=NOW)
    assert res["status"] == "logged"
    assert json.dumps(a, sort_keys=True) == snap                                   # the analysis is never changed
    row = db.one("SELECT * FROM scalp_signals")
    p = loads(row["payload"])
    assert row["entry"] == 100.0 and row["stop"] == 99.0 and row["tp1"] == 101.0 and row["fill_status"] == "FILLED"
    assert row["decision"] == "BUY" and p["grade"] == "A" and p["horizon_bars"] == T.horizon_for("15m") == 250
    assert p["scalp"] is True and p["leverage"] >= 1
    # one open call per coin; another coin is fine
    again = T.log_scalp(db, _demo(bar=NOW, side=-1), now=NOW + M15)
    assert again["status"] == "already_open" and again["id"] == row["id"]
    assert T.log_scalp(db, _demo("ETH/USDT"), now=NOW)["status"] == "logged"
    # a pullback waits for its fill
    db2 = Database("sqlite:///:memory:")
    db2.set_setting("scalping_since", NOW - DAY)
    T.log_scalp(db2, _demo(decision="BUY ON PULLBACK", live=100.4), now=NOW)
    assert db2.one("SELECT fill_status FROM scalp_signals")["fill_status"] == "PENDING"
    # nothing reached the record's tables
    assert db.one("SELECT COUNT(*) AS n FROM signals")["n"] == 0
    assert db.one("SELECT COUNT(*) AS n FROM decisions")["n"] == 0


def test_reentry_cooldown_after_a_close(frozen):
    db = Database("sqlite:///:memory:")
    db.set_setting("scalping_since", NOW - DAY)
    T.log_scalp(db, _demo(), now=NOW - 10 * M15)
    db.execute("UPDATE scalp_signals SET status = 'STOPPED', closed_at = ?, return_pct = -1, exit_reason = 'stop'",
               (NOW - M15,))
    res = T.log_scalp(db, _demo(bar=NOW), now=NOW)
    from app.config import settings
    assert res["status"] == ("not_logged" if settings.reentry_cooldown_bars > 0 else "logged")


def test_update_outcomes_accepts_only_known_tables():
    with pytest.raises(ValueError):
        T.update_signal_outcomes(RT(), table="users")


def _closed(i, ret, status, tp1=0, tp2=0, tp3=0, lev=10):
    return {"id": f"c{i}", "symbol": "BTC/USDT", "side": "LONG", "status": status, "return_pct": ret, "roi_pct": ret * lev,
            "leverage": lev, "created_at": NOW + i * H1, "filled_at": NOW + i * H1, "closed_at": NOW + i * H1 + 30 * 60_000,
            "tp1_hit": tp1, "tp2_hit": tp2, "tp3_hit": tp3}


def test_scalping_stats_numbers():
    xs = [_closed(0, 1.0, "TP3", 1, 1, 1), _closed(1, -0.5, "STOPPED"), _closed(2, 2.0, "TP2", 1, 1),
          _closed(3, -1.0, "STOPPED"), _closed(4, -1.0, "STOPPED"), _closed(5, 0.0, "TP1", 1),
          _closed(6, 0.5, "TP1", 1)]
    s = views.scalping_stats(xs)
    assert s["closed"] == 7 and s["wins"] == 3 and s["losses"] == 4                # 0.0 counts as a loss, as the record
    assert s["win_rate"] == pytest.approx(3 / 7)
    assert s["profit_factor"] == pytest.approx(3.5 / 2.5)
    assert s["total_return_pct"] == pytest.approx(1.0) and s["avg_return_pct"] == pytest.approx(1 / 7)
    # cumulative: 1, .5, 2.5, 1.5, .5, .5, 1 -> peak 2.5, trough .5 -> drawdown 2.0
    assert s["max_drawdown_pct"] == pytest.approx(2.0)
    assert s["max_drawdown_roi_pct"] == pytest.approx(20.0)
    assert s["streak"] == {"kind": "win", "n": 1, "best_win": 1, "best_loss": 3}
    assert s["hit_rates"]["tp1"] == pytest.approx(4 / 7) and s["hit_rates"]["tp2"] == pytest.approx(2 / 7)
    assert s["hit_rates"]["tp3"] == pytest.approx(1 / 7)
    assert s["best"]["id"] == "c2" and s["worst"]["return_pct"] == -1.0
    assert s["avg_hold_min"] == pytest.approx(30.0)
    assert s["total_roi_pct"] == pytest.approx(10.0)
    assert views.scalping_stats([_closed(0, 1.0, "TP1", 1)])["profit_factor"] is None     # no loss yet
    assert views.scalping_stats([])["closed"] == 0


def test_scalping_view_shape_and_size(frozen):
    rt = RT()
    v0 = views.scalping(rt)
    assert v0["started"] is False and v0["summary"]["closed"] == 0
    rt.db.set_setting("scalping_since", NOW - 30 * DAY)
    ins = ("INSERT INTO scalp_signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, "
           "tp1, tp2, tp3, status, return_pct, closed_at, payload, tp1_hit, tp2_hit, fill_status, filled_at) VALUES "
           "(?, ?, ?, '15m', ?, 'BUY', 'BUY', 100, ?, 100, 99, 101, 101.5, 102, ?, ?, ?, ?, ?, ?, 'FILLED', ?)")
    pay = json.dumps({"grade": "A", "horizon_bars": 250, "leverage": 20, "scalp": True})
    n = 0
    for i in range(300):                                       # far more than the view lists
        win = i % 3 != 0
        db_args = (f"s{i}", NOW - (300 - i) * H1, "BTC/USDT" if i % 2 else "ETH/USDT", i, 1, "TP2" if win else "STOPPED",
                   1.25 if win else -1.0, NOW - (300 - i) * H1 + 45 * 60_000, pay, int(win), int(win), NOW - (300 - i) * H1)
        rt.db.execute(ins, db_args)
        n += 1
    rt.db.execute(ins, ("open1", NOW - M15, "SOL/USDT", 999, -1, "OPEN", None, None, pay, 0, 0, NOW - M15))
    rt.db.execute(ins, ("old", NOW - 40 * DAY, "SOL/USDT", 1000, 1, "TP1", 0.5, NOW - 39 * DAY, pay, 1, 0, NOW - 40 * DAY))
    bots = {"bots": [{"config": {"id": "futures-demo-a-15m", "name": "Futures demo bot 15M", "starting_balance": 10000,
                                 "enabled": True},
                      "state": {"cash": 9000, "equity": 10250, "started_at": NOW - 5 * DAY},
                      "stats": {"trades": 2, "equity": 10250, "return_pct": 2.5, "win_rate": 0.5, "profit_factor": 1.8,
                                "max_drawdown_pct": -1.2, "open_positions": 1},
                      "trades": [{"symbol": "BTC/USDT", "side": 1, "opened_at": NOW - H1, "closed_at": NOW, "entry": 100,
                                  "exit": 101, "pnl": 20, "return_pct": 1.0, "exit_reason": "TP1",
                                  "info": {"roe_pct": 20.0, "leverage": 20}}]},
                     {"config": {"id": "futures-signal-ab-4h"}, "stats": {}, "state": {}}]}
    v = views.scalping(rt, bots)
    assert v["started"] and v["since"] == NOW - 30 * DAY and v["logged"] == 301          # the 40-day-old call is before `since`
    assert v["summary"]["closed"] == 300 and v["summary"]["wins"] == 200
    assert v["summary"]["win_rate"] == pytest.approx(2 / 3)
    assert len(v["open"]) == 1 and v["open"][0]["id"] == "open1" and v["open"][0]["horizon_bars"] == 250
    o = v["open"][0]
    assert o["expires_at"] == NOW - M15 + 250 * M15 and o["fill_status"] == "FILLED" and o["leverage"] == 20
    assert len(v["recent"]) == views.SCALP_RECENT and v["recent"][0]["id"] == "s299"
    assert {x["status"] for x in v["recent"]} == {"TP2", "STOPPED"}                     # wins and losses, unfiltered
    assert v["curve"][-1]["cum_return_pct"] == pytest.approx(v["summary"]["total_return_pct"])
    assert v["bot"]["id"] == "futures-demo-a-15m" and v["bot"]["return_pct"] == 2.5 and v["bot"]["recent"][0]["roe_pct"] == 20.0
    assert "before fees" in v["label"] and "not public" in v["label"]
    assert len(dumps(v).encode()) < 300_000                                               # one small document
    core = views.scalping_core(v)
    rt.db.execute("UPDATE scalp_signals SET tp1_hit = 1 WHERE id = 'open1'")
    assert views.scalping_core(views.scalping(rt, bots)) != core                           # a target hit goes out at once


def test_publish_writes_one_scalping_view_and_dedups(frozen, tmp_path):
    from app.sinks import LocalSink
    rt = RT()
    rt.db.set_setting("scalping_since", NOW - DAY)
    sink = LocalSink(tmp_path, rt.db)
    v = views.scalping(rt)
    sink.view("scalping", v, min_interval_s=900, core=views.scalping_core(v))
    assert sink.flush() == 1
    sink.view("scalping", views.scalping(rt), min_interval_s=900, core=views.scalping_core(v))
    assert sink.flush() == 0 and sink.skipped == 1


def test_scalping_since_is_set_once(tmp_path):
    from app import worker
    from app.services.runtime import Runtime
    from app.sinks import LocalSink

    class _P:
        name = "test"
    rt = Runtime(Database("sqlite:///:memory:"), _P())
    for f in ("watchlist_majors_v2", "gold_paxg_v21", "fresh_start_v23", "testing_v24", "testing_v24b", "pause_15m_v26",
              "tf_policy_v28", "demo_1d3d_v210"):
        rt.db.set_setting(f, True)
    sink = LocalSink(tmp_path)
    worker.sync_config(rt, sink)
    first = rt.db.get_setting("scalping_since")
    assert first and rt.db.get_setting("scalping_v1") is True
    rt.db.set_setting("scalping_since", first - 1)                  # never moved again by the engine
    worker.sync_config(rt, sink)
    assert rt.db.get_setting("scalping_since") == first - 1


def test_analysis_hook_logs_demo_calls_without_changing_the_analysis(monkeypatch):
    """analysis.analyze calls tracking.log_scalp only for 15m demo calls, after the record's own logging."""
    import inspect

    from app.services import analysis
    src = inspect.getsource(analysis.analyze)
    i_rec, i_scalp = src.index("tracking.log_signal(rt.db, out)"), src.index("tracking.log_scalp(rt.db, out)")
    assert i_rec < i_scalp and "if demo and timeframe in tracking.SCALP_TFS" in src
    assert "except Exception" in src[i_scalp:i_scalp + 300]
