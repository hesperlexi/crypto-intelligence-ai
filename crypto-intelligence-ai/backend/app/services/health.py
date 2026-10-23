"""System health: data freshness and quality, exchange / feed status, database, models, background jobs."""
from __future__ import annotations

import time
from typing import Any

from ..config import MODEL_TIMEFRAMES, settings
from ..data.quality import check_candles
from ..db import dumps, new_id, now_ms
from ..ml.models import model_status
from ..ml.trainer import active_version
from .runtime import Runtime

HEALTH_TIMEFRAMES = ["15m", "1h", "4h", "1d"]


def report(rt: Runtime, full: bool = True) -> dict[str, Any]:
    now = now_ms()
    feed = rt.feed.health() if rt.feed is not None else {"status": "DISABLED", "transport": None, "age_s": None}
    prov = rt.provider
    exchange = {
        "name": rt.exchange, "errors": getattr(prov, "errors", 0), "last_error": getattr(prov, "last_error", None),
        "last_ok_ms": getattr(prov, "last_ok_ms", None), "clock_skew_ms": rt.clock_skew_ms,
        "status": "UNKNOWN" if getattr(prov, "last_ok_ms", None) is None else
        ("OK" if now - prov.last_ok_ms < 300_000 else "STALE"),
    }
    db_ok = rt.db.ping()
    series, total_missing, total_expected = [], 0, 0
    if full:
        for sym in rt.symbols():
            for tf in HEALTH_TIMEFRAMES:
                q = check_candles(rt.candles(sym, tf, include_forming=True), tf, now)
                q["symbol"] = sym
                series.append(q)
                if q["candles"]:
                    bad = q["missing"] + q["malformed"] + q.get("misaligned", 0)
                    total_missing += bad
                    total_expected += q["candles"] + q["missing"]
    quality = None if not total_expected else round(100 * (1 - total_missing / total_expected), 3)
    models = []
    for sym in rt.symbols():
        for tf in MODEL_TIMEFRAMES:
            row = active_version(sym, tf, rt.db)
            st = rt.training.get(f"{sym}|{tf}", {})
            models.append({"symbol": sym, "timeframe": tf, "version": row["id"] if row else None,
                           "trained_at": row["created_at"] if row else None,
                           "age_h": None if not row else round((now - row["created_at"]) / 3.6e6, 1),
                           "edge_confirmed": bool(row["edge_confirmed"]) if row else None,
                           "state": st.get("state") or ("active" if row else "untrained"),
                           "progress": st.get("progress"), "message": st.get("error") or st.get("message")})
    stale = [s for s in series if s["status"] == "STALE"]
    overall = "LIVE"
    if not db_ok or feed["status"] == "DOWN":
        overall = "DOWN"
    elif feed["status"] in ("STALE", "STARTING", "DISABLED", "UNKNOWN") or stale or (quality is not None and quality < 99):
        overall = "DEGRADED"
    return {
        "status": overall, "generated_at": now, "uptime_s": rt.uptime_s(),
        "market_data": {"status": feed["status"], "transport": feed.get("transport"), "last_update_ms": feed.get("last_update_ms"),
                        "age_s": feed.get("age_s"), "reconnects": feed.get("reconnects"), "last_error": feed.get("last_error"),
                        "quality_pct": quality, "stale_series": len(stale)},
        "exchange": exchange, "database": {"ok": db_ok, "engine": "postgresql" if rt.db.is_postgres else "sqlite"},
        "series": series, "models": models, "model_libraries": model_status(),
        "recent_errors": rt.errors[-20:][::-1],
        "config": {"exchange": settings.exchange, "background_jobs": settings.enable_background_jobs,
                   "websocket_feed": settings.enable_websocket_feed, "deep_models": settings.enable_deep_models,
                   "forecast_refresh_s": rt.refresh_seconds(), "retrain_interval_h": settings.retrain_interval_h,
                   "mode": "ANALYSIS ONLY - no real orders are ever placed"},
    }


def snapshot(rt: Runtime) -> None:
    """Persist a compact health record (kept for 7 days)."""
    r = report(rt, full=False)
    for component, status, detail in (
        ("market_data", r["market_data"]["status"], r["market_data"]),
        ("exchange", r["exchange"]["status"], r["exchange"]),
        ("database", "OK" if r["database"]["ok"] else "DOWN", r["database"]),
    ):
        rt.db.execute("INSERT INTO system_health (id, ts, component, status, detail) VALUES (?, ?, ?, ?, ?)",
                      (new_id(), r["generated_at"], component, status, dumps(detail)))
    rt.db.execute("DELETE FROM system_health WHERE ts < ?", (int(time.time() * 1000) - 7 * 86_400_000,))
