"""Background workers. Three independent cadences:

  candle sync      every CANDLE_REFRESH_S     (data)
  forecast refresh every forecast_refresh_s   (inference only - loads saved models)
  model training   when a model is missing or older than RETRAIN_INTERVAL_H (slow, worker thread)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from ..config import MODEL_TIMEFRAMES, settings
from ..data.stream import LiveFeed
from . import alerts, analysis, health, market, tracking, training
from .runtime import Runtime

log = logging.getLogger(__name__)


class Jobs:
    def __init__(self, rt: Runtime):
        self.rt = rt
        self.tasks: list[asyncio.Task] = []
        self.heartbeat: dict[str, int] = {}

    async def _loop(self, name: str, interval: Callable[[], float], fn: Callable[[], Awaitable[Any]],
                    delay: float = 0.0) -> None:
        await asyncio.sleep(delay)
        while True:
            try:
                await fn()
                self.heartbeat[name] = health.now_ms()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # a failing job is logged and retried on its next tick
                log.exception("job %s failed", name)
                self.rt.record_error(f"job {name}", exc)
            await asyncio.sleep(max(1.0, interval()))

    async def sync_candles(self) -> None:
        await market.sync_all(self.rt)
        await asyncio.to_thread(tracking.resolve_outcomes, self.rt)
        await asyncio.to_thread(tracking.update_signal_outcomes, self.rt)

    async def refresh_forecasts(self) -> None:
        rt = self.rt
        for symbol in rt.symbols():
            for tf in MODEL_TIMEFRAMES:
                a = await asyncio.to_thread(analysis.analyze, rt, symbol, tf, None, None, False, False)
                for ev in alerts.evaluate(rt.db, a):
                    if rt.feed is not None:
                        rt.feed.publish({"type": "alert", "data": ev})
            await asyncio.sleep(0)
        if rt.feed is not None:
            rt.feed.publish({"type": "refresh", "data": {"ts": health.now_ms()}})

    async def refresh_books(self) -> None:
        for symbol in self.rt.symbols():
            await market.refresh_order_book(self.rt, symbol)
            await asyncio.sleep(0.2)

    async def train_due(self) -> None:
        due = training.due_for_training(self.rt)
        if due:
            log.info("training %d model(s)", len(due))
            await training.train_many(self.rt, due)

    async def housekeeping(self) -> None:
        await market.clock_skew(self.rt)
        await asyncio.to_thread(health.snapshot, self.rt)

    def start(self) -> None:
        rt = self.rt
        if rt.feed is None:
            rt.feed = LiveFeed(rt.provider, rt.symbols(), settings.enable_websocket_feed)
        rt.feed.start()
        spec = [
            ("candles", lambda: settings.candle_refresh_s, self.sync_candles, 0.0),
            ("forecasts", rt.refresh_seconds, self.refresh_forecasts, 20.0),
            ("order_books", lambda: 30.0, self.refresh_books, 5.0),
            ("training", lambda: 300.0, self.train_due, 45.0),
            ("housekeeping", lambda: 60.0, self.housekeeping, 10.0),
        ]
        for name, interval, fn, delay in spec:
            self.tasks.append(asyncio.create_task(self._loop(name, interval, fn, delay), name=f"job-{name}"))

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        if self.rt.feed is not None:
            await self.rt.feed.stop()
