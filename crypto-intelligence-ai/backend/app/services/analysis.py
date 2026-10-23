"""Per-asset analysis: assembles regime, multi-timeframe view, model forecast, signal, trade plan and risk
into the structured output the API returns. Every number originates in an engine, a model or the database."""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from ..backtest.benchmarks import NO_EDGE
from ..config import HORIZONS, MODEL_TIMEFRAMES, MTF_TIMEFRAMES, settings
from ..data.base import tf_ms
from ..data.quality import check_candles
from ..engine import mtf as mtf_engine
from ..engine.commentary import build_commentary
from ..engine.regime import describe_regime
from ..engine.risk import position_size
from ..engine.setup import build_setup
from ..engine.signal import build_signal
from ..features.dataset import InsufficientData
from ..features.liquidity import order_book_metrics
from ..features.structure import fib_levels, liquidity_zones, sr_zones, supply_demand_zones
from ..features.volatility import vol_state_name
from ..ml import trainer
from . import tracking
from .runtime import Runtime, ttl_get

TRADE_DECISIONS = ("BUY", "BUY ON PULLBACK", "SELL")


def model_forecast(rt: Runtime, symbol: str, timeframe: str, as_of: int | None = None,
                   bundle: dict[str, Any] | None = None, explain: bool = False) -> dict[str, Any]:
    """Forecast for the next bar of `timeframe` from that timeframe's own model."""
    if timeframe not in MODEL_TIMEFRAMES:
        return {"available": False, "status": "NOT MODELLED",
                "reason": f"no model is trained on {timeframe}; forecasts exist for {', '.join(MODEL_TIMEFRAMES)}"}
    if as_of is not None and bundle is None:
        # a historical replay may only use a model trained on data before the replay date
        return {"available": False, "status": "MODEL NOT TRAINED",
                "reason": "no model trained before the replay date was supplied"}
    bundle = bundle or trainer.load_bundle(symbol, timeframe, rt.db)
    if bundle is None:
        st = rt.training.get(f"{symbol}|{timeframe}", {})
        reason = st.get("error") or ("training in progress" if st.get("state") == "running"
                                     else "model not trained yet for this timeframe")
        return {"available": False, "status": "INSUFFICIENT DATA" if st.get("insufficient") else "MODEL NOT TRAINED",
                "reason": reason}
    try:
        ds = rt.dataset(symbol, timeframe, bundle["uses_btc"], as_of)
        mult = tracking.live_multipliers(rt.db, bundle) if as_of is None else {}
        fc = trainer.predict(bundle, ds, multipliers=mult)
    except InsufficientData as exc:
        return {"available": False, "status": "INSUFFICIENT DATA", "reason": str(exc)}
    except Exception as exc:  # model failure: surface it, never substitute a made-up forecast
        rt.record_error(f"forecast {symbol} {timeframe}", exc)
        return {"available": False, "status": "MODEL ERROR", "reason": f"{type(exc).__name__}: {exc}"[:200]}
    edge = bundle["edge"]
    fc.update({
        "available": True, "status": "OK", "timeframe": timeframe,
        "edge_confirmed": bool(edge["edge_confirmed"]), "edge_verdict": edge["verdict"],
        "edge_failed_checks": edge["failed_checks"], "trained_at": bundle["created_at"],
        "model_age_h": (time.time() * 1000 - bundle["created_at"]) / 3.6e6,
        "interval_coverage": bundle["interval_coverage"], "live_downweighted": sorted(mult),
        "best_model": bundle["best_model"]["name"] if bundle["best_model"]["supported"] else None,
    })
    if explain:
        try:
            fc["explanation"] = trainer.explain_prediction(bundle, ds)
        except Exception as exc:
            rt.record_error(f"explain {symbol} {timeframe}", exc)
            fc["explanation"] = None
    return fc


