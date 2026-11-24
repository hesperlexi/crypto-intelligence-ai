"""V3.0 BTC shock guard: an unusually large BTC 12 h move (in its own normal size) blocks new calls against it for 6 h."""
import numpy as np
import pandas as pd

from app.services import btc_shock

H = 3_600_000


class RT:
    def __init__(self, closes):
        n = len(closes)
        self.now = (n + 1) * H
        self.df = pd.DataFrame({"ts": np.arange(n) * H, "close": closes})

    def candles(self, s, tf):
        return self.df


def series(jump=0.0):
    rng = np.random.default_rng(3)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, 900)))
    if jump:
        c[-6:] *= 1 + jump
    return c


def test_up_shock_blocks_shorts_only():
    btc_shock._cache.clear()
    rt = RT(series(0.06))
    assert btc_shock.against(rt, -1, rt.now) is not None
    assert btc_shock.against(rt, 1, rt.now) is None


def test_calm_market_blocks_nothing():
    btc_shock._cache.clear()
    rt = RT(series(0.0))
    assert btc_shock.against(rt, -1, rt.now) is None and btc_shock.against(rt, 1, rt.now) is None


def test_old_shock_expires():
    btc_shock._cache.clear()
    rt = RT(series(0.06))
    assert btc_shock.against(rt, -1, rt.now + 12 * H) is None
