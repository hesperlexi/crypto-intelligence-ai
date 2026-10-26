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
    """Hourly frame: ts, funding, premium (empty when nothing is stored); crowd data rides along in .attrs."""
    rows = db.query("SELECT kind, ts, value FROM derivs WHERE symbol = ? AND kind IN ('funding_1h', 'premium_1h') "
                    "ORDER BY ts", (symbol,))
    if not rows:
        return pd.DataFrame(columns=["ts", "funding", "premium"])
    df = pd.DataFrame([dict(r) for r in rows]).pivot_table(index="ts", columns="kind", values="value")
    df = df.rename(columns={"funding_1h": "funding", "premium_1h": "premium"}).reset_index()
    for c in ("funding", "premium"):
        if c not in df:
            df[c] = np.nan
    out = df[["ts", "funding", "premium"]].sort_values("ts").reset_index(drop=True)
    return out


def coverage_days(db: Database, symbol: str) -> float:
    a, b = _first_ts(db, symbol), _last_ts(db, symbol)
    return 0.0 if a is None or b is None else (b - a) / 86_400_000


# ---- crowd positioning from Binance's public archive (v2.2) --------------------------------------------------
# data.binance.vision publishes one file per day per USDⓈ-M contract with 5-minute open interest, top-trader and
# account long/short ratios and taker buy/sell volume ratio. Reachable from the engine's runners (the live futures
# API is not). A day's file appears after the day ends, so features use these values with a fixed delay (see
# features.dataset.CROWD_LAG_MS) - the same in training and live, so the model never relies on fresher data than
# it will have.
METRICS_URL = "https://data.binance.vision/data/futures/um/daily/metrics/{s}/{s}-metrics-{d}.zip"
CROWD_KINDS = {"sum_open_interest_value": "oi_1h", "sum_toptrader_long_short_ratio": "ls_top_1h",
               "count_long_short_ratio": "ls_acct_1h", "sum_taker_long_short_vol_ratio": "taker_1h"}
K1000 = {"PEPE", "SHIB", "BONK", "FLOKI", "LUNC", "XEC", "SATS", "RATS", "CAT", "CHEEMS", "MOG", "WHY", "X"}
DAY = 86_400_000


def futures_symbol(symbol: str) -> str:
    base = symbol.split("/")[0].upper()
    return f"1000{base}USDT" if base in K1000 else f"{base}USDT"