def horizon_forecasts(rt: Runtime, symbol: str, as_of: int | None = None) -> list[dict[str, Any]]:
    """1H / 4H / 12H / 24H / 3D / 7D - each from the model of the matching timeframe, never extrapolated."""
    out = []
    for label, tf in HORIZONS.items():
        fc = model_forecast(rt, symbol, tf, as_of)
        row: dict[str, Any] = {"horizon": label, "timeframe": tf, "available": fc["available"]}
        if fc["available"]:
            dist = fc.get("distribution") or {}
            row.update({
                "expected_return": fc["expected_return"], "expected_price": dist.get("expected_price"),
                "p_up": fc["probabilities"]["up"], "p_down": fc["probabilities"]["down"],
                "p_neutral": fc["probabilities"]["neutral"], "predicted": fc["predicted"],
                "interval80": (dist.get("intervals") or {}).get("80"),
                "confidence": fc["confidence"]["confidence"], "edge_confirmed": fc["edge_confirmed"],
                "bar_ts": fc["bar_ts"], "model_version": fc["model_version"],
            })
        else:
            row.update({"status": fc["status"], "reason": fc["reason"]})
        out.append(row)
    return out


def _levels(fr: Any, price: float) -> dict[str, Any]:
    last = fr.ind.iloc[-1]
    atr = float(last["atr"]) if np.isfinite(last["atr"]) else float("nan")
    n = len(fr.df)
    zones = sr_zones(fr.swings, price, atr, n)
    return {
        "zones": zones,
        "liquidity": liquidity_zones(fr.df, fr.swings, atr),
        "supply_demand": supply_demand_zones(fr.df, fr.ind["atr"]),
        "fibonacci": fib_levels(fr.swings, n),
        "pivots": {k: (float(last[k]) if np.isfinite(last[k]) else None) for k in ("pivot", "r1", "r2", "r3", "s1", "s2", "s3")},
        "swings": [{"ts": int(fr.df["ts"].iloc[s["pos"]]), "price": s["price"], "kind": s["kind"], "label": s["label"]}
                   for s in fr.swings[-40:]],
    }


def _events(fr: Any, bars: int = 150) -> list[dict[str, Any]]:
    """BOS / CHoCH markers for the chart."""
    tail = fr.ind.iloc[-bars:]
    out = []
    for col, name in (("bos", "BOS"), ("choch", "CHoCH")):
        for ts, v, px in zip(tail["ts"], tail[col], tail["close"]):
            if v:
                out.append({"ts": int(ts), "type": name, "direction": int(v), "price": float(px)})
    return sorted(out, key=lambda e: e["ts"])


def _snapshot(last: Any) -> dict[str, Any]:
    keys = ["rsi", "stoch_k", "stoch_d", "macd", "macd_signal", "macd_hist", "adx", "plus_di", "minus_di", "atr",
            "cci", "willr", "roc", "momentum", "bb_upper", "bb_mid", "bb_lower", "bb_width", "bb_pctb", "vwap",
            "rel_volume", "vol_roc", "obv", "cmf", "mfi", "sma_20", "sma_50", "sma_100", "sma_200", "ema_9",
            "ema_21", "ema_50", "ema_200", "tenkan", "kijun", "span_a", "span_b", "dc_upper", "dc_lower",
            "kc_upper", "kc_lower", "rv", "hv", "vol_pct", "atr_pct", "range_ratio", "buy_pressure", "sigma_bar"]
    return {k: (float(last[k]) if k in last and np.isfinite(last[k]) else None) for k in keys}


