"""Rolling walk-forward validation with per-fold calibration and performance-weighted ensembling.

Timeline of one fold (bars strictly ordered in time, never shuffled):

    |<---------- train ---------->| gap |<-- validation -->| gap |<---- test ---->|
      fit models + scalers                fit calibrators          untouched: scored
                                          choose ensemble weights  out-of-sample

The window then rolls forward by one test length. `gap` (>= label horizon) purges the bars whose labels
would overlap the next segment. Nothing from validation or test ever reaches model fitting.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from .calibration import Calibrator, fit_calibrator
from .metrics import brier
from .models import REGISTRY, make_model, predict_with_context

log = logging.getLogger(__name__)
MIN_REGIME_ROWS = 80


@dataclass
class Fold:
    i: int
    train: tuple[int, int]
    val: tuple[int, int]
    test: tuple[int, int]


def make_folds(n: int, sizes: tuple[int, int, int], gap: int = 1, min_train: int = 150,
               min_folds: int = 2) -> list[Fold]:
    """Rolling folds ending exactly at the newest row. Window sizes shrink automatically for short histories;
    returns [] if even the minimum cannot be met."""
    train, val, test = sizes
    if n < train + val + 2 * gap + test * min_folds:
        val = test = max(20, min(test, n // 12))
        train = n - 2 * gap - val - test * min_folds
        if train < min_train:
            return []
    span = train + gap + val + gap + test
    start = (n - span) % test
    folds = []
    while start + span <= n:
        a = start
        b = a + train
        c = b + gap + val
        folds.append(Fold(len(folds), (a, b), (b + gap, c), (c + gap, c + gap + test)))
        start += test
    return folds


def _skill_weights(probs: dict[str, np.ndarray], y: np.ndarray, prior: np.ndarray,
                   history: dict[str, list[float]] | None = None) -> tuple[dict[str, float], dict[str, float], bool]:
    """Weight = max(Brier skill vs class prior, 0) x prediction stability. Returns (weights, skill, any_skill)."""
    if not probs:
        return {}, {}, False
    base = brier(np.tile(prior, (len(y), 1)), y)
    skill, raw = {}, {}
    for m, P in probs.items():
        s = [base - brier(P, y)] + (history or {}).get(m, [])[-3:]
        skill[m] = float(np.mean(s))
        stability = 1.0 - float(np.abs(np.diff(P[:, 2])).mean()) if len(P) > 1 else 1.0
        raw[m] = max(skill[m], 0.0) * max(stability, 0.0)
    total = sum(raw.values())
    if total <= 0:   # nothing beats the prior: fall back to equal weights and say so
        return {m: 1.0 / len(probs) for m in probs}, skill, False
    return {m: v / total for m, v in raw.items()}, skill, True


@dataclass
class WFResult:
    folds: list[Fold]
    model_names: list[str]
    ensemble_members: list[str]
    P_raw: dict[str, np.ndarray]
    P_cal: dict[str, np.ndarray]
    P_ens: np.ndarray
    exp_ret: np.ndarray
    fold_reports: list[dict[str, Any]] = field(default_factory=list)
    test_skill: dict[str, list[float]] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)


def class_means(y: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Mean volatility-standardised forward return per class, from training rows."""
    mu = np.zeros(3)
    for k in range(3):
        m = (y == k) & np.isfinite(z)
        mu[k] = float(z[m].mean()) if m.any() else 0.0
    return mu


def fit_stage(X: np.ndarray, y: np.ndarray, groups: np.ndarray, feature_names: list[str], model_names: list[str],
              train: tuple[int, int], val: tuple[int, int], history: dict[str, list[float]],
              failures: dict[str, str]) -> dict[str, Any]:
    """Fit every model on `train`, calibrate on `val`, derive ensemble weights. Shared by folds and the live fit."""
    tr, va = slice(*train), slice(*val)
    ytr, yva = y[tr].astype(int), y[va].astype(int)
    prior = np.bincount(ytr, minlength=3) / len(ytr)
    models, cals, reports, weight_probs = {}, {}, {}, {}
    n_val = val[1] - val[0]
    tail_lo = int(n_val * 0.7)
    for name in model_names:
        try:
            model = make_model(name, feature_names).fit(X[tr], ytr)
            p_val = predict_with_context(model, X, *val)
            if REGISTRY[name]["baseline"]:   # benchmarks are reported exactly as they are
                cal, rep = Calibrator("none"), {"method": "none", "reason": "baseline model: not calibrated"}
            else:
                cal, rep = fit_calibrator(p_val, yva)
        except Exception as exc:  # a failing model is dropped from this stage and reported, never faked
            failures[name] = f"{type(exc).__name__}: {exc}"[:200]
            log.warning("model %s failed: %s", name, failures[name])
            continue
        models[name], cals[name], reports[name] = model, cal, rep
        if not REGISTRY[name]["baseline"]:
            if cal.method == "none":      # raw validation predictions are fully out-of-sample for the model
                weight_probs[name] = (p_val, yva, groups[va])
            else:                         # calibrated: score only the part the calibration map did not see
                head = Calibrator(cal.method)
                head._fit(p_val[:tail_lo], yva[:tail_lo])
                weight_probs[name] = (head.transform(p_val[tail_lo:]), yva[tail_lo:], groups[va][tail_lo:])
    # every model is scored on the same rows: the whole validation window when nothing was calibrated,
    # otherwise only the tail that no calibration map was fitted on
    k = n_val if all(cals[m].method == "none" for m in weight_probs) else n_val - tail_lo
    common = {m: (P[-k:], yy[-k:], g[-k:]) for m, (P, yy, g) in weight_probs.items()}
    weights: dict[str, Any] = {"global": {}, "by_regime": {}, "skill": {}, "has_skill": False}
    if common:
        y_tail = next(iter(common.values()))[1]
        g_tail = next(iter(common.values()))[2]
        probs = {m: v[0] for m, v in common.items()}
        weights["global"], weights["skill"], weights["has_skill"] = _skill_weights(probs, y_tail, prior, history)
        for g in (0.0, 1.0, 2.0, 3.0):
            mask = g_tail == g
            if mask.sum() >= MIN_REGIME_ROWS and len(np.unique(y_tail[mask])) > 1:
                w, _, ok = _skill_weights({m: P[mask] for m, P in probs.items()}, y_tail[mask], prior)
                if ok:
                    weights["by_regime"][int(g)] = w
    return {"models": models, "calibrators": cals, "calibration": reports, "weights": weights, "prior": prior}


