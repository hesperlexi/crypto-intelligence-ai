"""Road to Rich - Hesper's all-in demo runs: only public grade-A calls, one trade at a time, all-in margin with leverage
<= 25 and the stop before liquidation, the bots' exits, runs that end only by liquidation / bust (FAIL) or $1,000
(SUCCESS) and restart at $100 - and the record, the bots and every public output stay byte-identical."""
import json

import pytest

from app import views
from app.db import Database, dumps
from app.engine import futures as F
from app.services import analysis
from app.services import bots as B
from app.services import hesper as H
from app.services.runtime import Runtime

STEP = 900_000
H1 = 3_600_000
DAY = 86_400_000
NOW = 1_762_000_000_000 - (1_762_000_000_000 % STEP)


class _P:
    name = "test"


def _rt():
    return Runtime(Database("sqlite:///:memory:"), _P())


def _put(rt, symbol, start_ts, candles):
    rows, ts = [], start_ts
    for c in candles:
        o, h, l, cl = c if isinstance(c, tuple) else (c, c + 0.05, c - 0.05, c)
        rows.append([ts, o, h, l, cl, 10.0])
        ts += STEP
    rt.store.upsert("test", symbol, "15m", rows)
    return ts


def _call(db, sid, symbol="BTC/USDT", tf="1h", side=1, entry=100.0, stop=98.0, tps=(102.0, 103.5, 105.0), grade="A",
          created=NOW - 5 * 60_000, conf=0.6, decision=None, status="OPEN", fill="FILLED", bar=None, payload=None):
    decision = decision or ("BUY" if side > 0 else "SELL")
    p = {"grade": grade, "horizon_bars": 200, "leverage": 10, **(payload or {})}
    db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, confidence, price, side, "
               "entry, stop, tp1, tp2, tp3, status, payload, fill_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
               "?, ?, ?, ?)", (sid, created, symbol, tf, bar if bar is not None else created - created % H1 - H1,
                               "BUY" if side > 0 else "SELL", decision, conf, entry, side, entry, stop, *tps, status,
                               json.dumps(p), fill))


@pytest.fixture
def quiet(monkeypatch):
    """No costs and a flat analysis (no reversals), so the arithmetic is exact."""
    from app.config import settings
    monkeypatch.setattr(settings, "fee_rate", 0.0)
    monkeypatch.setattr(settings, "slippage_bps", 0.0)
    monkeypatch.setattr(settings, "spread_bps", 0.0)
    monkeypatch.setattr(F, "FUTURES_FEE_RATE", 0.0)
    monkeypatch.setattr(F, "DEFAULT_FUNDING_RATE", 0.0)
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: {"status": "OK", "decision": "HOLD"})


def _state(rt):
    return rt.db.get_setting(H.STATE_KEY)


def test_one_time_start_and_never_restarted(quiet):
    rt = _rt()
    H.Hesper(rt).run(NOW)
    st = _state(rt)
    assert st["run"] == 1 and st["cash"] == H.START_BALANCE and rt.db.get_setting(H.FLAG) is True
    assert rt.db.get_setting(H.SINCE) == NOW
    H.Hesper(rt).run(NOW + STEP)
    assert _state(rt)["run"] == 1 and rt.db.get_setting(H.SINCE) == NOW
    assert rt.db.one("SELECT COUNT(*) AS n FROM hesper_runs")["n"] == 1


def test_all_in_sizing_leverage_capped_and_stop_before_liquidation(monkeypatch):
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: {"status": "OK", "decision": "HOLD"})
    # tight stop (0.5 %): the safe leverage would be far above 25 -> capped at 25
    rt = _rt()
    _put(rt, "BTC/USDT", NOW - 8 * STEP, [100.0] * 8)
    _call(rt.db, "c1", stop=99.5, tps=(100.5, 101.0, 101.5))
    ev = H.Hesper(rt).run(NOW)
    assert ev and ev[0]["type"] == "open"
    pos = _state(rt)["positions"][0]
    assert pos["lev"] == 25 <= H.MAX_LEVERAGE
    spent = pos["margin"] + pos["fees"]
    assert spent == pytest.approx(H.START_BALANCE * H.ALL_IN, rel=1e-3)           # the whole balance (with costs: slippage)
    assert spent <= H.START_BALANCE and _state(rt)["cash"] >= 0
    assert pos["liq"] < pos["stop"] < pos["entry"]                                 # long: stop first, then liquidation
    # wide stop (5 %): leverage lowered so the liquidation stays 1.5x the stop distance beyond the entry
    rt2 = _rt()
    _put(rt2, "ETH/USDT", NOW - 8 * STEP, [100.0] * 8)
    _call(rt2.db, "c2", symbol="ETH/USDT", side=-1, stop=105.0, tps=(95.0, 92.0, 90.0))
    H.Hesper(rt2).run(NOW)
    pos = _state(rt2)["positions"][0]
    assert pos["lev"] == F.safe_leverage(pos["entry"], 105.0, 25) < 25
    assert pos["entry"] < pos["stop"] < pos["liq"]                                 # short: stop first, then liquidation
    assert (pos["liq"] - pos["entry"]) >= 1.5 * (105.0 - pos["entry"]) - 1e-9


