"""Binance public market data over plain REST (no API key, no ccxt).

Default host is data-api.binance.vision, Binance's market-data-only endpoint, which is reachable from
cloud runners in regions where api.binance.com is geo-blocked (e.g. GitHub Actions in the US).
Hosts are tried in order; the last host that worked is tried first next time.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import requests

log = logging.getLogger(__name__)

DEFAULT_HOSTS = ["https://data-api.binance.vision", "https://api.binance.com", "https://api1.binance.com",
                 "https://api2.binance.com", "https://api3.binance.com"]
INTERVALS = {"1m", "5m", "15m", "30m", "1h", "4h", "12h", "1d", "3d", "1w"}


def to_binance(symbol: str) -> str:
    return symbol.replace("/", "").upper()


class BinancePublicProvider:
    name = "binance"

    def __init__(self, hosts: list[str] | None = None, timeout: float = 15.0, session: Any = None):
        env = [h.strip() for h in os.environ.get("BINANCE_HOSTS", "").split(",") if h.strip()]
        self.hosts = list(hosts or env or DEFAULT_HOSTS)
        self.timeout = timeout
        self.session = session or requests.Session()
        self.errors = 0
        self.last_error: str | None = None
        self.last_ok_ms: int | None = None
        self.host_used: str | None = None
        self._symbols: list[str] | None = None

    # -- transport --------------------------------------------------------------------------------------
    def _get_sync(self, path: str, params: dict[str, Any] | None = None) -> Any:
        order = sorted(self.hosts, key=lambda h: h != self.host_used)
        last_exc: Exception | None = None
        for host in order:
            for attempt in range(3):
                try:
                    r = self.session.get(host + path, params=params, timeout=self.timeout)
                except Exception as exc:  # network error: try the next host
                    last_exc = exc
                    break
                if r.status_code in (418, 429):            # rate limited: wait as instructed, then retry
                    time.sleep(min(float(r.headers.get("Retry-After", 2 ** attempt)), 30))
                    continue
                if r.status_code in (403, 451) or r.status_code >= 500:
                    last_exc = RuntimeError(f"{host} answered HTTP {r.status_code}")
                    break
                if r.status_code >= 400:                    # bad request (e.g. unknown symbol): no point retrying
                    self.errors += 1
                    self.last_error = f"{path}: HTTP {r.status_code} {r.text[:150]}"
                    raise ValueError(self.last_error)
                self.host_used = host
                self.last_ok_ms = int(time.time() * 1000)
                return r.json()
        self.errors += 1
        self.last_error = f"{path}: {type(last_exc).__name__}: {last_exc}"[:300]
        raise ConnectionError(self.last_error)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await asyncio.to_thread(self._get_sync, path, params)

    # -- provider interface ------------------------------------------------------------------------------
    async def fetch_ohlcv(self, symbol: str, timeframe: str, since: int | None = None,
                          limit: int = 1000) -> list[list[float]]:
        if timeframe not in INTERVALS:
            raise ValueError(f"unsupported timeframe {timeframe}")
        params: dict[str, Any] = {"symbol": to_binance(symbol), "interval": timeframe, "limit": min(int(limit), 1000)}
        if since is not None:
            params["startTime"] = int(since)
        rows = await self._get("/api/v3/klines", params)
        return [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in rows]

    @staticmethod
    def _ticker(symbol: str, t: dict[str, Any]) -> dict[str, Any]:
        last = float(t["lastPrice"])
        bid, ask = float(t.get("bidPrice") or 0) or None, float(t.get("askPrice") or 0) or None
        spread = (ask - bid) if bid and ask else None
        return {"symbol": symbol, "last": last, "bid": bid, "ask": ask, "spread": spread,
                "spread_bps": spread / last * 1e4 if spread is not None and last else None,
                "change_pct": float(t["priceChangePercent"]), "high": float(t["highPrice"]),
                "low": float(t["lowPrice"]), "base_volume": float(t["volume"]),
                "quote_volume": float(t["quoteVolume"]), "ts": int(t.get("closeTime") or time.time() * 1000)}

    async def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        t = await self._get("/api/v3/ticker/24hr", {"symbol": to_binance(symbol)})
        return self._ticker(symbol, t)

    async def fetch_tickers(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        if not symbols:
            return {}
        by = {to_binance(s): s for s in symbols}
        try:
            rows = await self._get("/api/v3/ticker/24hr", {"symbols": json.dumps(list(by), separators=(",", ":"))})
        except ValueError:      # one unknown symbol fails the whole batch: fall back to one by one
            out = {}
            for s in symbols:
                try:
                    out[s] = await self.fetch_ticker(s)
                except Exception:
                    continue
            return out
        return {by[r["symbol"]]: self._ticker(by[r["symbol"]], r) for r in rows if r["symbol"] in by}

    async def fetch_order_book(self, symbol: str, limit: int = 100) -> dict[str, Any]:
        lim = min([x for x in (5, 10, 20, 50, 100, 500, 1000) if x >= limit] or [1000])
        ob = await self._get("/api/v3/depth", {"symbol": to_binance(symbol), "limit": lim})
        return {"bids": [[float(p), float(q)] for p, q in ob.get("bids", [])],
                "asks": [[float(p), float(q)] for p, q in ob.get("asks", [])], "timestamp": None}

    async def fetch_trades(self, symbol: str, limit: int = 200) -> list[dict[str, Any]]:
        rows = await self._get("/api/v3/trades", {"symbol": to_binance(symbol), "limit": min(limit, 1000)})
        return [{"ts": r["time"], "price": float(r["price"]), "amount": float(r["qty"]),
                 "side": "sell" if r.get("isBuyerMaker") else "buy"} for r in rows]

    async def _all_symbols(self) -> list[str]:
        if self._symbols is None:
            rows = await self._get("/api/v3/ticker/price")
            self._symbols = sorted(r["symbol"] for r in rows if r["symbol"].endswith("USDT"))
        return self._symbols

    async def search_markets(self, query: str, limit: int = 20) -> list[str]:
        q = query.upper().replace("/", "").replace("-", "")
        hits = [s for s in await self._all_symbols() if q in s]
        hits.sort(key=lambda s: (not s.startswith(q), len(s)))
        return [f"{s[:-4]}/USDT" for s in hits[:limit]]

    async def server_time(self) -> int | None:
        try:
            return int((await self._get("/api/v3/time"))["serverTime"])
        except Exception:
            return None

    async def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass
