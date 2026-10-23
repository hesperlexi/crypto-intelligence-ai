"""Replay Market: reproduce exactly what the system would have known at a past moment, then reveal the future.

Everything used for the replayed analysis is rebuilt from candles that had CLOSED by the chosen time,
including a model trained only on that truncated history. The audit block reports the timestamps so any
look-ahead would be visible.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from ..config import MODEL_TIMEFRAMES
from ..data.base import tf_ms
from ..features.dataset import InsufficientData
from ..ml import trainer
from . import analysis
from .runtime import Runtime

_bundles: dict[tuple[str, str, int], dict[str, Any]] = {}


def replay(rt: Runtime, symbol: str, timeframe: str, as_of: int, bars_after: int = 30,
           with_model: bool = True) -> dict[str, Any]:
    step = tf_ms(timeframe)
    known = rt.candles(symbol, timeframe, as_of=as_of)
    if len(known) < 60:
        return {"status": "INSUFFICIENT DATA", "reason": f"only {len(known)} candles had closed by that time"}
    bar_ts = int(known["ts"].iloc[-1])
    bundle, model_note = None, None
    if with_model and timeframe in MODEL_TIMEFRAMES:
        key = (symbol, timeframe, bar_ts)
        bundle = _bundles.get(key)
        if bundle is None:
            try:
                fr = rt.frame(symbol, timeframe, as_of)
                btc = None
                if not symbol.startswith("BTC/"):
                    try:
                        btc = rt.frame("BTC/USDT", timeframe, as_of)
                    except InsufficientData:
                        btc = None
                bundle = trainer.train_bundle(symbol, timeframe, fr, btc, fast=True)
                _bundles[key] = bundle
                if len(_bundles) > 20:
                    _bundles.pop(next(iter(_bundles)))
                model_note = "Fast model set (baselines, logistic regression, technical rules, gradient boosting) " \
                             "trained on the truncated history for this replay."
            except InsufficientData as exc:
                model_note = f"No model: {exc}"
    a = analysis.analyze(rt, symbol, timeframe, as_of=as_of, bundle=bundle, detail=True, use_cache=False)

    full = rt.candles(symbol, timeframe)
    future = full[full["ts"] > bar_ts].iloc[:bars_after]
    reveal: dict[str, Any] = {"bars": int(len(future))}
    if len(future):
        c0 = float(known["close"].iloc[-1])
        nxt = float(future["close"].iloc[0] / c0 - 1)
        reveal.update({
            "next_bar_return": nxt, "path": [{"ts": int(t), "close": float(c), "return": float(c / c0 - 1)}
                                             for t, c in zip(future["ts"], future["close"])],
            "max_up": float(future["high"].max() / c0 - 1), "max_down": float(future["low"].min() / c0 - 1),
            "final_return": float(future["close"].iloc[-1] / c0 - 1),
        })
        fc = a.get("forecast") or {}
        if fc.get("available"):
            band = fc["neutral_band"]
            actual = 2 if nxt > band else 0 if nxt < -band else 1
            iv = ((fc.get("distribution") or {}).get("intervals") or {}).get("80")
            reveal["forecast_check"] = {
                "predicted": fc["predicted"], "actual": ["DOWN", "NEUTRAL", "UP"][actual],
                "correct": actual == fc["predicted_class"], "expected_return": fc["expected_return"],
                "inside_80_interval": None if not iv else bool(iv["low_return"] <= nxt <= iv["high_return"]),
            }
        setup = a.get("setup") or {}
        if setup.get("valid"):
            side, stop = setup["side_int"], setup["stop"]
            hits, stopped = [False, False, False], False
            for _, c in future.iterrows():
                if (side > 0 and c["low"] <= stop) or (side < 0 and c["high"] >= stop):
                    stopped = True
                    break
                for i, t in enumerate(setup["targets"]):
                    if (side > 0 and c["high"] >= t["price"]) or (side < 0 and c["low"] <= t["price"]):
                        hits[i] = True
            reveal["setup_check"] = {"tp1": hits[0], "tp2": hits[1], "tp3": hits[2], "stop_hit": stopped}
    else:
        reveal["note"] = "No later candles are stored yet, so there is nothing to reveal."

    newest_used = max((int(rt.candles(symbol, tf, as_of=as_of)["ts"].iloc[-1]) + tf_ms(tf)
                       for tf in {r["timeframe"] for r in a.get("mtf", {}).get("rows", []) if r.get("available")}
                       | {timeframe}), default=bar_ts + step)
    audit = {
        "as_of": as_of, "last_closed_bar_open": bar_ts, "last_closed_bar_close": bar_ts + step,
        "newest_candle_close_used": newest_used, "candles_known": int(len(known)),
        "model_trained_through": bundle["data_end"] + 2 * step if bundle else None,
        "no_future_data": bool(newest_used <= as_of and (bundle is None or bundle["data_end"] + 2 * step <= as_of)),
        "model_note": model_note,
    }
    return {"status": "OK", "symbol": symbol, "timeframe": timeframe, "analysis": a, "reveal": reveal, "audit": audit,
            "chart": {"known": _rows(known.iloc[-200:]), "future": _rows(future)}}


def _rows(df: Any) -> list[dict[str, float]]:
    return [{"ts": int(r.ts), "open": float(r.open), "high": float(r.high), "low": float(r.low),
             "close": float(r.close), "volume": float(r.volume)} for r in df.itertuples()]


def replay_range(rt: Runtime, symbol: str, timeframe: str) -> dict[str, Any]:
    df = rt.candles(symbol, timeframe)
    if len(df) < 400:
        return {"available": False, "reason": f"{len(df)} candles stored; replay needs a few hundred"}
    return {"available": True, "earliest": int(df["ts"].iloc[min(len(df) - 1, 350)]), "latest": int(df["ts"].iloc[-2]),
            "candles": int(len(df))}
