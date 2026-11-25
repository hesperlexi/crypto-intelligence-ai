"""V3.2 (Fable 5.2 audit R-02): live meta-model thresholds from time-ordered OUT-OF-FOLD scores, with an embargo.

Before V3.2 the trade filter v1, trade filter 2 and the runner model refit on every row and took the live threshold as a
quantile of that refit's own (in-sample) scores. In-sample scores are spread wider than the scores the model gives to
new rows, so the share of live calls kept was not the share that had been examined (15m: 67 of 67 calls blocked).

Here the rows (already in time order) are cut into N_FOLDS + 1 contiguous blocks. Block k (k = 1..N_FOLDS) is scored by
a model fitted only on rows whose position is more than `embargo` bars before block k's first row, so no training
label (which spans `embargo` bars) overlaps a scored row. The live threshold is the (1 - keep) quantile of those
out-of-fold scores. `kept_share_check` re-derives the threshold from folds 1..N-1 and measures, on the last fold (never
used for that threshold), what share of rows it actually keeps; within KEEP_TOLERANCE of `keep` = validated."""
from __future__ import annotations

from typing import Any, Callable

import numpy as np

N_FOLDS = 5
EMBARGO_BARS = 30
KEEP_TOLERANCE = 0.10
MIN_TRAIN = 100


def time_folds(pos: np.ndarray, n_folds: int = N_FOLDS, embargo: float = EMBARGO_BARS,
               min_train: int = MIN_TRAIN) -> list[tuple[np.ndarray, np.ndarray]]:
    """[(train_idx, test_idx)] over rows sorted by `pos` (bar index or time in bars). Expanding window, embargoed."""
    pos = np.asarray(pos, float)
    n = len(pos)
    if n < (n_folds + 1) * 10:
        return []
    if np.any(np.diff(pos) < 0):
        raise ValueError("rows must be in time order")
    edges = np.linspace(0, n, n_folds + 2).astype(int)
    out = []
    for k in range(1, n_folds + 1):
        a, b = int(edges[k]), int(edges[k + 1])
        if b <= a:
            continue
        tr = np.flatnonzero(pos < pos[a] - embargo)
        if len(tr) < min_train:
            continue
        out.append((tr, np.arange(a, b)))
    return out


def oof_scores(F: np.ndarray, y: np.ndarray, pos: np.ndarray, model_fn: Callable[[], Any], n_folds: int = N_FOLDS,
               embargo: float = EMBARGO_BARS, min_train: int = MIN_TRAIN) -> tuple[np.ndarray, np.ndarray]:
    """(scores, fold id) per row; NaN / -1 for rows no fold scored (the first block, or folds with too little data)."""
    F, y = np.asarray(F, float), np.asarray(y, int)
    p = np.full(len(y), np.nan)
    fold = np.full(len(y), -1, int)
    for k, (tr, te) in enumerate(time_folds(pos, n_folds, embargo, min_train)):
        if len(set(y[tr].tolist())) < 2:
            continue
        m = model_fn().fit(F[tr], y[tr])
        p[te] = m.predict_proba(F[te])[:, 1]
        fold[te] = k
    return p, fold


def kept_share_check(p: np.ndarray, fold: np.ndarray, keep: float, tol: float = KEEP_TOLERANCE) -> dict[str, Any]:
    """Threshold from every scored fold but the last, applied to the last (unseen for that threshold)."""
    ok = fold >= 0
    if keep >= 1:
        return {"kept_share_unseen": 1.0, "keep_fraction": 1.0, "n_unseen": int((fold == fold.max()).sum()) if ok.any() else 0,
                "kept_share_ok": True}
    if not ok.any() or len(set(fold[ok].tolist())) < 2:
        return {"kept_share_unseen": None, "keep_fraction": keep, "n_unseen": 0, "kept_share_ok": False,
                "why": "fewer than two scored folds"}
    last = int(fold[ok].max())
    ref, unseen = p[ok & (fold < last)], p[fold == last]
    thr = float(np.quantile(ref, 1 - keep))
    share = float((unseen >= thr).mean())
    return {"kept_share_unseen": round(share, 4), "keep_fraction": keep, "n_unseen": int(len(unseen)),
            "kept_share_ok": bool(abs(share - keep) <= tol)}


def threshold(p: np.ndarray, keep: float) -> float | None:
    """Live threshold = (1 - keep) quantile of the out-of-fold scores (None when nothing was scored)."""
    v = p[np.isfinite(p)]
    if keep >= 1:
        return 0.0
    return float(np.quantile(v, 1 - keep)) if len(v) else None


def fit_threshold(F: np.ndarray, y: np.ndarray, pos: np.ndarray, keep: float, model_fn: Callable[[], Any],
                  embargo: float = EMBARGO_BARS, in_sample: float | None = None) -> dict[str, Any]:
    """Everything the bundles store about how their live threshold was set."""
    p, fold = oof_scores(F, y, pos, model_fn, embargo=embargo)
    thr = threshold(p, keep)
    chk = kept_share_check(p, fold, keep)
    return {"threshold": thr, "threshold_method": "oof_embargo", "embargo_bars": embargo, "n_folds": N_FOLDS,
            "n_oof": int(np.isfinite(p).sum()), "threshold_in_sample": in_sample, **chk,
            "validated": bool(thr is not None and chk["kept_share_ok"])}
