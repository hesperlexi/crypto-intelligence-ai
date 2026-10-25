"""Champion / challenger: a retrained model replaces the active one only if it is not worse.

Fair head-to-head on the same bars: the bars that arrived AFTER the current model was trained are out-of-sample
for both - the current model never saw them, and the new model's walk-forward scored them with models trained
only on earlier data. On those bars both are scored (3-class Brier score and long/short hit rate). The new model
is rejected only when it is clearly worse on both; when there are too few shared bars it is compared on its own
walk-forward record instead. Each decision is stored so the app can show it.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from ..features.dataset import Dataset
from .metrics import brier

log = logging.getLogger(__name__)
MIN_SHARED = 100
BRIER_TOL = 0.002
HIT_TOL = 0.01


def _hit(P: np.ndarray, fwd: np.ndarray) -> float:
    side = np.sign(P[:, 2] - P[:, 0])
    return float(((np.sign(fwd) == side) & (side != 0)).mean())


def _old_predictions(old: dict[str, Any], ds: Dataset, rows: np.ndarray) -> np.ndarray:
    from .trainer import predict

    out = np.full((len(rows), 3), np.nan)
    for k, j in enumerate(rows):
        try:
            p = predict(old, ds, int(j))["probabilities"]
            out[k] = [p["down"], p["neutral"], p["up"]]
        except Exception:
            continue
    return out


def compare(old: dict[str, Any] | None, new: dict[str, Any], ds: Dataset | None) -> dict[str, Any]:
    if old is None:
        return {"activate": True, "basis": "first model"}
    o = new.get("oos") or {}
    ts, P, y, fwd = (np.asarray(o.get(k, []), float) for k in ("ts", "P_ens", "y", "fwd_ret"))
    shared = None
    if ds is not None and len(ts):
        after = (ts > float(old.get("data_end") or 0)) & np.isfinite(P).all(axis=1) & np.isfinite(y)
        if after.sum() >= MIN_SHARED:
            pos = {int(t): i for i, t in enumerate(ds.meta["ts"].to_numpy())}
            idx = np.where(after)[0]
            rows = np.array([pos.get(int(ts[i]), -1) for i in idx])
            keep = rows >= 0
            idx, rows = idx[keep], rows[keep]
            Po = _old_predictions(old, ds, rows)
            ok = np.isfinite(Po).all(axis=1)
            if ok.sum() >= MIN_SHARED:
                Pn, yy, ff = P[idx][ok], y[idx][ok].astype(int), fwd[idx][ok]
                shared = {"bars": int(ok.sum()), "brier_new": brier(Pn, yy), "brier_old": brier(Po[ok], yy),
                          "hit_new": _hit(Pn, ff), "hit_old": _hit(Po[ok], ff)}
    if shared:
        worse = shared["brier_new"] > shared["brier_old"] + BRIER_TOL and shared["hit_new"] < shared["hit_old"] - HIT_TOL
        return {"activate": not worse, "basis": f"head-to-head on {shared['bars']} bars neither model trained on", **shared}
    # too few shared bars: compare each model's own walk-forward record
    from .direction import direction_policy

    pn, po = direction_policy(o), direction_policy(old.get("oos") or {})
    if not pn or not po:
        return {"activate": True, "basis": "not enough history to compare"}
    lo = lambda p: ((p.get("best") or {}).get("ci95") or [0.5])[0]   # noqa: E731
    worse = pn["base_hit_rate"] < po["base_hit_rate"] - HIT_TOL and lo(pn) < lo(po) - HIT_TOL
    return {"activate": not worse, "basis": "walk-forward records", "hit_new": pn["base_hit_rate"],
            "hit_old": po["base_hit_rate"], "edge_new": pn.get("edge"), "edge_old": po.get("edge")}
