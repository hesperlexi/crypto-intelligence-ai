"""v3.1 (owner, 25 Nov 2026: "when the trade is closed, it should happen immediately rather than waiting for the candle
to close"): the record and the bots followed trades on CLOSED 15-minute candles only, so a target or stop touched at
12:01 showed at ~12:15 + the next engine cycle. The minutes since the last closed 15-minute candle are now followed too,
on CLOSED 1-minute candles (same rules, finer steps): a hit shows at the engine cycle right after it (~4 min).

`tail(rt, symbol, start)`: closed 1-minute candles with open time >= start (at most the last ~2 hours), cached in
SQLite table `m1_tail` so each cycle asks the exchange only for the new minutes (one request per coin per cycle,
memoised for the cycle on `rt`). Any problem -> an empty tail (the 15-minute rules alone, as before).
`path(rt, symbol, after_ts, p15)`: the bots' path after `after_ts` = 1-minute candles up to the next 15-minute
boundary (when `after_ts` was a minute), the closed 15-minute candles, then the 1-minute tail. Returns
[(ts, open, high, low, close, duration_ms)]."""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

MIN = 60_000
Q = 900_000
KEEP_MS = 6 * 3_600_000
ON = os.environ.get("M1_TAIL", "1") != "0"


def _table(db: Any) -> None:
    db.execute("CREATE TABLE IF NOT EXISTS m1_tail (symbol TEXT NOT NULL, ts INTEGER NOT NULL, open REAL, high REAL, "
               "low REAL, close REAL, PRIMARY KEY (symbol, ts))")


def _now() -> int:
    return int(time.time() * 1000)


def tail(rt: Any, symbol: str, start: int, now: int | None = None) -> list[tuple]:
    if not ON:
        return []
    now = now or _now()
    memo = rt.__dict__.setdefault("_m1_memo", {})
    try:
        if symbol not in memo:
            _table(rt.db)
            last = rt.db.one("SELECT MAX(ts) AS t FROM m1_tail WHERE symbol = ?", (symbol,))
            t = int((last or {}).get("t") or 0)
            since = max(t, now - 120 * MIN)
            prov = getattr(rt, "provider", None)
            rows = asyncio.run(prov.fetch_ohlcv(symbol, "1m", since=since, limit=130)) if prov is not None else []
            rt.db.executemany("INSERT INTO m1_tail (symbol, ts, open, high, low, close) VALUES (?, ?, ?, ?, ?, ?) "
                              "ON CONFLICT (symbol, ts) DO UPDATE SET open = excluded.open, high = excluded.high, "
                              "low = excluded.low, close = excluded.close",
                              [(symbol, int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rows or []])
            rt.db.execute("DELETE FROM m1_tail WHERE ts < ?", (now - KEEP_MS,))
            memo[symbol] = True
        got = rt.db.query("SELECT ts, open, high, low, close FROM m1_tail WHERE symbol = ? AND ts >= ? AND ts + ? <= ? "
                          "ORDER BY ts", (symbol, int(start), MIN, now))
        return [(int(r["ts"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])) for r in got]
    except Exception as exc:
        memo[symbol] = True
        try:
            rt.record_error(f"1m tail {symbol}", exc)
        except Exception:
            pass
        return []


def mark(ts: int, dur: int) -> int:
    """The `last_check` value after following a candle: its open time for a 15-minute candle, open time + 1 ms for a
    1-minute candle (so the next path knows to continue minute by minute)."""
    return int(ts) if dur >= Q else int(ts) + 1


def path(rt: Any, symbol: str, after_ts: int, p15: Any, now: int | None = None) -> list[tuple]:
    """Candles still to follow after `after_ts` (a `mark` value), finest available, each with its duration."""
    now = now or _now()
    out: list[tuple] = []
    df = p15 if p15 is not None and len(p15) else None
    if after_ts % Q:                                   # stopped inside a 15-minute candle: finish it minute by minute
        nxt = after_ts - 1 + MIN
        boundary = nxt if nxt % Q == 0 else nxt - nxt % Q + Q
        pre = [c for c in tail(rt, symbol, nxt, now) if c[0] < boundary]
        if pre:
            out += [(*c, MIN) for c in pre]
            if pre[-1][0] + MIN < boundary:            # minutes still to come (or missing): continue next cycle
                return out
        elif now >= boundary + 2 * MIN and df is not None:
            boundary -= Q                              # no 1-minute data at all: fall back to that whole candle
        else:
            return out
        start15 = boundary
    else:
        start15 = after_ts + 1
    if df is not None:
        d = df[df["ts"] >= start15]
        out += [(int(ts), float(o), float(h), float(l), float(c), Q)
                for ts, o, h, l, c in zip(d["ts"].astype(int), d["open"], d["high"], d["low"], d["close"])]
    nxt = out[-1][0] + out[-1][5] if out else (start15 if start15 % Q == 0 else start15 - 1 + Q)
    out += [(*c, MIN) for c in tail(rt, symbol, nxt, now)]
    return out
