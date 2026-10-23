"""HTTP API. Mounted both at / (the paths in the spec) and at /api (what the frontend uses).

Symbols are written without a slash in URLs: BTC-USDT, BTCUSDT or just BTC all mean BTC/USDT.
CPU-bound handlers are plain `def` so FastAPI runs them in its thread pool.
"""
from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import Response

from ..backtest.strategies import STRATEGIES
from ..config import HORIZONS, MODEL_TIMEFRAMES, MTF_TIMEFRAMES, TIMEFRAMES, settings
from ..data.quality import check_candles
from ..db import dumps
from ..engine.regime import describe_regime
from ..engine.risk import RiskProfile, position_size
from ..engine.signal import optimise_weights
from ..features.dataset import InsufficientData
from ..ml import trainer
from ..ml.drift import drift_report
from ..ml.models import REGISTRY, model_status
from ..services import alerts, analysis, backtests, health, market, paper, replay, scanner, tracking, training
from ..services.runtime import get_runtime

router = APIRouter()
OVERLAYS = ["ema_9", "ema_21", "ema_50", "ema_200", "sma_20", "sma_50", "sma_200", "vwap", "bb_upper", "bb_mid",
            "bb_lower", "rsi", "macd", "macd_signal", "macd_hist", "kc_upper", "kc_lower", "dc_upper", "dc_lower",
            "span_a", "span_b", "tenkan", "kijun"]


def ok(data: Any) -> Response:
    """Strict JSON (NaN -> null, numpy -> python)."""
    return Response(dumps(data), media_type="application/json")


def sym(raw: str) -> str:
    s = raw.upper().replace("-", "/").replace("_", "/")
    if "/" not in s:
        s = f"{s[:-4]}/USDT" if s.endswith("USDT") and len(s) > 4 else f"{s}/USDT"
    return s


def tf_ok(tf: str) -> str:
    if tf not in TIMEFRAMES:
        raise HTTPException(400, f"unsupported timeframe '{tf}'. Use one of {TIMEFRAMES}")
    return tf


# ---- meta / watchlist -----------------------------------------------------------------------------------

@router.get("/meta")
def meta():
    rt = get_runtime()
    return ok({
        "app": "Crypto Intelligence AI", "mode": "ANALYSIS ONLY", "exchange": rt.exchange,
        "watchlist": rt.watchlist(), "timeframes": TIMEFRAMES, "model_timeframes": MODEL_TIMEFRAMES,
        "mtf_timeframes": MTF_TIMEFRAMES, "horizons": HORIZONS,
        "strategies": {k: {"label": v["label"], "params": v["params"]} for k, v in STRATEGIES.items()},
        "alert_types": alerts.ALERT_TYPES, "models": model_status(),
        "policy": {"min_confidence": settings.min_confidence, "min_model_agreement": settings.min_model_agreement,
                   "min_risk_reward": settings.min_risk_reward, "require_edge_for_ml": settings.require_edge_for_ml,
                   "require_edge_for_trade": settings.require_edge_for_trade, "edge_alpha": settings.edge_alpha,
                   "neutral_band_sigma": settings.neutral_band_sigma},
        "costs": {"fee_rate": settings.fee_rate, "slippage_bps": settings.slippage_bps, "spread_bps": settings.spread_bps},
    })


@router.get("/watchlist")
def watchlist():
    return ok(get_runtime().watchlist())


@router.post("/watchlist")
async def watchlist_add(body: dict = Body(...)):
    rt = get_runtime()
    s = sym(body["symbol"])
    try:   # only accept markets the exchange really lists
        found = await rt.provider.search_markets(s.split("/")[0], 50)
    except Exception as exc:
        raise HTTPException(502, f"exchange lookup failed: {exc}")
    if s not in found:
        raise HTTPException(404, f"{s} is not listed on {rt.exchange}")
    rt.add_symbol(s)
    asyncio.create_task(market.sync_symbol(rt, s, force=True))
    return ok(rt.watchlist())


@router.delete("/watchlist/{symbol}")
def watchlist_remove(symbol: str):
    rt = get_runtime()
    rt.remove_symbol(sym(symbol))
    return ok(rt.watchlist())


