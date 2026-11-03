"""AI research v3 (Nov 2026): trade-outcome meta-model ("meta-labelling"), honest confidence and strict promotion
statistics. RESEARCH LIBRARY: the live engine does not import this module (see `app/research_v3.py`).

* `purged_folds`      expanding walk-forward folds in time; a training row is used only when its trade CLOSED before the
                      validation block starts and it was decided at least `embargo_ms` (>= the trade horizon) earlier.
* `make_classifier` / `make_regressor`  gradient boosting (sklearn HistGradientBoosting: no extra dependency), one per
                      timeframe pooled over coins (coin id as a categorical feature).
* `Calibrator`        isotonic map from raw scores to P(net win), fitted on out-of-fold (validation) predictions only.
* `reliability`       Brier score, expected calibration error and reliability bins.
* `block_keys`, `bootstrap_mean`, `family_test`  block bootstrap by coin x week (trades of one coin in one week are
                      resampled together), White's reality check and Hansen's SPA for a family of strategies, Holm-adjusted
                      one-sided p-values per strategy.
"""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np

WEEK_MS = 7 * 86_400_000


# ---- validation design ----------------------------------------------------------------------------------------------

def purged_folds(ts: np.ndarray, closed_ts: np.ndarray, k: int = 5, embargo_ms: int = 0,
                 min_train: int = 200) -> list[tuple[np.ndarray, np.ndarray]]:
    """Expanding walk-forward folds. The rows are cut into k blocks of equal count by decision time; fold f (f >= 1)
    validates on block f and trains on rows whose trade closed before block f starts AND that were decided at least
    `embargo_ms` before it (purge + embargo). Folds with fewer than `min_train` training rows are skipped."""
    ts = np.asarray(ts, np.int64)
    closed_ts = np.asarray(closed_ts, np.int64)
    n = len(ts)
    if n == 0 or k < 2:
        return []
    order = np.argsort(ts, kind="stable")
    edges = [int(ts[order[min(n - 1, int(round(i * n / k)))]]) for i in range(k)] + [int(ts[order[-1]]) + 1]
    out = []
    for f in range(1, k):
        lo, hi = edges[f], edges[f + 1]
        val = np.flatnonzero((ts >= lo) & (ts < hi))
        tr = np.flatnonzero((closed_ts < lo) & (ts < lo - embargo_ms))
        if len(tr) >= min_train and len(val):
            out.append((tr, val))
    return out


# ---- models -------------------------------------------------------------------------------------------------------------

def make_classifier(cat_mask: np.ndarray | None = None, seed: int = 0):
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=250, learning_rate=0.04, max_leaf_nodes=15, min_samples_leaf=100,
                                          l2_regularization=2.0, max_bins=127, categorical_features=cat_mask,
                                          early_stopping=False, random_state=seed)


def make_regressor(cat_mask: np.ndarray | None = None, seed: int = 0):
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(max_iter=250, learning_rate=0.04, max_leaf_nodes=15, min_samples_leaf=100,
                                         l2_regularization=2.0, max_bins=127, categorical_features=cat_mask,
                                         loss="squared_error", early_stopping=False, random_state=seed)


class Calibrator:
    """Isotonic regression of the outcome on the raw score (fitted on validation predictions only)."""

    def __init__(self) -> None:
        self.iso = None
        self.base = None

    def fit(self, score: np.ndarray, y: np.ndarray) -> "Calibrator":
        from sklearn.isotonic import IsotonicRegression
        score, y = np.asarray(score, float), np.asarray(y, float)
        ok = np.isfinite(score) & np.isfinite(y)
        self.base = float(y[ok].mean()) if ok.any() else 0.5
        if ok.sum() >= 50 and len(np.unique(y[ok])) == 2:
            self.iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(score[ok], y[ok])
        return self

    def __call__(self, score: np.ndarray) -> np.ndarray:
        score = np.asarray(score, float)
        if self.iso is None:
            return np.full(len(score), self.base if self.base is not None else 0.5)
        return np.clip(self.iso.predict(np.nan_to_num(score, nan=float(np.nanmedian(score)) if np.isfinite(score).any() else 0.0)), 0, 1)