def test_only_fresh_public_grade_a_calls_best_first(quiet):
    rt = _rt()
    for s in ("BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT", "DOGE/USDT"):
        _put(rt, s, NOW - 8 * STEP, [100.0] * 8)
    _call(rt.db, "b", symbol="BTC/USDT", grade="B", conf=0.9)                       # grade B: never
    _call(rt.db, "old", symbol="ETH/USDT", conf=0.95, created=NOW - 3 * H1)       # not fresh
    _call(rt.db, "shut", symbol="SOL/USDT", conf=0.95, status="STOPPED")          # already closed in the record
    _call(rt.db, "nf", symbol="DOGE/USDT", conf=0.95, status="NOT_FILLED", fill="NOT_FILLED")
    _call(rt.db, "a1", symbol="XRP/USDT", conf=0.6, created=NOW - 10 * 60_000)
    _call(rt.db, "a2", symbol="BNB/USDT", conf=0.6, created=NOW - 2 * 60_000)    # same confidence, newer -> chosen
    rt.db.execute("INSERT INTO shadow_signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, "
                  "entry, stop, tp1, tp2, tp3, status, payload) VALUES ('sh', ?, 'SOL/USDT', '1h', 1, 'BUY', 'BUY', 100, 1, "
                  "100, 98, 102, 103, 104, 'OPEN', ?)", (NOW - 60_000, json.dumps({"grade": "A", "shadow": True})))
    hz = H.Hesper(rt)
    assert [c["id"] for c in hz.candidates(NOW)] == ["a2", "a1"]
    hz.run(NOW)
    st = _state(rt)
    assert len(st["positions"]) == 1 and st["positions"][0]["symbol"] == "BNB/USDT"
    assert st["positions"][0]["info"]["signal_id"] == "a2"
    # one trade at a time: the other fresh call (and a brand-new one) are not taken while the trade is open
    _call(rt.db, "a3", symbol="DOGE/USDT", conf=0.99, created=NOW + 60_000, bar=NOW)
    H.Hesper(rt).run(NOW + STEP)
    st = _state(rt)
    assert len(st["positions"]) == 1 and not st["pending"] and st["positions"][0]["symbol"] == "BNB/USDT"


def test_pullback_call_waits_as_a_limit_and_counts_as_the_one_trade(quiet):
    rt = _rt()
    _put(rt, "BTC/USDT", NOW - 8 * STEP, [101.0] * 8)
    _call(rt.db, "p1", decision="BUY ON PULLBACK", entry=100.0, stop=98.0, fill="PENDING")
    _call(rt.db, "x", symbol="ETH/USDT", conf=0.1)
    _put(rt, "ETH/USDT", NOW - 8 * STEP, [100.0] * 8)
    H.Hesper(rt).run(NOW)
    st = _state(rt)
    assert not st["positions"] and len(st["pending"]) == 1 and st["pending"][0]["limit"] == 100.0
    assert st["cash"] == pytest.approx(H.START_BALANCE - st["pending"][0]["reserved"])
    # the limit fills on the next candles; no second trade meanwhile
    _put(rt, "BTC/USDT", NOW, [(101, 101.1, 99.9, 100.2)])
    H.Hesper(rt).run(NOW + 2 * STEP)
    st = _state(rt)
    assert len(st["positions"]) == 1 and st["positions"][0]["entry"] == 100.0 and not st["pending"]


