"""v2.79 liquidity-sweep guard (owner, 23 Nov 2026: "stop run / liquidity grab -> that's where things change").

PROVEN before going live (`app/research_sweep.py`, `research-results/results/sweep-latest.json`, 921 unseen calls,
baseline = the live pipeline): no new SHORT within 6 h after a bullish sweep on the coin's 1h chart, no new LONG within 6 h
after a bearish one -> +19.8R -> +39.1R, max drawdown 45.0R -> 31.6R, better in both halves (1.2 -> 11.3, 18.6 -> 27.8),
bootstrap 94 %, 204 calls held back: PASS. (Trading the sweeps themselves as signals lost heavily - not used.)

A sweep = a 1h candle that pokes >= 0.1 ATR beyond the lowest low (highest high) of the previous 48 hours - where the
stop-losses sit - and CLOSES back inside the range: the stop run and the reclaim in one candle. Env SWEEP_GUARD=0 turns
the guard off; SWEEP_GUARD_HOURS (6) is the window."""
from __future__ import annotations

import os
import time
from typing import Any

import numpy as np
import pandas as pd

H = 3_600_000
POOL = 48
POKE_ATR = 0.1
ON = os.environ.get("SWEEP_GUARD", "1") != "0"
HOURS = float(os.environ.get("SWEEP_GUARD_HOURS", "6"))
FLAG = "LIQUIDITY SWEEP"


def recent_sweep(df: pd.DataFrame, now: int, hours: float = HOURS) -> dict[str, Any] | None:
    """The newest sweep on closed 1h candles whose candle closed within `hours` before `now`:
    {'side': +1 bullish (lows swept, reclaimed) / -1 bearish, 'at': close time, 'level', 'extreme'} or None."""
    if df is None or len(df) < POOL + 16:
        return None
    d = df.tail(POOL + 40).reset_index(drop=True)
    h, l, c = (d[k].to_numpy(float) for k in ("high", "low", "close"))
    ts = d["ts"].to_numpy(np.int64)
    prev = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))
    atr = pd.Series(tr).rolling(14, min_periods=1).mean().to_numpy()
    best = None
    for i in range(POOL, len(c)):
        close_at = int(ts[i]) + H
        if not (now - hours * H < close_at <= now):
            continue
        lo, hi = l[i - POOL:i].min(), h[i - POOL:i].max()
        if l[i] <= lo - POKE_ATR * atr[i] and c[i] > lo:
            best = {"side": 1, "at": close_at, "level": float(lo), "extreme": float(l[i])}
        elif h[i] >= hi + POKE_ATR * atr[i] and c[i] < hi:
            best = {"side": -1, "at": close_at, "level": float(hi), "extreme": float(h[i])}
    return best


def against(rt: Any, symbol: str, side: int, now: int | None = None) -> dict[str, Any] | None:
    """The sweep that stands against a new call on `side` (a bullish sweep against a short, a bearish one against a
    long), or None."""
    if not ON or not side:
        return None
    try:
        df = rt.candles(symbol, "1h")
    except Exception:
        return None
    s = recent_sweep(df, int(time.time() * 1000) if now is None else int(now))
    return s if s and s["side"] == -side else None


def reason(s: dict[str, Any], side: int) -> str:
    where = "lows" if s["side"] > 0 else "highs"
    hrs = f"{HOURS:g}"
    return (f"liquidity sweep: price just ran the stops below the recent {where} and closed back inside (a stop run that "
            f"often turns the market), so no new {'short' if side < 0 else 'long'} for {hrs} hours")
