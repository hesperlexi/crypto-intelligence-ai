"""v2.78 market-turn watch: coin break against a call (recommend-only + shadow)."""
import numpy as np
import pandas as pd

from app.services import guardian as G
from app.services import turn_watch as TW

H = 3_600_000


class _RT:
    def __init__(self, closes):
        n = len(closes)
        c = np.array(closes, float)
        self.df = pd.DataFrame({"ts": np.arange(n) * 4 * H, "open": c, "high": c + 0.1, "low": c - 0.1, "close": c})

    def candles(self, s, tf):
        return self.df


def test_break_up_is_against_a_short_only():
    rt = _RT([100.0] * 30 + [102.0])                     # last 4h candle closes above the 2-day range
    now = int(rt.df["ts"].iloc[-1]) + 4 * H + 1000
    assert TW.against(rt, "X/USDT", -1, now)["broke"] is True
    assert TW.against(rt, "X/USDT", 1, now)["broke"] is False
    assert TW.against(rt, "X/USDT", -1, now + 30 * H)["broke"] is False        # older than 24 h


def _rows(price):
    return [(i * 60_000, price, price, price, price) for i in range(80)]


def test_guardian_locks_profit_only_when_in_profit():
    call = {"symbol": "SOL/USDT", "timeframe": "4h", "side": -1, "entry": 100.0, "stop": 102.0, "tp1_hit": False}
    turn = {"broke": True, "at": 1, "level": 99.0, "close": 99.2}
    win = G.assess(call, _rows(99.0), 0.5, 102.0, None, None, None, turn)       # short in profit (+0.5R)
    assert any(r["code"] == "turn" for r in win["reasons"]) and win["band"] == "CLOSE"
    lose = G.assess(call, _rows(101.0), 0.5, 102.0, None, None, None, turn)     # short losing: stop handles it
    assert not any(r["code"] == "turn" for r in lose["reasons"])


def test_shadow_log_once_per_call(tmp_path):
    from app.db import Database
    db = Database(f"sqlite:///{tmp_path}/x.db")
    assert TW.log_first(db, "a", {"r_now": 0.4}) is True
    assert TW.log_first(db, "a", {"r_now": 0.9}) is False
    assert len(db.get_setting(TW.LOG)) == 1