@router.put("/watchlist/{symbol}/pin")
def watchlist_pin(symbol: str, body: dict = Body(...)):
    rt = get_runtime()
    rt.pin_symbol(sym(symbol), bool(body.get("pinned", True)))
    return ok(rt.watchlist())


@router.get("/search")
async def search(q: str = Query(..., min_length=1)):
    rt = get_runtime()
    try:
        return ok({"query": q, "results": await rt.provider.search_markets(q, 20)})
    except Exception as exc:
        raise HTTPException(502, f"exchange lookup failed: {exc}")


# ---- market data ----------------------------------------------------------------------------------------

@router.get("/market/{symbol}")
def market_summary(symbol: str, timeframe: str = "4h"):
    rt = get_runtime()
    s = sym(symbol)
    a = analysis.analyze(rt, s, tf_ok(timeframe), detail=False)
    return ok({"symbol": s, "ticker": rt.ticker(s), "price": a.get("price"), "status": a["status"],
               "regime": a.get("regime"), "signal": (a.get("signal") or {}).get("signal"), "decision": a.get("decision"),
               "confidence": a.get("confidence"), "flags": a.get("flags"), "volatility": a.get("volatility")})


@router.get("/market/{symbol}/ohlcv")
def ohlcv(symbol: str, timeframe: str = "4h", limit: int = Query(500, ge=10, le=5000), overlays: bool = True):
    rt = get_runtime()
    s, tf = sym(symbol), tf_ok(timeframe)
    df = rt.candles(s, tf, include_forming=True).iloc[-limit:]
    out: dict[str, Any] = {"symbol": s, "timeframe": tf, "exchange": rt.exchange,
                           "candles": [[int(r.ts), r.open, r.high, r.low, r.close, r.volume] for r in df.itertuples()],
                           "quality": check_candles(df, tf)}
    if overlays:
        try:
            ind = rt.frame(s, tf).ind.iloc[-limit:]
            out["overlays"] = {"ts": ind["ts"].tolist(), **{k: ind[k].tolist() for k in OVERLAYS}}
        except InsufficientData as exc:
            out["overlays"], out["overlays_reason"] = None, str(exc)
    return ok(out)


@router.get("/market/{symbol}/orderbook")
async def orderbook(symbol: str):
    rt = get_runtime()
    s = sym(symbol)
    book = await market.refresh_order_book(rt, s)
    if not book:
        return ok({"symbol": s, "available": False, "reason": "the data source returned no order book"})
    from ..features.liquidity import order_book_metrics

    return ok({"symbol": s, "available": True, "metrics": order_book_metrics(book),
               "bids": book["bids"][:25], "asks": book["asks"][:25], "trade_flow": await market.recent_trade_flow(rt, s)})


@router.get("/market/{symbol}/derivatives")
async def derivatives(symbol: str):
    return ok(await market.derivatives_snapshot(get_runtime(), sym(symbol)))


# ---- analysis -------------------------------------------------------------------------------------------

@router.get("/analysis/{symbol}")
def full_analysis(symbol: str, timeframe: str = "4h"):
    return ok(analysis.analyze(get_runtime(), sym(symbol), tf_ok(timeframe)))


@router.get("/signal/{symbol}")
def signal(symbol: str, timeframe: str = "4h"):
    a = analysis.analyze(get_runtime(), sym(symbol), tf_ok(timeframe))
    return ok({"summary": analysis.final_signal(a), "signal": a.get("signal"), "setup": a.get("setup"),
               "risk": a.get("risk"), "commentary": a.get("commentary"), "confidence_detail": a.get("confidence_detail")})


@router.get("/forecast/{symbol}")
def forecast(symbol: str):
    rt = get_runtime()
    s = sym(symbol)
    return ok({"symbol": s, "price": rt.live_price(s), "horizons": analysis.horizon_forecasts(rt, s),
               "note": "Each horizon comes from the model trained on the matching timeframe (one bar ahead)."})


@router.get("/forecast/{symbol}/{timeframe}")
def forecast_tf(symbol: str, timeframe: str):
    return ok(analysis.model_forecast(get_runtime(), sym(symbol), tf_ok(timeframe), explain=True))


