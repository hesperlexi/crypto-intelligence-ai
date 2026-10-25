"""Payload builders shared by the batch engine (published to Firestore) and the local HTTP API.

Every function returns plain data in exactly the shape the website expects.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .backtest.strategies import STRATEGIES
from .config import HORIZONS, MODEL_TIMEFRAMES, MTF_TIMEFRAMES, TIMEFRAMES, settings
from .db import loads, now_ms
from .ml import trainer
from .ml.drift import drift_report
from .ml.models import REGISTRY, model_status
from .services import alerts, backtests, replay, tracking
from .services.runtime import Runtime

ASSET_TIMEFRAMES = ["15m", "1h", "4h", "12h", "1d", "3d", "1w"]


def slug(symbol: str) -> str:
    return symbol.replace("/", "")


def meta(rt: Runtime, engine: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "app": "Crypto Intelligence AI", "mode": "ANALYSIS ONLY", "exchange": rt.exchange,
        "watchlist": rt.watchlist(), "timeframes": TIMEFRAMES, "asset_timeframes": ASSET_TIMEFRAMES,
        "model_timeframes": MODEL_TIMEFRAMES, "mtf_timeframes": MTF_TIMEFRAMES, "horizons": HORIZONS,
        "strategies": {k: {"label": v["label"], "params": v["params"]} for k, v in STRATEGIES.items()},
        "alert_types": alerts.ALERT_TYPES, "models": model_status(),
        "policy": {"min_confidence": settings.min_confidence, "min_model_agreement": settings.min_model_agreement,
                   "min_risk_reward": settings.min_risk_reward, "require_edge_for_ml": settings.require_edge_for_ml,
                   "require_edge_for_trade": settings.require_edge_for_trade, "edge_alpha": settings.edge_alpha,
                   "neutral_band_sigma": settings.neutral_band_sigma},
        "costs": {"fee_rate": settings.fee_rate, "slippage_bps": settings.slippage_bps, "spread_bps": settings.spread_bps},
        "engine": engine or {},
    }


def models(rt: Runtime, symbol: str, tf: str) -> dict[str, Any]:
    b = trainer.load_bundle(symbol, tf, rt.db)
    if b is None:
        return {"symbol": symbol, "timeframe": tf, "available": False, "training": rt.training.get(f"{symbol}|{tf}"),
                "reason": "no trained model for this symbol/timeframe yet", "libraries": model_status()}
    rows = [{"name": k, "label": "Ensemble" if k == "ensemble" else REGISTRY[k]["label"],
             "weight": b["weights"]["global"].get(k), "calibration_method": (b["calibration"].get(k) or {}).get("method"),
             "calibration_reason": (b["calibration"].get(k) or {}).get("reason"), **v} for k, v in b["metrics"].items()]
    return {
        "symbol": symbol, "timeframe": tf, "available": True, "version": b["version"], "trained_at": b["created_at"],
        "fast": b.get("fast", False),
        "n_samples": b["n_samples"], "n_oos": b["n_oos"], "data_start": b["data_start"], "data_end": b["data_end"],
        "models": rows, "weights": b["weights"]["global"], "weights_by_regime": b["weights"]["by_regime"],
        "has_skill": b["weights"]["has_skill"], "edge": b["edge"], "best_model": b["best_model"],
        "folds": b["folds"], "live_fit": b["live_fit"], "sizes": b["sizes"], "fold_reports": b["fold_reports"][-20:],
        "interval_coverage": b["interval_coverage"], "reliability": b["reliability"], "importance": b["importance"],
        "failures": b["failures"], "libraries": b["model_status"], "features": len(b["feature_names"]),
        "selective": b.get("selective"), "uses_htf": b.get("uses_htf"),
        "selection_note": "The best single model is only named as 'supported' if its out-of-sample Brier score is "
                          "significantly better than the class-prior baseline. Model choice never uses RMSE alone.",
    }


def performance_all(rt: Runtime) -> dict[str, Any]:
    rows = []
    for s in rt.symbols():
        for tf in MODEL_TIMEFRAMES:
            v = trainer.active_version(s, tf, rt.db)
            if not v:
                continue
            m = trainer.metrics_table(v["id"], rt.db).get("ensemble", {})
            live = tracking.live_stats(rt.db, s, tf, last=100)
            rows.append({"symbol": s, "timeframe": tf, "version": v["id"], "trained_at": v["created_at"],
                         "edge_confirmed": bool(v["edge_confirmed"]), "n_oos": v["n_oos"],
                         "oos_accuracy": m.get("accuracy"), "oos_directional_accuracy": m.get("directional_accuracy"),
                         "oos_brier": m.get("brier"), "oos_sharpe": m.get("sharpe"), "oos_net_return": m.get("net_return"),
                         "oos_max_drawdown": m.get("max_drawdown"), "oos_profit_factor": m.get("profit_factor"),
                         "live_n": live["resolved"], "live_accuracy": live["overall"]["accuracy"],
                         "live_30d": live["rolling"]["30d"]["accuracy"]})
    live = tracking.live_stats(rt.db)
    live.pop("recent", None)
    return {"rows": rows, "live": live, "signals": tracking.signal_summary(rt.db)}


def performance(rt: Runtime, symbol: str, tf: str) -> dict[str, Any]:
    live = tracking.live_stats(rt.db, symbol, tf)
    b = trainer.load_bundle(symbol, tf, rt.db)
    out: dict[str, Any] = {"symbol": symbol, "timeframe": tf, "live": live, "model": None, "drift": None}
    if b is None:
        out["reason"] = "no trained model for this symbol/timeframe yet"
        return out
    out["model"] = {"version": b["version"], "trained_at": b["created_at"], "n_oos": b["n_oos"],
                    "ensemble": b["metrics"]["ensemble"], "edge": b["edge"], "reliability": b["reliability"],
                    "interval_coverage": b["interval_coverage"],
                    "source": "walk-forward out-of-sample predictions (never seen during fitting)"}
    try:
        ds = rt.dataset(symbol, tf, b["uses_btc"])
        X = ds.X[b["feature_names"]].to_numpy(float)
        recent = X[np.isfinite(X).all(axis=1)][-200:]
        preds = rt.db.query("SELECT p_up FROM predictions WHERE symbol = ? AND timeframe = ? ORDER BY bar_ts DESC LIMIT 200",
                            (symbol, tf))
        p_up = np.array([p["p_up"] for p in preds], float) if len(preds) >= 30 else None
        out["drift"] = drift_report(b, recent, p_up, float(ds.X["vol_pct"].iloc[-1]), tracking.performance_windows(rt.db, b))
    except Exception as exc:
        out["drift"] = {"drift_detected": None, "error": f"{type(exc).__name__}: {exc}"[:200]}
    return out


def models_status(rt: Runtime) -> dict[str, Any]:
    rows = list(rt.training.values())
    for s in rt.symbols():          # the engine is short-lived: fill in active versions from the database
        for tf in MODEL_TIMEFRAMES:
            key = f"{s}|{tf}"
            if key in rt.training:
                continue
            v = trainer.active_version(s, tf, rt.db)
            if v:
                rows.append({"symbol": s, "timeframe": tf, "state": "done", "progress": 1.0, "version": v["id"],
                             "message": "NO STATISTICALLY CONFIRMED EDGE" if not v["edge_confirmed"] else "edge confirmed",
                             "finished_at": v["created_at"], "fast": (v.get("summary") or {}).get("fast")})
    return {"training": rows, "libraries": model_status()}


def signals(rt: Runtime) -> dict[str, Any]:
    return {"signals": tracking.signal_history(rt.db, None, 300), "summary": tracking.signal_summary(rt.db)}


def alerts_view(rt: Runtime, user_id: str | None = None) -> dict[str, Any]:
    """Alert state and fired events. With `user_id`, only that user's rules (members never see each other's)."""
    rows = rt.db.query("SELECT * FROM alerts" + (" WHERE user_id = ?" if user_id else ""), (user_id,) if user_id else ())
    state = {a["id"]: {"last_fired_at": a["last_fired_at"], "last_state": a["last_state"]} for a in rows}
    if user_id:
        # this member's own events, however many other members there are
        ids = list(state)
        evs = rt.db.query(f"SELECT * FROM alert_events WHERE alert_id IN ({','.join('?' * len(ids))}) "
                          "ORDER BY created_at DESC LIMIT 100", tuple(ids)) if ids else []
    else:
        evs = alerts.events(rt.db, 100)
    return {"events": evs[:100], "state": state, "types": alerts.ALERT_TYPES}


def backtest_history(rt: Runtime) -> list[dict[str, Any]]:
    return backtests.history(rt)


def replay_ranges(rt: Runtime) -> dict[str, Any]:
    return {f"{slug(s)}_{tf}": replay.replay_range(rt, s, tf) for s in rt.symbols() for tf in ("1h", "4h", "12h", "1d")}


def settings_view(rt: Runtime) -> dict[str, Any]:
    return {"risk_profile": rt.risk_profile().__dict__, "signal_weights": rt.signal_weights(), "generated_at": now_ms()}


# ---- futures -----------------------------------------------------------------------------------------------
FUTURES_TIMEFRAMES = ("1h", "4h", "12h", "1d")


def futures(rt: Runtime, timeframe: str, analyses: dict[tuple[str, str], dict]) -> dict[str, Any]:
    from .engine import futures as F

    funding = getattr(rt, "funding_rates", None) or {}
    rows = [F.futures_view(analyses[(s, timeframe)], funding.get(s)) for s in rt.symbols() if (s, timeframe) in analyses]
    order = {"LONG": 0, "LONG ON PULLBACK": 0, "SHORT": 0, "NO TRADE": 1}
    rows.sort(key=lambda r: (order.get(r.get("action"), 2), -(r.get("confidence") or 0)))
    return {
        "timeframe": timeframe, "rows": rows,
        "funding_source": "Binance futures (live)" if funding else
            f"assumed {F.DEFAULT_FUNDING_RATE * 100:.2f}% per 8h: Binance's futures API is not reachable from the engine's "
            "server, your browser shows the live rate",
        "assumptions": {"maintenance_margin": F.MAINTENANCE_MARGIN, "fee_rate": F.FUTURES_FEE_RATE,
                        "max_suggested_leverage": 10, "liquidation_buffer": 1.5},
    }


# ---- public track record ---------------------------------------------------------------------------------------

def track_record(rt: Runtime, bot_report: dict[str, Any] | None = None, limit: int = 150) -> dict[str, Any]:
    """Everything a visitor needs to judge the app honestly, readable without an account (views/track_record):
    every trade signal since launch with its real outcome, the models' results on past data they never trained on
    (clearly a simulation), and the demo bots' results. Nothing is filtered for looks."""
    import numpy as np

    from .ml import direction as dirview, trainer

    rows = rt.db.query("SELECT * FROM signals WHERE status != 'INFO' ORDER BY created_at DESC")
    sigs = []
    for r in rows:
        p = loads(r.get("payload"), {}) if isinstance(r.get("payload"), str) else (r.get("payload") or {})
        sigs.append({"symbol": r["symbol"], "timeframe": r["timeframe"], "side": "LONG" if r["side"] > 0 else "SHORT",
                     "decision": r["decision"], "grade": p.get("grade"), "created_at": r["created_at"], "entry": r["entry"],
                     "stop": r["stop"], "tp1": r["tp1"], "tp2": r["tp2"], "tp3": r["tp3"], "status": r["status"],
                     "closed_at": r["closed_at"], "return_pct": r["return_pct"]})
    closed = [x for x in sigs if x["status"] not in ("OPEN",) and x["return_pct"] is not None]

    def summ(xs: list[dict[str, Any]]) -> dict[str, Any]:
        r = np.array([x["return_pct"] for x in xs], float)
        if not len(r):
            return {"closed": 0}
        wins = r[r > 0]
        losses = r[r <= 0]
        return {"closed": int(len(r)), "win_rate": float((r > 0).mean()), "avg_return_pct": float(r.mean()),
                "total_return_pct": float(r.sum()), "best_pct": float(r.max()), "worst_pct": float(r.min()),
                "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else None}

    by_tf = {tf: summ([x for x in closed if x["timeframe"] == tf]) for tf in sorted({x["timeframe"] for x in closed})}
    by_grade = {g: summ([x for x in closed if (x["grade"] or "-") == g]) for g in sorted({x["grade"] or "-" for x in closed})}
    curve, acc = [], 0.0
    for x in sorted(closed, key=lambda x: x["closed_at"] or x["created_at"]):
        acc += x["return_pct"]
        curve.append({"ts": x["closed_at"] or x["created_at"], "cum_return_pct": acc})

    tested = []
    for s in rt.symbols():
        for tf in MODEL_TIMEFRAMES:
            try:
                b = trainer.load_bundle(s, tf, rt.db)
            except Exception:
                b = None
            if not b:
                continue
            pol = dirview.direction_policy(b.get("oos") or {}, b.get("version"))
            if not pol:
                continue
            best = pol.get("best") or {}
            o = b.get("oos") or {}
            ts = o.get("ts")
            days = (int(ts[-1]) - int(ts[0])) / 86_400_000 if ts is not None and len(ts) > 1 else None
            tested.append({"symbol": s, "timeframe": tf, "edge": pol.get("edge"), "all_calls_hit_rate": pol.get("base_hit_rate"),
                           "selective_hit_rate": best.get("hit_rate"), "selective_ci95": best.get("ci95"),
                           "selective_calls": best.get("n"), "coverage": best.get("coverage"), "tested_days": days,
                           "calls_per_day": (best.get("n") / days) if best.get("n") and days else None})
    bots = []
    for bt in (bot_report or {}).get("bots", []):
        st, cfg = bt.get("stats") or {}, bt.get("config") or {}
        if not cfg.get("enabled", True):
            continue
        bots.append({"name": cfg.get("name") or cfg.get("id"), "mode": cfg.get("mode"), "market": cfg.get("market", "spot"), "timeframe": cfg.get("timeframe"),
                     "grades": cfg.get("grades"), "trades": st.get("trades"), "return_pct": st.get("return_pct"),
                     "benchmark_return_pct": st.get("benchmark_return_pct"), "win_rate": st.get("win_rate"),
                     "max_drawdown_pct": st.get("max_drawdown_pct"), "started_at": (bt.get("state") or {}).get("started_at")})
    first = min((x["created_at"] for x in sigs), default=None)
    return {"generated_at": now_ms(), "since": first, "live": {"summary": summ(closed), "by_timeframe": by_tf,
            "by_grade": by_grade, "open": sum(x["status"] == "OPEN" for x in sigs), "curve": curve[-500:],
            "signals": sigs[:limit]},
            "tested": sorted(tested, key=lambda t: (not t["edge"], -(t["selective_hit_rate"] or 0))), "bots": bots,
            "method": {"live": "Every trade signal the engine published, followed candle by candle: a third of the position "
                               "exits at each take-profit, the rest at the stop or after 30 candles. Fees not included.",
                       "tested": "Walk-forward test: the models are trained only on data before each test period and then "
                                 "scored on the following period, which they never saw. A simulation, not live results."}}
