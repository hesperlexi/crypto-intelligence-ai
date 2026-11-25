"""v2.79 liquidity-sweep guard (owner, 23 Nov 2026: "stop run / liquidity grab -> that's where things change").

PROVEN before going live (`app/research_sweep.py`, `research-results/results/sweep-latest.json`, 921 unseen calls,
baseline = the live pipeline): no new SHORT within 6 h after a bullish sweep on the coin's 1h chart, no new LONG within 6 h
after a bearish one -> +19.8R -> +39.1R, max drawdown 45.0R -> 31.6R, better in both halves (1.2 -> 11.3, 18.6 -> 27.8),
bootstrap 94 %, 204 calls held back: PASS. (Trading the sweeps themselves as signals lost heavily - not used.)

A sweep = a 1h candle that pokes >= 0.1 ATR beyond the lowest low (highest high) of the previous 48 hours - where the
stop-losses sit - and CLOSES back inside the range: the stop run and the reclaim in one candle. Env SWEEP_GUARD=0 turns
the guard off; SWEEP_GUARD_HOURS (6) is the window.

V3.2 (Fable 5.2 audit R-01) fail closed: `status()` says "block", "clear" or "unavailable" (the coin's 1h candles cannot
be read, fewer than POOL + 16 of them, the newest closed one older than MAX_AGE_H hours, or the check raised).
`analysis.analyze` turns "unavailable" into NO TRADE "CHECK UNAVAILABLE" for new entries only."""
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
MIN_BARS = POOL + 16
MAX_AGE_H = float(os.environ.get("SWEEP_GUARD_MAX_AGE_H", "2"))


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


def status(rt: Any, symbol: str, side: int, now: int | None = None) -> dict[str, Any]:
    """{'state': 'block' | 'clear' | 'unavailable', 'hit': sweep or None, 'reason': why unavailable or None}."""
    if not ON or not side:
        return {"state": "clear", "hit": None, "reason": None}
    now = int(time.time() * 1000) if now is None else int(now)
    try:
        df = rt.candles(symbol, "1h")
        if df is None or len(df) == 0:
            return {"state": "unavailable", "hit": None, "reason": f"no {symbol} 1h candles"}
        closes = df["ts"].to_numpy(np.int64) + H
        n = int((closes <= now).sum())
        if n < MIN_BARS:
            return {"state": "unavailable", "hit": None,
                    "reason": f"insufficient {symbol} 1h history ({n} of {MIN_BARS} candles)"}
        age_h = (now - int(closes[closes <= now][-1])) / H
        if age_h > MAX_AGE_H:
            return {"state": "unavailable", "hit": None,
                    "reason": f"{symbol} 1h data is stale (newest closed candle {age_h:.1f} h old, limit {MAX_AGE_H:g} h)"}
        s = recent_sweep(df, now)
    except Exception as exc:
        return {"state": "unavailable", "hit": None, "reason": f"{type(exc).__name__}: {exc}"[:160]}
    if s and s["side"] == -side:
        return {"state": "block", "hit": s, "reason": None}
    return {"state": "clear", "hit": None, "reason": None}


def against(rt: Any, symbol: str, side: int, now: int | None = None) -> dict[str, Any] | None:
    """The sweep that stands against a new call on `side` (a bullish sweep against a short, a bearish one against a
    long), or None (clear or unavailable). Live decisions use `status()` (fail closed)."""
    return status(rt, symbol, side, now)["hit"]


def reason(s: dict[str, Any], side: int) -> str:
    where = "lows" if s["side"] > 0 else "highs"
    hrs = f"{HOURS:g}"
    return (f"liquidity sweep: price just ran the stops below the recent {where} and closed back inside (a stop run that "
            f"often turns the market), so no new {'short' if side < 0 else 'long'} for {hrs} hours")
