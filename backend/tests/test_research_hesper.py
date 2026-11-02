"""Hesper 30-day window simulator (python -m app.research hesper): success, liquidation, time-up, fixed-risk sizing and
the skip-long-calls rule, on synthetic candles."""
import numpy as np
import pytest

from app.engine import futures as F
from app.research_hesper import DAY, STEP15, Market, run_window, simulate_scope, window_starts

T0 = 1_760_000_000_000 - (1_760_000_000_000 % DAY)


@pytest.fixture(autouse=True)
def no_costs(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "slippage_bps", 0.0)
    monkeypatch.setattr(settings, "spread_bps", 0.0)
    monkeypatch.setattr(F, "FUTURES_FEE_RATE", 0.0)
    monkeypatch.setattr(F, "DEFAULT_FUNDING_RATE", 0.0)


def _market(candles, symbol="BTC/USDT"):
    """candles: list of (open, high, low, close) on consecutive 15m candles from T0 - 1 day."""
    m = Market()
    n = len(candles)
    ts = T0 - DAY + np.arange(n, dtype=np.int64) * STEP15
    o, h, l, c = (np.array([x[i] for x in candles], float) for i in range(4))
    m.add(symbol, "15m", ts, h, l, c, o)
    return m


def _flat(px, n):
    return [(px, px, px, px)] * n


def _call(i, ts, side=1, entry=100.0, stop=98.0, horizon=200, tf="1h", conf=0.6):
    d = abs(entry - stop)
    return {"id": f"c{i}", "symbol": "BTC/USDT", "tf": tf, "ts": ts, "side": side, "conf": conf,
            "decision": "BUY" if side > 0 else "SELL", "entry": entry, "stop": stop,
            "tps": [entry + side * m * d for m in (1.0, 1.75, 2.5)], "horizon": horizon, "rec_close": 2 ** 62}


A = {"risk": None, "skip_horizon": False}


def test_success_after_winning_trades():
    # every 4 hours a long call at the current price; the next candle runs to +5 % (all three targets)
    candles = _flat(100.0, 96)                     # the day before the window
    calls = []
    px = 100.0
    for k in range(20):
        candles += _flat(px, 15)
        calls.append(_call(k, T0 + (k * 16 + 15) * STEP15, entry=px, stop=px * 0.98))
        candles.append((px, px * 1.06, px, px * 1.06))
        px *= 1.06
    m = _market(candles + _flat(px, 3000))
    r = run_window(calls, m, T0, A)
    assert r["result"] == "SUCCESS" and r["end_balance"] >= 1000
    # 25x on a 2 % stop: +3.125 % blended move = +78.1 % on 99.5 % of the balance per trade: 4 trades reach $998,
    # the fifth passes $1,000
    assert r["trades"] == 5
    assert r["end_balance"] == pytest.approx(100 * (1 + 0.995 * 25 * 0.03125) ** 5, rel=1e-6)
    assert r["days"] < 2


def test_liquidation_on_a_gap_through_stop_and_liquidation():
    candles = _flat(100.0, 96 + 4) + [(90.0, 90.0, 89.0, 89.5)] + _flat(89.5, 3000)   # opens far below the stop
    calls = [_call(0, T0 + 4 * STEP15, entry=100.0, stop=98.0)]
    r = run_window(calls, _market(candles), T0, A)
    assert r["result"] == "FAIL" and r["reason"] == "liquidated"
    assert r["end_balance"] < 1.0                  # all-in margin lost (a sliver stays: ALL_IN 0.995)


def test_plain_stop_is_not_a_liquidation_and_fixed_risk_loses_its_share():
    candles = _flat(100.0, 96 + 4) + [(100.0, 100.0, 97.5, 97.8)] + _flat(97.8, 3000)
    calls = [_call(0, T0 + 4 * STEP15, entry=100.0, stop=98.0)]
    a = run_window(calls, _market(candles), T0, A)
    assert a["result"] == "TIME_UP" and a["trades"] == 1
    assert a["end_balance"] == pytest.approx(100 - 0.995 * 100 * 25 * 0.02, rel=1e-6)   # 25x on -2 %
    b = run_window(calls, _market(candles), T0, {"risk": 0.25, "skip_horizon": False})
    assert b["end_balance"] == pytest.approx(75.0, rel=1e-6)