def _crowd_days(db: Database, symbol: str) -> tuple[int | None, int | None]:
    row = db.one("SELECT MIN(ts) AS a, MAX(ts) AS b FROM derivs WHERE symbol = ? AND kind = 'oi_1h'", (symbol,))
    return (int(row["a"]) // DAY * DAY if row and row["a"] is not None else None,
            int(row["b"]) // DAY * DAY if row and row["b"] is not None else None)


def _metrics_day(symbol: str, day_ms: int, session: Any = None) -> list[tuple[str, str, int, float]] | None:
    """Hourly rows for one day (the last 5-minute value in each hour); None when the file does not exist."""
    import io
    import zipfile

    d = time.strftime("%Y-%m-%d", time.gmtime(day_ms / 1000))
    fs = futures_symbol(symbol)
    r = (session or requests).get(METRICS_URL.format(s=fs, d=d), timeout=20)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        df = pd.read_csv(z.open(z.namelist()[0]))
    if df.empty or "create_time" not in df:
        return []
    # milliseconds, independent of the pandas version's default datetime precision
    ts = (pd.to_datetime(df["create_time"], utc=True) - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)
    df = df.assign(_hour=(ts // HOUR) * HOUR, _ts=ts).sort_values("_ts").groupby("_hour").last()
    out = []
    for col, kind in CROWD_KINDS.items():
        if col in df:
            for h, v in df[col].items():
                if pd.notna(v) and np.isfinite(float(v)):
                    out.append((symbol, kind, int(h), float(v)))
    return out


def sync_crowd(db: Database, symbols: list[str], history_days: int = 400, max_files: int = 60,
               session: Any = None, now: int | None = None) -> dict[str, Any]:
    """Newest days first for every symbol, then older history, within `max_files` downloads."""
    now = now or int(time.time() * 1000)
    newest = (now // DAY - 1) * DAY                       # yesterday: the newest file that can exist
    floor = (now // DAY - history_days) * DAY
    out: dict[str, Any] = {"files": 0, "rows": 0, "missing": [], "errors": []}

    def fetch(sym: str, day: int) -> bool | None:
        try:
            rows = _metrics_day(sym, day, session)
        except Exception as exc:
            out["errors"].append(f"{sym}: {type(exc).__name__}"[:100])
            return None
        out["files"] += 1
        if rows is None:
            return False
        if rows:
            db.executemany("INSERT INTO derivs (symbol, kind, ts, value) VALUES (?, ?, ?, ?) "
                           "ON CONFLICT (symbol, kind, ts) DO UPDATE SET value = excluded.value", rows)
            out["rows"] += len(rows)
        return True

    todo = [s for s in symbols if not db.get_setting(f"crowd_none_{s}", False)]
    # 1) forward
    for s in todo:
        first, last = _crowd_days(db, s)
        day = (last + DAY) if last is not None else newest
        while day <= newest and out["files"] < max_files:
            ok = fetch(s, day)
            if ok is False and last is None:
                db.set_setting(f"crowd_none_{s}", True)  # no Binance futures contract for this coin
                out["missing"].append(s)
                break
            if ok is None:
                break
            day += DAY
    # 2) backward, one day per symbol per round
    progress = True
    while progress and out["files"] < max_files:
        progress = False
        for s in todo:
            if out["files"] >= max_files or db.get_setting(f"crowd_none_{s}", False):
                continue
            first, _ = _crowd_days(db, s)
            if first is None or first <= floor or db.get_setting(f"crowd_first_{s}", None):
                continue
            ok = fetch(s, first - DAY)
            if ok is False:
                db.set_setting(f"crowd_first_{s}", first)  # nothing older (contract listed then)
            elif ok:
                progress = True
    return out


def load_crowd(db: Database, symbol: str) -> pd.DataFrame:
    """Hourly frame: ts, oi, ls_top, ls_acct, taker (empty when nothing is stored)."""
    rows = db.query("SELECT kind, ts, value FROM derivs WHERE symbol = ? AND kind IN ('oi_1h', 'ls_top_1h', "
                    "'ls_acct_1h', 'taker_1h') ORDER BY ts", (symbol,))
    cols = ["ts", "oi", "ls_top", "ls_acct", "taker"]
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame([dict(r) for r in rows]).pivot_table(index="ts", columns="kind", values="value").reset_index()
    df = df.rename(columns={"oi_1h": "oi", "ls_top_1h": "ls_top", "ls_acct_1h": "ls_acct", "taker_1h": "taker"})
    for c in cols:
        if c not in df:
            df[c] = np.nan
    return df[cols].sort_values("ts").reset_index(drop=True)


def crowd_days(db: Database, symbol: str) -> float:
    a, b = _crowd_days(db, symbol)
    return 0.0 if a is None or b is None else (b - a) / DAY + 1


def load_all(db: Database, symbol: str) -> pd.DataFrame:
    """Funding / premium and crowd positioning on one hourly index (missing values stay NaN)."""
    a, b = load(db, symbol), load_crowd(db, symbol)
    if a.empty and b.empty:
        return pd.DataFrame(columns=["ts", "funding", "premium", "oi", "ls_top", "ls_acct", "taker"])
    if a.empty:
        a = pd.DataFrame(columns=["ts", "funding", "premium"])
    if b.empty:
        b = pd.DataFrame(columns=["ts", "oi", "ls_top", "ls_acct", "taker"])
    m = pd.merge(a.astype({"ts": "int64"}), b.astype({"ts": "int64"}), on="ts", how="outer")
    return m.sort_values("ts").reset_index(drop=True)
