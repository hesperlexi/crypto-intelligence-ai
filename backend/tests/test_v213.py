"""v2.13 honest record + stricter grading: market entry, net results, gap / through fills, edge-required grading,
fail-closed gates, maintenance tiers and liquidation, auto-trade 20x cap and same-timeframe reversal, record restart."""
import numpy as np
import pandas as pd
import pytest

from app.data.base import tf_ms
from app.db import Database, loads
from app.engine import futures as F
from app.engine import manage as M
from app.ml import series_sim as S
from app.services import analysis as A
from app.services import autopaper as AP
from app.services import tracking as T

H1 = tf_ms("1h")
M15 = tf_ms("15m")
BAR = 1_700_000_000_000 - (1_700_000_000_000 % tf_ms("4h"))


def _a(decision="BUY", side=1, entry=100.0, live=101.0, stop=98.0, tps=(102.0, 103.5, 105.0), tf="1h"):
    if side < 0:
        tps = tuple(entry - (t - entry) for t in tps)
    rr = [abs(t - entry) / abs(entry - stop) for t in tps]
    return {"symbol": "BTC/USDT", "timeframe": tf, "bar_ts": BAR, "price": live, "decision": decision, "grade": "A",
            "confidence": 0.6, "regime": {"regime": "BULL"}, "volatility": {"state": "NORMAL"},
            "signal": {"signal": "BUY" if side > 0 else "SELL", "score": 70, "reasons": [], "warnings": []},
            "setup": {"valid": True, "side_int": side, "ideal_entry": entry, "stop": stop, "risk_reward": 1.6, "atr": 1.0,
                      "targets": [{"price": t, "rr": r} for t, r in zip(tps, rr)]}, "flags": []}


# ---- C1: entry at the market price --------------------------------------------------------------------------------

def test_sell_is_recorded_at_the_live_price_not_the_better_ideal_entry():
    db = Database("sqlite:///:memory:")
    assert T.log_signal(db, _a("SELL", side=-1, entry=100.0, live=99.4, stop=102.0), now=BAR + H1)
    s = db.one("SELECT * FROM signals")
    assert s["entry"] == 99.4 and s["fill_status"] == "FILLED"
    d = 102.0 - 99.4
    assert s["tp1"] == pytest.approx(99.4 - d)                     # TP1 = exactly 1R from the real entry
    assert loads(s["payload"])["leverage"] == F.signal_leverage(99.4, 102.0, symbol="BTC/USDT")


def test_pullback_stays_a_pending_limit_at_the_ideal_entry():
    db = Database("sqlite:///:memory:")
    T.log_signal(db, _a("BUY ON PULLBACK", entry=100.0, live=101.5), now=BAR + H1)
    s = db.one("SELECT * FROM signals")
    assert s["entry"] == 100.0 and s["fill_status"] == "PENDING"


def test_no_record_when_the_price_is_already_beyond_the_stop():
    db = Database("sqlite:///:memory:")
    a = _a(entry=100.0, live=97.5, stop=98.0)
    assert not T.log_signal(db, a, now=BAR + H1)
    assert a["record_status"] == "not_logged" and db.one("SELECT COUNT(*) AS n FROM signals WHERE status = 'OPEN'")["n"] == 0


# ---- net results ------------------------------------------------------------------------------------------------------

def test_cost_is_the_apps_futures_round_trip():
    assert T.cost_pct() == pytest.approx(A.round_trip_cost(futures=True) * 100)
    assert T.cost_pct() == pytest.approx(0.15)


def test_exposure_weights_follow_the_partial_exits():
    ev = [{"type": "tp1", "ts": 4 * 3_600_000}, {"type": "tp2", "ts": 6 * 3_600_000}]
    assert T.exposure(0, 10 * 3_600_000, ev) == [(0, 4 * 3_600_000, 1.0), (4 * 3_600_000, 6 * 3_600_000, 0.5),
                                                  (6 * 3_600_000, 10 * 3_600_000, 0.25)]
    assert T.exposure(0, 5, ev, runner=True) == [(0, 5, 1.0)]


