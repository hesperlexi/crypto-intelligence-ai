"""Per-asset analysis: assembles regime, multi-timeframe view, model forecast, signal, trade plan and risk
into the structured output the API returns. Every number originates in an engine, a model or the database."""
from __future__ import annotations

import os

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
from ..ml import direction as dirview, trainer
from . import tracking
from .runtime import Runtime, ttl_get

TRADE_DECISIONS = ("BUY", "BUY ON PULLBACK", "SELL")
# v2.3: a trade is only worth taking when target 1 (= 1R) clearly beats the cost of getting in and out. Futures:
# 0.05 % taker fee + slippage/spread per side; target 1 must be at least COST_MULT x the round trip.
COST_MULT = 3.0
ONE_CALL_TFS = ("15m",)
# timeframes whose trade calls are paused (owner decision 30 Oct 2026: 15m lost money on unseen data, -0.17R per trade);
# the analysis, chart and forecast still run, only no trade call is issued. Env PAUSED_TFS, comma separated ("" = none).
# v2.8 (owner decision 31 Oct 2026, from the time-limit / timeframe study `research_horizon.py`): 1d and 3d paused
# (they lost after costs on unseen calls); 1h grade A only; 15m demo bots only (grade A, never on the public list)
def _tfs(name: str, default: str) -> tuple[str, ...]:
    return tuple(t.strip() for t in os.environ.get(name, default).split(",") if t.strip())


PAUSED_TFS = _tfs("PAUSED_TFS", "1d,3d")
A_ONLY_TFS = _tfs("A_ONLY_TFS", "1h")
# demo-only timeframes: the public decision is NO TRADE ("DEMO BOTS ONLY"); the call the demo bots may take is in `demo`
DEMO_ONLY_TFS = _tfs("DEMO_ONLY_TFS", "15m")


def round_trip_cost(futures: bool = True) -> float:
    """Fraction of price paid to enter and exit once (fees + slippage + half spread, both sides)."""
    from ..engine.futures import FUTURES_FEE_RATE
    side = (FUTURES_FEE_RATE if futures else settings.fee_rate) + (settings.slippage_bps + settings.spread_bps / 2) / 1e4
    return 2 * side


