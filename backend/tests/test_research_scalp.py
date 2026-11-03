"""Scalping study (research_scalp.py): aggregation, no look-ahead, fills / costs and stop-before-target."""
import numpy as np
import pandas as pd

from app import research_scalp as S

T0 = 1_767_225_600_000                                    # 2026-01-01 00:00 UTC (day aligned)


def _klines(n, seed=1, drop=()):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    o = np.concatenate([[100.0], c[:-1]])
    h = np.maximum(o, c) * 1.0005
    lo = np.minimum(o, c) * 0.9995
    df = pd.DataFrame({"ts": T0 + np.arange(n) * 60_000, "open": o, "high": h, "low": lo, "close": c,
                       "volume": rng.uniform(1, 2, n)})
    return df.drop(index=list(drop)).reset_index(drop=True)


def _grid(o, h, lo, c):
    n = len(o)
    return {"open": np.array(o, float), "high": np.array(h, float), "low": np.array(lo, float),
            "close": np.array(c, float), "volume": np.ones(n), "valid": np.ones(n, bool),
            "fund_cum": np.zeros(n + 1), "t0": T0, "n": n}


def test_aggregation_matches_manual_and_drops_incomplete():
    k = _klines(60, drop=(17,))
    g = S.to_grid(k)
    b = S.aggregate(g, 5)
    raw = _klines(60)
    for i in range(12):
        seg = raw.iloc[i * 5:(i + 1) * 5]
        if i == 3:                                       # minute 17 missing -> bar 3 incomplete
            assert not b["complete"][i]
            continue
        assert b["complete"][i]
        assert np.isclose(b["open"][i], seg["open"].iloc[0])
        assert np.isclose(b["high"][i], seg["high"].max())
        assert np.isclose(b["low"][i], seg["low"].min())
        assert np.isclose(b["close"][i], seg["close"].iloc[-1])
        assert np.isclose(b["volume"][i], seg["volume"].sum())
    assert b["entry_min"][0] == 5                        # earliest entry = next 1m open after the bar closed


def test_signals_do_not_look_ahead():
    """Changing data after bar k never changes the signals up to bar k."""
    k = _klines(6000, seed=4)
    g1 = S.to_grid(k)
    k2 = k.copy()
    cut = 4000
    k2.loc[cut:, ["open", "high", "low", "close"]] *= 1.3
    k2.loc[cut:, "volume"] *= 5
    g2 = S.to_grid(k2)
    for tf in (5, 15):
        b1, b2 = S.aggregate(g1, tf), S.aggregate(g2, tf)
        last = cut // tf - 1                             # last bar fully before the change
        for fam, (fn, plist) in S.FAMILIES.items():
            for p in plist:
                s1, st1 = fn(b1, p, {"atr": S.atr(b1)})
                s2, st2 = fn(b2, p, {"atr": S.atr(b2)})
                assert np.array_equal(s1[:last + 1], s2[:last + 1]), fam
                assert np.allclose(np.nan_to_num(st1[:last + 1]), np.nan_to_num(st2[:last + 1])), fam


def _sim(g, entry, side, P, sd, tmax=50, limit=False):
    return S.simulate(g["open"], g["high"], g["low"], g["close"], g["valid"], np.array([entry], np.int64),
                      np.array([side], np.int64), np.array([P]), np.array([sd]), 1.0, 2.0, tmax, limit, 3)


def test_stop_checked_before_target_in_same_bar():
    # entry at open 100 (minute 1); minute 1 spans both stop 99 and TP1 101 -> stopped at the stop
    g = _grid([100, 100, 100], [100, 101.5, 100], [100, 98.5, 100], [100, 100, 100])
    taken, ei, ep, x1, t1, i1, x2, t2, i2 = _sim(g, 1, 1, 100.0, 1.0)
    assert taken[0] and ep[0] == 100 and x1[0] == 99 and x2[0] == 99 and t1[0] == 1 and t2[0] == 1