def test_target_exits_follow_the_bots_rules_and_success_starts_a_new_run(quiet):
    rt = _rt()
    _put(rt, "BTC/USDT", NOW - 8 * STEP, [100.0] * 8)
    _call(rt.db, "w", stop=98.0, tps=(102.0, 103.5, 105.0))
    hz = H.Hesper(rt)
    hz.start(NOW)
    st = _state(rt)
    st["cash"] = 700.0                       # a run already well on its way (as if earlier trades had won)
    rt.db.set_setting(H.STATE_KEY, st)
    H.Hesper(rt).run(NOW)
    pos = _state(rt)["positions"][0]
    lev = pos["lev"]
    assert lev == 25 and F.safe_leverage(100.0, 98.0, 100) == 28           # 2 % stop: 28x would be safe, capped at 25
    # TP1 -> TP2 -> TP3 on the next candles
    _put(rt, "BTC/USDT", NOW, [(100, 102.2, 99.9, 102), (102, 103.6, 101.9, 103.5), (103.5, 105.2, 103.4, 105)])
    ev = H.Hesper(rt).run(NOW + 4 * STEP)
    t = rt.db.one("SELECT * FROM hesper_trades")
    assert t["exit_reason"] == "TP3" and t["tp_hit"] == 3 and t["run"] == 1
    assert t["pnl"] == pytest.approx(pos["qty"] * (0.5 * 2 + 0.25 * 3.5 + 0.25 * 5))
    assert t["roi_pct"] == pytest.approx(t["pnl"] / t["margin"] * 100)
    assert t["balance_after"] >= H.GOAL and t["balance_before"] == 700.0
    assert any(e["type"] == "run_end" and e["result"] == "SUCCESS" for e in ev)
    r1 = rt.db.one("SELECT * FROM hesper_runs WHERE run = 1")
    assert r1["result"] == "SUCCESS" and r1["reason"] == "goal" and r1["end_balance"] == pytest.approx(t["balance_after"])
    assert r1["trades"] == 1 and r1["peak"] == pytest.approx(t["balance_after"]) and json.loads(r1["best_trade"])["id"] == t["id"]
    st = _state(rt)
    assert st["run"] == 2 and st["cash"] == H.START_BALANCE and st["trades"] == 0 and not st["positions"]
    assert rt.db.one("SELECT result FROM hesper_runs WHERE run = 2")["result"] == "RUNNING"


def test_breakeven_after_tp1(quiet):
    rt = _rt()
    _put(rt, "BTC/USDT", NOW - 8 * STEP, [100.0] * 8)
    _call(rt.db, "be")
    H.Hesper(rt).run(NOW)
    pos = _state(rt)["positions"][0]
    _put(rt, "BTC/USDT", NOW, [(100, 102.2, 99.9, 102), (102, 102.1, 99.5, 99.8)])
    H.Hesper(rt).run(NOW + 3 * STEP)
    t = rt.db.one("SELECT * FROM hesper_trades")
    assert t["exit_reason"] == "breakeven stop" and t["pnl"] == pytest.approx(pos["qty"] * 0.5 * 2)
    assert _state(rt)["run"] == 1                     # the run goes on


def test_liquidation_fails_the_run_and_a_new_100_run_starts(quiet):
    rt = _rt()
    _put(rt, "BTC/USDT", NOW - 8 * STEP, [100.0] * 8)
    _call(rt.db, "liq", stop=99.5, tps=(100.5, 101.0, 101.5))
    H.Hesper(rt).run(NOW)
    pos = _state(rt)["positions"][0]
    assert pos["liq"] < pos["stop"]
    # a gap candle opens below both the stop and the liquidation price: the margin is lost
    _put(rt, "BTC/USDT", NOW, [(pos["liq"] - 1, pos["liq"] - 0.5, pos["liq"] - 2, pos["liq"] - 1)])
    ev = H.Hesper(rt).run(NOW + 2 * STEP)
    t = rt.db.one("SELECT * FROM hesper_trades")
    assert t["exit_reason"] == "liquidated" and t["pnl"] == pytest.approx(-pos["margin"])
    assert any(e["type"] == "run_end" and e["result"] == "FAIL" and e["reason"] == "liquidated" for e in ev)
    r1 = rt.db.one("SELECT * FROM hesper_runs WHERE run = 1")
    assert r1["result"] == "FAIL" and r1["reason"] == "liquidated" and r1["end_balance"] < H.MIN_BALANCE
    st = _state(rt)
    assert st["run"] == 2 and st["cash"] == H.START_BALANCE and st["liquidations"] == 0
    # the finished run is never changed again
    H.Hesper(rt).run(NOW + 3 * STEP)
    assert dumps(rt.db.one("SELECT * FROM hesper_runs WHERE run = 1")) == dumps(r1)