@router.get("/regime/{symbol}")
def regime(symbol: str, timeframe: str = "4h"):
    rt = get_runtime()
    try:
        fr = rt.frame(sym(symbol), tf_ok(timeframe))
    except InsufficientData as exc:
        return ok({"regime": "INSUFFICIENT DATA", "reason": str(exc)})
    tail = fr.ind.iloc[-300:]
    return ok({**describe_regime(fr.ind), "symbol": sym(symbol), "timeframe": timeframe,
               "history": {"ts": tail["ts"].tolist(), "regime": tail["regime"].tolist(),
                           "score": tail["regime_score"].tolist()}})


@router.get("/indicators/{symbol}")
def indicators(symbol: str, timeframe: str = "4h"):
    a = analysis.analyze(get_runtime(), sym(symbol), tf_ok(timeframe))
    if a["status"] != "OK":
        return ok(a)
    return ok({"symbol": a["symbol"], "timeframe": timeframe, "bar_ts": a["bar_ts"], "values": a["indicators"],
               "levels": a["levels"], "events": a["events"], "volatility": a["volatility"], "liquidity": a["liquidity"]})


@router.get("/scanner")
def scan(timeframe: str = "4h"):
    return ok({"timeframe": timeframe, "rows": scanner.scan(get_runtime(), tf_ok(timeframe))})


@router.get("/dashboard")
def dashboard(timeframe: str = "4h"):
    return ok(scanner.dashboard(get_runtime(), tf_ok(timeframe)))


@router.get("/cross-asset")
def cross_asset(timeframe: str = "1d"):
    return ok(scanner.cross_asset(get_runtime(), tf_ok(timeframe)))


@router.get("/context")
async def context():
    return ok(await market.external_context(get_runtime()))


# ---- models / performance ------------------------------------------------------------------------------

@router.get("/models/status")
def models_status():
    rt = get_runtime()
    return ok({"training": list(rt.training.values()), "libraries": model_status()})


@router.get("/models/{symbol}")
def models(symbol: str, timeframe: str = "4h"):
    rt = get_runtime()
    s, tf = sym(symbol), tf_ok(timeframe)
    b = trainer.load_bundle(s, tf, rt.db)
    if b is None:
        return ok({"symbol": s, "timeframe": tf, "available": False, "training": rt.training.get(f"{s}|{tf}"),
                   "reason": "no trained model for this symbol/timeframe yet", "libraries": model_status()})
    rows = [{"name": k, "label": "Ensemble" if k == "ensemble" else REGISTRY[k]["label"],
             "weight": b["weights"]["global"].get(k), "calibration_method": (b["calibration"].get(k) or {}).get("method"),
             "calibration_reason": (b["calibration"].get(k) or {}).get("reason"), **v} for k, v in b["metrics"].items()]
    return ok({
        "symbol": s, "timeframe": tf, "available": True, "version": b["version"], "trained_at": b["created_at"],
        "n_samples": b["n_samples"], "n_oos": b["n_oos"], "data_start": b["data_start"], "data_end": b["data_end"],
        "models": rows, "weights": b["weights"]["global"], "weights_by_regime": b["weights"]["by_regime"],
        "has_skill": b["weights"]["has_skill"], "edge": b["edge"], "best_model": b["best_model"],
        "folds": b["folds"], "live_fit": b["live_fit"], "sizes": b["sizes"], "fold_reports": b["fold_reports"],
        "interval_coverage": b["interval_coverage"], "reliability": b["reliability"], "importance": b["importance"],
        "failures": b["failures"], "libraries": b["model_status"], "features": len(b["feature_names"]),
        "selection_note": "The best single model is only named as 'supported' if its out-of-sample Brier score is "
                          "significantly better than the class-prior baseline. Model choice never uses RMSE alone.",
    })


@router.post("/models/train")
async def train(body: dict = Body(default={})):
    rt = get_runtime()
    symbols = [sym(body["symbol"])] if body.get("symbol") else rt.symbols()
    tfs = [tf_ok(body["timeframe"])] if body.get("timeframe") else MODEL_TIMEFRAMES
    pairs = [(s, tf) for s in symbols for tf in tfs if tf in MODEL_TIMEFRAMES]
    if not pairs:
        raise HTTPException(400, f"models are trained on {MODEL_TIMEFRAMES}")
    asyncio.create_task(training.train_many(rt, pairs, bool(body.get("fast", False))))
    return ok({"queued": [f"{s} {tf}" for s, tf in pairs]})


