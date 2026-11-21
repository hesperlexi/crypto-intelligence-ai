"""v2.65 portfolio risk controller in SHADOW mode (research/risk-latest.json, 21 Nov 2026: better in both halves,
drawdown 37.4R -> 31.9R, bootstrap 98 %, but only 86 test calls differ - INCONCLUSIVE under the standard verdict).

Two rules, recorded on every published call (payload `risk_shadow`), never blocking anything yet:
* volatile: the coin's 4h ATR14 is above 1.5 x its ATR100 (closed 4h candles only).
* loss stop: record calls closed today (UTC) total <= -3R net, or this week (Monday UTC) <= -6R net.
The weekly check-up compares published calls the rules would have blocked with the rest; promote only on proof."""
from __future__ import annotations

import time
from typing import Any

import numpy as np

H4 = 4 * 3_600_000
DAY = 86_400_000
VOL_RATIO, DAY_R, WEEK_R = 1.5, 3.0, 6.0
_cache: dict[str, Any] = {}


def volatile(rt: Any, symbol: str) -> bool | None:
    try:
        df = rt.candles(symbol, "4h")
    except Exception:
        return None
    if df is None or len(df) < 110:
        return None
    h, l, c = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
    prev = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))
    a14, a100 = float(tr[-14:].mean()), float(tr[-100:].mean())
    return bool(a100 > 0 and a14 > VOL_RATIO * a100)


def _net_r(r: dict[str, Any]) -> float | None:
    from . import tracking
    net, e, s = tracking.net_pct(r), r.get("entry"), r.get("stop")
    if net is None or not e or not s:
        return None
    risk = abs(float(e) - float(s)) / float(e) * 100
    return net / risk if risk > 0 else None


def loss_sums(rt: Any, now: int) -> tuple[float, float]:
    """Net R of record calls closed today and this week (cached 5 minutes)."""
    hit = _cache.get("sums")
    if hit and now - hit[0] < 300_000:
        return hit[1]
    from . import tracking
    d0 = now // DAY * DAY
    w0 = d0 - ((d0 // DAY + 3) % 7) * DAY
    closed = tuple(tracking.CLOSED_STATUSES)
    rows = rt.db.query(f"SELECT * FROM signals WHERE closed_at >= ? AND status IN ({','.join('?' * len(closed))})",
                       (w0, *closed))
    day = week = 0.0
    for r in rows:
        if r.get("fill_status") == "NOT_FILLED":
            continue
        x = _net_r(r)
        if x is None:
            continue
        week += x
        if int(r["closed_at"]) >= d0:
            day += x
    out = (round(day, 3), round(week, 3))
    _cache["sums"] = (now, out)
    return out


def assess(rt: Any, symbol: str, now: int | None = None) -> dict[str, Any]:
    now = int(time.time() * 1000) if now is None else int(now)
    vol = volatile(rt, symbol)
    try:
        day, week = loss_sums(rt, now)
    except Exception:
        day = week = None
    stop = day is not None and (day <= -DAY_R or week <= -WEEK_R)
    return {"volatile": vol, "day_r": day, "week_r": week, "loss_stop": bool(stop),
            "would_block": bool(vol) or bool(stop)}
