"""Model training jobs. Runs in a worker thread, completely separate from forecast refresh."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ..config import MODEL_TIMEFRAMES, settings
from ..db import now_ms
from ..features.dataset import HTF_OF, InsufficientData
from ..ml import trainer
from .runtime import Runtime

log = logging.getLogger(__name__)
_lock = asyncio.Lock()


def train_one(rt: Runtime, symbol: str, timeframe: str, fast: bool = False) -> dict[str, Any]:
    """Blocking. Trains, validates and activates a new model version for one symbol/timeframe."""
    key = f"{symbol}|{timeframe}"
    status = rt.training[key] = {"symbol": symbol, "timeframe": timeframe, "state": "running", "progress": 0.0,
                                 "message": "building features", "started_at": now_ms()}

    def progress(p: float, msg: str) -> None:
        status.update(progress=round(0.05 + 0.85 * p, 3), message=msg)

    try:
        frame = rt.frame(symbol, timeframe)
        btc = None if symbol.startswith("BTC/") else _try_frame(rt, "BTC/USDT", timeframe)
        htf, htf_gate_res = None, None
        if timeframe in HTF_OF:
            hf = _try_frame(rt, symbol, HTF_OF[timeframe])
            if hf is not None and settings.use_htf_features:          # forced on for every series (old switch)
                htf = hf
            elif hf is not None and not fast:                          # v2.3: on only where it proves it helps
                status.update(message="testing higher-timeframe context")
                try:
                    from ..ml import htf_gate
                    htf_gate_res = htf_gate.decide(rt.db, symbol, timeframe, frame, btc, hf)
                    if htf_gate_res.get("on"):
                        htf = hf
                except Exception as exc:               # the gate must never stop training
                    log.warning("htf gate failed for %s %s: %s", symbol, timeframe, exc)
        deriv, gate = None, None
        if settings.use_deriv_features and not fast:
            status.update(message="testing futures features")
            try:
                from ..ml import deriv_gate
                gate = deriv_gate.decide(rt.db, symbol, timeframe, frame, btc, htf)
                if gate.get("on"):
                    deriv = rt.deriv_frame(symbol)
            except Exception as exc:               # the gate must never stop training
                log.warning("deriv gate failed for %s %s: %s", symbol, timeframe, exc)
        bundle = trainer.train_bundle(symbol, timeframe, frame, btc, fast=fast, progress=progress, htf=htf, deriv=deriv)
        bundle.setdefault("extras", {})["deriv_gate"] = gate
        bundle["extras"]["htf_gate"] = htf_gate_res
        status.update(progress=0.95, message="saving")
        trainer.save_bundle(bundle, rt.db)
        rt.analysis_cache.clear()
        status.update(state="done", progress=1.0, message=bundle["edge"]["verdict"], version=bundle["version"],
                      finished_at=now_ms(), edge_confirmed=bundle["edge"]["edge_confirmed"],
                      seconds=round((now_ms() - status["started_at"]) / 1000, 1))
    except InsufficientData as exc:
        status.update(state="skipped", insufficient=True, error=str(exc), message="INSUFFICIENT DATA", finished_at=now_ms(),
                      candles=rt.store.count(rt.exchange, symbol, timeframe))
    except Exception as exc:
        log.exception("training failed for %s %s", symbol, timeframe)
        rt.record_error(f"train {symbol} {timeframe}", exc)
        status.update(state="failed", error=f"{type(exc).__name__}: {exc}"[:300], message="failed", finished_at=now_ms())
    return status


def _try_frame(rt: Runtime, symbol: str, timeframe: str):
    try:
        return rt.frame(symbol, timeframe)
    except InsufficientData:
        return None


async def train_many(rt: Runtime, pairs: list[tuple[str, str]], fast: bool = False) -> None:
    """Sequential (one model fit at a time) so training never starves the API of CPU."""
    for symbol, tf in pairs:
        rt.training.setdefault(f"{symbol}|{tf}", {"symbol": symbol, "timeframe": tf, "state": "queued",
                                                  "progress": 0.0, "message": "queued"})
    async with _lock:
        for symbol, tf in pairs:
            await asyncio.to_thread(train_one, rt, symbol, tf, fast)


def due_for_training(rt: Runtime) -> list[tuple[str, str]]:
    """Symbol/timeframe pairs with no active model, or one older than RETRAIN_INTERVAL_H.

    A series is only trained once its history download has caught up with the present (otherwise a model
    could be fitted on a half-downloaded, stale history). CSV sources are exempt: they are static by nature.
    """
    due = []
    max_age = settings.retrain_interval_h * 3_600_000
    live_source = settings.exchange != "csv"
    for symbol in rt.symbols():
        for tf in MODEL_TIMEFRAMES:
            st = rt.training.get(f"{symbol}|{tf}", {})
            if st.get("state") in ("running", "queued"):
                continue
            if live_source and not rt.store.is_current(rt.exchange, symbol, tf):
                continue
            row = trainer.active_version(symbol, tf, rt.db)
            if row is None:
                # a series that was just refused for lack of data is retried only when more candles have
                # arrived, or after an hour
                if st.get("state") in ("skipped", "failed") and time.time() * 1000 - st.get("finished_at", 0) < 3_600_000 \
                        and rt.store.count(rt.exchange, symbol, tf) <= st.get("candles", 10 ** 12):
                    continue
                due.append((symbol, tf))
            elif now_ms() - row["created_at"] > max_age:
                due.append((symbol, tf))
    return due
