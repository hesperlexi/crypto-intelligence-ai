"""Evaluation metrics for 3-class direction probabilities (0 DOWN, 1 NEUTRAL, 2 UP)."""
from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import roc_auc_score

EPS = 1e-12


def onehot(y: np.ndarray, k: int = 3) -> np.ndarray:
    out = np.zeros((len(y), k))
    out[np.arange(len(y)), y.astype(int)] = 1.0
    return out


def brier(P: np.ndarray, y: np.ndarray) -> float:
    """Multi-class Brier score (0 = perfect, 2 = worst; uniform guess = 0.667)."""
    return float(((P - onehot(y)) ** 2).sum(axis=1).mean()) if len(y) else float("nan")


def log_loss(P: np.ndarray, y: np.ndarray) -> float:
    return float(-np.log(np.clip(P[np.arange(len(y)), y.astype(int)], EPS, 1)).mean()) if len(y) else float("nan")


def reliability_table(P: np.ndarray, y: np.ndarray, edges: tuple[float, ...] = (0.0, 0.4, 0.45, 0.5, 0.55, 0.6, 0.7, 1.0001)
                      ) -> list[dict[str, Any]]:
    """Confidence (max class probability) vs realised accuracy, per confidence bin."""
    conf, pred = P.max(axis=1), P.argmax(axis=1)
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf >= lo) & (conf < hi)
        if m.sum():
            rows.append({"lo": lo, "hi": min(hi, 1.0), "n": int(m.sum()), "mean_confidence": float(conf[m].mean()),
                         "accuracy": float((pred[m] == y[m]).mean())})
    return rows


def ece(P: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    """Expected calibration error of the predicted class."""
    if not len(y):
        return float("nan")
    conf, pred = P.max(axis=1), P.argmax(axis=1)
    idx = np.minimum((conf * bins).astype(int), bins - 1)
    total = 0.0
    for b in np.unique(idx):
        m = idx == b
        total += m.mean() * abs((pred[m] == y[m]).mean() - conf[m].mean())
    return float(total)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (float(max(0.0, c - h)), float(min(1.0, c + h)))


def calibration_label(e: float) -> str:
    if not np.isfinite(e):
        return "Unknown"
    return "Good" if e < 0.03 else "Fair" if e < 0.07 else "Poor"


def classification_metrics(P: np.ndarray, y: np.ndarray, fwd_ret: np.ndarray | None = None) -> dict[str, Any]:
    """`accuracy` is 3-class accuracy. `directional_accuracy` is, among UP/DOWN calls only, how often the
    realised return had the predicted sign (the figure most people mean by 'direction accuracy')."""
    n = len(y)
    if n == 0:
        return {"n": 0}
    y = y.astype(int)
    pred = P.argmax(axis=1)
    out: dict[str, Any] = {"n": int(n), "accuracy": float((pred == y).mean())}
    per = {}
    for k, name in ((2, "up"), (0, "down")):
        tp = int(((pred == k) & (y == k)).sum())
        pp, ap = int((pred == k).sum()), int((y == k).sum())
        prec = tp / pp if pp else None
        rec = tp / ap if ap else None
        f1 = 2 * prec * rec / (prec + rec) if prec and rec else (0.0 if pp or ap else None)
        per[name] = (prec, rec, f1)
        out[f"precision_{name}"], out[f"recall_{name}"], out[f"f1_{name}"] = prec, rec, f1
    f1s = [v[2] for v in per.values() if v[2] is not None]
    out["precision"] = _avg([per["up"][0], per["down"][0]])
    out["recall"] = _avg([per["up"][1], per["down"][1]])
    out["f1"] = float(np.mean(f1s)) if f1s else None
    calls = pred != 1
    out["call_rate"] = float(calls.mean())
    if fwd_ret is not None and calls.sum():
        sign = np.where(pred[calls] == 2, 1.0, -1.0)
        out["directional_accuracy"] = float((np.sign(fwd_ret[calls]) == sign).mean())
        out["directional_n"] = int(calls.sum())
    else:
        out["directional_accuracy"], out["directional_n"] = None, int(calls.sum())
    try:
        out["roc_auc"] = float(roc_auc_score(y, P, multi_class="ovr", labels=[0, 1, 2])) if len(np.unique(y)) == 3 else None
    except Exception:
        out["roc_auc"] = None
    out["brier"], out["log_loss"] = brier(P, y), log_loss(P, y)
    out["ece"] = ece(P, y)
    out["calibration"] = calibration_label(out["ece"])
    return out


def _avg(vals: list[float | None]) -> float | None:
    v = [x for x in vals if x is not None]
    return float(np.mean(v)) if v else None


def regression_metrics(pred_ret: np.ndarray, actual_ret: np.ndarray, close: np.ndarray) -> dict[str, Any]:
    """Error of the point forecast, in return space and price space, next to the naive 'no change' forecast."""
    ok = np.isfinite(pred_ret) & np.isfinite(actual_ret)
    if not ok.sum():
        return {"n": 0}
    p, a, c = pred_ret[ok], actual_ret[ok], close[ok]
    err = p - a
    price_ape = np.abs((c * (1 + p)) - (c * (1 + a))) / (c * (1 + a))
    naive_ape = np.abs(c - c * (1 + a)) / (c * (1 + a))
    return {
        "n": int(ok.sum()), "mae": float(np.abs(err).mean()), "rmse": float(np.sqrt((err ** 2).mean())),
        "mape_price": float(price_ape.mean()), "naive_mae": float(np.abs(a).mean()),
        "naive_rmse": float(np.sqrt((a ** 2).mean())), "naive_mape_price": float(naive_ape.mean()),
        "beats_naive": bool(np.abs(err).mean() < np.abs(a).mean()),
    }


def brier_skill_test(P_model: np.ndarray, P_ref: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    """Paired one-sided t-test on per-row Brier scores: is the model better than the reference forecast?"""
    from scipy import stats as sps

    oh = onehot(y)
    d = ((P_ref - oh) ** 2).sum(axis=1) - ((P_model - oh) ** 2).sum(axis=1)   # > 0 where the model is better
    if len(d) < 30 or d.std(ddof=1) == 0:
        return {"n": int(len(d)), "mean_improvement": float(d.mean()) if len(d) else None, "p_value": None}
    t = d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))
    return {"n": int(len(d)), "mean_improvement": float(d.mean()), "p_value": float(sps.t.sf(t, len(d) - 1))}