def test_funding_uses_stored_rates_then_the_default_and_signs_by_side():
    db = Database("sqlite:///:memory:")
    hr = 3_600_000
    db.execute("INSERT INTO derivs (symbol, kind, ts, value) VALUES (?, 'funding_1h', ?, ?)", ("BTC/USDT", 2 * hr, 0.001))
    segs = [(0, 3 * hr, 1.0)]                       # hours 1, 2, 3: default, stored 0.1 %, default
    default = F.DEFAULT_FUNDING_RATE / 8
    long_ = T.funding_pct(db, "BTC/USDT", 1, segs)
    assert long_ == pytest.approx((2 * default + 0.001) * 100)
    assert T.funding_pct(db, "BTC/USDT", -1, segs) == pytest.approx(-long_)          # shorts receive a positive rate


def test_a_tiny_gross_win_is_a_net_loss_everywhere():
    db = Database("sqlite:///:memory:")
    T.log_signal(db, _a(entry=100.0, live=100.0), now=BAR + H1)
    db.execute("UPDATE signals SET status = 'EXPIRED', return_pct = 0.10, closed_at = ?, return_net_pct = -0.06",
               (BAR + 2 * H1,))
    s = T.signal_summary(db)
    assert s["win_rate"] == 0.0 and s["avg_return_pct"] == pytest.approx(-0.06) and s["avg_gross_return_pct"] == pytest.approx(0.10)
    row = db.one("SELECT * FROM signals")
    rf = T.result_fields(row)
    assert rf["return_pct"] == pytest.approx(-0.06) and rf["gross_return_pct"] == pytest.approx(0.10) and rf["net"]
    assert T.margin_fields(row)["roi_pct"] < 0                       # ROI on margin from the net result


def test_closing_a_call_stores_net_fields():
    created = BAR + H1
    rows = [[created + i * M15, 100, 102.6, 99.8, 102.5] for i in range(2)]

    class RT:
        db = Database("sqlite:///:memory:")

        def candles(self, symbol, tf):
            return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"])
    rt = RT()
    T.log_signal(rt.db, _a(entry=100.0, live=100.0, tps=(102.0, 102.2, 102.4)), now=created)
    T.update_signal_outcomes(rt, now=created + 2 * M15)
    s = rt.db.one("SELECT * FROM signals")
    assert s["status"] == "TP3"
    assert s["cost_pct"] == pytest.approx(0.15)
    assert s["return_net_pct"] == pytest.approx(s["return_pct"] - s["cost_pct"] - s["funding_pct"])


# ---- fills ------------------------------------------------------------------------------------------------------------

def test_stop_on_a_gap_fills_at_the_open():
    r = M.follow(1, 100, 98, [102, 103, 104], [(0, 100, 100.5, 99.5, 100), (1, 97.0, 97.5, 96.5, 97)], complete=True)
    assert r["status"] == "STOPPED" and r["exit_price"] == pytest.approx(97.0)
    assert r["return_pct"] == pytest.approx(-3.0)
    r = M.follow(-1, 100, 102, [98, 97, 96], [(0, 100, 100.5, 99.5, 100), (1, 103.0, 103.5, 102.5, 103)], complete=True)
    assert r["exit_price"] == pytest.approx(103.0)
    # a normal stop (opened above it) still fills at the stop
    r = M.follow(1, 100, 98, [102, 103, 104], [(0, 100, 100.5, 97.5, 98)], complete=True)
    assert r["exit_price"] == pytest.approx(98.0)


def test_break_even_stop_gap_fills_at_the_open():
    rows = [(0, 100, 102.5, 100.1, 102), (1, 99.0, 99.5, 98.8, 99)]          # TP1, then opens below break-even
    r = M.follow(1, 100, 98, [102, 103, 104], rows, complete=True)
    assert r["exit_reason"] == "break_even" and r["exit_price"] == pytest.approx(99.0)
    assert r["return_pct"] == pytest.approx(0.5 * 2 + 0.5 * -1.0)


def test_limit_fills_only_when_traded_through():
    assert M.find_fill(1, 100, [(0, 101, 102, 100.0, 101)]) is None              # touch only
    assert M.find_fill(1, 100, [(0, 101, 102, 100.0, 101), (1, 101, 101, 99.9, 100)]) == 1
    assert M.find_fill(-1, 100, [(0, 99, 100.0, 98, 99)]) is None
    assert M.find_fill(-1, 100, [(0, 99, 100.1, 98, 99)]) == 0


