"""Accuracy experiment on real stored candles: does an enhancement beat the current recipe out-of-sample?

    python -m app.evaluate --symbols BTC/USDT,ETH/USDT --timeframes 1h,4h,1d --out report.json

For every symbol / timeframe the same walk-forward (same folds, same models, same calibration and ensembling as
production) is run twice: the current feature set ("baseline") and the feature set with higher-timeframe context
("htf"). Only out-of-sample predictions are scored. The verdict needs the enhancement to win on Brier score
(the main probabilistic metric) in most series, not on one lucky series.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from typing import Any

import numpy as np

from .config import WALK_FORWARD, settings
from .db import get_db
from .features.dataset import HTF_OF, InsufficientData, make_dataset
from .ml.metrics import brier, classification_metrics
from .ml.trainer import GAP, selective_threshold
from .ml.walkforward import run_walk_forward
from .services import market
from .services.runtime import Runtime

log = logging.getLogger("evaluate")
MODELS = ["prior_baseline", "prev_candle", "logistic", "technical_rules", "hist_gbm", "lightgbm", "xgboost"]


def _score(ds, names: list[str], tf: str) -> dict[str, Any]:
    idx = np.where(ds.trainable)[0]
    X = ds.X.to_numpy(float)[idx]
    m = ds.meta.iloc[idx]
    y, sigma, fwd = m["y"].to_numpy(float), m["sigma"].to_numpy(float), m["fwd_ret"].to_numpy(float)
    groups = np.nan_to_num(m["regime_group"].to_numpy(float), nan=1.0)
    wf = run_walk_forward(X, y, sigma, fwd, groups, ds.feature_names, names, WALK_FORWARD[tf], GAP, settings.min_train_samples)
    oos = np.isfinite(wf.P_ens).all(axis=1)
    P, yy = wf.P_ens[oos], y[oos].astype(int)
    prior = np.bincount(yy, minlength=3) / len(yy)
    cm = classification_metrics(P, yy, fwd[oos])
    sel = selective_threshold(P, yy, fwd[oos]) or {}
    b, b0 = brier(P, yy), brier(np.tile(prior, (len(yy), 1)), yy)
    return {"n_oos": int(oos.sum()), "brier": b, "brier_skill_vs_prior": 1 - b / b0 if b0 else None,
            "accuracy": cm.get("accuracy"), "directional_accuracy": cm.get("directional_accuracy"),
            "log_loss": cm.get("log_loss"), "confident_threshold": sel.get("threshold"),
            "confident_hit_rate": sel.get("hit_rate"), "confident_coverage": sel.get("coverage"),
            "n_features": len(ds.feature_names)}


def run(rt: Runtime, symbols: list[str], tfs: list[str], deadline: float) -> dict[str, Any]:
    from .ml.models import default_models

    avail = set(default_models())
    names = [m for m in MODELS if m in avail]
    rows = []
    for tf in tfs:
        for s in symbols:
            if time.time() > deadline:
                rows.append({"symbol": s, "timeframe": tf, "skipped": "time budget"})
                continue
            try:
                fr = rt.frame(s, tf)
                btc = None if s.startswith("BTC/") else rt.frame("BTC/USDT", tf)
                htf = rt.frame(s, HTF_OF[tf]) if tf in HTF_OF else None
                base = _score(make_dataset(fr, btc), names, tf)
                enh = _score(make_dataset(fr, btc, htf=htf), names, tf) if htf is not None else None
                row = {"symbol": s, "timeframe": tf, "baseline": base, "htf": enh}
                if enh:
                    # compare on the same out-of-sample bars only when both runs scored a comparable number of them
                    row["brier_better"] = bool(enh["brier"] < base["brier"])
                    row["delta_brier_skill"] = _diff(enh["brier_skill_vs_prior"], base["brier_skill_vs_prior"])
                    row["delta_directional"] = _diff(enh["directional_accuracy"], base["directional_accuracy"])
                    row["oos_ratio"] = enh["n_oos"] / max(1, base["n_oos"])
                rows.append(row)
                log.info("%s %s done: %s", s, tf, json.dumps({k: v for k, v in row.items() if k.startswith("delta")}))
            except InsufficientData as exc:
                rows.append({"symbol": s, "timeframe": tf, "skipped": str(exc)})
            except Exception as exc:
                log.exception("evaluation failed for %s %s", s, tf)
                rows.append({"symbol": s, "timeframe": tf, "error": f"{type(exc).__name__}: {exc}"[:200]})
    done = [r for r in rows if r.get("htf") and r.get("delta_brier_skill") is not None and r.get("oos_ratio", 0) > 0.8]
    wins = sum(r["brier_better"] for r in done)
    summary = {
        "series": len(done), "htf_wins_on_brier": wins,
        "mean_delta_brier_skill": _mean([r["delta_brier_skill"] for r in done]),
        "mean_delta_directional_accuracy": _mean([r["delta_directional"] for r in done]),
        "mean_confident_hit_rate_baseline": _mean([r["baseline"]["confident_hit_rate"] for r in done]),
        "mean_directional_accuracy_baseline": _mean([r["baseline"]["directional_accuracy"] for r in done]),
        "verdict": ("ENABLE: higher-timeframe features improve out-of-sample Brier in most series"
                    if done and wins >= 0.6 * len(done) and (_mean([r["delta_brier_skill"] for r in done]) or 0) > 0
                    else "KEEP OFF: no consistent out-of-sample improvement"),
    }
    return {"generated_at": int(time.time() * 1000), "models": names, "summary": summary, "rows": rows}


def _mean(v):
    v = [x for x in v if x is not None and np.isfinite(x)]
    return float(np.mean(v)) if v else None


def _diff(a, b):
    return None if a is None or b is None or not np.isfinite(a) or not np.isfinite(b) else float(a - b)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="python -m app.evaluate")
    ap.add_argument("--symbols", default="BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT,XRP/USDT")
    ap.add_argument("--timeframes", default="1h,4h,1d")
    ap.add_argument("--budget", type=float, default=2400)
    ap.add_argument("--out", default="report.json")
    a = ap.parse_args()
    rt = Runtime(get_db(), market.make_provider())
    rep = run(rt, a.symbols.split(","), a.timeframes.split(","), time.time() + a.budget)
    with open(a.out, "w") as f:
        json.dump(rep, f, indent=1, default=float)
    log.info("summary: %s", json.dumps(rep["summary"]))


if __name__ == "__main__":
    main()
