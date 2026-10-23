"""Offline provider that reads REAL exported candles from CSV files (e.g. data.binance.vision dumps).

File name: <CSV_DIR>/<BASE><QUOTE>_<timeframe>.csv, e.g. BTCUSDT_4h.csv
Accepted layouts:
  * Binance kline export, no header: open_time, open, high, low, close, volume, ...
  * Header row containing ts|timestamp|time|date|open_time plus open, high, low, close, volume
This provider never fabricates data; a missing file raises FileNotFoundError.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .base import tf_ms, to_frame


def read_candle_csv(path: str | Path) -> pd.DataFrame:
    raw = pd.read_csv(path, header=None, low_memory=False)
    first = str(raw.iloc[0, 0]).strip().lower()
    if not first.replace(".", "", 1).isdigit():  # has a header row
        raw = pd.read_csv(path)
        raw.columns = [str(c).strip().lower() for c in raw.columns]
        tcol = next(c for c in ("ts", "timestamp", "open_time", "time", "date", "datetime") if c in raw.columns)
        t = raw[tcol]
        if pd.api.types.is_numeric_dtype(t):
            ts = t.astype("int64")
        else:
            ts = (pd.to_datetime(t, utc=True) - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(milliseconds=1)
        df = pd.DataFrame({"ts": ts, **{c: raw[c] for c in ("open", "high", "low", "close", "volume")}})
    else:
        df = raw.iloc[:, :6].copy()
        df.columns = ["ts", "open", "high", "low", "close", "volume"]
    ts = df["ts"].astype("int64")
    ts = ts.where(ts < 10**14, ts // 1000)   # microseconds -> milliseconds (newer Binance dumps)
    ts = ts.where(ts > 10**11, ts * 1000)    # seconds -> milliseconds
    df["ts"] = ts
    return to_frame(df)


class CSVProvider:
    def __init__(self, directory: str, name: str = "csv"):
        self.dir = Path(directory)
        self.name = name
        self.errors = 0
        self.last_error: str | None = None
        self.last_ok_ms: int | None = None

    def _path(self, symbol: str, timeframe: str) -> Path:
        return self.dir / f"{symbol.replace('/', '')}_{timeframe}.csv"

    async def fetch_ohlcv(self, symbol: str, timeframe: str, since: int | None = None,
                          limit: int = 1000) -> list[list[float]]:
        path = self._path(symbol, timeframe)
        if not path.exists():
            raise FileNotFoundError(f"no CSV for {symbol} {timeframe} at {path}")
        df = read_candle_csv(path)
        if since is not None:
            df = df[df["ts"] >= since]
        return df[["ts", "open", "high", "low", "close", "volume"]].head(limit).values.tolist()

    async def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        for tf in ("1m", "5m", "15m", "30m", "1h", "4h", "12h", "1d"):
            if self._path(symbol, tf).exists():
                df = read_candle_csv(self._path(symbol, tf))
                last = df.iloc[-1]
                day = df[df["ts"] > last["ts"] - 86_400_000]
                return {"symbol": symbol, "last": float(last["close"]), "bid": None, "ask": None, "spread": None,
                        "spread_bps": None, "high": float(day["high"].max()), "low": float(day["low"].min()),
                        "change_pct": float(last["close"] / day["open"].iloc[0] - 1) * 100,
                        "base_volume": float(day["volume"].sum()),
                        "quote_volume": float((day["volume"] * day["close"]).sum()),
                        "ts": int(last["ts"]) + tf_ms(tf), "stale_source": "csv"}
        raise FileNotFoundError(f"no CSV for {symbol}")

    async def fetch_tickers(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        out = {}
        for s in symbols:
            try:
                out[s] = await self.fetch_ticker(s)
            except FileNotFoundError:
                continue
        return out

    async def fetch_order_book(self, symbol: str, limit: int = 100) -> dict[str, Any]:
        return {"bids": [], "asks": [], "timestamp": None}

    async def fetch_trades(self, symbol: str, limit: int = 200) -> list[dict[str, Any]]:
        return []

    async def search_markets(self, query: str, limit: int = 20) -> list[str]:
        q = query.upper().replace("/", "")
        names = sorted({p.name.split("_")[0] for p in self.dir.glob("*_*.csv")})
        return [f"{n[:-4]}/USDT" for n in names if q in n and n.endswith("USDT")][:limit]

    async def server_time(self) -> int | None:
        return None

    async def close(self) -> None:
        return None