def beats_costs(entry: float, stop: float, futures: bool = True, mult: float = COST_MULT) -> bool:
    return bool(entry and stop) and abs(entry - stop) / entry >= mult * round_trip_cost(futures)


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
        ds = rt.dataset(symbol, timeframe, bundle["uses_btc"], as_of, htf_tf=bundle.get("uses_htf"))
        mult = tracking.live_multipliers(rt.db, bundle) if as_of is None else {}
        fc = trainer.predict(bundle, ds, multipliers=mult)
    except InsufficientData as exc:
        return {"available": False, "status": "INSUFFICIENT DATA", "reason": str(exc)}
    except Exception as exc:  # model failure: surface it, never substitute a made-up forecast
        rt.record_error(f"forecast {symbol} {timeframe}", exc)
        return {"available": False, "status": "MODEL ERROR", "reason": f"{type(exc).__name__}: {exc}"[:200]}
    try:
        from ..ml import trade_filter
        x_row = ds.X[bundle["feature_names"]].to_numpy(float)[-1]
        fc["trade_filter"] = trade_filter.score(bundle.get("trade_filter"), x_row, fc["probabilities"])
    except Exception as exc:
        rt.record_error(f"trade filter {symbol} {timeframe}", exc)
        fc["trade_filter"] = None
    try:
        from ..ml import target_model
        fc["target_lift"] = target_model.lifts(bundle.get("target_model"), x_row, fc["probabilities"])
    except Exception:
        fc["target_lift"] = None
    try:
        from ..ml import runner_model
        fc["runner"] = runner_model.score(bundle.get("runner_model"), x_row, fc["probabilities"])
    except Exception:
        fc["runner"] = None
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
    lift_of = lambda side: ((fc.get("target_lift") or {}).get("long" if side > 0 else "short") if fc.get("available") else None)  # noqa: E731
    stop_kw = {"stop_mode": "struct", "struct_buffer_atr": settings.struct_stop_buffer_atr} if settings.struct_stops else {}
    setup = build_setup(ind, levels["zones"], direction, settings.min_risk_reward, live_price=price,
                        lift=lift_of(direction), **stop_kw) if direction else None
    if vol_state == "EXTREME":
        flags.append("UNSTABLE MARKET — REDUCED CONFIDENCE")

    # ---- confidence -------------------------------------------------------------------------------------
    # engine v2: the confidence quoted for a long / short call is DIRECTIONAL: how often comparable past
    # out-of-sample calls (same side, similar UP-vs-DOWN margin) got the direction right. The old 3-class figure
    # (exact class incl. "neutral") is kept as class_confidence for reference.
    confidence, conf_detail, dv = None, None, None
    if fc["available"]:
        bun = bundle if bundle is not None else trainer.load_bundle(symbol, timeframe, rt.db)
        dv = dirview.view(fc, bun)
        conf_detail = {"class_confidence": fc["confidence"].get("confidence"), "class_basis": fc["confidence"].get("basis")}
        if dv and dv.get("confidence") is not None:
            confidence = float(dv["confidence"])
            if vol_state == "HIGH":
                confidence = 0.5 + (confidence - 0.5) * 0.85     # shrink towards a coin flip in turbulent markets
                conf_detail["volatility_haircut"] = 0.85
            conf_detail.update({"basis": dv["confidence_detail"].get("basis"), "n": dv["confidence_detail"].get("n"),
                                "ci95": dv["confidence_detail"].get("ci95"), "side": dv["side"], "margin": dv["margin"]})
        conf_detail["applied"] = confidence

    # ---- decision (engine v2) ---------------------------------------------------------------------------
    # A trade needs the technical tilt and the AI to point the same way (or, with no tilt, a model lean that clears
    # its own out-of-sample threshold), a directional confidence above a coin flip and a valid trade plan.
    #   grade A: firm technical tilt + model lean above its threshold + good model agreement + confidence >= A level
    #   grade B: everything else that passes (weak tilt confirmed by the model, or a model-led call)
    decision, why, grade, basis = "HOLD", None, None, None
    # v2.6: per coin/timeframe policy computed nightly from out-of-sample history (series gate, grade-B threshold)
    spol = series_policy_view(rt, symbol, timeframe) if bundle is None else {"blocked": False, "reason": None, "conf_b": None}
    conf_b_min = spol["conf_b"] if spol["conf_b"] is not None else settings.min_dir_confidence_b
    idx = sig.get("label_index")
    weak = idx in (2, 4)
    if sig["signal"] == "INSUFFICIENT DATA":
        decision, why = "INSUFFICIENT DATA", "not enough closed candles"
    elif vol_state == "EXTREME":
        decision, why = ("NO TRADE" if direction else "HOLD"), "volatility is extreme (above its 95th percentile)"
    elif not fc["available"]:
        decision, why = ("NO TRADE" if direction else "HOLD"), f"no validated model for {timeframe} ({fc['reason']})"
    elif settings.require_edge_for_trade and not fc["edge_confirmed"]:
        decision, why = "NO TRADE", "the model has no statistically confirmed edge"
    else:
        mside = dv["side"] if dv else 0
        clears = bool(dv and dv["clears_policy"])
        model_led = direction == 0 and clears and bool(dv and dv["policy_edge"])
        side = direction if direction and mside == direction else (mside if model_led else 0)
        agree = fc["model_agreement"]
        if side == 0:
            if direction == 0:
                why = "no directional tilt, and the AI lean is below its proven threshold"
            else:
                why = f"the AI leans {'up' if mside > 0 else 'down'}, against the {'bullish' if direction > 0 else 'bearish'} technical tilt"
        else:
            if side != direction:          # model-led call: build the plan on the model's side
                setup = build_setup(ind, levels["zones"], side, settings.min_risk_reward, live_price=price, lift=lift_of(side),
                                    **stop_kw)
            firm = bool(direction) and not weak
            conf_ok_a = confidence is not None and confidence >= max(settings.min_dir_confidence_a, conf_b_min)
            conf_ok_b = confidence is not None and confidence >= conf_b_min
            if firm and clears and agree >= settings.min_model_agreement and conf_ok_a:
                grade, basis = "A", "technical tilt and AI agree, AI lean above its proven threshold"
            elif conf_ok_b and agree >= settings.min_agreement_b and (clears or firm):
                grade = "B"
                basis = ("AI-led: the AI lean clears its proven threshold" if model_led else
                         "technical tilt confirmed by the AI lean" if not clears else "weak technical tilt, AI lean above its threshold")
            if grade is None:
                if confidence is None:
                    why = "too few comparable out-of-sample calls to state a confidence"
                elif not conf_ok_b:
                    why = f"directional confidence {confidence:.0%} is not above a coin flip"
                elif agree < settings.min_agreement_b:
                    why = f"model agreement {agree:.0%} is too low"
                else:
                    why = "the tilt is weak and the AI lean is below its proven threshold"
                decision = "HOLD" if weak or not direction else "NO TRADE"
            elif not setup or not setup["valid"]:
                decision, why, grade = "NO TRADE", (setup or {}).get("reason") or "no valid trade setup", None
            elif side > 0:
                decision = "BUY ON PULLBACK" if setup["extended"] else "BUY"
            else:
                decision = "SELL"
            if grade:
                direction = side
    # bigger-trend check (v2.2): a trade against BOTH of the next two higher timeframes' trends is refused; against
    # one of them, a grade A call is lowered to B. Quick timeframes are where this matters most.
    trend_check = higher_trend_check(matrix, timeframe, direction if decision in TRADE_DECISIONS else 0)
    if decision in TRADE_DECISIONS and trend_check:
        if trend_check["against"] >= 2:
            decision, why, grade = "NO TRADE", f"the bigger trend points the other way ({trend_check['label']})", None
            flags.append("AGAINST BIGGER TREND")
        elif trend_check["against"] == 1 and grade == "A":
            grade = "B"
            basis = f"{basis}; one higher timeframe disagrees ({trend_check['label']})" if basis else trend_check["label"]
    # trade filter: the model's own record of which setups reach their targets before the stop
    tf_view = (fc or {}).get("trade_filter") if fc.get("available") else None
    filter_score = None
    if tf_view and decision in TRADE_DECISIONS:
        tside = 1 if decision in ("BUY", "BUY ON PULLBACK") else -1
        filter_score = tf_view["p_long"] if tside > 0 else tf_view["p_short"]
        if filter_score < tf_view["threshold"]:
            decision, why = "NO TRADE", (f"the trade filter scores this setup {filter_score:.0%}, below the "
                                         f"{tf_view['threshold']:.0%} bar at which past setups paid off")
            grade = None
            flags.append("FILTERED")

    # v2.6 proven-only series gate: a coin/timeframe whose out-of-sample + live expectancy is not credibly positive
    if decision in TRADE_DECISIONS and spol["blocked"]:
        decision, why, grade = "NO TRADE", spol["reason"], None
        flags.append("NO PROVEN EDGE")
    # v2.6 pooled trade filter (one per timeframe, trained on the calls the pipeline itself made)
    filter2 = None
    if decision in TRADE_DECISIONS and settings.trade_filter2 and setup and setup.get("valid") and bundle is None:
        try:
            from ..ml import trade_filter2 as TF2
            f2 = TF2.load(rt.db, timeframe)
            if f2 is not None:
                fside = 1 if decision in ("BUY", "BUY ON PULLBACK") else -1
                row = TF2.live_features(fc, confidence, grade, fside, last, matrix, _btc_last(rt, symbol, timeframe, as_of, last),
                                        setup, int(last["ts"]) + tf_ms(timeframe))
                sc = TF2.score(f2, row)
                if sc is not None:
                    filter2 = {"score": sc, "threshold": f2["threshold"]}
                    if sc < f2["threshold"]:
                        decision, grade = "NO TRADE", None
                        why = (f"the {timeframe.upper()} trade filter scores this call {sc:.0%}, below the {f2['threshold']:.0%} "
                               "bar at which comparable past calls paid off")
                        flags.append("FILTERED")
        except Exception as exc:
            rt.record_error(f"trade filter2 {symbol} {timeframe}", exc)

    # costs (v2.3): a target 1 that barely covers fees and slippage is no trade (mostly tight 15m setups)
    if decision in TRADE_DECISIONS and setup and setup.get("valid") and not beats_costs(setup["ideal_entry"], setup["stop"]):
        rp = abs(setup["ideal_entry"] - setup["stop"]) / setup["ideal_entry"] * 100
        decision, grade = "NO TRADE", None
        why = (f"target 1 is only {rp:.2f}% away: too small to beat trading costs "
               f"(about {round_trip_cost() * 100:.2f}% to get in and out; it needs at least {COST_MULT:g}x that)")
        flags.append("TARGET TOO SMALL FOR COSTS")

    # paused timeframes (v2.6): live calls only, so research replays still measure every timeframe
    if decision in TRADE_DECISIONS and timeframe in PAUSED_TFS and live and bundle is None and as_of is None:
        decision, grade = "NO TRADE", None
        why = (f"{timeframe.upper()} trade calls are paused: on past calls they lost money after costs. "
               "The chart and forecast stay available")
        flags.append("TIMEFRAME PAUSED")
    if decision in TRADE_DECISIONS and timeframe in A_ONLY_TFS and grade != "A" and live and bundle is None and as_of is None:
        decision, grade = "NO TRADE", None
        why = f"{timeframe.upper()} trade calls are grade A only; this setup is grade B"
        flags.append("GRADE A ONLY")

    # one call at a time on quick timeframes (v2.3): while a 15m call on this coin is still running, an opposite 15m
    # call is not issued (the 15m view can swing within the hour; flip-flopping cut winners and entered losers)
    if decision in TRADE_DECISIONS and timeframe in ONE_CALL_TFS and live and bundle is None and as_of is None:
        nside = 1 if decision in ("BUY", "BUY ON PULLBACK") else -1
        running = rt.db.one("SELECT side, created_at FROM signals WHERE symbol = ? AND timeframe = ? AND status = 'OPEN' "
                            "AND side != 0 ORDER BY created_at DESC LIMIT 1", (symbol, timeframe))
        if running and int(running["side"]) == -nside:
            decision, grade = "NO TRADE", None
            why = (f"the previous {timeframe.upper()} {'long' if nside < 0 else 'short'} call on this coin is still "
                   "running; no opposite call until it closes")
            flags.append("CALL STILL RUNNING")

    # let winners run (v2.3): where the runner model proved itself on unseen trades and scores this setup above its
    # threshold, the whole position stays open at TP1 and the stop follows the price up to the 1:4 runner target
    run_view = (fc or {}).get("runner") if fc.get("available") else None
    if run_view and decision in TRADE_DECISIONS and setup and setup.get("valid"):
        rside = 1 if decision in ("BUY", "BUY ON PULLBACK") else -1
        rp = run_view["p_long"] if rside > 0 else run_view["p_short"]
        if rp >= run_view["threshold"]:
            dist = abs(setup["ideal_entry"] - setup["stop"])
            rr = float(run_view.get("run_r") or 4.0)
            tgt = float(setup["ideal_entry"] + rside * rr * dist)
            setup["runner"] = {"on": True, "target": tgt, "rr": rr, "score": rp, "threshold": run_view["threshold"],
                               "move_pct": float(rside * (tgt / setup["ideal_entry"] - 1) * 100),
                               "basis": "AI: let it run - nothing closes at TP1; the stop moves to break-even at TP1, "
                                        f"to TP1 at TP2, to TP2 at TP3; the whole position closes at 1:{rr:g}"}

    # safety switch (v2.2): a coin/timeframe whose recent live signals lost pauses; its would-be trades are
    # tracked as hidden practice trades until they recover
    safety_state, shadow = None, None
    if live and bundle is None and timeframe in MODEL_TIMEFRAMES:
        try:
            from . import safety
            from ..views import record_for
            safety_state = safety.check(rt.db, symbol, timeframe, record_for(rt, timeframe))
        except Exception:
            safety_state = None
        if safety_state and safety_state.get("paused") and decision in TRADE_DECISIONS and setup and setup.get("valid"):
            shadow = (decision, setup)
            decision, why, grade = "NO TRADE", safety_state["reason"], None
            flags.append("PAUSED")
    # high-impact US data release (CPI, jobs report, Fed): pause fresh entries around it
    news_risk = None
    try:
        from .news import event_risk
        news_risk = event_risk(rt.db, (as_of if as_of is not None else int(time.time() * 1000)))
    except Exception:
        news_risk = None
    if news_risk:
        flags.append("NEWS RISK")
        if decision in TRADE_DECISIONS:
            held = decision
            decision, why = "NO TRADE", news_risk["reason"]
            basis = f"{held} paused for the news" if basis is None else f"{basis} (paused: {news_risk['title']})"
            grade = None
    # stale data (audit A3): if the newest closed candle is older than 2 bars, or the data-quality check fails hard,
    # nothing is traded on it - the candle sync must have failed
    quality = check_candles(fr.df, timeframe, as_of)
    recent_q = check_candles(fr.df.tail(300), timeframe, as_of)     # hard failures judged on the recent candles
    stale = bool(live and bundle is None and is_stale(recent_q, int(last["ts"]), timeframe))
    if stale:
        flags.append("STALE DATA")
        if decision != "INSUFFICIENT DATA":
            decision, why, grade = "NO TRADE", "market data is stale", None
    demo = None
    if decision in TRADE_DECISIONS and timeframe in DEMO_ONLY_TFS and live and bundle is None and as_of is None:
        # v2.8: the demo bots may take it (their own grade rule applies); it is never published or recorded as a signal
        demo = {"decision": decision, "grade": grade}
        decision, grade = "NO TRADE", None
        why = f"{timeframe.upper()} calls go to the demo bots only while they are tested"
        flags.append("DEMO BOTS ONLY")
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
        "stale": stale,
        "signal": sig, "decision": decision, "decision_reason": why, "flags": list(dict.fromkeys(flags)), "trend_check": trend_check,
        "safety": safety_state,
        "grade": grade, "demo": demo, "decision_basis": basis, "direction_view": dv, "news_risk": news_risk,
        "filter_score": filter_score, "filter_threshold": (tf_view or {}).get("threshold"), "filter2": filter2,
        "series_policy": spol if (spol.get("blocked") or spol.get("conf_b") is not None) else None,
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
        out["data_quality"] = quality
    out["commentary"] = build_commentary(out)
    if live and bundle is None:
        if fc["available"]:
            tracking.log_prediction(rt.db, symbol, timeframe, fc)
        tracking.log_signal(rt.db, out)                  # sets out["record_status"] (logged / already_open / not_logged)
        if out.get("record_status") is None and decision in TRADE_DECISIONS:
            out["record_status"] = "not_logged"
        if shadow and not stale:
            tracking.log_shadow(rt.db, out, shadow[0], shadow[1])
        out["call"] = tracking.current_call(rt.db, symbol, timeframe)
        ai = tracking.latest_ai(rt.db, symbol, timeframe)
        if ai:
            out["ai"] = ai
        rt.analysis_cache[key] = (time.time(), out)
    return out


