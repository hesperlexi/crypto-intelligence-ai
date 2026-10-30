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


def _row(P: np.ndarray, conf: float, grade: str | None, side: float, regime: float, tech: float, btc_regime: float,
         btc_tech: float, agree: float, vol_state: float, atr_pct: float, stop_atr: float, extended: bool, ts: int) -> np.ndarray:
    hour = (int(ts) // 3_600_000) % 24
    return np.array([
        P[2] if side > 0 else P[0], abs(P[2] - P[0]), P[1], conf if np.isfinite(conf) else 0.5,
        1.0 if grade == "A" else 0.0, side, side * np.nan_to_num(regime), side * np.nan_to_num(tech),
        side * np.nan_to_num(btc_regime), side * np.nan_to_num(btc_tech), agree, np.nan_to_num(vol_state, nan=1.0),
        np.nan_to_num(atr_pct), np.nan_to_num(stop_atr, nan=1.5), float(bool(extended)),
        np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24)], float)


def features(ctx: Any, d: dict[str, np.ndarray], j: int) -> np.ndarray:
    """Feature row of the call at context row j (everything known at the bar's close)."""
    side = float(d["side"][j]) or 1.0
    pl = d["plan"][j] or {}
    dirs = [x for x in (ctx.mtf_dir[t][j] for t in ctx.mtf_dir) if np.isfinite(x)]
    agree = float(np.mean([x == side for x in dirs])) if dirs else 0.5
    atr = float(ctx.atr[j])
    return _row(ctx.P[j], float(d["confidence"][j]), d["grade"][j], side, ctx.regime_score[j], ctx.tech[j],
                ctx.btc_regime[j], ctx.btc_tech[j], agree, ctx.vol_state[j],
                atr / float(ctx.close[j]) * 100 if ctx.close[j] else 0.0,
                float(pl.get("dist", np.nan)) / atr if pl and atr else 1.5, bool(pl.get("extended")), int(ctx.decision_ts[j]))


def live_features(fc: dict[str, Any], confidence: float | None, grade: str | None, side: int, last: Any,
                  matrix: dict[str, Any], btc_last: Any, setup: dict[str, Any], decision_ts: int) -> np.ndarray:
    """The same row for a live analysis (services/analysis.py)."""
    p = fc["probabilities"]
    P = np.array([p["down"], p["neutral"], p["up"]], float)
    dirs = [r["direction"] for r in matrix.get("rows", []) if r.get("available") and r.get("regime_score") is not None]
    agree = float(np.mean([d == side for d in dirs])) if dirs else 0.5
    atr = float(last["atr"])
    g = lambda row, c: float(row[c]) if row is not None and c in row and np.isfinite(row[c]) else np.nan  # noqa: E731
    return _row(P, float(confidence) if confidence is not None else np.nan, grade, float(side), g(last, "regime_score"),
                g(last, "tech_score"), g(btc_last, "regime_score"), g(btc_last, "tech_score"), agree, g(last, "vol_state"),
                atr / float(last["close"]) * 100 if atr and last["close"] else 0.0,
                float(setup.get("stop_distance_atr") or np.nan), bool(setup.get("extended")), decision_ts)


# ---- storage: one joblib file per timeframe next to the models; the summary (no model) in app_settings ----------------

def _path(tf: str) -> str:
    from pathlib import Path

    from ..config import settings
    return str(Path(settings.model_dir) / f"trade_filter2-{tf}.joblib")


def save(db: Any, tf: str, f: dict[str, Any]) -> None:
    import time

    import joblib
    from pathlib import Path
    summary = {k: v for k, v in f.items() if k != "model"}
    summary["at"] = int(time.time() * 1000)
    if f.get("enabled") and f.get("model") is not None:
        Path(_path(tf)).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": f["model"], "threshold": f["threshold"], "summary": summary}, _path(tf), compress=3)
    else:
        try:
            Path(_path(tf)).unlink()
        except OSError:
            pass
    db.set_setting(f"trade_filter2|{tf}", summary)
    _cache.pop(tf, None)


_cache: dict[str, tuple[float, Any]] = {}


def load(db: Any, tf: str) -> dict[str, Any] | None:
    """The enabled filter of this timeframe (None when off, missing or older than 3 days)."""
    import os
    import time

    import joblib
    summary = db.get_setting(f"trade_filter2|{tf}", None)
    if not summary or not summary.get("enabled") or time.time() * 1000 - int(summary.get("at") or 0) > 3 * 86_400_000:
        return None
    p = _path(tf)
    if not os.path.exists(p):
        return None
    mt = os.path.getmtime(p)
    hit = _cache.get(tf)
    if hit and hit[0] == mt:
        return hit[1]
    f = {**joblib.load(p), "enabled": True}
    _cache[tf] = (mt, f)
    return f


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