@router.get("/performance")
def performance_all():
    rt = get_runtime()
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
    return ok({"rows": rows, "live": tracking.live_stats(rt.db), "signals": tracking.signal_summary(rt.db)})


@router.get("/performance/{symbol}")
def performance(symbol: str, timeframe: str = "4h"):
    rt = get_runtime()
    s, tf = sym(symbol), tf_ok(timeframe)
    live = tracking.live_stats(rt.db, s, tf)
    b = trainer.load_bundle(s, tf, rt.db)
    out: dict[str, Any] = {"symbol": s, "timeframe": tf, "live": live, "model": None, "drift": None}
    if b is None:
        out["reason"] = "no trained model for this symbol/timeframe yet"
        return ok(out)
    out["model"] = {"version": b["version"], "trained_at": b["created_at"], "n_oos": b["n_oos"],
                    "ensemble": b["metrics"]["ensemble"], "edge": b["edge"], "reliability": b["reliability"],
                    "interval_coverage": b["interval_coverage"],
                    "source": "walk-forward out-of-sample predictions (never seen during fitting)"}
    try:
        ds = rt.dataset(s, tf, b["uses_btc"])
        X = ds.X[b["feature_names"]].to_numpy(float)
        recent = X[np.isfinite(X).all(axis=1)][-200:]
        preds = rt.db.query("SELECT p_up FROM predictions WHERE symbol = ? AND timeframe = ? ORDER BY bar_ts DESC LIMIT 200",
                            (s, tf))
        p_up = np.array([p["p_up"] for p in preds], float) if len(preds) >= 30 else None
        vol_now = float(ds.X["vol_pct"].iloc[-1])
        out["drift"] = drift_report(b, recent, p_up, vol_now, tracking.performance_windows(rt.db, b))
    except Exception as exc:
        out["drift"] = {"drift_detected": None, "error": f"{type(exc).__name__}: {exc}"[:200]}
    return ok(out)


@router.get("/signals/history")
def signals_history(symbol: str | None = None, limit: int = Query(200, ge=1, le=1000)):
    rt = get_runtime()
    return ok({"signals": tracking.signal_history(rt.db, sym(symbol) if symbol else None, limit),
               "summary": tracking.signal_summary(rt.db)})


# ---- backtesting / replay ------------------------------------------------------------------------------

@router.post("/backtest")
def backtest(body: dict = Body(...)):
    if "symbol" not in body:
        raise HTTPException(400, "symbol is required")
    body = {**body, "symbol": sym(body["symbol"]), "timeframe": tf_ok(body.get("timeframe", "4h"))}
    if body.get("strategy", "technical") not in STRATEGIES:
        raise HTTPException(400, f"unknown strategy. Use one of {list(STRATEGIES)}")
    return ok(backtests.run(get_runtime(), body))


@router.get("/backtest/{backtest_id}")
def backtest_get(backtest_id: str):
    r = backtests.get(get_runtime(), backtest_id)
    if not r:
        raise HTTPException(404, "backtest not found")
    return ok(r)


@router.get("/backtests")
def backtest_history():
    return ok(backtests.history(get_runtime()))


@router.get("/replay/{symbol}/range")
def replay_range(symbol: str, timeframe: str = "4h"):
    return ok(replay.replay_range(get_runtime(), sym(symbol), tf_ok(timeframe)))


@router.get("/replay/{symbol}")
def replay_run(symbol: str, as_of: int, timeframe: str = "4h", bars_after: int = Query(30, ge=1, le=200),
               with_model: bool = True):
    return ok(replay.replay(get_runtime(), sym(symbol), tf_ok(timeframe), as_of, bars_after, with_model))


# ---- alerts --------------------------------------------------------------------------------------------

@router.get("/alerts")
def alerts_list():
    rt = get_runtime()
    return ok({"alerts": alerts.list_alerts(rt.db), "events": alerts.events(rt.db), "types": alerts.ALERT_TYPES})


