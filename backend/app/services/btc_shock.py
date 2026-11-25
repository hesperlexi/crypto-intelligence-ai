"""V3.0 adaptive BTC shock guard (owner brief "adaptive BTC volatility", 24 Nov 2026).

PROVEN before going live (`app/research_btc.py`, `research-results/results/btc-latest.json`, 953 unseen calls, baseline =
the live pipeline incl. the liquidity-sweep guard): variant `shock|12h|z1.5|6h` -> +12.7R -> +23.1R, max drawdown
39.7R -> 30.1R, better in both halves, bootstrap 82 %, 124 calls differ: PASS. Every other shock variant also raised the
total and lowered the drawdown, but missed one criterion (fewer than 100 calls differ, or not better in both halves).

A BTC shock is measured in BTC's own normal size, not a fixed %: z = BTC's 12-hour return (closed 1h candles) divided by
the standard deviation of all 12-hour returns over the previous 30 days. After an up-shock (z >= 1.5) no new SHORT for
6 hours; after a down-shock (z <= -1.5) no new LONG. Calls WITH the move are untouched. Env BTC_SHOCK_GUARD=0 turns it
off. NO TRADE flag "BTC SHOCK" (in proof_checks.FLAGS: held-back calls are followed in rejected_signals).

V3.2 (Fable 5.2 audit R-01, 25 Nov 2026) fail closed: `status()` says "block", "clear" or "unavailable". Unavailable =
the BTC 1h candles cannot be read, there are fewer than MIN_BARS of them (insufficient history), the newest closed one
closed more than MAX_AGE_H hours ago (stale), or the calculation raised. `analysis.analyze` turns "unavailable" into
NO TRADE "CHECK UNAVAILABLE" for new entries only (open positions and exits are not touched) and lists it on Health."""
from __future__ import annotations

import os
import time
from typing import Any

import numpy as np

H = 3_600_000
W = 12
K = 1.5
HOURS = 6.0
ON = os.environ.get("BTC_SHOCK_GUARD", "1") != "0"
FLAG = "BTC SHOCK"
MIN_BARS = 30 * 24 + W + 2
MAX_AGE_H = float(os.environ.get("BTC_SHOCK_MAX_AGE_H", "2"))
_cache: dict[str, Any] = {}


class Unavailable(Exception):
    """The guard cannot give a verdict (missing, stale or too short BTC history)."""


def shocks(rt: Any, now: int) -> list[tuple[int, float]]:
    """(close time, z) of every closed 1h candle in the last HOURS hours whose 12-hour z passes K either way."""
    df = rt.candles("BTC/USDT", "1h")
    if df is None or len(df) < 30 * 24 + W + 2:
        return []
    ts = df["ts"].to_numpy(np.int64) + H
    keep = ts <= now
    c, ts = df["close"].to_numpy(float)[keep], ts[keep]
    last = int(ts[-1]) if len(ts) else 0
    hit = _cache.get("z")
    if not hit or hit[0] != last:
        r = c[W:] / c[:-W] - 1
        r = np.r_[np.full(W, np.nan), r]
        out = []
        win = 30 * 24
        for i in range(max(win + W, len(c) - 12), len(c)):          # only the last few hours are ever needed
            sd = np.nanstd(r[i - win:i])
            if sd > 0 and np.isfinite(r[i]):
                out.append((int(ts[i]), float(r[i] / sd), float(r[i] * 100)))
        _cache["z"] = (last, out)
    return [(t, z, pct) for t, z, pct in _cache["z"][1] if now - t <= HOURS * H and abs(z) >= K]


def _check_data(rt: Any, now: int) -> None:
    """Raise Unavailable unless the BTC 1h history is present, long enough and fresh."""
    df = rt.candles("BTC/USDT", "1h")
    if df is None or len(df) == 0:
        raise Unavailable("no BTC 1h candles")
    ts = df["ts"].to_numpy(np.int64) + H
    n = int((ts <= now).sum())
    if n < MIN_BARS:
        raise Unavailable(f"insufficient BTC 1h history ({n} of {MIN_BARS} candles)")
    age_h = (now - int(ts[ts <= now][-1])) / H
    if age_h > MAX_AGE_H:
        raise Unavailable(f"BTC 1h data is stale (newest closed candle {age_h:.1f} h old, limit {MAX_AGE_H:g} h)")


def status(rt: Any, side: int, now: int | None = None) -> dict[str, Any]:
    """{'state': 'block' | 'clear' | 'unavailable', 'hit': shock or None, 'reason': why unavailable or None}."""
    if not ON or not side:
        return {"state": "clear", "hit": None, "reason": None}
    now = int(time.time() * 1000) if now is None else int(now)
    try:
        _check_data(rt, now)
        hits = [x for x in shocks(rt, now) if (x[1] > 0) == (side < 0)]
    except Unavailable as exc:
        return {"state": "unavailable", "hit": None, "reason": str(exc)}
    except Exception as exc:
        return {"state": "unavailable", "hit": None, "reason": f"{type(exc).__name__}: {exc}"[:160]}
    if not hits:
        return {"state": "clear", "hit": None, "reason": None}
    t, z, pct = max(hits, key=lambda x: x[0])
    return {"state": "block", "hit": {"at": t, "z": round(z, 2), "move_pct": round(pct, 2)}, "reason": None}


def against(rt: Any, side: int, now: int | None = None) -> dict[str, Any] | None:
    """The BTC shock standing against a new call on `side` (an up-shock against a short, a down-shock against a long).
    Research / display helper: None when clear OR unavailable. Live decisions use `status()` (fail closed)."""
    return status(rt, side, now)["hit"]


def reason(s: dict[str, Any], side: int) -> str:
    way = "up" if s["z"] > 0 else "down"
    return (f"BTC just made an unusually large {way} move ({s['move_pct']:+.1f}% in 12 h, {abs(s['z']):.1f}x its normal size): "
            f"no new {'short' if side < 0 else 'long'} for 6 hours against it")
