"""Probability calibration (Platt scaling / isotonic regression), applied only when it is justified.

Policy:
  * fewer than 200 validation rows  -> no calibration (too little data to fit a calibration map)
  * 200-999 rows                    -> Platt scaling (2 parameters per class)
  * 1000+ rows                      -> isotonic regression
  * in every case the map must lower the Brier score on the LAST 30% of the validation window when
    fitted on the first 70%; otherwise the raw probabilities are kept.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from .metrics import brier

MIN_PLATT, MIN_ISOTONIC = 200, 1000


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


class Calibrator:
    def __init__(self, method: str = "none"):
        self.method = method
        self.maps: list[Any] = [None, None, None]
        self.reason = ""

    def _fit(self, P: np.ndarray, y: np.ndarray) -> None:
        self.maps = [None, None, None]
        for k in range(3):
            t = (y == k).astype(int)
            if t.sum() < 10 or (1 - t).sum() < 10:
                continue  # class too rare in this window: leave its probability untouched
            if self.method == "platt":
                self.maps[k] = LogisticRegression(C=1e6, max_iter=1000).fit(_logit(P[:, k]).reshape(-1, 1), t)
            elif self.method == "isotonic":
                self.maps[k] = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(P[:, k], t)

    def transform(self, P: np.ndarray) -> np.ndarray:
        if self.method == "none":
            return P
        out = np.array(P, float, copy=True)
        for k, m in enumerate(self.maps):
            if m is None:
                continue
            out[:, k] = m.predict_proba(_logit(P[:, k]).reshape(-1, 1))[:, 1] if self.method == "platt" \
                else m.predict(P[:, k])
        s = out.sum(axis=1, keepdims=True)
        return np.where(s > 1e-9, out / np.where(s > 1e-9, s, 1.0), P)


def fit_calibrator(P_val: np.ndarray, y_val: np.ndarray) -> tuple[Calibrator, dict[str, Any]]:
    """Returns the calibrator and a report with the held-out Brier scores used to accept or reject it."""
    n = len(y_val)
    y_val = y_val.astype(int)
    cut = int(n * 0.7)
    report: dict[str, Any] = {"n_val": n, "holdout_n": n - cut}
    raw_tail = brier(P_val[cut:], y_val[cut:]) if n - cut > 0 else float("nan")
    report["holdout_brier_raw"] = raw_tail
    if n < MIN_PLATT:
        cal = Calibrator("none")
        cal.reason = f"only {n} validation rows (< {MIN_PLATT}): calibration not statistically justified"
        report.update(method="none", reason=cal.reason, holdout_brier=raw_tail)
        return cal, report
    method = "isotonic" if n >= MIN_ISOTONIC else "platt"
    trial = Calibrator(method)
    trial._fit(P_val[:cut], y_val[:cut])
    cal_tail = brier(trial.transform(P_val[cut:]), y_val[cut:])
    report["holdout_brier_calibrated"] = cal_tail
    if not cal_tail < raw_tail:
        cal = Calibrator("none")
        cal.reason = f"{method} did not improve held-out Brier ({cal_tail:.4f} vs raw {raw_tail:.4f})"
        report.update(method="none", reason=cal.reason, holdout_brier=raw_tail)
        return cal, report
    final = Calibrator(method)
    final._fit(P_val, y_val)
    final.reason = f"{method} improved held-out Brier {raw_tail:.4f} -> {cal_tail:.4f}"
    report.update(method=method, reason=final.reason, holdout_brier=cal_tail)
    return final, report
