"""Futures-market history for the models: hourly funding rate and premium (perp price vs index) from
Hyperliquid's public API. Binance's futures API is geo-blocked on the engine's US cloud runners; Hyperliquid is
reachable, keyless, and serves the same history and live values from one source (no live/historical mismatch).

Stored in the `derivs` table: kind 'funding_1h' and 'premium_1h', ts = the funding hour (value known at ts).
"""
from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np
import pandas as pd
import requests

from ..db import Database

log = logging.getLogger(__name__)
URL = "https://api.hyperliquid.xyz/info"
HOUR = 3_600_000
PAGE = 500                       # rows per fundingHistory call
KPREFIX = {"PEPE", "SHIB", "BONK", "FLOKI", "LUNC", "DOGS", "NEIRO"}   # quoted per 1000 units on Hyperliquid
_universe: tuple[float, set[str]] | None = None


def coin_of(symbol: str) -> str:
    base = symbol.split("/")[0].upper()
    return f"k{base}" if base in KPREFIX else base


def universe(session: Any = None) -> set[str]:
    global _universe
    if _universe and time.time() - _universe[0] < 6 * 3600:
        return _universe[1]
    r = (session or requests).post(URL, json={"type": "meta"}, timeout=15)
    r.raise_for_status()
    names = {u["name"] for u in r.json().get("universe", [])}
    _universe = (time.time(), names)
    return names


def _last_ts(db: Database, symbol: str) -> int | None:
    row = db.one("SELECT MAX(ts) AS t FROM derivs WHERE symbol = ? AND kind = 'funding_1h'", (symbol,))
    return int(row["t"]) if row and row["t"] is not None else None


def _first_ts(db: Database, symbol: str) -> int | None:
    row = db.one("SELECT MIN(ts) AS t FROM derivs WHERE symbol = ? AND kind = 'funding_1h'", (symbol,))
    return int(row["t"]) if row and row["t"] is not None else None


def _store(db: Database, symbol: str, rows: list[dict[str, Any]]) -> int:
    vals = []
    for r in rows:
        ts = int(r["time"]) // HOUR * HOUR
        vals.append((symbol, "funding_1h", ts, float(r["fundingRate"])))
        if r.get("premium") not in (None, ""):
            vals.append((symbol, "premium_1h", ts, float(r["premium"])))
    if vals:
        db.executemany("INSERT INTO derivs (symbol, kind, ts, value) VALUES (?, ?, ?, ?) "
                       "ON CONFLICT (symbol, kind, ts) DO UPDATE SET value = excluded.value", vals)
    return len(rows)


def _page(coin: str, start: int, session: Any) -> list[dict[str, Any]]:
    for attempt in range(3):
        r = (session or requests).post(URL, json={"type": "fundingHistory", "coin": coin, "startTime": int(start)}, timeout=15)
        if r.status_code == 429 and attempt < 2:          # rate limited: back off and retry
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        if session is None:
            time.sleep(0.4)                               # stay well inside the public rate limit
        return r.json() or []
    return []


def sync(db: Database, symbols: list[str], history_days: int = 900, max_calls: int = 40,
         session: Any = None, now: int | None = None) -> dict[str, Any]:
    """Bring every symbol up to date (newest first), then extend history backwards, within `max_calls` requests."""
    now = now or int(time.time() * 1000)
    out: dict[str, Any] = {"calls": 0, "rows": 0, "unsupported": [], "errors": []}
    try:
        names = universe(session)
    except Exception as exc:
        out["errors"].append(f"meta: {type(exc).__name__}: {exc}"[:160])
        return out
    todo = []
    for s in symbols:
        c = coin_of(s)
        if c not in names:
            out["unsupported"].append(s)
            continue
        todo.append((s, c))
    # 1) forward: from the newest stored hour to now
    for s, c in todo:
        start = (_last_ts(db, s) or now - 30 * 86_400_000) + HOUR
        while start < now - HOUR and out["calls"] < max_calls:
            try:
                rows = _page(c, start, session)
            except Exception as exc:
                out["errors"].append(f"{s}: {type(exc).__name__}"[:120])
                break
            out["calls"] += 1
            if not rows:
                break
            out["rows"] += _store(db, s, rows)
            start = int(rows[-1]["time"]) + 1
            if len(rows) < PAGE:
                break
    # 2) backward: older history, one page per symbol per round, until `history_days` or listing date
    floor = now - history_days * 86_400_000
    progress = True
    while progress and out["calls"] < max_calls:
        progress = False
        for s, c in todo:
            first = _first_ts(db, s)
            if first is None or first <= floor or out["calls"] >= max_calls:
                continue
            if db.get_setting(f"derivs_listed_{s}", None) and first <= int(db.get_setting(f"derivs_listed_{s}")) + HOUR:
                continue
            start = max(floor, first - PAGE * HOUR)
            try:
                rows = [r for r in _page(c, start, session) if int(r["time"]) < first]
            except Exception as exc:
                out["errors"].append(f"{s}: {type(exc).__name__}"[:120])
                continue
            out["calls"] += 1
            if not rows:
                db.set_setting(f"derivs_listed_{s}", first)      # nothing older: the market's first hour
                continue
            out["rows"] += _store(db, s, rows)
            progress = True
    return out


def load(db: Database, symbol: str) -> pd.DataFrame:
    """Hourly frame: ts, funding, premium (empty when nothing is stored)."""
    rows = db.query("SELECT kind, ts, value FROM derivs WHERE symbol = ? ORDER BY ts", (symbol,))
    if not rows:
        return pd.DataFrame(columns=["ts", "funding", "premium"])
    df = pd.DataFrame([dict(r) for r in rows]).pivot_table(index="ts", columns="kind", values="value")
    df = df.rename(columns={"funding_1h": "funding", "premium_1h": "premium"}).reset_index()
    for c in ("funding", "premium"):
        if c not in df:
            df[c] = np.nan
    return df[["ts", "funding", "premium"]].sort_values("ts").reset_index(drop=True)


def coverage_days(db: Database, symbol: str) -> float:
    a, b = _first_ts(db, symbol), _last_ts(db, symbol)
    return 0.0 if a is None or b is None else (b - a) / 86_400_000
