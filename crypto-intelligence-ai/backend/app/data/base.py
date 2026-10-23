"""Market-data abstractions shared by every provider."""
from __future__ import annotations

import time
from typing import Any, Protocol

import numpy as np
import pandas as pd

from ..config import TF_SECONDS

OHLCV_COLS = ["ts", "open", "high", "low", "close", "volume"]
_WEEK_OFFSET_MS = 4 * 86400 * 1000  # 1970-01-05 was a Monday; weekly candles open on Mondays


def tf_ms(timeframe: str) -> int:
    return TF_SECONDS[timeframe] * 1000


def bars_per_year(timeframe: str) -> float:
    return 365.25 * 86400 / TF_SECONDS[timeframe]


def to_frame(rows: Any) -> pd.DataFrame:
    """rows: iterable of [ts, o, h, l, c, v] or list of dicts -> canonical OHLCV frame."""
    df = pd.DataFrame(rows, columns=OHLCV_COLS) if not isinstance(rows, pd.DataFrame) else rows[OHLCV_COLS].copy()
    if df.empty:
        df = pd.DataFrame({c: pd.Series(dtype="int64" if c == "ts" else "float64") for c in OHLCV_COLS})
    df["ts"] = df["ts"].astype("int64")
    for c in OHLCV_COLS[1:]:
        df[c] = df[c].astype("float64")
    df = df.drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True)
    df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df.index.name = "time"
    return df


def closed_only(df: pd.DataFrame, timeframe: str, now_ms: int | None = None) -> pd.DataFrame:
    """Drop the still-forming candle. Features and models only ever see closed candles."""
    if df.empty:
        return df
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    return df[df["ts"].to_numpy() + tf_ms(timeframe) <= now_ms]


def truncate_as_of(df: pd.DataFrame, timeframe: str, as_of_ms: int) -> pd.DataFrame:
    """What was knowable at `as_of_ms`: only candles that had fully closed by then."""
    return closed_only(df, timeframe, as_of_ms)


def bucket_start(ts: np.ndarray, timeframe: str) -> np.ndarray:
    step = tf_ms(timeframe)
    off = _WEEK_OFFSET_MS if timeframe == "1w" else 0
    return (ts - off) // step * step + off


def resample_ohlcv(df: pd.DataFrame, base_tf: str, target_tf: str) -> pd.DataFrame:
    """Aggregate closed base candles into a higher timeframe. Incomplete buckets are dropped."""
    if df.empty:
        return df
    ratio = tf_ms(target_tf) // tf_ms(base_tf)
    if ratio <= 1 or tf_ms(target_tf) % tf_ms(base_tf):
        raise ValueError(f"cannot resample {base_tf} -> {target_tf}")
    b = bucket_start(df["ts"].to_numpy(), target_tf)
    g = df.assign(_b=b).groupby("_b", sort=True)
    out = pd.DataFrame({
        "ts": g["_b"].first().astype("int64"),
        "open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
        "close": g["close"].last(), "volume": g["volume"].sum(), "_n": g["open"].size(),
    })
    out = out[out["_n"] == ratio].drop(columns="_n")
    return to_frame(out.reset_index(drop=True))


class MarketDataProvider(Protocol):
    """Every exchange adapter implements this. All methods are async."""

    name: str

    async def fetch_ohlcv(self, symbol: str, timeframe: str, since: int | None = None,
                          limit: int = 1000) -> list[list[float]]: ...

    async def fetch_ticker(self, symbol: str) -> dict[str, Any]: ...

    async def fetch_tickers(self, symbols: list[str]) -> dict[str, dict[str, Any]]: ...

    async def fetch_order_book(self, symbol: str, limit: int = 100) -> dict[str, Any]: ...

    async def fetch_trades(self, symbol: str, limit: int = 200) -> list[dict[str, Any]]: ...

    async def search_markets(self, query: str, limit: int = 20) -> list[str]: ...

    async def server_time(self) -> int | None: ...

    async def close(self) -> None: ...