@router.post("/alerts")
def alerts_create(body: dict = Body(...)):
    try:
        return ok(alerts.create_alert(get_runtime().db, body["type"], sym(body["symbol"]), tf_ok(body.get("timeframe", "4h")),
                                      body.get("params"), int(body.get("cooldown_s", 3600))))
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc))


@router.delete("/alerts/{alert_id}")
def alerts_delete(alert_id: str):
    alerts.delete_alert(get_runtime().db, alert_id)
    return ok({"deleted": alert_id})


@router.put("/alerts/{alert_id}")
def alerts_toggle(alert_id: str, body: dict = Body(...)):
    alerts.set_enabled(get_runtime().db, alert_id, bool(body.get("enabled", True)))
    return ok({"id": alert_id, "enabled": bool(body.get("enabled", True))})


@router.post("/alerts/read")
def alerts_read():
    alerts.mark_read(get_runtime().db)
    return ok({"ok": True})


# ---- paper trading -------------------------------------------------------------------------------------

@router.get("/paper")
def paper_state():
    return ok(paper.state(get_runtime()))


@router.post("/paper/order")
def paper_order(body: dict = Body(...)):
    try:
        t = paper.order(get_runtime(), sym(body["symbol"]), body["side"], body.get("qty"), body.get("notional"),
                        body.get("note"))
    except (paper.PaperError, KeyError) as exc:
        raise HTTPException(400, str(exc))
    return ok({"trade": t, "state": paper.state(get_runtime())})


@router.post("/paper/reset")
def paper_reset(body: dict = Body(default={})):
    try:
        paper.reset(get_runtime(), float(body.get("starting_balance", 10_000)))
    except paper.PaperError as exc:
        raise HTTPException(400, str(exc))
    return ok(paper.state(get_runtime()))


# ---- settings / risk -----------------------------------------------------------------------------------

@router.get("/settings")
def settings_get():
    rt = get_runtime()
    return ok({"risk_profile": rt.risk_profile().__dict__, "signal_weights": rt.signal_weights(),
               "forecast_refresh_s": rt.refresh_seconds(), "refresh_options_s": [60, 300, 900, 1800, 3600]})


@router.put("/settings")
def settings_put(body: dict = Body(...)):
    rt = get_runtime()
    if "risk_profile" in body:
        rt.db.set_setting("risk_profile", RiskProfile.from_dict(body["risk_profile"]).__dict__)
    if "signal_weights" in body:
        w = {k: max(0.0, float(v)) for k, v in body["signal_weights"].items() if k in rt.signal_weights()}
        if sum(w.values()) <= 0:
            raise HTTPException(400, "weights must not all be zero")
        rt.db.set_setting("signal_weights", w)
    if "forecast_refresh_s" in body:
        if int(body["forecast_refresh_s"]) not in (60, 300, 900, 1800, 3600):
            raise HTTPException(400, "refresh must be 60, 300, 900, 1800 or 3600 seconds")
        rt.db.set_setting("forecast_refresh_s", int(body["forecast_refresh_s"]))
    rt.analysis_cache.clear()
    return settings_get()


@router.post("/settings/optimise-weights")
def settings_optimise(body: dict = Body(...)):
    rt = get_runtime()
    try:
        fr = rt.frame(sym(body["symbol"]), tf_ok(body.get("timeframe", "4h")))
    except InsufficientData as exc:
        return ok({"ok": False, "reason": str(exc)})
    fwd = fr.ind["close"].shift(-1) / fr.ind["close"] - 1
    return ok(optimise_weights(fr.ind, fwd))


@router.post("/risk/position-size")
def risk_size(body: dict = Body(...)):
    rt = get_runtime()
    profile = RiskProfile.from_dict({**rt.risk_profile().__dict__, **(body.get("profile") or {})})
    try:
        entry, stop = float(body["entry"]), float(body["stop"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "entry and stop are required numbers")
    st = paper.state(rt)
    return ok(position_size(profile, entry, stop, body.get("sigma_bar"), body.get("timeframe", "4h"),
                            open_exposure=st["market_value"], realised_today=st["day_realized_pnl"]))


# ---- system --------------------------------------------------------------------------------------------

@router.get("/system/health")
def system_health():
    return ok(health.report(get_runtime()))
