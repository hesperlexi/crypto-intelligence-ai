"""v2.78 market-turn watch (owner, 23 Nov 2026; recommend-only + shadow, never changes a call by itself).

`against(rt, symbol, side)`: has the coin closed a 4h candle beyond its previous 12-candle (2-day) range AGAINST the call
in the last 24 h? (the "coin break" rule of research_turn.py - the closest candidate in the 23 Nov study, not proven:
+19.8R -> +24.9R on 610 unseen calls, both halves better but bootstrap 62 % < 80 %, so it is NOT switched on.)
Used by:
* Trade Guardian - a running call that is in profit after costs when its coin breaks against it gets a CLOSE
  recommendation "lock profit" (the admin decides; losing calls keep their stop - the study showed closing them hurt);
* the shadow record - every published call stores `risk_shadow.turn` (would the rule have paused it?) and Guardian logs
  the first break against each running call (setting `turn_shadow_log`, last 500) so the rule can be re-tested on live
  calls before it is ever switched on."""
from __future__ import annotations

from typing import Any

H = 3_600_000
LOOK = 12            # 4h candles = 2 days
RECENT_H = 24        # a break counts for 24 h
LOG = "turn_shadow_log"
LOG_MAX = 500


def against(rt: Any, symbol: str, side: int, now: int | None = None, cache: dict | None = None) -> dict[str, Any] | None:
    """{'broke': bool, 'at': close time of the breaking 4h candle, 'level': the range edge, 'close': its close} or None
    without data. side +1 long (a break DOWN is against it), -1 short (a break UP is against it)."""
    if not side:
        return None
    key = symbol
    if cache is not None and key in cache:
        ev = cache[key]
    else:
        try:
            df = rt.candles(symbol, "4h")
        except Exception:
            return None
        if df is None or len(df) < LOOK + 2:
            return None
        hi, lo, cl = (df[k].to_numpy(float) for k in ("high", "low", "close"))
        ts = df["ts"].to_numpy("int64") + 4 * H
        ev = {"up": [], "down": []}
        for i in range(max(LOOK, len(cl) - 12), len(cl)):          # only the last 2 days matter
            top, bot = hi[i - LOOK:i].max(), lo[i - LOOK:i].min()
            if cl[i] > top:
                ev["up"].append((int(ts[i]), float(top), float(cl[i])))
            elif cl[i] < bot:
                ev["down"].append((int(ts[i]), float(bot), float(cl[i])))
        if cache is not None:
            cache[key] = ev
    import time
    now = int(time.time() * 1000) if now is None else int(now)
    hits = [e for e in ev["up" if side < 0 else "down"] if now - RECENT_H * H <= e[0] <= now]
    if not hits:
        return {"broke": False}
    at, level, close = hits[-1]
    return {"broke": True, "at": at, "level": level, "close": close}


def log_first(db: Any, signal_id: str, row: dict[str, Any]) -> bool:
    """Shadow log: the first break against a running call (once per call). Returns True when it was new."""
    log = db.get_setting(LOG, None) or []
    if any(x.get("id") == signal_id for x in log):
        return False
    db.set_setting(LOG, (log + [{"id": signal_id, **row}])[-LOG_MAX:])
    return True