def test_time_up_closes_the_open_trade_at_day_30():
    candles = _flat(100.0, 96 + 4) + _flat(100.5, 4000)     # drifts, never reaches stop or TP1
    calls = [_call(0, T0 + 4 * STEP15, entry=100.0, stop=98.0, horizon=10_000)]
    r = run_window(calls, _market(candles), T0, A)
    assert r["result"] == "TIME_UP" and r["reason"] == "day_30" and r["days"] == 30
    assert r["trades"] == 1 and r["end_balance"] == pytest.approx(100 + 99.5 * 25 * 0.005, rel=1e-6)
    # with the skip rule the call (time limit past day 30) is never taken
    s = run_window(calls, _market(candles), T0, {"risk": None, "skip_horizon": True})
    assert s["trades"] == 0 and s["end_balance"] == 100.0


def test_stale_calls_and_scope_windows():
    candles = _flat(100.0, 96) + _flat(100.0, 4000)
    calls = [_call(0, T0 - 2 * 3_600_000)]            # published 2 h before the start: not fresh
    r = run_window(calls, _market(candles), T0, A)
    assert r["trades"] == 0 and r["result"] == "TIME_UP"
    st = window_starts(T0, T0 + 60 * DAY)
    assert st[0] == T0 + DAY and all(b - a == 7 * DAY for a, b in zip(st, st[1:])) and st[-1] + 30 * DAY <= T0 + 60 * DAY
    out = simulate_scope([_call(0, T0 + DAY + STEP15)], _market(candles), {}, T0 + 40 * DAY)
    assert out["windows"] == len(window_starts(T0 + DAY + STEP15, T0 + 40 * DAY))
    assert set(out["variants"]) >= {"A_all_in", "B25_risk", "B35_risk_skip_long"}


def test_published_calls_follow_the_record_rules_on_a_synthetic_series():
    """Replay source: only grade-A calls reach Hesper, one open call per series (live time limit + cooldown), and the
    whole pipeline (calls -> windows) runs end to end."""
    from app.ml import series_policy as SP
    from app.research_hesper import published_calls
    from tests.test_series_policy import _ctx
    ctx, paths, df = _ctx(n=900, edge=0.15)
    test = np.zeros(ctx.n, bool)
    test[700:] = True
    tune = ~test
    d = SP.decide(ctx, tune)
    v = {"ctx": ctx, "paths": paths, "d": d, "test": test}
    prep = {"entry_choice": {"1h": {"chosen": "old:0.0"}}, "filters": {}, "news": None}
    calls, flips = published_calls("BTC/USDT 1h", v, prep)
    assert set(flips) == {("BTC/USDT", "1h", 1), ("BTC/USDT", "1h", -1)}
    a_rows = {int(ctx.decision_ts[j]) for j in np.flatnonzero(d["trade"] & (d["grade"] == "A"))}
    assert all(c["ts"] in a_rows for c in calls)
    for a, b in zip(calls, calls[1:]):
        assert b["ts"] >= a["rec_close"]                    # never two open calls on the series
    assert all(c["horizon"] == 200 for c in calls)
    m = Market()
    m.add_df("BTC/USDT", "1h", df)
    if calls:
        out = simulate_scope(calls, m, flips, int(df["ts"].iloc[-1]) + 3_600_000, first=int(df["ts"].iloc[0]))
        for name, x in out["variants"].items():
            o = x["overlapping"]
            assert o["windows"] == out["windows"]
            if o["windows"]:
                assert abs(o["success_pct"] + o["fail_pct"] + o["time_up_pct"] - 100) < 1e-9
