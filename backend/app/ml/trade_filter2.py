"""v2.6 trade filter: one meta-model per timeframe, pooled over every coin, trained on the trades the pipeline itself
would have recorded (series_policy.run_series on the models' walk-forward out-of-sample calls, simulated with the
record's rules and costs), with the live record's and the hidden practice (shadow) trades replacing the simulated
outcome where they exist.

Compared with ml/trade_filter.py (per coin, one fixed ATR bracket on every leaning bar, model features) it learns from
the actual call population - grade, confidence, plan geometry - and from the market around the call: the coin's own
regime, the BTC regime / technical score in the trade's direction, multi-timeframe agreement, volatility state.

Honesty rules are those of ml/trade_filter.py: time order; A (first 50 %) fits, B (next 25 %) chooses how selective
to be, C (last 25 %) is the exam; enabled only when the kept trades on C earned at least MIN_GAIN_R more than all of C.
"""
from __future__ import annotations

from typing import Any

import numpy as np

KEEP_GRID = (0.4, 0.5, 0.6, 0.7, 0.8)
MIN_GAIN_R = 0.03
MIN_TRADES = 300
FEATURES = ["p_side", "margin", "p_neutral", "confidence", "grade_a", "side", "regime_side", "tech_side",
            "btc_regime_side", "btc_tech_side", "mtf_agree", "vol_state", "atr_pct", "stop_atr", "extended", "hour_sin",
            "hour_cos"]


def features(ctx: Any, d: dict[str, np.ndarray], j: int) -> np.ndarray:
    """Feature row of the call at context row j (everything known at the bar's close)."""
    side = float(d["side"][j]) or 1.0
    P = ctx.P[j]
    pl = d["plan"][j] or {}
    dirs = [ctx.mtf_dir[t][j] for t in ctx.mtf_dir]
    dirs = [x for x in dirs if np.isfinite(x)]
    agree = float(np.mean([x == side for x in dirs])) if dirs else 0.5
    hour = (int(ctx.decision_ts[j]) // 3_600_000) % 24
    c = d["confidence"][j]
    return np.array([
        P[2] if side > 0 else P[0], abs(P[2] - P[0]), P[1], c if np.isfinite(c) else 0.5,
        1.0 if d["grade"][j] == "A" else 0.0, side,
        side * np.nan_to_num(ctx.regime_score[j]), side * np.nan_to_num(ctx.tech[j]),
        side * np.nan_to_num(ctx.btc_regime[j]), side * np.nan_to_num(ctx.btc_tech[j]), agree,
        np.nan_to_num(ctx.vol_state[j], nan=1.0), float(ctx.atr[j] / ctx.close[j] * 100) if ctx.close[j] else 0.0,
        float(pl.get("dist", np.nan) / ctx.atr[j]) if pl and ctx.atr[j] else 1.5, float(bool(pl.get("extended"))),
        np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24)], float)


def _model():
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(max_iter=150, learning_rate=0.05, max_leaf_nodes=8, min_samples_leaf=30,
                                          l2_regularization=1.0, random_state=0)


def train(F: np.ndarray, R: np.ndarray, ts: np.ndarray) -> dict[str, Any]:
    """F: feature rows, R: trade results in R after costs, ts: decision times. Rows are sorted by time here."""
    o = np.argsort(ts, kind="stable")
    F, R = np.asarray(F, float)[o], np.asarray(R, float)[o]
    ok = np.isfinite(F).all(axis=1) & np.isfinite(R)
    F, R = F[ok], R[ok]
    n = len(R)
    if n < MIN_TRADES:
        return {"enabled": False, "reason": f"only {n} trades to learn from", "n": n}
    y = (R > 0).astype(int)
    a, b = int(n * 0.5), int(n * 0.75)
    if len(set(y[:a])) < 2:
        return {"enabled": False, "reason": "no winning and losing trades to learn from", "n": n}
    m = _model().fit(F[:a], y[:a])
    pB, pC = m.predict_proba(F[a:b])[:, 1], m.predict_proba(F[b:])[:, 1]
    best, gain = None, -1e9
    for keep in KEEP_GRID:
        thr = np.quantile(pB, 1 - keep)
        sel = pB >= thr
        if sel.sum() >= 30 and R[a:b][sel].mean() - R[a:b].mean() > gain:
            best, gain = keep, R[a:b][sel].mean() - R[a:b].mean()
    if best is None:
        return {"enabled": False, "reason": "too few trades to choose a threshold", "n": n}
    thr = float(np.quantile(pB, 1 - best))
    selC = pC >= thr
    exam = {"n": int(len(pC)), "kept": int(selC.sum()), "avg_r_all": float(R[b:].mean()),
            "avg_r_kept": float(R[b:][selC].mean()) if selC.any() else None}
    enabled = bool(selC.sum() >= 25 and exam["avg_r_kept"] is not None and exam["avg_r_kept"] - exam["avg_r_all"] >= MIN_GAIN_R)
    out = {"enabled": enabled, "keep_fraction": best, "n": n, "exam": exam, "features": FEATURES}
    if not enabled:
        out["reason"] = "the filter did not improve results on unseen trades"
        return out
    final = _model().fit(F, y)
    out.update(model=final, threshold=float(np.quantile(final.predict_proba(F)[:, 1], 1 - best)),
               reason=f"kept trades earned {exam['avg_r_kept']:+.2f}R vs {exam['avg_r_all']:+.2f}R for all, on unseen trades")
    return out


def score(f: dict[str, Any] | None, row: np.ndarray) -> float | None:
    if not f or not f.get("enabled") or f.get("model") is None or not np.isfinite(row).all():
        return None
    return float(f["model"].predict_proba(row.reshape(1, -1))[:, 1][0])
