"""Scanner and dashboard aggregations over the tracked universe."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..engine.cross_asset import cross_asset_report
from ..features.dataset import InsufficientData
from . import analysis
from .runtime import Runtime


def breakout_base_rate(ind: pd.DataFrame, bars: int = 5, tol: float = 0.1, min_n: int = 50) -> dict[str, Any]:
    """Historical frequency of a close above the 20-bar range within `bars` bars, among past bars that sat at a
    similar position inside the range as now. A base rate, not a model output."""
    hi, lo, c = ind["dc_upper"], ind["dc_lower"], ind["close"]
    pos = ((c - lo) / (hi - lo).replace(0, np.nan)).to_numpy(float)
    brk = (c > hi).to_numpy(float)
    fut = pd.Series(brk[::-1]).rolling(bars, min_periods=1).max().to_numpy()[::-1]   # max over bars t..t+bars-1
    fut = np.concatenate([fut[1:], [np.nan]])                                         # -> bars t+1..t+bars
    now = pos[-1]
    if not np.isfinite(now):
        return {"probability": None, "n": 0}
    m = np.isfinite(pos) & (np.abs(pos - now) <= tol)
    m[-bars:] = False                     # their look-ahead window is not complete yet
    n = int(m.sum())
    return {"probability": float(np.nanmean(fut[m])) if n >= min_n else None, "n": n, "bars": bars}


def scan(rt: Runtime, timeframe: str = "4h") -> list[dict[str, Any]]:
    rows = []
    for sym in rt.symbols():
        a = analysis.analyze(rt, sym, timeframe, detail=False)
        row: dict[str, Any] = {"symbol": sym, "status": a["status"], "price": a.get("price"),
                               "pinned": False, "timeframe": timeframe}
        if a["status"] != "OK":
            row["reason"] = a.get("reason")
            rows.append(row)
            continue
        sig, fc, setup = a["signal"], a["forecast"], a.get("setup") or {}
        comp = {c["key"]: c["score"] for c in sig.get("components", [])}
        try:
            ind = rt.frame(sym, timeframe).ind
            last = ind.iloc[-1]
            br = breakout_base_rate(ind)
            rsi, adx = float(last["rsi"]), float(last["adx"])
        except InsufficientData:
            br, rsi, adx = {"probability": None, "n": 0}, None, None
        row.update({
            "change_24h_pct": a.get("change_24h_pct"), "quote_volume_24h": a.get("quote_volume_24h"),
            "trend": comp.get("trend"), "momentum": comp.get("momentum"),
            "trend_label": "Up" if (comp.get("trend") or 0) > 0.25 else "Down" if (comp.get("trend") or 0) < -0.25 else "Flat",
            "rsi": rsi, "adx": adx,
            "p_up": fc["probabilities"]["up"] if fc["available"] else None,
            "p_down": fc["probabilities"]["down"] if fc["available"] else None,
            "edge_confirmed": fc.get("edge_confirmed") if fc["available"] else None,
            "model_status": fc["status"], "regime": a["regime"]["regime"], "regime_group": a["regime"].get("group"),
            "regime_confidence": a["regime"].get("confidence"),
            "signal": sig["signal"], "score": sig.get("score"), "bull_score": sig.get("bull_score"),
            "composite": sig.get("composite"), "decision": a["decision"], "decision_reason": a.get("decision_reason"),
            "grade": a.get("grade"),
            "confidence": a.get("confidence"), "risk_reward": setup.get("risk_reward") if setup.get("valid") else None,
            "mtf_alignment": a.get("mtf_alignment"), "volatility": a["volatility"]["state"],
            "breakout_base_rate": br["probability"], "breakout_n": br["n"], "flags": a.get("flags"),
            "expected_return": fc.get("expected_return") if fc["available"] else None,
        })
        rows.append(row)
    pins = {w["symbol"]: bool(w["pinned"]) for w in rt.watchlist()}
    for r in rows:
        r["pinned"] = pins.get(r["symbol"], False)
    return rows


def cross_asset(rt: Runtime, timeframe: str = "1d") -> dict[str, Any]:
    closes, above = {}, {}
    for sym in rt.symbols():
        try:
            fr = rt.frame(sym, timeframe)
        except InsufficientData:
            continue
        closes[sym] = fr.df["close"].iloc[-400:]
        last = fr.ind.iloc[-1]
        if np.isfinite(last["ema_50"]):
            above[sym] = bool(last["close"] > last["ema_50"])
    out = cross_asset_report(closes, above)
    out["timeframe"] = timeframe
    return out


def dashboard(rt: Runtime, timeframe: str = "4h") -> dict[str, Any]:
    rows = scan(rt, timeframe)
    ok = [r for r in rows if r["status"] == "OK"]
    by = {r["symbol"]: r for r in ok}
    groups = [r["regime_group"] for r in ok if r.get("regime_group")]
    bull, bear = groups.count("Bull"), groups.count("Bear")
    n = len(groups)
    status = "INSUFFICIENT DATA" if n == 0 else "BULL" if bull / n >= 0.6 else "BEAR" if bear / n >= 0.6 else "NEUTRAL"
    actionable = [r for r in ok if r["decision"] in analysis.TRADE_DECISIONS]
    top = sorted(ok, key=lambda r: -abs(r["composite"] or 0))[:6]
    risks = []
    for r in ok:
        for f in r.get("flags") or []:
            if f.startswith("UNSTABLE") or f == "LOW MODEL AGREEMENT":
                risks.append({"symbol": r["symbol"], "risk": f})
        if r["volatility"] in ("HIGH", "EXTREME"):
            risks.append({"symbol": r["symbol"], "risk": f"{r['volatility']} volatility"})
        if r.get("rsi") is not None and (r["rsi"] >= 75 or r["rsi"] <= 25):
            risks.append({"symbol": r["symbol"], "risk": f"RSI {r['rsi']:.0f} ({'overbought' if r['rsi'] >= 75 else 'oversold'})"})
        if r.get("mtf_alignment") is not None and r["mtf_alignment"] < 0.5:
            risks.append({"symbol": r["symbol"], "risk": f"timeframes disagree (alignment {r['mtf_alignment']:.0%})"})
    forecast_table = []
    for sym in rt.symbols():
        hz = analysis.horizon_forecasts(rt, sym)
        forecast_table.append({"symbol": sym, "price": by.get(sym, {}).get("price") or rt.live_price(sym),
                               "horizons": {h["horizon"]: ({"expected_return": h["expected_return"], "p_up": h["p_up"],
                                                            "edge_confirmed": h["edge_confirmed"]} if h["available"]
                                                           else {"status": h["status"]}) for h in hz}})
    return {
        "timeframe": timeframe,
        "market_status": {"status": status, "bull": bull, "bear": bear, "neutral": n - bull - bear, "assets": n,
                          "basis": f"share of tracked assets in a bullish / bearish {timeframe} regime (60% needed)"},
        "regimes": [{"symbol": r["symbol"], "regime": r["regime"], "confidence": r["regime_confidence"]} for r in ok],
        "top_signals": [{k: r[k] for k in ("symbol", "signal", "score", "decision", "confidence", "composite")} for r in top],
        "opportunities": [{k: r[k] for k in ("symbol", "decision", "signal", "score", "confidence", "risk_reward")}
                          for r in sorted(actionable, key=lambda r: -(r["confidence"] or 0))],
        "risks": risks[:12],
        "heatmap": [{"symbol": r["symbol"], "change_24h_pct": r.get("change_24h_pct"), "bull_score": r.get("bull_score"),
                     "signal": r["signal"], "regime": r["regime"]} for r in ok],
        "forecast_table": forecast_table, "rows": rows,
    }