def test_series_sim_matches_manage_with_gaps():
    rng = np.random.default_rng(3)
    for trial in range(300):
        n = 50
        cl = 100 * np.exp(np.cumsum(rng.normal(0, 0.008, n)))
        op = np.concatenate([[100.0], cl[:-1] * (1 + rng.normal(0, 0.004, n - 1))])      # gapped opens
        hi = np.maximum(op, cl) * (1 + np.abs(rng.normal(0, 0.003, n)))
        lo = np.minimum(op, cl) * (1 - np.abs(rng.normal(0, 0.003, n)))
        df = pd.DataFrame({"ts": np.arange(n) * M15, "open": op, "high": hi, "low": lo, "close": cl})
        side = 1 if trial % 2 else -1
        stop = 100 - side * rng.uniform(0.5, 2.0)
        tps = S.ladder(side, 100.0, stop)
        ref = M.follow(side, 100.0, stop, tps, df, complete=True)
        got = S.follow(side, 100.0, stop, tps, hi, lo, cl, complete=True, open_=op)
        assert got.status == ref["status"] and got.return_pct == pytest.approx(ref["return_pct"], abs=1e-9), trial


def test_series_sim_ideal_mode_is_the_old_record_and_limits_need_a_trade_through():
    p = {"ideal": 99.5, "stop": 98.0, "extended": False}
    hi, lo, cl = np.array([101.0]), np.array([99.0]), np.array([100.0])
    assert S.fill("ideal", 1, 100.0, 1.0, p, hi, lo, cl, 3) == (0, 99.5, False)
    assert S.fill("old", 1, 100.0, 1.0, p, hi, lo, cl, 3) == (0, 100.0, False)
    pe = {**p, "extended": True}
    assert S.fill("old", 1, 100.0, 1.0, pe, np.array([101.0]), np.array([99.5]), cl, 3) is None      # touch
    assert S.fill("old", 1, 100.0, 1.0, pe, np.array([101.0]), np.array([99.4]), cl, 3) == (0, 99.5, True)


# ---- C2: edge required ------------------------------------------------------------------------------------------------

def test_grades_need_a_proven_edge():
    assert A.edge_gate({"edge_confirmed": True}, {"policy_edge": True}, required=True) is None
    why = A.edge_gate({"edge_confirmed": True}, {"policy_edge": False}, required=True)
    assert why and "direction" in why
    assert "walk-forward" in A.edge_gate({"edge_confirmed": False}, {"policy_edge": True}, required=True)
    assert A.edge_gate({"edge_confirmed": False}, None, required=True)
    assert A.edge_gate({"edge_confirmed": False}, None, required=False) is None
    from app.config import settings
    assert settings.require_edge_for_trade is False                 # owner 3 Nov 2026 (v2.14): no edge rule by default
    assert A.edge_gate({"edge_confirmed": False}, None) is None      # default: graded calls are not refused for it


# ---- fail closed ------------------------------------------------------------------------------------------------------

def test_calendar_unavailable_only_when_stale_after_a_sync():
    db = Database("sqlite:///:memory:")
    now = 10_000_000_000
    assert A.calendar_unavailable(db, now) is None                    # never synced (fresh install): not blocking
    db.set_setting("calendar_synced_at", now - 3_600_000)
    assert A.calendar_unavailable(db, now) is None
    db.set_setting("calendar_synced_at", now - A.CALENDAR_MAX_AGE_MS - 1)
    assert A.calendar_unavailable(db, now)


def test_gate_failures_are_kept_for_health():
    class RT:
        db = Database("sqlite:///:memory:")
    A.gate_failure(RT, "safety", "BTC/USDT", "1h", RuntimeError("boom"))
    A.gate_failure(RT, "safety", "ETH/USDT", "4h", RuntimeError("boom"))
    g = A.gate_failures(RT.db)
    assert g["safety"]["count"] == 2 and g["safety"]["symbol"] == "ETH/USDT"


# ---- liquidation maths ------------------------------------------------------------------------------------------------

def test_maintenance_tiers():
    assert F.maintenance_rate("BTC/USDT") == 0.004 and F.maintenance_rate("ETH/USDT") == 0.004
    assert F.maintenance_rate("SOL/USDT") == 0.005
    assert F.maintenance_rate("PAXG/USDT") >= 0.01 and F.maintenance_rate("PEPE/USDT") >= 0.01
    assert F.maintenance_rate("SOMEALT/USDT") == F.MAINTENANCE_MARGIN == 0.01


