"""v2.79 liquidity-sweep guard: no new call against a fresh stop run (proven in research_sweep.py)."""
import numpy as np
import pandas as pd

from app.services import sweep_guard as SG

H = 3_600_000


def _df(sweep_at: int, bullish: bool = True, n: int = 120):
    c = np.full(n, 100.0)
    h, l = c + 0.5, c - 0.5
    if bullish:
        l[sweep_at], c[sweep_at] = 97.0, 100.2          # ran the lows' stops, closed back inside
    else:
        h[sweep_at], c[sweep_at] = 103.0, 99.8
    return pd.DataFrame({"ts": np.arange(n) * H, "open": c, "high": h, "low": l, "close": c, "volume": 1.0})


class _RT:
    def __init__(self, df):
        self.df = df

    def candles(self, s, tf):
        return self.df


def test_bullish_sweep_blocks_shorts_only_for_6_hours():
    df = _df(110)
    close_at = 110 * H + H
    rt = _RT(df)
    assert SG.against(rt, "X/USDT", -1, close_at + 2 * H)["side"] == 1
    assert SG.against(rt, "X/USDT", 1, close_at + 2 * H) is None
    assert SG.against(rt, "X/USDT", -1, close_at + 7 * H) is None


def test_bearish_sweep_blocks_longs():
    rt = _RT(_df(115, bullish=False))
    assert SG.against(rt, "X/USDT", 1, 116 * H + 1)["side"] == -1
    assert "no new long" in SG.reason({"side": -1}, 1)


def test_no_sweep_without_reclaim():
    df = _df(110)
    df.loc[110, "close"] = 96.0                           # broke down and stayed down: not a sweep
    assert SG.against(_RT(df), "X/USDT", -1, 111 * H + 1) is None
