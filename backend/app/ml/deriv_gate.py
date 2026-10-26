"""Should a coin / timeframe's model use the futures-positioning features (funding, premium)?

Decided per series by evidence, not by default: the same walk-forward (same folds, fast models) is run with and
without the features, and only out-of-sample bars where futures data existed are compared. The features are
switched on only when they lower the Brier score (paired test) without hurting directional accuracy. A decision
is kept for 30 days, then re-tested on newer data.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from ..config import WALK_FORWARD, settings
from ..data import derivs
from ..db import Database
from ..features.dataset import Frame, make_dataset
from .metrics import brier, brier_skill_test
from .walkforward import run_walk_forward

log = logging.getLogger(__name__)
GATE_MODELS = ["logistic", "hist_gbm"]
MIN_DAYS = 90
TTL_MS = 30 * 86_400_000


def _key(symbol: str, tf: str) -> str:
    return f"deriv_gate2|{symbol}|{tf}"          # v2.2: re-tested with the crowd-positioning features


def cached(db: Database, symbol: str, tf: str) -> dict[str, Any] | None:
    d = db.get_setting(_key(symbol, tf), None)
    return d if d and time.time() * 1000 - d.get("at", 0) < TTL_MS else None


def decide(db: Database, symbol: str, tf: str, frame: Frame, btc: Frame | None, htf: Frame | None,
           force: bool = False) -> dict[str, Any]:
    if not force and (hit := cached(db, symbol, tf)):
        return hit
    days = max(derivs.coverage_days(db, symbol), derivs.crowd_days(db, symbol))
    if days < MIN_DAYS:
        return {"on": False, "reason": f"collecting futures data ({days:.0f} of {MIN_DAYS} days)", "at": None}
    from .trainer import GAP

    d = derivs.load_all(db, symbol)
    base, enh = make_dataset(frame, btc, htf=htf), make_dataset(frame, btc, htf=htf, deriv=d)
    idx = np.where(base.trainable & enh.trainable)[0]
    m = base.meta.iloc[idx]
    y, sigma, fwd = m["y"].to_numpy(float), m["sigma"].to_numpy(float), m["fwd_ret"].to_numpy(float)
    groups = np.nan_to_num(m["regime_group"].to_numpy(float), nan=1.0)
    names = [n for n in GATE_MODELS]
    runs = {}
    for label, ds in (("base", base), ("deriv", enh)):
        X = ds.X.to_numpy(float)[idx]
        runs[label] = run_walk_forward(X, y, sigma, fwd, groups, ds.feature_names, names, WALK_FORWARD[tf], GAP,
                                       settings.min_train_samples).P_ens
    avail = enh.X["deriv_avail"].to_numpy(float)[idx] > 0
    if "crowd_avail" in enh.X:
        avail |= enh.X["crowd_avail"].to_numpy(float)[idx] > 0
    ok = np.isfinite(runs["base"]).all(axis=1) & np.isfinite(runs["deriv"]).all(axis=1) & avail
    n = int(ok.sum())
    if n < 200:
        out = {"on": False, "reason": f"only {n} comparable out-of-sample bars", "at": int(time.time() * 1000), "n": n}
        db.set_setting(_key(symbol, tf), out)
        return out
    yy, Pb, Pd, f = y[ok].astype(int), runs["base"][ok], runs["deriv"][ok], fwd[ok]

    def hit(P):
        side = np.sign(P[:, 2] - P[:, 0])
        return float(((np.sign(f) == side) & (side != 0)).mean())

    test = brier_skill_test(Pd, Pb, yy)
    hb, hd = hit(Pb), hit(Pd)
    on = bool((test.get("mean_improvement") or 0) > 0 and (test.get("p_value") or 1) < 0.2 and hd >= hb - 0.005)
    out = {"on": on, "at": int(time.time() * 1000), "n": n, "brier_base": brier(Pb, yy), "brier_deriv": brier(Pd, yy),
           "p_value": test.get("p_value"), "hit_base": hb, "hit_deriv": hd,
           "reason": ("futures features improved out-of-sample accuracy" if on else
                      "no reliable out-of-sample improvement from futures features")}
    db.set_setting(_key(symbol, tf), out)
    log.info("deriv gate %s %s: %s", symbol, tf, out)
    return out
