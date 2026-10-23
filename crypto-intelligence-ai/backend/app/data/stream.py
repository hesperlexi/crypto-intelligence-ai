"""Live ticker feed: exchange WebSocket (ccxt.pro) with automatic REST-polling fallback.

Subscribers (the app's own /ws endpoint) receive every ticker update.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .ccxt_provider import _ticker

log = logging.getLogger(__name__)


class LiveFeed:
    def __init__(self, provider: Any, symbols: list[str], use_websocket: bool = True, poll_s: float = 5.0):
        self.provider = provider
        self.symbols = list(symbols)
        self.use_websocket = use_websocket
        self.poll_s = poll_s
        self.tickers: dict[str, dict[str, Any]] = {}
        self.status = "STARTING"       # LIVE (websocket) | POLLING (REST) | DOWN
        self.last_update_ms: int | None = None
        self.reconnects = 0
        self.last_error: str | None = None
        self._subs: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None
        self._ws_ex: Any = None

    def set_symbols(self, symbols: list[str]) -> None:
        self.symbols = list(symbols)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, message: dict[str, Any]) -> None:
        for q in list(self._subs):
            if q.full():  # slow consumer: drop the oldest message rather than block the feed
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(message)

    def _on_ticker(self, symbol: str, t: dict[str, Any]) -> None:
        self.tickers[symbol] = t
        self.last_update_ms = int(time.time() * 1000)
        self.publish({"type": "ticker", "symbol": symbol, "data": t})

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="live-feed")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self._ws_ex is not None:
            try:
                await self._ws_ex.close()
            except Exception:
                pass

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            try:
                if self.use_websocket and await self._websocket_loop():
                    backoff = 1.0
                    continue
                await self._poll_loop()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.status = "DOWN"
                self.last_error = f"{type(exc).__name__}: {exc}"[:300]
                self.reconnects += 1
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _websocket_loop(self) -> bool:
        """Returns False if websockets are unavailable for this provider (caller falls back to polling)."""
        try:
            import ccxt.pro as ccxtpro
        except Exception:
            return False
        ex_id = getattr(self.provider, "name", "")
        if not hasattr(ccxtpro, ex_id):
            return False
        if self._ws_ex is None:
            self._ws_ex = getattr(ccxtpro, ex_id)({"enableRateLimit": True})
        if not self._ws_ex.has.get("watchTickers"):
            return False
        failures = 0
        while True:
            try:
                raw = await asyncio.wait_for(self._ws_ex.watch_tickers(self.symbols), timeout=30)
                self.status = "LIVE"
                failures = 0
                for sym, t in raw.items():
                    if sym in self.symbols:
                        self._on_ticker(sym, _ticker(t))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failures += 1
                self.reconnects += 1
                self.last_error = f"ws: {type(exc).__name__}: {exc}"[:300]
                if failures >= 3:      # give up on the socket for now, poll instead
                    self.status = "POLLING"
                    await self._poll_loop(max_rounds=24)
                    failures = 0
                else:
                    await asyncio.sleep(2 ** failures)

    async def _poll_loop(self, max_rounds: int | None = None) -> None:
        rounds = 0
        while max_rounds is None or rounds < max_rounds:
            rounds += 1
            try:
                tickers = await self.provider.fetch_tickers(self.symbols)
                self.status = "POLLING"
                for sym, t in tickers.items():
                    self._on_ticker(sym, t)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.status = "DOWN"
                self.last_error = f"poll: {type(exc).__name__}: {exc}"[:300]
            await asyncio.sleep(self.poll_s)

    def health(self) -> dict[str, Any]:
        now = int(time.time() * 1000)
        age = None if self.last_update_ms is None else (now - self.last_update_ms) / 1000
        status = self.status
        if age is not None and age > max(30, 4 * self.poll_s) and status != "DOWN":
            status = "STALE"
        return {"status": status, "transport": "websocket" if self.status == "LIVE" else "rest-polling",
                "last_update_ms": self.last_update_ms, "age_s": age, "reconnects": self.reconnects,
                "symbols": len(self.tickers), "last_error": self.last_error}
