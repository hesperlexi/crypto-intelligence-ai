"""TEST FIXTURES ONLY. Synthetic candles exist so unit tests are deterministic and offline.

Nothing in `app/` imports this module: the application itself only ever uses real exchange/CSV data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.data.base import tf_ms, to_frame


def synthetic_candles(n: int = 3000, timeframe: str = "1h", seed: int = 7, start_price: float = 100.0,
                      drift: float = 0.0, predictable: float = 0.0, end_ms: int | None = None) -> pd.DataFrame:
    """Regime-switching random walk with volatility clustering.

    `predictable` > 0 adds AR(1) momentum to returns, giving tests a series with a real, learnable edge.
    """
    rng = np.random.default_rng(seed)
    step = tf_ms(timeframe)
    end_ms = 1_750_000_000_000 // step * step if end_ms is None else end_ms // step * step
    ts = end_ms - step * np.arange(n, 0, -1)
    vol = np.empty(n)
    v = 0.01
    regime = 0.0
    r = np.empty(n)
    prev = 0.0
    for i in range(n):
        if rng.random() < 0.01:
            regime = rng.choice([-0.0008, 0.0, 0.0008])
        v = 0.9 * v + 0.1 * 0.01 * (1 + 2 * abs(rng.standard_normal()))
        vol[i] = v
        prev = drift + regime + predictable * prev + v * rng.standard_normal()
        r[i] = prev
    close = start_price * np.exp(np.cumsum(r))
    open_ = np.concatenate([[start_price], close[:-1]])
    wick = np.abs(rng.standard_normal((2, n))) * vol * close * 0.5
    high = np.maximum(open_, close) + wick[0]
    low = np.minimum(open_, close) - wick[1]
    volume = 1000 * (1 + 5 * vol / 0.01 * rng.random(n))
    return to_frame(np.column_stack([ts, open_, high, low, close, volume]))


class ArrayProvider:
    """In-memory provider for tests: serves the synthetic series above through the normal provider interface."""

    def __init__(self, symbols=("BTC/USDT", "ETH/USDT"), base_bars: int = 60000, predictable: float = 0.0,
                 end_ms: int | None = None):
        from app.data.base import resample_ohlcv

        self.name = "test"
        self.errors, self.last_error, self.last_ok_ms = 0, None, None
        self.data: dict[tuple[str, str], pd.DataFrame] = {}
        for i, s in enumerate(symbols):
            base = synthetic_candles(base_bars, "15m", seed=11 + i, start_price=100.0 * (i + 1), predictable=predictable,
                                     end_ms=end_ms)
            self.data[(s, "15m")] = base
            for tf in ("1h", "4h", "12h", "1d", "3d", "1w"):
                self.data[(s, tf)] = resample_ohlcv(base, "15m", tf)

    async def fetch_ohlcv(self, symbol, timeframe, since=None, limit=1000):
        df = self.data.get((symbol, timeframe))
        if df is None:
            return []
        if since is not None:
            df = df[df["ts"] >= since]
        return df[["ts", "open", "high", "low", "close", "volume"]].head(limit).values.tolist()

    async def fetch_ticker(self, symbol):
        last = self.data[(symbol, "15m")].iloc[-1]
        return {"symbol": symbol, "last": float(last["close"]), "bid": float(last["close"]) * 0.9999,
                "ask": float(last["close"]) * 1.0001, "change_pct": 1.0, "quote_volume": 1e6, "ts": int(last["ts"])}

    async def fetch_tickers(self, symbols):
        return {s: await self.fetch_ticker(s) for s in symbols if (s, "15m") in self.data}

    async def fetch_order_book(self, symbol, limit=100):
        px = float(self.data[(symbol, "15m")]["close"].iloc[-1])
        return {"bids": [[px * (1 - 0.0005 * (i + 1)), 2.0 + i % 3] for i in range(40)],
                "asks": [[px * (1 + 0.0005 * (i + 1)), 1.0 + i % 2] for i in range(40)], "timestamp": None}

    async def fetch_trades(self, symbol, limit=200):
        return []

    async def search_markets(self, query, limit=20):
        return [s for s, _ in self.data if query.upper() in s][:limit]

    async def server_time(self):
        return None

    async def close(self):
        return None


def make_runtime(symbols=("BTC/USDT", "ETH/USDT"), predictable: float = 0.0, model_dir: str | None = None):
    """Runtime on an in-memory SQLite DB, fully synced from an ArrayProvider. Returns (rt, provider)."""
    import asyncio
    import tempfile

    from app.config import settings
    from app.db import Database
    from app.services.runtime import Runtime

    settings.symbols = list(symbols)
    settings.model_dir = model_dir or tempfile.mkdtemp(prefix="cia-models-")
    prov = ArrayProvider(symbols, predictable=predictable)
    rt = Runtime(Database("sqlite:///:memory:"), prov)

    async def sync():
        for s in symbols:
            for tf in ("15m", "1h", "4h", "12h", "1d", "3d", "1w"):
                await rt.store.sync(prov, s, tf, bars=70000)

    asyncio.run(sync())
    return rt, prov


_shared: dict = {}


def shared_runtime():
    """One synced runtime with a fast model trained for BTC/USDT and ETH/USDT 4h, reused across test modules."""
    if "rt" not in _shared:
        from app.services import training

        rt, prov = make_runtime(predictable=0.15)
        for s in ("BTC/USDT", "ETH/USDT"):
            st = training.train_one(rt, s, "4h", fast=True)
            assert st["state"] == "done", st
        _shared["rt"], _shared["prov"] = rt, prov
    return _shared["rt"], _shared["prov"]