def ensemble_proba(P_cal: dict[str, np.ndarray], weights: dict[str, Any], groups: np.ndarray) -> np.ndarray:
    """Linear pool of calibrated probabilities; rows use regime-specific weights where those exist."""
    members = [m for m in weights["global"] if m in P_cal]
    n = len(groups)
    if not members:
        return np.full((n, 3), np.nan)
    out = np.zeros((n, 3))
    wsum = np.zeros(n)
    for m in members:
        w = np.full(n, weights["global"][m])
        for g, wg in weights["by_regime"].items():
            w = np.where(groups == g, wg.get(m, 0.0), w)
        out += w[:, None] * P_cal[m]
        wsum += w
    return out / np.where(wsum > 0, wsum, 1.0)[:, None]


def run_walk_forward(X: np.ndarray, y: np.ndarray, sigma: np.ndarray, fwd_ret: np.ndarray, groups: np.ndarray,
                     feature_names: list[str], model_names: list[str], sizes: tuple[int, int, int],
                     gap: int = 1, min_train: int = 150,
                     progress: Callable[[float, str], None] | None = None) -> WFResult:
    n = len(y)
    folds = make_folds(n, sizes, gap, min_train)
    nan3 = lambda: np.full((n, 3), np.nan)  # noqa: E731
    res = WFResult(folds, list(model_names), [m for m in model_names if not REGISTRY[m]["baseline"]],
                   {m: nan3() for m in model_names}, {m: nan3() for m in model_names}, nan3(), np.full(n, np.nan))
    z = fwd_ret / sigma
    for f in folds:
        if progress:
            progress(f.i / max(len(folds), 1), f"fold {f.i + 1}/{len(folds)}")
        ytr = y[slice(*f.train)].astype(int)
        if np.bincount(ytr, minlength=3).min() < 5:
            res.fold_reports.append({"fold": f.i, "skipped": "a class has fewer than 5 training samples"})
            continue
        stage = fit_stage(X, y, groups, feature_names, model_names, f.train, f.val, res.test_skill, res.failures)
        te = slice(*f.test)
        yte = y[te].astype(int)
        base = brier(np.tile(stage["prior"], (len(yte), 1)), yte)
        for name, model in stage["models"].items():
            try:
                raw = predict_with_context(model, X, *f.test)
            except Exception as exc:
                res.failures[name] = f"{type(exc).__name__}: {exc}"[:200]
                continue
            res.P_raw[name][te] = raw
            res.P_cal[name][te] = stage["calibrators"][name].transform(raw)
        fold_cal = {m: res.P_cal[m][te] for m in stage["models"] if np.isfinite(res.P_cal[m][te]).all()}
        res.P_ens[te] = ensemble_proba(fold_cal, stage["weights"], groups[te])
        mu = class_means(ytr, z[slice(*f.train)])
        res.exp_ret[te] = sigma[te] * (res.P_ens[te] @ mu)
        for name, P in fold_cal.items():   # recorded AFTER the fold is scored; only later folds may use it
            res.test_skill.setdefault(name, []).append(base - brier(P, yte))
        res.fold_reports.append({
            "fold": f.i, "train": list(f.train), "val": list(f.val), "test": list(f.test),
            "weights": stage["weights"]["global"], "weights_by_regime": stage["weights"]["by_regime"],
            "has_skill": stage["weights"]["has_skill"],
            "calibration": {m: r.get("method") for m, r in stage["calibration"].items()},
            "test_brier": {m: brier(P, yte) for m, P in fold_cal.items()}, "prior_brier": base,
        })
    if progress:
        progress(1.0, "walk-forward complete")
    return res