def analyze(rt: Runtime, symbol: str, timeframe: str = "4h", as_of: int | None = None,
            bundle: dict[str, Any] | None = None, detail: bool = True, use_cache: bool = True) -> dict[str, Any]:
    key = (symbol, timeframe, detail)
    if as_of is None and bundle is None and use_cache:
        hit = ttl_get(rt.analysis_cache, key, min(rt.refresh_seconds(), 60))
        if hit is not None:
            return hit
    live = as_of is None
    frames, unavailable = {}, {}
    for tf in dict.fromkeys(MTF_TIMEFRAMES + [timeframe]):
        try:
            frames[tf] = rt.frame(symbol, tf, as_of)
        except InsufficientData as exc:
            unavailable[tf] = str(exc)
    base = {"symbol": symbol, "timeframe": timeframe, "as_of": as_of, "generated_at": int(time.time() * 1000),
            "exchange": rt.exchange}
    if timeframe not in frames:
        out = {**base, "status": "INSUFFICIENT DATA", "reason": unavailable.get(timeframe), "decision": "INSUFFICIENT DATA",
               "signal": {"signal": "INSUFFICIENT DATA"}, "flags": ["INSUFFICIENT DATA"], "price": rt.live_price(symbol),
               "bar_ts": None, "regime": {"regime": "INSUFFICIENT DATA"}, "forecast": {"available": False,
               "status": "INSUFFICIENT DATA", "reason": unavailable.get(timeframe)}}
        return out
    fr = frames[timeframe]
    ind, last = fr.ind, fr.ind.iloc[-1]
    close = float(last["close"])
    price = (rt.live_price(symbol) if live else None) or close
    regime = describe_regime(ind)
    matrix = mtf_engine.mtf_matrix(frames, unavailable)
    htf = mtf_engine.higher_tf_score(matrix, timeframe)
    vol_state = vol_state_name(last["vol_state"])

    fc = model_forecast(rt, symbol, timeframe, as_of, bundle, explain=detail)
    flags: list[str] = []
    ml_score = None
    if fc["available"]:
        if fc["edge_confirmed"] or not settings.require_edge_for_ml:
            ml_score = fc["probabilities"]["up"] - fc["probabilities"]["down"]
        if not fc["edge_confirmed"]:
            flags.append(NO_EDGE)
        if fc["model_agreement"] < settings.min_model_agreement:
            flags.append("LOW MODEL AGREEMENT")
    else:
        flags.append(fc["status"])

    book = ttl_get(rt.order_books, symbol, 30) if live else None
    liq = order_book_metrics(book) if book else None
    lean = int(np.sign(last["tech_score"])) if np.isfinite(last["tech_score"]) else 0
    sig = build_signal(ind, timeframe, ml_score, htf, liq["imbalance"] if liq else None, rt.signal_weights(),
                       mtf_engine.alignment_with(matrix, lean), matrix["conflict"])
    direction = sig.get("direction") or 0
    levels = _levels(fr, price)
    setup = build_setup(ind, levels["zones"], direction, settings.min_risk_reward, live_price=price) if direction else None
    if vol_state == "EXTREME":
        flags.append("UNSTABLE MARKET — REDUCED CONFIDENCE")

    # ---- confidence: realised hit-rate of comparable past out-of-sample predictions --------------------
    confidence, conf_detail = None, None
    if fc["available"]:
        conf_detail = dict(fc["confidence"])
        confidence = conf_detail["confidence"]
        if confidence is not None and vol_state == "HIGH" and not conf_detail["vol_conditioned"]:
            confidence *= 0.85    # policy haircut when there were too few high-volatility cases to measure it
            conf_detail["volatility_haircut"] = 0.85
        model_dir = {2: 1, 0: -1}.get(fc["predicted_class"], 0)
        if direction and model_dir != direction:
            # the figure describes the ensemble's own call; it cannot be quoted as confidence in the opposite signal
            confidence = None
            conf_detail["note"] = f"the ensemble predicts {fc['predicted']}, which does not confirm this signal"
        conf_detail["applied"] = confidence

    # ---- decision -------------------------------------------------------------------------------------
    decision, why = "HOLD", None
    idx = sig.get("label_index")
    if sig["signal"] == "INSUFFICIENT DATA":
        decision, why = "INSUFFICIENT DATA", "not enough closed candles"
    elif direction == 0 or idx in (2, 4):
        decision = "HOLD"
        why = "no directional tilt" if direction == 0 else "the tilt is weak"
    else:
        model_dir = {2: 1, 0: -1}.get(fc.get("predicted_class"), 0) if fc["available"] else 0
        if vol_state == "EXTREME":
            decision, why = "NO TRADE", "volatility is extreme (above its 95th percentile)"
        elif not fc["available"]:
            decision, why = "NO TRADE", f"no validated model for {timeframe}, so confidence cannot be established ({fc['reason']})"
        elif settings.require_edge_for_trade and not fc["edge_confirmed"]:
            decision, why = "NO TRADE", "the model has no statistically confirmed edge"
        elif model_dir != direction:
            decision, why = "NO TRADE", f"the ensemble does not confirm the direction (it predicts {fc['predicted']})"
        elif fc["model_agreement"] < settings.min_model_agreement:
            decision, why = "NO TRADE", f"model agreement {fc['model_agreement']:.0%} is below {settings.min_model_agreement:.0%}"
        elif confidence is None:
            decision, why = "NO TRADE", "too few comparable out-of-sample predictions to state a confidence"
        elif confidence < settings.min_confidence:
            decision, why = "NO TRADE", f"confidence {confidence:.0%} is below the {settings.min_confidence:.0%} threshold"
        elif not setup or not setup["valid"]:
            decision, why = "NO TRADE", (setup or {}).get("reason") or "no valid trade setup"
        elif direction > 0:
            decision = "BUY ON PULLBACK" if setup["extended"] else "BUY"
        else:
            decision = "SELL"
    if decision == "NO TRADE":
        flags.append("NO TRADE")

    risk = None
    if setup and setup.get("ideal_entry"):
        risk = position_size(rt.risk_profile(), setup["ideal_entry"], setup["stop"],
                             float(last["sigma_bar"]) if np.isfinite(last["sigma_bar"]) else None, timeframe)
    tk = rt.ticker(symbol) if live else None
    out: dict[str, Any] = {
        **base, "status": "OK", "bar_ts": int(last["ts"]), "bar_close_ts": int(last["ts"]) + tf_ms(timeframe),
        "price": price, "last_close": close,
        "change_24h_pct": tk.get("change_pct") if tk else None, "quote_volume_24h": tk.get("quote_volume") if tk else None,
        "regime": regime, "volatility": {
            "state": vol_state, "percentile": _n(last["vol_pct"]), "realized": _n(last["rv"]), "historical": _n(last["hv"]),
            "atr": _n(last["atr"]), "atr_pct": _n(last["atr_pct"]), "bb_width": _n(last["bb_width"]),
            "bb_width_percentile": _n(last["bb_width_pct"]), "range_expansion": bool(last["range_expansion"]),
            "range_compression": bool(last["range_compression"])},
        "signal": sig, "decision": decision, "decision_reason": why, "flags": list(dict.fromkeys(flags)),
        "confidence": confidence, "confidence_detail": conf_detail,
        "forecast": fc, "mtf": matrix, "setup": setup, "risk": risk,
        "model_agreement": fc.get("model_agreement") if fc["available"] else None,
        "mtf_alignment": matrix["alignment"],
        "liquidity": {"order_book": liq, "relative_volume": _n(last["rel_volume"]), "volume_spike": bool(last["volume_spike"]),
                      "buy_pressure": _n(last["buy_pressure"]), "volume_divergence": int(last["volume_divergence"] or 0)},
    }
    out["now"] = {"breakout": int(last["breakout"] or 0), "bos": int(last["bos"] or 0), "choch": int(last["choch"] or 0),
                  "range_expansion": bool(last["range_expansion"])}
    if detail:
        out["horizons"] = horizon_forecasts(rt, symbol) if live else []
        out["levels"] = levels
        out["events"] = _events(fr)
        out["indicators"] = _snapshot(last)
        out["data_quality"] = check_candles(fr.df, timeframe, as_of)
    out["commentary"] = build_commentary(out)
    if live and bundle is None:
        if fc["available"]:
            tracking.log_prediction(rt.db, symbol, timeframe, fc)
        tracking.log_signal(rt.db, out)
        rt.analysis_cache[key] = (time.time(), out)
    return out