def test_gap_stop_fills_at_open_and_tp_then_break_even():
    # long, entry 100 at minute 1; minute 2 gaps open 98 below the stop 99 -> fill 98
    g = _grid([100, 100, 98], [100, 100.2, 98.5], [100, 99.8, 97], [100, 100, 98])
    r = _sim(g, 1, 1, 100.0, 1.0)
    assert r[3][0] == 98 and r[6][0] == 98
    # TP1 at 101 (traded through) then later back to entry -> second half at break-even
    g = _grid([100, 100, 100.5, 100.5], [100, 100.3, 101.2, 100.6], [100, 99.9, 100.4, 99.95], [100, 100, 100.5, 100])
    r = _sim(g, 1, 1, 100.0, 1.0)
    assert r[3][0] == 101 and r[4][0] == 0 and r[6][0] == 100 and r[7][0] == 1
    # a short: TP1 and TP2 must trade through
    g = _grid([100, 100, 99.5, 98.5], [100, 100.1, 99.6, 98.6], [100, 99.5, 98.9, 97.9], [100, 99.6, 99, 98])
    r = _sim(g, 1, -1, 100.0, 1.0)
    assert r[3][0] == 99 and r[6][0] == 98 and r[7][0] == 0


def test_limit_entry_needs_trade_through_and_time_exit():
    # limit long at 100: minutes 1-3 never trade below 100 -> no trade
    g = _grid([100.2] * 6, [100.5] * 6, [100.0] * 6, [100.2] * 6)
    assert not _sim(g, 1, 1, 100.0, 1.0, limit=True)[0][0]
    # trades through at minute 2 -> filled at 100; nothing hit for 3 minutes -> time exit at the close
    g = _grid([100.2, 100.2, 100.1, 100.2, 100.3, 100.3], [100.5] * 6, [100.1, 100.1, 99.9, 100.0, 100.1, 100.1],
              [100.2, 100.2, 100.1, 100.2, 100.4, 100.3])
    r = _sim(g, 1, 1, 100.0, 1.0, tmax=3, limit=True)
    assert r[0][0] and r[1][0] == 2 and r[2][0] == 100.0 and r[7][0] == 2 and r[8][0] == 4 and r[6][0] == 100.4


def test_cost_math():
    df = pd.DataFrame({"side": [1, 1], "E": [100.0, 100.0], "sd": [1.0, 1.0], "x1": [101.0, 99.0], "t1": [0, 1],
                       "x2": [102.0, 99.0], "t2": [0, 1], "fund": [0.0001, 0.0], "limit": [False, True],
                       "m1": [5, 5], "m2": [9, 5], "e_min": [1, 1]})
    out = S.apply_costs(df, S.FEES_BASE)
    # trade 1: gross +1.5 %, cost taker+slip entry 0.07 % + maker 0.02 % exits + funding 0.01 %
    assert np.isclose(out["gross_pct"][0], 0.015)
    assert np.isclose(out["cost_pct"][0], 0.0005 + 0.0002 + 0.0002 + 0.0001)
    assert np.isclose(out["net_r"][0], (0.015 - 0.001) / 0.01)
    # trade 2: maker entry, stopped: taker + stop slippage
    assert np.isclose(out["cost_pct"][1], 0.0002 + 0.0005 + 0.0003)
    assert np.isclose(out["gross_r"][1], -1.0)


def test_one_position_at_a_time():
    g = _grid([100] * 20, [100.05] * 20, [99.95] * 20, [100] * 20)
    r = S.simulate(g["open"], g["high"], g["low"], g["close"], g["valid"], np.array([1, 3, 12], np.int64),
                   np.array([1, 1, 1], np.int64), np.full(3, 100.0), np.full(3, 1.0), 1.0, 2.0, 8, False, 3)
    assert list(r[0]) == [True, False, True]              # second signal falls inside the first trade (exit minute 8)


def test_month_list_and_bootstrap():
    from datetime import date
    assert S.month_list(3, date(2026, 1, 15)) == ["2025-10", "2025-11", "2025-12"]
    df = pd.DataFrame({"net_r": np.r_[np.full(50, 0.5), np.full(50, -0.1)], "day": np.repeat(np.arange(20), 5)})
    b = S.block_boot(df, n_boot=300)
    assert b["ci95"][0] <= b["mean"] <= b["ci95"][1]
    assert S.max_dd(np.array([1, -2, -1, 3])) == 3.0
