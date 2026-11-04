"""AI research v3 stress study (research only): stress-window detection on BTC candles / open interest."""
import numpy as np
import pandas as pd

from app import research_stress as RS

DAY, HOUR = RS.DAY, RS.HOUR
T0 = 1_750_000_000_000 // DAY * DAY


def _hourly(closes):
    c = np.asarray(closes, float)
    return pd.DataFrame({"ts": T0 + np.arange(len(c)) * HOUR, "open": c, "high": c * 1.001, "low": c * 0.999, "close": c})


def test_btc_drop_window_covers_the_drop_day_and_the_next_three():
    d1 = pd.DataFrame({"ts": T0 + np.arange(10) * DAY, "close": [100, 101, 100, 94, 95, 96, 96, 97, 97, 98.0]})
    w = RS.market_windows(d1, _hourly(np.full(300, 100.0)), None)
    assert w["btc_drop"] == [(T0 + 3 * DAY, T0 + 7 * DAY)] and w["btc_drop_days"] == [T0 + 3 * DAY]
    ts = np.array([T0 + 2 * DAY, T0 + 3 * DAY, T0 + 6 * DAY + HOUR, T0 + 7 * DAY])
    assert list(RS.in_windows(ts, w["btc_drop"])) == [False, True, True, False]


def test_reversal_needs_an_opposite_move_within_48h_and_liquidation_needs_oi():
    up = list(np.full(30, 100.0)) + list(np.linspace(100, 105, 24)) + list(np.linspace(105, 101.5, 20)) + list(np.full(100, 101.5))
    d1 = pd.DataFrame({"ts": T0 + np.arange(10) * DAY, "close": np.full(10, 100.0)})
    w = RS.market_windows(d1, _hourly(up), None)
    assert w["reversal"] and w["liq_cascade"] == [] and w["oi_history_days"] == 0.0
    flat = list(np.full(30, 100.0)) + list(np.linspace(100, 105, 24)) + list(np.full(100, 105.0))
    assert RS.market_windows(d1, _hourly(flat), None)["reversal"] == []
    # open interest -10 % over 24 h with a 5 % fall: a liquidation-cascade proxy
    h = _hourly(list(np.full(30, 100.0)) + list(np.linspace(100, 95, 24)) + list(np.full(50, 95.0)))
    oi = pd.DataFrame({"ts": h["ts"], "oi": np.r_[np.full(30, 1000.0), np.linspace(1000, 880, 24), np.full(50, 880.0)]})
    assert RS.market_windows(d1, h, oi)["liq_cascade"]


def test_merge_intervals():
    assert RS._merge([(5, 9), (1, 3), (2, 6), (20, 21)]) == [(1, 9), (20, 21)]