def test_a_balance_too_small_to_trade_is_busted(quiet):
    rt = _rt()
    hz = H.Hesper(rt)
    hz.start(NOW)
    st = _state(rt)
    st["cash"] = 0.4
    rt.db.set_setting(H.STATE_KEY, st)
    ev = H.Hesper(rt).run(NOW)
    assert ev[0]["type"] == "run_end" and ev[0]["reason"] == "busted"
    assert rt.db.one("SELECT result FROM hesper_runs WHERE run = 1")["result"] == "FAIL"
    assert _state(rt)["run"] == 2 and _state(rt)["cash"] == 100.0


def test_admin_close_of_the_call_closes_hesper_trade(quiet):
    rt = _rt()
    _put(rt, "BTC/USDT", NOW - 8 * STEP, [100.0] * 8)
    _call(rt.db, "ac")
    H.Hesper(rt).run(NOW)
    sig = rt.db.one("SELECT * FROM signals WHERE id = 'ac'")
    assert H.Hesper(rt).apply_close(sig, 101.0, NOW + STEP + 60_000) == 1
    assert H.Hesper(rt).apply_close({**sig, "id": "other"}, 101.0, NOW + STEP) == 0
    _put(rt, "BTC/USDT", NOW, [(100, 100.4, 99.8, 100.2), (100.2, 100.5, 100, 100.4)])
    H.Hesper(rt).run(NOW + 3 * STEP)
    t = rt.db.one("SELECT * FROM hesper_trades")
    assert t["exit_reason"] == "closed by admin" and t["exit"] == pytest.approx(101.0)


def test_reversal_on_1h_but_never_on_15m(monkeypatch, quiet):
    for tf, flips in (("1h", True), ("15m", False)):
        rt = _rt()
        _put(rt, "BTC/USDT", NOW - 8 * STEP, [100.0] * 8)
        _call(rt.db, "r" + tf, tf=tf)
        H.Hesper(rt).run(NOW)
        monkeypatch.setattr(analysis, "analyze", lambda *a, **k: {"status": "OK", "decision": "SELL", "grade": "A",
                                                                  "setup": {"valid": True}})
        _put(rt, "BTC/USDT", NOW, [(100, 100.3, 99.9, 100.1)])
        H.Hesper(rt).run(NOW + 2 * STEP)
        n = rt.db.one("SELECT COUNT(*) AS n FROM hesper_trades")["n"]
        assert n == (1 if flips else 0), tf
        monkeypatch.setattr(analysis, "analyze", lambda *a, **k: {"status": "OK", "decision": "HOLD"})


def test_view_shape_scoreboard_and_size(quiet):
    rt = _rt()
    hz = H.Hesper(rt)
    hz.start(NOW - 10 * DAY)
    ins = ("INSERT INTO hesper_trades (id, run, signal_id, symbol, timeframe, side, leverage, opened_at, closed_at, entry, "
           "exit, qty, margin, pnl, fees, funding, roi_pct, exit_reason, tp_hit, balance_before, balance_after) VALUES "
           "(?, ?, 's', 'BTC/USDT', '1h', 1, 20, ?, ?, 100, 101, 1, ?, ?, 0, 0, ?, ?, 0, ?, ?)")
    rt.db.execute("UPDATE hesper_runs SET result = 'FAIL', reason = 'liquidated', ended_at = ?, end_balance = 0.3, "
                  "peak = 180, trades = 3 WHERE run = 1", (NOW - 9 * DAY,))
    rt.db.execute("INSERT INTO hesper_runs (run, started_at, ended_at, result, reason, start_balance, end_balance, peak, "
                  "trades, wins) VALUES (2, ?, ?, 'SUCCESS', 'goal', 100, 1100, 1100, 5, 5)", (NOW - 9 * DAY, NOW - 2 * DAY))
    rt.db.execute("INSERT INTO hesper_runs (run, started_at, result, start_balance, peak, trades, wins) "
                  "VALUES (3, ?, 'RUNNING', 100, 140, 1, 1)", (NOW - 2 * DAY,))
    bal = 100.0
    for i in range(150):
        run = 2 if i < 140 else 3
        pnl = 5.0 if i % 4 else -3.0
        rt.db.execute(ins, (f"t{i:03d}", run, NOW - (200 - i) * H1, NOW - (199 - i) * H1, 10.0, pnl, pnl * 10, "TP1", bal, bal + pnl))
        bal += pnl
    st = H._fresh_state(3, NOW - 2 * DAY)
    st["cash"], st["peak"], st["trades"] = 140.0, 140.0, 1
    rt.db.set_setting(H.STATE_KEY, st)
    v = H.view(rt)
    sc = v["score"]
    assert sc["successes"] == 1 and sc["failures"] == 1 and sc["liquidations"] == 1 and sc["runs"] == 3
    assert sc["best_peak"] == {"run": 2, "peak": 1100} and sc["all_time_peak"] == 1100
    assert sc["avg_trades_per_run"] == pytest.approx(4.0)                # finished runs: (3 + 5) / 2
    assert sc["fastest_success"]["run"] == 2 and sc["fastest_success"]["ms"] == 7 * DAY
    assert sc["streak"]["kind"] == "win" and sc["trades"] == 150
    assert len(v["trades"]) == H.VIEW_TRADES and v["trades"][0]["id"] == "t149"
    assert v["current"]["run"] == 3 and v["current"]["open"] is None and v["goal"] == 1000 and v["start"] == 100
    assert v["curves"]["2"][0][1] == 100 and len(v["curves"]["2"]) == 141
    assert [r["run"] for r in v["runs"]] == [3, 2, 1]
    assert len(dumps(v).encode()) < 200_000
    c0 = H.core(v)
    rt.db.execute(ins, ("t999", 3, NOW - H1, NOW, 10.0, 1.0, 10.0, "TP1", bal, bal + 1))
    assert H.core(H.view(rt)) != c0


