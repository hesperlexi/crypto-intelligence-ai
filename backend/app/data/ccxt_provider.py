"""Exchange access through CCXT (Binance, Coinbase, Bybit, OKX, Kraken, ... share this adapter).

Only public market-data endpoints are used. No API keys are needed and no orders are ever sent.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from ..config import TF_SECONDS
from .base import resample_ohlcv, tf_ms, to_frame

log = logging.getLogger(__name__)


class CCXTProvider:
    def __init__(self, exchange_id: str = "binance", options: dict[str, Any] | None = None):
        import ccxt.async_support as ccxt_async  # imported lazily so the quant core works without ccxt

        if not hasattr(ccxt_async, exchange_id):
            raise ValueError(f"unknown exchange '{exchange_id}'")
        self.name = exchange_id
        self.ex = getattr(ccxt_async, exchange_id)({"enableRateLimit": True, **(options or {})})
        self.errors = 0
        self.last_error: str | None = None
        self.last_ok_ms: int | None = None
        self._markets_loaded = False

    async def _ensure_markets(self) -> None:
        if not self._markets_loaded:
            await self.ex.load_markets()
            self._markets_loaded = True

    async def _call(self, fn: str, *args: Any, **kwargs: Any) -> Any:
        try:
            await self._ensure_markets()
            out = await getattr(self.ex, fn)(*args, **kwargs)
            self.last_ok_ms = int(time.time() * 1000)
            return out
        except Exception as exc:
            self.errors += 1
            self.last_error = f"{fn}: {type(exc).__name__}: {exc}"[:300]
            raise

    def supports(self, timeframe: str) -> bool:
        return timeframe in (self.ex.timeframes or {})

    def _base_tf(self, timeframe: str) -> str | None:
        target = TF_SECONDS[timeframe]
        cands = [tf for tf in TF_SECONDS if self.supports(tf) and TF_SECONDS[tf] < target
                 and target % TF_SECONDS[tf] == 0]
        return max(cands, key=lambda t: TF_SECONDS[t]) if cands else None

    async def fetch_ohlcv(self, symbol: str, timeframe: str, since: int | None = None,
                          limit: int = 1000) -> list[list[float]]:
        await self._ensure_markets()
        if self.supports(timeframe):
            return await self._call("fetch_ohlcv", symbol, timeframe, since, limit)
        base = self._base_tf(timeframe)  # exchange lacks this timeframe: build it from a lower one
        if base is None:
            raise ValueError(f"{self.name} cannot provide {timeframe} candles")
        ratio = tf_ms(timeframe) // tf_ms(base)
        step = tf_ms(timeframe)
        cursor = None if since is None else since // step * step
        rows: list[list[float]] = []
        for _ in range(min(limit * ratio // 1000 + 1, 30)):
            page = await self._call("fetch_ohlcv", symbol, base, cursor, 1000)
            if not page:
                break
            rows.extend(page)
            if len(page) < 1000:
                break
            cursor = int(page[-1][0]) + tf_ms(base)
        if not rows:
            return []
        out = resample_ohlcv(to_frame(rows), base, timeframe)
        return out[["ts", "open", "high", "low", "close", "volume"]].values.tolist()[:limit]

    async def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        return _ticker(await self._call("fetch_ticker", symbol))

    async def fetch_tickers(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        try:
            raw = await self._call("fetch_tickers", symbols)
            return {s: _ticker(t) for s, t in raw.items() if s in symbols}
        except Exception:
            out = {}
            for s in symbols:
                try:
                    out[s] = await self.fetch_ticker(s)
                except Exception:  # one bad symbol must not blank the whole board
                    continue
            return out

    async def fetch_order_book(self, symbol: str, limit: int = 100) -> dict[str, Any]:
        ob = await self._call("fetch_order_book", symbol, limit)
        return {"bids": ob.get("bids", []), "asks": ob.get("asks", []), "timestamp": ob.get("timestamp")}

    async def fetch_trades(self, symbol: str, limit: int = 200) -> list[dict[str, Any]]:
        trades = await self._call("fetch_trades", symbol, None, limit)
        return [{"ts": t.get("timestamp"), "price": t.get("price"), "amount": t.get("amount"),
                 "side": t.get("side")} for t in trades]

    async def search_markets(self, query: str, limit: int = 20) -> list[str]:
        await self._ensure_markets()
        q = query.upper().replace("-", "/")
        hits = [s for s, m in self.ex.markets.items()
                if m.get("spot") and m.get("active", True) and q in s and s.endswith("/USDT")]
        hits.sort(key=lambda s: (not s.startswith(q), len(s)))
        return hits[:limit]

    async def server_time(self) -> int | None:
        try:
            return int(await self._call("fetch_time"))
        except Exception:
            return None

    async def close(self) -> None:
        try:
            await self.ex.close()
        except Exception:  # pragma: no cover
            pass


class DerivativesProvider:
    """Funding / open interest from a perpetual-futures venue, where the exchange offers them."""

    def __init__(self, exchange_id: str = "binanceusdm"):
        self._p = CCXTProvider(exchange_id)
        self.name = exchange_id

    @staticmethod
    def perp(symbol: str) -> str:
        return symbol if ":" in symbol else f"{symbol}:{symbol.split('/')[1]}"

    async def funding_rate(self, symbol: str) -> dict[str, Any] | None:
        if not self._p.ex.has.get("fetchFundingRate"):
            return None
        fr = await self._p._call("fetch_funding_rate", self.perp(symbol))
        return {"rate": fr.get("fundingRate"), "next_ts": fr.get("fundingTimestamp") or fr.get("nextFundingTimestamp"),
                "mark": fr.get("markPrice")}

    async def open_interest_history(self, symbol: str, timeframe: str = "1h", limit: int = 48) -> list[dict[str, Any]]:
        if not self._p.ex.has.get("fetchOpenInterestHistory"):
            return []
        rows = await self._p._call("fetch_open_interest_history", self.perp(symbol), timeframe, None, limit)
        return [{"ts": r.get("timestamp"), "oi": r.get("openInterestAmount"), "oi_value": r.get("openInterestValue")}
                for r in rows]

    async def close(self) -> None:
        await self._p.close()


def _ticker(t: dict[str, Any]) -> dict[str, Any]:
    bid, ask = t.get("bid"), t.get("ask")
    last = t.get("last") or t.get("close")
    spread = (ask - bid) if bid and ask else None
    return {
        "symbol": t.get("symbol"), "last": last, "bid": bid, "ask": ask,
        "spread": spread, "spread_bps": (spread / last * 1e4) if spread is not None and last else None,
        "change_pct": t.get("percentage"), "high": t.get("high"), "low": t.get("low"),
        "base_volume": t.get("baseVolume"), "quote_volume": t.get("quoteVolume"),
        "ts": t.get("timestamp") or int(time.time() * 1000),
    }