def series_policy_view(rt: Runtime, symbol: str, timeframe: str) -> dict[str, Any]:
    """The cached nightly policy of this coin/timeframe as the live decision uses it (all off unless enabled)."""
    if not (settings.series_gate or settings.series_conf):
        return {"blocked": False, "reason": None, "conf_b": None}
    try:
        from ..ml import series_policy
        return series_policy.apply(series_policy.cached(rt.db, symbol, timeframe))
    except Exception:
        return {"blocked": False, "reason": None, "conf_b": None}


def _btc_last(rt: Runtime, symbol: str, timeframe: str, as_of: int | None, own_last: Any) -> Any:
    if symbol.startswith("BTC/"):
        return own_last
    try:
        return rt.frame("BTC/USDT", timeframe, as_of).ind.iloc[-1]
    except Exception:
        return None


def is_stale(quality: dict[str, Any], last_ts: int, timeframe: str, now: int | None = None) -> bool:
    """Newest closed candle older than 2 bars of its timeframe, or a hard data-quality failure."""
    now = int(time.time() * 1000) if now is None else now
    step = tf_ms(timeframe)
    if now - (int(last_ts) + step) > 2 * step:
        return True
    return quality.get("status") == "NO DATA" or (quality.get("quality_pct") is not None and quality["quality_pct"] < 90.0)


def higher_trend_check(matrix: dict[str, Any], timeframe: str, side: int) -> dict[str, Any] | None:
    """How many of the next two higher timeframes trend against `side` (+1 long / -1 short)."""
    if not side:
        return None
    from ..config import TF_SECONDS

    rows = sorted((r for r in matrix.get("rows", []) if r.get("available") and r.get("direction") is not None
                   and TF_SECONDS.get(r["timeframe"], 0) > TF_SECONDS.get(timeframe, 0)),
                  key=lambda r: TF_SECONDS[r["timeframe"]])[:2]
    if not rows:
        return None
    against = [r["timeframe"] for r in rows if r["direction"] == -side]
    label = ", ".join(f"{r['timeframe'].upper()} {r['direction_label'].lower()}" for r in rows)
    return {"checked": [r["timeframe"] for r in rows], "against": len(against), "label": label}


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
