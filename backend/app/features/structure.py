"""Market-structure engine: swings, BOS / CHoCH, zones, liquidity, divergences.

Causality: a swing at bar c needs k bars on each side, so it only becomes *known* at bar c + k.
Every per-bar output below respects that confirmation delay.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view


def find_swings(high: np.ndarray, low: np.ndarray, k: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Boolean arrays marking pivot highs / lows (centered window; apply the k-bar confirmation lag)."""
    n = len(high)
    is_sh, is_sl = np.zeros(n, bool), np.zeros(n, bool)
    if n >= 2 * k + 1:
        is_sh[k:n - k] = sliding_window_view(high, 2 * k + 1).argmax(axis=1) == k
        is_sl[k:n - k] = sliding_window_view(low, 2 * k + 1).argmin(axis=1) == k
    return is_sh, is_sl


def market_structure(df: pd.DataFrame, k: int = 3, false_break_bars: int = 5) -> tuple[pd.DataFrame, list[dict]]:
    """Per-bar structure state plus the list of confirmed swings.

    Columns: struct_trend (+1 bullish / -1 bearish / 0 undefined), bos, choch (+1 up / -1 down on the event
    bar), last_sh, last_sl, prev_sh, prev_sl, sh_label (+1 HH / -1 LH), sl_label (+1 HL / -1 LL),
    false_breakout (+1 failed breakdown = bullish, -1 failed breakout = bearish).
    """
    high, low, close = (df[c].to_numpy(float) for c in ("high", "low", "close"))
    n = len(df)
    is_sh, is_sl = find_swings(high, low, k)
    trend = np.zeros(n)
    bos, choch, fb = np.zeros(n), np.zeros(n), np.zeros(n)
    a_last_sh, a_last_sl = np.full(n, np.nan), np.full(n, np.nan)
    a_prev_sh, a_prev_sl = np.full(n, np.nan), np.full(n, np.nan)
    a_shl, a_sll = np.zeros(n), np.zeros(n)
    swings: list[dict[str, Any]] = []
    last_sh = prev_sh = last_sl = prev_sl = np.nan
    sh_broken = sl_broken = True
    shl = sll = 0.0
    cur = 0.0
    pending: list[tuple[int, float, int]] = []  # (bar of break, level, direction)
    for t in range(n):
        c = t - k
        if c >= k:
            if is_sh[c]:
                prev_sh, last_sh, sh_broken = last_sh, high[c], False
                shl = 0.0 if np.isnan(prev_sh) else (1.0 if last_sh > prev_sh else -1.0)
                swings.append({"pos": c, "confirm_pos": t, "price": float(high[c]), "kind": "high",
                               "label": "HH" if shl > 0 else ("LH" if shl < 0 else "H")})
            if is_sl[c]:
                prev_sl, last_sl, sl_broken = last_sl, low[c], False
                sll = 0.0 if np.isnan(prev_sl) else (1.0 if last_sl > prev_sl else -1.0)
                swings.append({"pos": c, "confirm_pos": t, "price": float(low[c]), "kind": "low",
                               "label": "HL" if sll > 0 else ("LL" if sll < 0 else "L")})
        if not sh_broken and close[t] > last_sh:
            sh_broken = True
            if cur < 0:
                choch[t] = 1
            else:
                bos[t] = 1
            cur = 1.0
            pending.append((t, last_sh, 1))
        elif not sl_broken and close[t] < last_sl:
            sl_broken = True
            if cur > 0:
                choch[t] = -1
            else:
                bos[t] = -1
            cur = -1.0
            pending.append((t, last_sl, -1))
        if pending:
            keep = []
            for t0, level, d in pending:
                if t == t0:
                    keep.append((t0, level, d))
                elif t - t0 <= false_break_bars:
                    if (d > 0 and close[t] < level) or (d < 0 and close[t] > level):
                        fb[t] = -d       # the break failed: signal points the other way
                    else:
                        keep.append((t0, level, d))
            pending = keep
        trend[t] = cur
        a_last_sh[t], a_last_sl[t], a_prev_sh[t], a_prev_sl[t] = last_sh, last_sl, prev_sh, prev_sl
        a_shl[t], a_sll[t] = shl, sll
    out = pd.DataFrame({
        "struct_trend": trend, "bos": bos, "choch": choch, "false_breakout": fb,
        "last_sh": a_last_sh, "last_sl": a_last_sl, "prev_sh": a_prev_sh, "prev_sl": a_prev_sl,
        "sh_label": a_shl, "sl_label": a_sll,
    }, index=df.index)
    return out, swings


