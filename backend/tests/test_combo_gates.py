"""v2.22 combination gates (volume profile, fee, same-side cap)."""
import numpy as np
import pandas as pd

from app.db import Database
from app.services import combo_gates as CG


def _df(prices, vols):
    p = np.asarray(prices, float)
    return pd.DataFrame({"ts": np.arange(len(p)) * 1000, "open": p, "high": p * 1.001, "low": p * 0.999, "close": p,
                         "volume": np.asarray(vols, float)})


def test_profile_finds_the_heavy_row():
    n = 200
    prices = np.r_[np.linspace(90, 110, n - 50), np.full(50, 105.0)]
    vols = np.r_[np.ones(n - 50), np.full(50, 50.0)]
    p = CG.profile(*(_df(prices, vols)[k].to_numpy(float) for k in ("high", "low", "close", "volume")))
    assert abs(p["poc"] - 105) < 0.5 and p["val"] <= p["poc"] <= p["vah"]


def test_volume_wall_blocks_a_long_just_below_it_but_not_a_short():
    n = 200
    prices = np.r_[np.linspace(90, 110, n - 50), np.full(50, 105.0)]
    vols = np.r_[np.ones(n - 50), np.full(50, 50.0)]
    df = _df(prices, vols)
    assert CG.vp_block(df, +1, 104.8, atr=1.0)            # POC 0.2 ATR above a long
    assert CG.vp_block(df, -1, 104.8, atr=1.0) is None     # behind a short: fine
    assert CG.vp_block(df, +1, 102.0, atr=1.0) is None     # 3 ATR away: fine
    assert CG.vp_block(df.head(50), +1, 104.8, atr=1.0) is None   # too little history: never blocks


def test_fee_filter_only_on_1h_4h():
    assert CG.fee_block("1h", 100.0, 99.0)                 # 1 % stop
    assert CG.fee_block("4h", 100.0, 98.0) is None         # 2 %
    assert CG.fee_block("15m", 100.0, 99.5) is None        # 15m left out


def test_same_side_cap():
    db = Database("sqlite:///:memory:")
    for i in range(CG.SAME_SIDE_CAP):
        db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, status, fill_status) "
                   "VALUES (?, 0, ?, '4h', ?, 'SELL', 'SELL', 1, -1, 'OPEN', 'FILLED')", (f"s{i}", f"C{i}/USDT", i))
    assert CG.cap_block(db, -1) and CG.cap_block(db, +1) is None
    db.execute("UPDATE signals SET fill_status = 'PENDING' WHERE id = 's0'")      # a pending limit is not a running trade
    assert CG.cap_block(db, -1) is None


def test_same_side_cap_reserves_one_slot_per_timeframe():
    """v2.68: when the limit is full, a timeframe with no running call on that side may still open one."""
    db = Database("sqlite:///:memory:")
    for i in range(CG.SAME_SIDE_CAP):
        db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, status, fill_status) "
                   "VALUES (?, 0, ?, '4h', ?, 'BUY', 'BUY', 1, 1, 'OPEN', 'FILLED')", (f"s{i}", f"C{i}/USDT", i))
    assert CG.cap_block(db, 1, "4h")                       # 4h already has calls: blocked
    assert CG.cap_block(db, 1, "15m") is None              # 15m has none: its reserved slot
    db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, status, fill_status) "
               "VALUES ('r', 0, 'X/USDT', '15m', 1, 'BUY', 'BUY', 1, 1, 'OPEN', 'FILLED')")
    assert CG.cap_block(db, 1, "15m")                      # the slot is used
