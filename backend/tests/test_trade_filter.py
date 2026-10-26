"""Trade filter: trades are replayed under the bots' rules, and the filter only switches on when it helps on unseen data."""
import numpy as np

from app.ml import trade_filter as T


def test_trade_r_follows_the_bot_rules():
    atr = np.full(40, 1.0)
    close = np.full(40, 100.0)
    # long: stop 98.5 (1.5 ATR), targets 100.75 / 101.125 / 101.5 (0.5R / 0.75R / 1R)
    high = close.copy(); low = close.copy()
    high[1], low[1] = 100.8, 99.9            # target 1
    high[2], low[2] = 101.2, 100.9           # target 2 (stop now at entry, then trails to target 1)
    high[3], low[3] = 101.0, 100.7           # back down: trailing stop at target 1 (100.75)
    r = T.trade_r(high, low, close, atr, 0, 1, 0.0)
    assert abs(r - (0.5 + 0.75 + 0.5) / 3) < 1e-9
    high2, low2 = close.copy(), close.copy(); low2[1], high2[1] = 98.0, 103.0      # stop and target in one candle
    assert abs(T.trade_r(high2, low2, close, atr, 0, 1, 0.0) + 1.0) < 1e-9          # the stop counts first
    assert T.trade_r(high, low, close, atr, 20, 1, 0.0) is None                     # future unknown


def _market(n, seed, informative):
    """Each candidate's trade result depends on feature x0 when `informative`, otherwise it is noise."""
    rng = np.random.default_rng(seed)
    L = n * 40
    close = np.full(L, 100.0); high = close.copy(); low = close.copy(); atr = np.full(L, 1.0)
    rows = np.arange(n) * 40
    X = rng.normal(size=(n, 5))
    P = np.tile([0.25, 0.25, 0.5], (n, 1))                     # leaning long
    for k, r in enumerate(rows):
        good = (X[k, 0] > 0) if informative else rng.random() < 0.5
        if good if informative else good:
            win = rng.random() < (0.8 if informative else 0.5)
        else:
            win = rng.random() < 0.2
        if win:
            high[r + 1:r + 6] = 106.5
        else:
            low[r + 1:r + 6] = 98.0
    return X, P, rows, high, low, close, atr


def test_filter_switches_on_only_when_it_helps():
    on = T.train(*_market(1600, 1, True), cost_rate=0.0)
    assert on["enabled"] and on["exam"]["avg_r_kept"] > on["exam"]["avg_r_all"] + 0.3
    s = T.score(on, np.array([1.5, 0, 0, 0, 0]), {"down": 0.25, "neutral": 0.25, "up": 0.5})
    s_bad = T.score(on, np.array([-1.5, 0, 0, 0, 0]), {"down": 0.25, "neutral": 0.25, "up": 0.5})
    assert s["p_long"] > s["threshold"] > s_bad["p_long"]
    off = T.train(*_market(1600, 2, False), cost_rate=0.0)
    assert not off["enabled"] and T.score(off, np.zeros(5), {"down": 0.3, "neutral": 0.3, "up": 0.4}) is None
