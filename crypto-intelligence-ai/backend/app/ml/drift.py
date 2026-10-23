"""Model-drift detection: feature drift (PSI), prediction drift, volatility-regime shift, performance decay."""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy import stats as sps

PSI_WARN, PSI_ALERT = 0.10, 0.25


def reference_bins(values: np.ndarray, bins: int = 10) -> dict[str, Any] | None:
    v = values[np.isfinite(values)]
    if len(v) < 50:
        return None
    edges = np.unique(np.quantile(v, np.linspace(0, 1, bins + 1)[1:-1]))
    if len(edges) < 2:
        return None
    props = np.bincount(np.searchsorted(edges, v, side="right"), minlength=len(edges) + 1) / len(v)
    return {"edges": edges, "props": props}


def psi(ref: dict[str, Any] | None, values: np.ndarray) -> float | None:
    """Population stability index of `values` against reference bins. <0.1 stable, 0.1-0.25 moderate, >0.25 shifted."""
    v = values[np.isfinite(values)]
    if ref is None or len(v) < 30:
        return None
    cur = np.bincount(np.searchsorted(ref["edges"], v, side="right"), minlength=len(ref["edges"]) + 1) / len(v)
    a, b = np.clip(ref["props"], 1e-4, None), np.clip(cur, 1e-4, None)
    return float(((b - a) * np.log(b / a)).sum())


def feature_drift(ref_bins: dict[str, Any], X_recent: np.ndarray, feature_names: list[str], top: int = 8) -> dict[str, Any]:
    rows = []
    for j, name in enumerate(feature_names):
        val = psi(ref_bins.get(name), X_recent[:, j])
        if val is not None:
            rows.append({"feature": name, "psi": val})
    rows.sort(key=lambda r: -r["psi"])
    n = len(rows)
    shifted = sum(r["psi"] > PSI_ALERT for r in rows)
    return {"n_features": n, "shifted": shifted, "share_shifted": shifted / n if n else None,
            "median_psi": float(np.median([r["psi"] for r in rows])) if rows else None, "top": rows[:top]}


def performance_drift(recent_hits: int, recent_n: int, ref_hits: int, ref_n: int, alpha: float = 0.05) -> dict[str, Any]:
    """One-sided two-proportion z-test: is recent accuracy significantly BELOW the reference accuracy?"""
    if recent_n < 30 or ref_n < 30:
        return {"tested": False, "reason": "fewer than 30 resolved predictions in one of the windows",
                "recent_n": recent_n, "reference_n": ref_n}
    p1, p0 = recent_hits / recent_n, ref_hits / ref_n
    pooled = (recent_hits + ref_hits) / (recent_n + ref_n)
    se = np.sqrt(pooled * (1 - pooled) * (1 / recent_n + 1 / ref_n))
    z = (p1 - p0) / se if se > 0 else 0.0
    p = float(sps.norm.cdf(z))
    return {"tested": True, "recent_accuracy": p1, "reference_accuracy": p0, "recent_n": recent_n,
            "reference_n": ref_n, "z": float(z), "p_value": p, "degraded": bool(p < alpha)}


def drift_report(bundle: dict[str, Any], X_recent: np.ndarray, p_up_recent: np.ndarray | None,
                 vol_pct_now: float | None, live: dict[str, Any] | None = None) -> dict[str, Any]:
    feats = feature_drift(bundle["drift_ref"]["features"], X_recent, bundle["feature_names"])
    pred = psi(bundle["drift_ref"].get("p_up"), p_up_recent) if p_up_recent is not None else None
    flags = []
    if feats["share_shifted"] is not None and feats["share_shifted"] > 0.25:
        flags.append(f"feature drift: {feats['shifted']} of {feats['n_features']} features have PSI > {PSI_ALERT}")
    if pred is not None and pred > PSI_ALERT:
        flags.append(f"prediction drift: PSI of P(up) = {pred:.2f}")
    train_vol = bundle["drift_ref"].get("vol_pct_median")
    if vol_pct_now is not None and np.isfinite(vol_pct_now) and vol_pct_now > 0.95:
        flags.append("volatility regime: current realized volatility is above its 95th percentile")
    perf = None
    if live:
        perf = performance_drift(live["recent_hits"], live["recent_n"], live["ref_hits"], live["ref_n"])
        if perf.get("degraded"):
            flags.append(f"performance: recent accuracy {perf['recent_accuracy']:.1%} vs reference "
                         f"{perf['reference_accuracy']:.1%} (p = {perf['p_value']:.3f})")
    return {
        "drift_detected": bool(flags), "flags": flags,
        "recommendation": "Retrain / reduce model weight" if flags else "No action needed",
        "feature_drift": feats, "prediction_psi": pred, "performance": perf,
        "train_vol_pct_median": train_vol, "vol_pct_now": vol_pct_now,
    }
