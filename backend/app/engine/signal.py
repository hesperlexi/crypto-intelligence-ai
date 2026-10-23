"""Transparent signal engine: weighted component scores -> label, with reasons and warnings.

A signal is never produced from one indicator. Each component is a score in [-1, +1]; components that are
unavailable (e.g. no order book, or no validated ML model) are left out and their weight is redistributed
proportionally - the effective weights are reported with every signal.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..config import DEFAULT_SIGNAL_WEIGHTS

LABELS = ["STRONG SELL", "SELL", "WEAK SELL", "HOLD", "WEAK BUY", "BUY", "STRONG BUY"]
THRESHOLDS = (0.15, 0.35, 0.60)   # |composite| needed for WEAK / plain / STRONG
COMPONENT_LABELS = {
    "trend": "Trend", "momentum": "Momentum", "volume": "Volume", "structure": "Market structure",
    "ml": "ML direction probability", "volatility": "Volatility", "liquidity": "Liquidity / order flow",
    "htf": "Higher-timeframe confirmation",
}


def label_for(composite: float) -> int:
    """Index into LABELS (3 = HOLD)."""
    a = abs(composite)
    level = 3 if a >= THRESHOLDS[2] else 2 if a >= THRESHOLDS[1] else 1 if a >= THRESHOLDS[0] else 0
    return 3 + int(np.sign(composite)) * level


def _f(v: Any) -> float | None:
    return float(v) if v is not None and np.isfinite(v) else None


def build_signal(ind: pd.DataFrame, timeframe: str, ml_score: float | None, htf_score: float | None,
                 liquidity_score: float | None, weights: dict[str, float] | None = None,
                 mtf_alignment: float | None = None, mtf_conflict: bool = False) -> dict[str, Any]:
    last = ind.iloc[-1]
    w = {**DEFAULT_SIGNAL_WEIGHTS, **(weights or {})}
    values = {
        "trend": _f(last["sc_trend"]), "momentum": _f(last["sc_momentum"]), "volume": _f(last["sc_volume"]),
        "structure": _f(last["sc_structure"]), "ml": _f(ml_score), "volatility": _f(last["sc_volatility"]),
        "liquidity": _f(liquidity_score), "htf": _f(htf_score),
    }
    avail = {k: v for k, v in values.items() if v is not None and w.get(k, 0) > 0}
    if "trend" not in avail or "momentum" not in avail:
        return {"signal": "INSUFFICIENT DATA", "label_index": None, "composite": None, "score": None,
                "components": [], "reasons": [], "warnings": ["Not enough closed candles to compute the core scores"]}
    wsum = sum(w[k] for k in avail)
    components = []
    composite = 0.0
    for k in COMPONENT_LABELS:
        eff = w[k] / wsum if k in avail else 0.0
        contrib = eff * avail[k] if k in avail else 0.0
        composite += contrib
        components.append({"key": k, "label": COMPONENT_LABELS[k], "score": values[k], "weight": w.get(k, 0.0),
                           "effective_weight": eff, "contribution": contrib, "available": k in avail})
    composite = float(np.clip(composite, -1, 1))
    idx = label_for(composite)
    notes = []
    # timeframes that disagree with the signal cost it one notch
    if idx != 3 and (mtf_conflict or (mtf_alignment is not None and mtf_alignment < 0.5)):
        idx -= int(np.sign(idx - 3))
        notes.append("Downgraded one level: timeframes disagree with this direction")
    direction = int(np.sign(idx - 3)) or int(np.sign(composite)) if abs(composite) >= 0.05 else 0
    bull_score = 50 + 50 * composite
    facts = _facts(ind, timeframe, values, mtf_alignment)
    side = int(np.sign(idx - 3)) or (1 if composite >= 0 else -1)
    reasons = [f["text"] for f in facts if f["polarity"] == side]
    warnings = [f["text"] for f in facts if f["polarity"] == -side or f["polarity"] == 0] + notes
    return {
        "signal": LABELS[idx], "label_index": idx, "direction": int(np.sign(idx - 3)), "lean": direction,
        "composite": composite, "bull_score": float(bull_score),
        # strength of the signal in its own direction, 0-100 (50 = no tilt)
        "score": float(bull_score if composite >= 0 else 100 - bull_score),
        "components": components, "reasons": reasons, "warnings": warnings,
        "weights_note": None if len(avail) == len(COMPONENT_LABELS) else
        "Unavailable components are excluded and their weight redistributed: "
        + ", ".join(COMPONENT_LABELS[k] for k in COMPONENT_LABELS if k not in avail),
    }


def _facts(ind: pd.DataFrame, tf: str, values: dict[str, float | None], mtf_alignment: float | None
           ) -> list[dict[str, Any]]:
    """Statements derived from computed values only. polarity: +1 bullish, -1 bearish, 0 risk note."""
    last = ind.iloc[-1]
    c = float(last["close"])
    out: list[dict[str, Any]] = []
    add = lambda text, pol: out.append({"text": text, "polarity": pol})  # noqa: E731
    tr = values["trend"]
    if tr is not None and abs(tr) >= 0.3:
        add(f"{tf.upper()} trend {'bullish' if tr > 0 else 'bearish'} (trend score {tr:+.2f})", int(np.sign(tr)))
    for n in (50, 200):
        e = last.get(f"ema_{n}")
        if e is not None and np.isfinite(e):
            add(f"Price {'above' if c > e else 'below'} EMA {n}", 1 if c > e else -1)
    macd_diff = (ind["macd"] - ind["macd_signal"]).iloc[-4:]
    if macd_diff.notna().all():
        crossed = np.sign(macd_diff.iloc[-1]) != np.sign(macd_diff.iloc[0])
        s = int(np.sign(macd_diff.iloc[-1]))
        if s:
            add(f"MACD {'bullish' if s > 0 else 'bearish'} crossover" if crossed else
                f"MACD {'above' if s > 0 else 'below'} its signal line", s)
    vc = last.get("vol_confirm")
    if vc is not None and np.isfinite(vc) and abs(vc) > 0.15:
        add(f"{'Positive' if vc > 0 else 'Negative'} volume confirmation (relative volume {last['rel_volume']:.2f}x)",
            int(np.sign(vc)))
    st = last["struct_trend"]
    if st:
        hl = "higher highs / higher lows" if last["sh_label"] > 0 and last["sl_label"] > 0 else \
             "lower highs / lower lows" if last["sh_label"] < 0 and last["sl_label"] < 0 else "last break of structure"
        add(f"{'Bullish' if st > 0 else 'Bearish'} market structure ({hl})", int(st))
    recent = ind.iloc[-10:]
    for col, name in (("bos", "Break of structure"), ("choch", "Change of character")):
        ev = recent[col].to_numpy()
        nz = np.nonzero(ev)[0]
        if len(nz):
            d = int(ev[nz[-1]])
            add(f"{name} {'up' if d > 0 else 'down'} {len(ev) - 1 - nz[-1]} bars ago", d)
    fb = recent["false_breakout"].to_numpy()[-5:]
    if np.any(fb):
        d = int(fb[np.nonzero(fb)[0][-1]])
        add(f"Failed {'breakdown' if d > 0 else 'breakout'} in the last 5 bars", d)
    if recent["golden_cross"].any():
        add("Golden cross (SMA 50 above SMA 200) in the last 10 bars", 1)
    if recent["death_cross"].any():
        add("Death cross (SMA 50 below SMA 200) in the last 10 bars", -1)
    if recent["bull_div_rsi"].any() or recent["bull_div_macd"].any():
        add("Bullish divergence between price and momentum", 1)
    if recent["bear_div_rsi"].any() or recent["bear_div_macd"].any():
        add("Bearish divergence between price and momentum", -1)
    brk = last.get("breakout")
    if brk:
        add(f"{'Breakout above' if brk > 0 else 'Breakdown below'} the 20-bar range on above-average volume", int(brk))
    ml = values["ml"]
    if ml is not None and abs(ml) >= 0.05:
        add(f"Model probability tilt {'bullish' if ml > 0 else 'bearish'} (P(up) - P(down) = {ml:+.0%})", int(np.sign(ml)))
    liq = values["liquidity"]
    if liq is not None and abs(liq) >= 0.2:
        add(f"Order book {'bid' if liq > 0 else 'ask'}-heavy within 1% of mid (imbalance {liq:+.0%})", int(np.sign(liq)))
    htf = values["htf"]
    if htf is not None and abs(htf) >= 0.2:
        add(f"Higher timeframes lean {'bullish' if htf > 0 else 'bearish'} ({htf:+.2f})", int(np.sign(htf)))
    rsi = last["rsi"]
    if np.isfinite(rsi):
        if rsi >= 70:
            add(f"RSI overbought ({rsi:.0f})", -1)
        elif rsi >= 65:
            add(f"RSI approaching overbought ({rsi:.0f})", -1)
        elif rsi <= 30:
            add(f"RSI oversold ({rsi:.0f})", 1)
        elif rsi <= 35:
            add(f"RSI approaching oversold ({rsi:.0f})", 1)
    vs = last.get("vol_state")
    if vs is not None and np.isfinite(vs) and vs >= 2:
        add("Extreme volatility: forecasts are less reliable" if vs >= 3 else
            f"High volatility ({last['vol_pct']:.0%} percentile)", 0)
    if last.get("range_compression"):
        add("Range compression: a volatility expansion often follows", 0)
    if last.get("volume_divergence"):
        add("Volume is fading while price trends (volume divergence)", -int(last["volume_divergence"]))
    if mtf_alignment is not None and mtf_alignment < 0.5:
        add(f"Multi-timeframe alignment only {mtf_alignment:.0%}", 0)
    return out


def optimise_weights(ind: pd.DataFrame, fwd_ret: pd.Series, train_frac: float = 0.7) -> dict[str, Any]:
    """Data-driven weights for the candle-based components: a logistic regression of next-bar direction on the
    component scores, fitted on the first `train_frac` of history and scored on the remainder.
    Returned for review - the user decides whether to adopt them."""
    from sklearn.linear_model import LogisticRegression

    cols = {"trend": "sc_trend", "momentum": "sc_momentum", "volume": "sc_volume", "structure": "sc_structure",
            "volatility": "sc_volatility"}
    X = ind[list(cols.values())]
    ok = X.notna().all(axis=1) & fwd_ret.notna()
    X, y = X[ok].to_numpy(), (fwd_ret[ok] > 0).astype(int).to_numpy()
    if len(y) < 300:
        return {"ok": False, "reason": f"only {len(y)} usable bars"}
    cut = int(len(y) * train_frac)
    lr = LogisticRegression(C=1.0, max_iter=1000).fit(X[:cut], y[:cut])
    coef = np.clip(lr.coef_[0], 0, None)       # a component that predicts the wrong way gets zero weight
    base = sum(DEFAULT_SIGNAL_WEIGHTS[k] for k in cols)
    if coef.sum() <= 0:
        return {"ok": False, "reason": "no component had a positive out-of-sample-consistent relationship"}
    w = coef / coef.sum() * base
    acc_test = float((lr.predict(X[cut:]) == y[cut:]).mean())
    return {"ok": True, "weights": {**DEFAULT_SIGNAL_WEIGHTS, **{k: float(v) for k, v in zip(cols, w)}},
            "raw_coefficients": {k: float(v) for k, v in zip(cols, lr.coef_[0])},
            "train_rows": int(cut), "test_rows": int(len(y) - cut), "test_accuracy": acc_test,
            "test_base_rate": float(max(y[cut:].mean(), 1 - y[cut:].mean())),
            "note": "Fitted on the first 70% of history; accuracy is measured on the last 30%."}
