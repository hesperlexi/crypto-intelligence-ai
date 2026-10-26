"""Trade filter: trades are replayed under the bots' rules, and the filter only switches on when it helps on unseen data."""
import numpy as np

from app.ml import trade_filter as T


def test_trade_r_follows_the_bot_rules():
    atr = np.full(40, 1.0)
    close = np.full(40, 100.0)
    # long: stop 98.5 (1.5 ATR), targets 101.5 / 102.625 / 103.75 (1R / 1.75R / 2.5R), closing 50% / 25% / 25%
    high = close.copy(); low = close.copy()
    high[1], low[1] = 101.6, 99.9            # target 1: half off, stop to break-even
    high[2], low[2] = 102.7, 101.6           # target 2: a quarter off, stop trails to target 1
    high[3], low[3] = 102.0, 101.4           # back down: trailing stop at target 1 (101.5)
    r = T.trade_r(high, low, close, atr, 0, 1, 0.0)
    assert abs(r - (0.5 * 1.0 + 0.25 * 1.75 + 0.25 * 1.0)) < 1e-9
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


def test_target_model_lifts_only_where_it_beats_the_average():
    """Setups whose x0 > 0 run much further: the model learns it (on unseen calls) and lifts their far targets;
    on pure noise it stays off."""
    from app.ml import target_model as TM

    def market(n, seed, informative):
        rng = np.random.default_rng(seed)
        L = n * 40
        close = np.full(L, 100.0); high = close.copy(); low = close.copy(); atr = np.full(L, 1.0)
        rows = np.arange(n) * 40
        X = rng.normal(size=(n, 5))
        P = np.tile([0.25, 0.25, 0.5], (n, 1))
        for k, r in enumerate(rows):
            far = (X[k, 0] > 0) if informative else rng.random() < 0.5
            run = rng.uniform(3.2, 4.8) if far else rng.uniform(0.3, 2.2)     # in ATRs; the stop is 1.5 ATR
            high[r + 1:r + 6] = 100 + run
            low[r + 1:r + 6] = 99.9
        return X, P, rows, high, low, close, atr

    tm = TM.train(*market(1600, 1, True))
    assert tm["enabled"] and 2.5 in tm["models"]
    x_far, x_near = np.array([2.0, 0, 0, 0, 0]), np.array([-2.0, 0, 0, 0, 0])
    probs = {"down": 0.25, "neutral": 0.25, "up": 0.5}
    assert TM.lifts(tm, x_far, probs)["long"][2.5] > 1.3 > TM.lifts(tm, x_near, probs)["long"].get(2.5, 1.0)
    noise = TM.train(*market(1600, 2, False))
    assert not noise["enabled"] or len(noise["models"]) <= 2
