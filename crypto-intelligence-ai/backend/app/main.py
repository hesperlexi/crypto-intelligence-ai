"""FastAPI entry point:  uvicorn app.main:app --reload --port 8000"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes import router
from .config import settings
from .db import dumps, get_db
from .services import market
from .services.jobs import Jobs
from .services.runtime import Runtime, get_runtime, set_runtime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("crypto-ai")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    rt = Runtime(get_db(), market.make_provider())
    if settings.exchange != "csv" and settings.derivatives_exchange:
        try:
            from .data.ccxt_provider import DerivativesProvider

            rt.derivatives = DerivativesProvider(settings.derivatives_exchange)
        except Exception as exc:  # derivatives data is optional
            log.warning("derivatives venue unavailable: %s", exc)
    set_runtime(rt)
    jobs = Jobs(rt)
    if settings.enable_background_jobs:
        jobs.start()
    app.state.jobs = jobs
    log.info("Crypto Intelligence AI started (exchange=%s, mode=ANALYSIS ONLY)", rt.exchange)
    try:
        yield
    finally:
        await jobs.stop()
        for p in (rt.provider, rt.derivatives):
            if p is not None:
                await p.close()
        set_runtime(None)


app = FastAPI(title="Crypto Intelligence AI", version="0.1.0", lifespan=lifespan,
              description="Multi-model crypto forecasting, market regime and trading-signal research platform. "
                          "Analysis only: no real orders are ever placed.")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(router, prefix="/api")
app.include_router(router, include_in_schema=False)   # the un-prefixed paths from the spec


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    """Database / model / provider failures become a clear JSON error instead of a stack trace."""
    log.exception("unhandled error on %s", request.url.path)
    try:
        get_runtime().record_error(request.url.path, exc)
    except Exception:
        pass
    return JSONResponse(status_code=500, content={"error": type(exc).__name__, "detail": str(exc)[:300],
                                                  "path": request.url.path})


@app.get("/")
def root():
    return {"app": "Crypto Intelligence AI", "docs": "/docs", "health": "/api/system/health", "mode": "ANALYSIS ONLY"}


@app.websocket("/ws")
async def ws(socket: WebSocket):
    """Pushes live tickers, alert events and 'refresh' notices to the dashboard."""
    await socket.accept()
    rt = get_runtime()
    if rt.feed is None:
        await socket.send_text(dumps({"type": "status", "data": {"feed": "DISABLED"}}))
        await socket.close()
        return
    q = rt.feed.subscribe()
    try:
        await socket.send_text(dumps({"type": "snapshot", "data": rt.feed.tickers, "feed": rt.feed.health()}))
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=15)
                await socket.send_text(dumps(msg))
            except asyncio.TimeoutError:
                await socket.send_text(dumps({"type": "heartbeat", "feed": rt.feed.health()}))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        rt.feed.unsubscribe(q)
