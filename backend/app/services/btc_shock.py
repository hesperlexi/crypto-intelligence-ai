"""V3.0 adaptive BTC shock guard (owner brief "adaptive BTC volatility", 24 Nov 2026).

PROVEN before going live (`app/research_btc.py`, `research-results/results/btc-latest.json`, 953 unseen calls, baseline =
the live pipeline incl. the liquidity-sweep guard): variant `shock|12h|z1.5|6h` -> +12.7R -> +23.1R, max drawdown
39.7R -> 30.1R, better in both halves, bootstrap 82 %, 124 calls differ: PASS. Every other shock variant also raised the
total and lowered the drawdown, but missed one criterion (fewer than 100 calls differ, or not better in both halves).

A BTC shock is measured in BTC's own normal size, not a fixed %: z = BTC's 12-hour return (closed 1h candles) divided by
the standard deviation of all 12-hour returns over the previous 30 days. After an up-shock (z >= 1.5) no new SHORT for
6 hours; after a down-shock (z <= -1.5) no new LONG. Calls WITH the move are untouched. Env BTC_SHOCK_GUARD=0 turns it
off. NO TRADE flag "BTC SHOCK" (in proof_checks.FLAGS: held-back calls are followed in rejected_signals)."""
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
_cache: dict[str, Any] = {}


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


def against(rt: Any, side: int, now: int | None = None) -> dict[str, Any] | None:
    """The BTC shock standing against a new call on `side` (an up-shock against a short, a down-shock against a long)."""
    if not ON or not side:
        return None
    now = int(time.time() * 1000) if now is None else int(now)
    try:
        hits = [x for x in shocks(rt, now) if (x[1] > 0) == (side < 0)]
    except Exception:
        return None
    if not hits:
        return None
    t, z, pct = max(hits, key=lambda x: x[0])
    return {"at": t, "z": round(z, 2), "move_pct": round(pct, 2)}


def reason(s: dict[str, Any], side: int) -> str:
    way = "up" if s["z"] > 0 else "down"
    return (f"BTC just made an unusually large {way} move ({s['move_pct']:+.1f}% in 12 h, {abs(s['z']):.1f}x its normal size): "
            f"no new {'short' if side < 0 else 'long'} for 6 hours against it")