def divergences(df: pd.DataFrame, swings: list[dict], osc: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Regular divergences between price swings and an oscillator, flagged on the swing's confirmation bar.

    bullish: price lower low + oscillator higher low; bearish: price higher high + oscillator lower high.
    """
    n = len(df)
    bull, bear = np.zeros(n), np.zeros(n)
    o = osc.to_numpy(float)
    prev = {"high": None, "low": None}
    for s in swings:
        p = prev[s["kind"]]
        if p is not None and np.isfinite(o[s["pos"]]) and np.isfinite(o[p["pos"]]):
            if s["kind"] == "low" and s["price"] < p["price"] and o[s["pos"]] > o[p["pos"]]:
                bull[s["confirm_pos"]] = 1
            if s["kind"] == "high" and s["price"] > p["price"] and o[s["pos"]] < o[p["pos"]]:
                bear[s["confirm_pos"]] = 1
        prev[s["kind"]] = s
    return bull, bear


def sr_zones(swings: list[dict], price: float, atr: float, n_bars: int, lookback: int = 400,
             max_zones: int = 6) -> dict[str, list[dict]]:
    """Cluster confirmed swing prices into support / resistance zones around the current price."""
    if not swings or not np.isfinite(atr) or atr <= 0:
        return {"support": [], "resistance": []}
    recent = sorted((s for s in swings if s["pos"] >= n_bars - lookback), key=lambda s: s["price"])
    tol = 0.6 * atr
    clusters: list[list[dict]] = []
    for s in recent:
        if clusters and s["price"] - clusters[-1][-1]["price"] <= tol:
            clusters[-1].append(s)
        else:
            clusters.append([s])
    zones = []
    for cl in clusters:
        lo, hi = cl[0]["price"], cl[-1]["price"]
        pad = max(0.0, 0.25 * atr - (hi - lo)) / 2
        lo, hi = lo - pad, hi + pad
        last_touch = max(s["pos"] for s in cl)
        recency = 1.0 - min(1.0, (n_bars - 1 - last_touch) / lookback)
        zones.append({"low": float(lo), "high": float(hi), "mid": float((lo + hi) / 2), "touches": len(cl),
                      "last_touch_pos": int(last_touch), "strength": round(len(cl) * (0.5 + 0.5 * recency), 3)})
    support = sorted((z for z in zones if z["high"] < price), key=lambda z: price - z["high"])[:max_zones]
    resistance = sorted((z for z in zones if z["low"] > price), key=lambda z: z["low"] - price)[:max_zones]
    for z in support:
        z["distance_pct"] = float((z["high"] / price - 1) * 100)
    for z in resistance:
        z["distance_pct"] = float((z["low"] / price - 1) * 100)
    return {"support": support, "resistance": resistance}


def liquidity_zones(df: pd.DataFrame, swings: list[dict], atr: float, lookback: int = 300) -> list[dict]:
    """Resting-liquidity estimates: unswept swing highs/lows (stops cluster just beyond them).

    Equal highs / equal lows (>= 2 swings within 0.25 ATR) are marked as stronger pools.
    `hunt_zone` is the band just past the level where a stop-run would be expected to reach.
    """
    n = len(df)
    if not swings or not np.isfinite(atr) or atr <= 0:
        return []
    high, low = df["high"].to_numpy(float), df["low"].to_numpy(float)
    out = []
    for kind in ("high", "low"):
        pts = [s for s in swings if s["kind"] == kind and s["pos"] >= n - lookback]
        live = []
        for s in pts:  # unswept = no later bar traded through the level
            after = high[s["pos"] + 1:] if kind == "high" else low[s["pos"] + 1:]
            swept = (after.max() > s["price"]) if (kind == "high" and len(after)) else \
                    (after.min() < s["price"]) if len(after) else False
            if not swept:
                live.append(s)
        live.sort(key=lambda s: s["price"])
        used: set[int] = set()
        for i, s in enumerate(live):
            if i in used:
                continue
            group = [s] + [live[j] for j in range(i + 1, len(live))
                           if abs(live[j]["price"] - s["price"]) <= 0.25 * atr and not used.add(j)]
            level = max(g["price"] for g in group) if kind == "high" else min(g["price"] for g in group)
            hunt = (level, level + 0.5 * atr) if kind == "high" else (level - 0.5 * atr, level)
            out.append({"side": "buy-side (above highs)" if kind == "high" else "sell-side (below lows)",
                        "kind": kind, "level": float(level), "equal_levels": len(group),
                        "hunt_zone": [float(hunt[0]), float(hunt[1])]})
    return out


def supply_demand_zones(df: pd.DataFrame, atr: pd.Series, impulse_atr: float = 1.5, lookback: int = 300,
                        max_zones: int = 4) -> dict[str, list[dict]]:
    """Origin candles of impulsive moves that price has not yet closed back through."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    a = atr.to_numpy(float)
    n = len(df)
    demand, supply = [], []
    for i in range(max(1, n - lookback), n):
        if not np.isfinite(a[i]) or a[i] <= 0:
            continue
        body = c[i] - o[i]
        if body > impulse_atr * a[i]:          # bullish impulse -> the candle before it is the demand base
            lo, hi = l[i - 1], h[i - 1]
            if not (c[i + 1:] < lo).any():
                demand.append({"low": float(lo), "high": float(hi), "pos": i - 1})
        elif -body > impulse_atr * a[i]:
            lo, hi = l[i - 1], h[i - 1]
            if not (c[i + 1:] > hi).any():
                supply.append({"low": float(lo), "high": float(hi), "pos": i - 1})
    return {"demand": demand[-max_zones:], "supply": supply[-max_zones:]}


def fib_levels(swings: list[dict], n_bars: int, lookback: int = 150) -> dict[str, Any] | None:
    """Retracement levels of the dominant swing leg inside the lookback window."""
    recent = [s for s in swings if s["pos"] >= n_bars - lookback]
    highs = [s for s in recent if s["kind"] == "high"]
    lows = [s for s in recent if s["kind"] == "low"]
    if not highs or not lows:
        return None
    hi, lo = max(highs, key=lambda s: s["price"]), min(lows, key=lambda s: s["price"])
    if hi["price"] <= lo["price"]:
        return None
    up_leg = lo["pos"] < hi["pos"]
    rng = hi["price"] - lo["price"]
    ratios = (0.236, 0.382, 0.5, 0.618, 0.786)
    levels = {f"{r:.3f}": float(hi["price"] - r * rng if up_leg else lo["price"] + r * rng) for r in ratios}
    return {"direction": "up" if up_leg else "down", "high": hi["price"], "low": lo["price"], "levels": levels}