def reliability(p: np.ndarray, y: np.ndarray, bins: int = 10) -> dict[str, Any]:
    """Brier, ECE (equal-width bins, weighted by count), log loss and the reliability table."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    ok = np.isfinite(p) & np.isfinite(y)
    p, y = p[ok], y[ok]
    n = len(p)
    if n == 0:
        return {"n": 0}
    pc = np.clip(p, 1e-6, 1 - 1e-6)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    table, ece = [], 0.0
    for b in range(bins):
        m = idx == b
        if not m.any():
            continue
        mp, rate = float(p[m].mean()), float(y[m].mean())
        ece += m.sum() / n * abs(mp - rate)
        table.append({"bin": [round(float(edges[b]), 2), round(float(edges[b + 1]), 2)], "n": int(m.sum()),
                      "mean_p": round(mp, 4), "win_rate": round(rate, 4)})
    base = float(y.mean())
    brier = float(np.mean((p - y) ** 2))
    brier_base = float(np.mean((base - y) ** 2))
    return {"n": n, "brier": brier, "brier_climatology": brier_base,
            "brier_skill": (1 - brier / brier_base) if brier_base > 0 else None, "ece": float(ece),
            "log_loss": float(-np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc))), "win_rate": base,
            "mean_p": float(p.mean()), "bins": table}


# ---- statistics ---------------------------------------------------------------------------------------------------------

def block_keys(symbols: Iterable[str], ts: Iterable[int]) -> np.ndarray:
    """Bootstrap block of each trade: its coin and the calendar week of its decision."""
    return np.array([f"{s}|{int(t) // WEEK_MS}" for s, t in zip(symbols, ts)], dtype=object)


def _block_sums(r: np.ndarray, keys: np.ndarray, universe: list[str]) -> tuple[np.ndarray, np.ndarray]:
    pos = {k: i for i, k in enumerate(universe)}
    S = np.zeros(len(universe))
    C = np.zeros(len(universe))
    for x, k in zip(r, keys):
        i = pos[k]
        S[i] += x
        C[i] += 1
    return S, C


def bootstrap_mean(r: np.ndarray, keys: np.ndarray, n_boot: int = 2000, seed: int = 0) -> dict[str, Any]:
    """Mean R per trade with a block-bootstrap 95 % interval and one-sided 95 % lower bound."""
    r = np.asarray(r, float)
    if len(r) == 0:
        return {"n": 0, "mean": None, "ci95": None, "lb95": None, "p_le_0": None}
    uni = sorted(set(keys))
    S, C = _block_sums(r, np.asarray(keys), uni)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(uni), size=(n_boot, len(uni)))
    cs = C[idx].sum(axis=1)
    means = np.where(cs > 0, S[idx].sum(axis=1) / np.maximum(cs, 1), np.nan)
    means = means[np.isfinite(means)]
    m = float(r.mean())
    return {"n": int(len(r)), "blocks": len(uni), "mean": m,
            "ci95": [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))],
            "lb95": float(np.quantile(means, 0.05)),
            # one-sided bootstrap p-value of H0: mean <= 0 (centred resamples at least as large as the estimate)
            "p_le_0": float(np.mean(means - m >= m)) if len(means) else None}


def holm(p: dict[str, float | None]) -> dict[str, float | None]:
    items = sorted(((k, v) for k, v in p.items() if v is not None), key=lambda kv: kv[1])
    m = len(items)
    out: dict[str, float | None] = {k: None for k in p}
    run = 0.0
    for i, (k, v) in enumerate(items):
        run = max(run, min(1.0, (m - i) * v))
        out[k] = run
    return out


def family_test(strats: dict[str, tuple[np.ndarray, np.ndarray]], bench: tuple[np.ndarray, np.ndarray] | None = None,
                n_boot: int = 2000, seed: int = 0) -> dict[str, Any]:
    """Multiple-testing-aware test of a family of strategies on the SAME period.

    strats: name -> (R per trade, block key per trade). bench: None (H0: mean R <= 0, i.e. no better than costs) or
    (R, keys) of the benchmark (H0: mean R <= the benchmark's mean R per trade). Blocks (coin x week) are resampled
    jointly for all strategies and the benchmark, so their dependence is kept.
    Returns per strategy: estimate, bootstrap s.e., one-sided p and Holm-adjusted p; and for the family White's reality
    check p-value and Hansen's SPA (consistent) p-value of the best strategy."""
    names = [k for k, (r, _) in strats.items() if len(r)]
    if not names:
        return {"strategies": {}, "reality_check_p": None, "spa_p": None, "n_strategies": 0}
    uni = sorted(set().union(*[set(strats[k][1]) for k in names], set(bench[1]) if bench is not None and len(bench[0]) else set()))
    sums = {k: _block_sums(np.asarray(strats[k][0], float), np.asarray(strats[k][1]), uni) for k in names}
    bsum = _block_sums(np.asarray(bench[0], float), np.asarray(bench[1]), uni) if bench is not None and len(bench[0]) else None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(uni), size=(n_boot, len(uni)))

    def mean_of(S, C, ix=None):
        if ix is None:
            return S.sum() / C.sum() if C.sum() else np.nan
        cs = C[ix].sum(axis=1)
        return np.where(cs > 0, S[ix].sum(axis=1) / np.maximum(cs, 1), np.nan)

    d, dstar = {}, {}
    b0 = mean_of(*bsum) if bsum is not None else 0.0
    bstar = mean_of(*bsum, idx) if bsum is not None else 0.0
    for k in names:
        d[k] = float(mean_of(*sums[k]) - b0)
        dstar[k] = mean_of(*sums[k], idx) - bstar
    D = np.vstack([dstar[k] for k in names])                   # (strategies, boot)
    D = np.where(np.isfinite(D), D, np.nan)
    dv = np.array([d[k] for k in names])
    se = np.nanstd(D, axis=1)
    se = np.where(se > 0, se, np.nan)
    cen = D - dv[:, None]
    # White (2000) reality check on the raw means
    V = np.nanmax(dv)
    Vs = np.nanmax(cen, axis=0)
    rc = float(np.mean(Vs >= V))
    # Hansen (2005) SPA, studentised, consistent re-centring
    nblk = len(uni)
    thr = se * np.sqrt(2 * np.log(max(np.log(max(nblk, 3)), 1.0001)))
    g = np.where(dv <= -thr, dv, 0.0)
    T = max(0.0, float(np.nanmax(dv / se))) if np.isfinite(dv / se).any() else 0.0
    Ts = np.maximum(0.0, np.nanmax((cen + g[:, None]) / se[:, None], axis=0))
    spa = float(np.mean(Ts >= T)) if T > 0 else 1.0
    p_one = {k: float(np.nanmean(cen[i] >= dv[i])) for i, k in enumerate(names)}
    adj = holm(p_one)
    out = {k: {"diff": d[k], "se": float(se[i]) if np.isfinite(se[i]) else None, "p": p_one[k], "p_holm": adj[k],
               "lb95": float(np.nanquantile(D[i], 0.05)) if np.isfinite(D[i]).any() else None}
           for i, k in enumerate(names)}
    return {"strategies": out, "reality_check_p": rc, "spa_p": spa, "n_strategies": len(names), "blocks": nblk,
            "best": names[int(np.nanargmax(dv))], "benchmark": "zero (costs only)" if bench is None else "benchmark mean"}