def test_liquidation_includes_maintenance_and_exit_fee():
    lq = F.liquidation_price(100.0, 1, 10, symbol="BTC/USDT")
    assert lq == pytest.approx(100 * 0.9 / (1 - 0.004 - F.FUTURES_FEE_RATE))
    assert lq > 100 * (1 - 0.1 + 0.004)                               # earlier than the old fee-less formula
    sh = F.liquidation_price(100.0, -1, 10, symbol="BTC/USDT")
    assert sh == pytest.approx(100 * 1.1 / (1 + 0.004 + F.FUTURES_FEE_RATE))


@pytest.mark.parametrize("sym", ["BTC/USDT", "DOGE/USDT", "XYZ/USDT"])
@pytest.mark.parametrize("side", [1, -1])
def test_safe_leverage_keeps_liquidation_1_5x_beyond_the_stop(sym, side):
    for dist in (0.003, 0.01, 0.025, 0.06):
        stop = 100 * (1 - side * dist)
        lev = F.safe_leverage(100.0, stop, 50, symbol=sym, buffer=1.0)       # a smaller buffer is raised to 1.5
        liq = F.liquidation_price(100.0, side, lev, symbol=sym)
        assert side * (100 - liq) >= 1.5 * dist * 100 - 1e-9 or lev == 1


# ---- auto-trade ---------------------------------------------------------------------------------------------------------

def _sig(tf="1h", side=1, px=100.0):
    stop = px - side * 2
    return {"symbol": "BTC/USDT", "timeframe": tf, "side": side, "price": px, "grade": "A",
            "plan": {"entry": px, "entry_zone": [px - 0.5, px + 0.5], "stop": stop, "suggested_leverage": 50,
                     "targets": [{"price": px + side * 2}, {"price": px + side * 3}, {"price": px + side * 4}]},
            "call": {"id": "c1", "created_at": 1}}


def test_autotrade_leverage_is_capped_at_20x():
    assert AP.MAX_LEV == 20
    assert AP.settings_of({"leverage": 50})["leverage"] == 20
    s = AP.settings_of({"enabled": True, "leverage": 50, "scale": False})
    acc, res = AP.place(None, {**_sig(), "plan": {**_sig()["plan"], "stop": 99.9}}, s, 1000)
    assert res["action"] == "opened" and res["leverage"] <= 20
    pos = next(iter(acc["positions"].values()))
    assert pos["liq"] == pytest.approx(F.liquidation_price(pos["entry"], 1, pos["leverage"], symbol="BTC/USDT", fee=AP.FEE))


def test_autotrade_reversal_only_for_the_same_timeframe():
    s = AP.settings_of({"enabled": True, "scale": False})
    acc, res = AP.place(None, _sig("4h", 1), s, 1000)
    assert res["action"] == "opened"
    # a 1h short on the same coin does not close the 4h long: skipped (one position per coin, no hedging)
    acc2, res2 = AP.place(acc, _sig("1h", -1), s, 2000)
    assert acc2 is None and res2["action"] == "skipped" and "reversed" not in res2
    # a 4h short does reverse it
    acc3, res3 = AP.place(acc, _sig("4h", -1), s, 3000)
    assert res3.get("reversed") and res3["action"] == "opened"
    assert next(iter(acc3["positions"].values()))["side"] == -1


# ---- record restart -----------------------------------------------------------------------------------------------------

class _RT:
    def __init__(self):
        self.db = Database("sqlite:///:memory:")


def test_honest_record_restart_is_merged_into_the_v214_fresh_restart():
    """v2.14: the v2.13 restart never moves the record on its own (the fresh restart does it once); it only sets its flag."""
    from app import worker
    rt = _RT()
    T.log_signal(rt.db, _a(), now=BAR + H1)
    rt.db.set_setting("record_since", 5)
    rt.db.set_setting("record_since_tf", {"15m": 9})
    assert worker.honest_record_v213(rt, now=1234) == {"merged_into": "fresh_restart_v214"}
    assert rt.db.get_setting("record_since") == 5 and rt.db.get_setting("record_since_tf") == {"15m": 9}
    assert rt.db.get_setting("honest_record_since", None) is None
    assert worker.honest_record_v213(rt, now=9999) is None
    assert rt.db.one("SELECT COUNT(*) AS n FROM signals")["n"] == 1       # nothing deleted by it


def test_edge_rule_policy_only_needs_the_direction_edge(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "edge_rule", "policy")
    assert A.edge_gate({"edge_confirmed": False}, {"policy_edge": True}, required=True) is None
    assert A.edge_gate({"edge_confirmed": True}, {"policy_edge": False}, required=True)
