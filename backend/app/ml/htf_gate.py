"""Should a coin / timeframe's model use higher-timeframe context (v2.3)?

A blanket test (24 Oct 2026, 15 series) found no consistent gain from higher-timeframe features: they helped some
series and hurt others. So, like the futures-data gate, it is decided per series by evidence: the same walk-forward
(same folds, fast models) runs with and without the higher-timeframe columns, and only out-of-sample predictions
are compared. The context is switched on only when it lowers the Brier score (paired test, p < 0.2) without hurting
directional accuracy. A decision is kept for 30 days, then re-tested on newer data. The separate bigger-trend check
in analysis.py (no trade against both higher timeframes) is always on and is not affected by this.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from ..config import WALK_FORWARD, settings
from ..db import Database
from ..features.dataset import Frame, make_dataset
from .metrics import brier, brier_skill_test
from .walkforward import run_walk_forward

log = logging.getLogger(__name__)
GATE_MODELS = ["logistic", "hist_gbm"]
TTL_MS = 30 * 86_400_000
MIN_OOS = 200


def _key(symbol: str, tf: str) -> str:
    return f"htf_gate1|{symbol}|{tf}"


def cached(db: Database, symbol: str, tf: str) -> dict[str, Any] | None:
    d = db.get_setting(_key(symbol, tf), None)
    return d if d and time.time() * 1000 - d.get("at", 0) < TTL_MS else None


def decide(db: Database, symbol: str, tf: str, frame: Frame, btc: Frame | None, htf: Frame,
           force: bool = False) -> dict[str, Any]:
    if not force and (hit := cached(db, symbol, tf)):
        return hit
    from .trainer import GAP

    base, enh = make_dataset(frame, btc), make_dataset(frame, btc, htf=htf)
    idx = np.where(base.trainable & enh.trainable)[0]
    m = base.meta.iloc[idx]
    y, sigma, fwd = m["y"].to_numpy(float), m["sigma"].to_numpy(float), m["fwd_ret"].to_numpy(float)
    groups = np.nan_to_num(m["regime_group"].to_numpy(float), nan=1.0)
    runs = {}
    for label, ds in (("base", base), ("htf", enh)):
        X = ds.X.to_numpy(float)[idx]
        runs[label] = run_walk_forward(X, y, sigma, fwd, groups, ds.feature_names, list(GATE_MODELS), WALK_FORWARD[tf],
                                       GAP, settings.min_train_samples).P_ens
    ok = np.isfinite(runs["base"]).all(axis=1) & np.isfinite(runs["htf"]).all(axis=1)
    n = int(ok.sum())
    now = int(time.time() * 1000)
    if n < MIN_OOS:
        out = {"on": False, "at": now, "n": n, "htf": htf.timeframe,
               "reason": f"only {n} comparable out-of-sample bars"}
        db.set_setting(_key(symbol, tf), out)
        return out
    yy, Pb, Ph, f = y[ok].astype(int), runs["base"][ok], runs["htf"][ok], fwd[ok]

    def hit(P):
        side = np.sign(P[:, 2] - P[:, 0])
        return float(((np.sign(f) == side) & (side != 0)).mean())

    test = brier_skill_test(Ph, Pb, yy)
    hb, hh = hit(Pb), hit(Ph)
    on = bool((test.get("mean_improvement") or 0) > 0 and (test.get("p_value") or 1) < 0.2 and hh >= hb - 0.005)
    out = {"on": on, "at": now, "n": n, "htf": htf.timeframe, "brier_base": brier(Pb, yy), "brier_htf": brier(Ph, yy),
           "p_value": test.get("p_value"), "hit_base": hb, "hit_htf": hh,
           "reason": (f"{htf.timeframe.upper()} context improved out-of-sample accuracy" if on else
                      f"no reliable out-of-sample improvement from {htf.timeframe.upper()} context")}
    db.set_setting(_key(symbol, tf), out)
    log.info("htf gate %s %s: %s (n=%d, p=%s)", symbol, tf, "ON" if on else "off", n, out["p_value"])
    return out