def _record_fixture(db):
    db.set_setting("record_since", NOW - 30 * DAY)
    for sid, tf, st, ret, created in (("w1", "1h", "TP3", 2.5, NOW - 9 * DAY), ("l1", "4h", "STOPPED", -2.0, NOW - 8 * DAY)):
        _call(db, sid, tf=tf, created=created, status=st)
        db.execute("UPDATE signals SET return_pct = ?, closed_at = ? WHERE id = ?", (ret, created + DAY, sid))


def _public(rt):
    track = views.track_record(rt)
    return {"track_record": dumps(track), "wins_today": dumps(views.wins_today(rt)),
            "weekly_reports": dumps(views.weekly_reports(rt)), "achievements": dumps(views.achievements(rt, track))}


def _tables(db):
    return {t: dumps(db.query(f"SELECT * FROM {t} ORDER BY 1")) for t in
            ("signals", "shadow_signals", "decisions", "signal_adjustments", "bot_trades", "bot_equity", "paper_accounts")}


def test_record_bots_and_public_outputs_unchanged(quiet, monkeypatch):
    monkeypatch.setattr(views, "now_ms", lambda: NOW + 5 * STEP)
    rt = _rt()
    _record_fixture(rt.db)
    _put(rt, "BTC/USDT", NOW - 8 * STEP, [100.0] * 8)
    eng = B.BotEngine(rt)
    eng.sync_configs([{"id": "futures-signal-ab-1h", "name": "t", "mode": "decision", "timeframe": "1h", "symbols": [],
                       "starting_balance": 10_000, "market": "futures", "leverage": 20, "reset_token": "1"}])
    eng.run(NOW)
    before, tables0 = _public(rt), _tables(rt.db)
    bots_row0 = dumps(rt.db.query("SELECT * FROM bots"))
    report0 = eng.report()
    _call(rt.db, "h1")
    tables0 = _tables(rt.db)                       # (the new call is the record's own row; Hesper must not touch it)
    H.Hesper(rt).run(NOW)
    _put(rt, "BTC/USDT", NOW, [(100, 102.2, 99.9, 102), (102, 103.6, 101.9, 103.5), (103.5, 105.2, 103.4, 105)])
    H.Hesper(rt).run(NOW + 4 * STEP)
    assert rt.db.one("SELECT COUNT(*) AS n FROM hesper_trades")["n"] == 1
    after = _public(rt)
    # Hesper never writes the record's or the bots' tables, nor the bots' rows
    assert _tables(rt.db) == tables0
    assert dumps(rt.db.query("SELECT * FROM bots")) == bots_row0
    rep = B.BotEngine(rt).report()
    assert [b["config"]["id"] for b in rep["bots"]] == [b["config"]["id"] for b in report0["bots"]]
    assert "hesper" not in dumps(rep).lower()
    # the public views only change by the record's own new call (compare with a twin database that never ran Hesper)
    twin = _rt()
    _record_fixture(twin.db)
    _call(twin.db, "h1")
    for k, v in _public(twin).items():
        assert after[k] == v, k
    assert set(before) == set(after)


def test_hesper_is_not_a_bot_and_stays_off_lists():
    assert H.BOT_ID not in {b["id"] for b in B.DEFAULT_BOTS + B.DEMO_BOTS + [B.FUTURES_3D]}
    assert H.Hesper(_rt()).bots() == []
    assert H.Hesper(_rt()).report()["bots"] == []