def _n(v: Any) -> float | None:
    return float(v) if v is not None and np.isfinite(v) else None


def final_signal(a: dict[str, Any]) -> dict[str, Any]:
    """The compact structured output (one object per asset)."""
    fc, setup, sig = a.get("forecast") or {}, a.get("setup") or {}, a.get("signal") or {}
    p = fc.get("probabilities") or {}
    tps = setup.get("targets") or []
    show = bool(setup.get("valid"))
    return {
        "asset": a["symbol"], "timeframe": a["timeframe"], "price": a.get("price"),
        "regime": (a.get("regime") or {}).get("regime"), "regime_confidence": (a.get("regime") or {}).get("confidence"),
        "signal": sig.get("signal"), "signal_score": sig.get("score"), "confidence": a.get("confidence"),
        "bullish": p.get("up"), "neutral": p.get("neutral"), "bearish": p.get("down"),
        "forecast": {h["horizon"]: h.get("expected_return") for h in a.get("horizons", [])},
        "entry": setup.get("entry_zone") if show else None, "stop": setup.get("stop") if show else None,
        "tp1": tps[0]["price"] if show and tps else None, "tp2": tps[1]["price"] if show and len(tps) > 1 else None,
        "tp3": tps[2]["price"] if show and len(tps) > 2 else None,
        "risk_reward": setup.get("risk_reward") if show else None,
        "multi_timeframe_alignment": a.get("mtf_alignment"), "model_agreement": a.get("model_agreement"),
        "warnings": sig.get("warnings"), "flags": a.get("flags"), "decision": a.get("decision"),
        "decision_reason": a.get("decision_reason"),
    }
