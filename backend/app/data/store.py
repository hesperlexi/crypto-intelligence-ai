"""Candle persistence + incremental backfill."""
from __future__ import annotations

import logging
import time

import pandas as pd

from ..config import HISTORY_BARS
from ..db import Database, get_db
from .base import MarketDataProvider, tf_ms, to_frame

log = logging.getLogger(__name__)


class CandleStore:
    def __init__(self, db: Database | None = None):
        self.db = db or get_db()
        self._cache: dict[tuple[str, str, str], tuple[int, pd.DataFrame]] = {}

    def upsert(self, exchange: str, symbol: str, timeframe: str, rows: list[list[float]]) -> int:
        clean = [(exchange, symbol, timeframe, int(r[0]), float(r[1]), float(r[2]), float(r[3]),
                  float(r[4]), float(r[5] or 0.0)) for r in rows if r and None not in r[:5]]
        self.db.executemany(
            "INSERT INTO market_data (exchange, symbol, timeframe, ts, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (exchange, symbol, timeframe, ts) DO UPDATE SET "
            "open = excluded.open, high = excluded.high, low = excluded.low, "
            "close = excluded.close, volume = excluded.volume",
            clean,
        )
        self._cache.pop((exchange, symbol, timeframe), None)
        return len(clean)

    def last_ts(self, exchange: str, symbol: str, timeframe: str) -> int | None:
        row = self.db.one("SELECT MAX(ts) AS ts FROM market_data WHERE exchange = ? AND symbol = ? AND timeframe = ?",
                          (exchange, symbol, timeframe))
        return int(row["ts"]) if row and row["ts"] is not None else None

    def count(self, exchange: str, symbol: str, timeframe: str) -> int:
        row = self.db.one("SELECT COUNT(*) AS n FROM market_data WHERE exchange = ? AND symbol = ? AND timeframe = ?",
                          (exchange, symbol, timeframe))
        return int(row["n"]) if row else 0

    def load(self, exchange: str, symbol: str, timeframe: str, limit: int | None = None,
             start: int | None = None, end: int | None = None) -> pd.DataFrame:
        """Full-history loads are cached until the next upsert for that series."""
        key = (exchange, symbol, timeframe)
        if key not in self._cache:
            rows = self.db.query(
                "SELECT ts, open, high, low, close, volume FROM market_data "
                "WHERE exchange = ? AND symbol = ? AND timeframe = ? ORDER BY ts", key)
            self._cache[key] = (len(rows), to_frame([[r["ts"], r["open"], r["high"], r["low"], r["close"], r["volume"]]
                                                    for r in rows]))
        df = self._cache[key][1]
        if start is not None:
            df = df[df["ts"] >= start]
        if end is not None:
            df = df[df["ts"] <= end]
        if limit:
            df = df.iloc[-limit:]
        return df

    async def sync(self, provider: MarketDataProvider, symbol: str, timeframe: str,
                   bars: int | None = None, page: int = 1000) -> int:
        """Backfill up to `bars` candles, then only fetch what is new. Returns rows written."""
        bars = bars or HISTORY_BARS.get(timeframe, 1500)
        step = tf_ms(timeframe)
        now = int(time.time() * 1000)
        last = self.last_ts(provider.name, symbol, timeframe)
        have = self.count(provider.name, symbol, timeframe)
        if last is None or have < min(bars, 200):
            since = now - bars * step
        else:
            since = last  # re-fetch the last candle: it may have been forming when stored
        written = 0
        if last is not None and have >= min(bars, 200) and have < 0.9 * bars:
            written += await self._deepen(provider, symbol, timeframe, bars, step, now, page)
        # exchanges cap a page at very different sizes (100-1000), so paging continues until the present
        # is reached or no progress is made, not until a short page comes back
        for _ in range(bars // 100 + 5):
            rows = await provider.fetch_ohlcv(symbol, timeframe, since=since, limit=page)
            if not rows:
                break
            written += self.upsert(provider.name, symbol, timeframe, rows)
            newest = int(rows[-1][0])
            if newest + step > now or newest < since or (newest == since and len(rows) == 1):
                break
            since = newest + step
        return written

    BACKFILL_PAGES_PER_RUN = 120         # older-history pages fetched per process run (keeps one engine cycle short)
    _pages_used = 0

    async def _deepen(self, provider: MarketDataProvider, symbol: str, timeframe: str, bars: int, step: int,
                      now: int, page: int) -> int:
        """Fetch history older than what is stored when HISTORY_BARS was raised (e.g. 15m for the quick-trade
        models). Spread over several runs; marked done once the exchange has nothing older."""
        key = f"deep:{provider.name}:{symbol}:{timeframe}:{bars}"
        if self.db.get_setting(key, False):
            return 0
        row = self.db.one("SELECT MIN(ts) AS ts FROM market_data WHERE exchange = ? AND symbol = ? AND timeframe = ?",
                          (provider.name, symbol, timeframe))
        oldest = int(row["ts"]) if row and row["ts"] is not None else now
        since = now - bars * step
        if oldest <= since + 10 * step:
            self.db.set_setting(key, True)
            return 0
        written, first = 0, True
        while since < oldest and CandleStore._pages_used < self.BACKFILL_PAGES_PER_RUN:
            rows = await provider.fetch_ohlcv(symbol, timeframe, since=since, limit=page)
            CandleStore._pages_used += 1
            if not rows:
                self.db.set_setting(key, True)
                break
            if first and int(rows[0][0]) > since + 50 * step and int(rows[0][0]) >= oldest - step:
                self.db.set_setting(key, True)        # nothing older on the exchange (coin listed later)
                break
            first = False
            written += self.upsert(provider.name, symbol, timeframe, [r for r in rows if int(r[0]) < oldest])
            newest = int(rows[-1][0])
            if newest <= since:
                break
            since = newest + step
        else:
            if since >= oldest:
                self.db.set_setting(key, True)
        if written:
            log.info("deepened %s %s by %d candles", symbol, timeframe, written)
        return written

    def is_current(self, exchange: str, symbol: str, timeframe: str, now_ms: int | None = None) -> bool:
        """True when the newest stored candle is the forming one or the one before it (backfill finished)."""
        last = self.last_ts(exchange, symbol, timeframe)
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        return last is not None and last + 2 * tf_ms(timeframe) >= now_ms
