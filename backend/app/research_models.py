"""Model value study (audit v2.51, owner 17 Nov 2026) - READ-ONLY (`python -m app.research models-value`).

Which of the ensemble's models earn their place? Read from every ACTIVE nightly bundle (no retraining):
  * each model's walk-forward out-of-sample Brier score next to the class-prior baseline of the same bars
    (skill = 1 - brier / brier_prior; > 0 = better than always predicting the historic class mix),
  * its weight in the ensemble the live engine uses (global weights of the live fit),
  * how often it is the series' best single model, and whether that best model beats the prior with p < alpha,
  * the ensemble's own skill, and its reliability (confidence vs realised accuracy on the out-of-sample bars).
Aggregates per model and per timeframe only. Nothing is written to the engine state (works on a private copy).
"""
from __future__ import annotations

import statistics
import time
from typing import Any

from .config import MODEL_TIMEFRAMES
from .db import Database


def _skill(m: dict[str, Any], prior: float | None) -> float | None:
    b = m.get("brier")
    if b is None or not prior:
        return None
    return 1.0 - float(b) / float(prior)


def run(db_url: str, budget_s: float = 3600) -> dict[str, Any]:
    from .ml import trainer
    from .ml.models import REGISTRY
    db = Database(db_url)
    t0 = time.time()
    rows = db.query("SELECT DISTINCT symbol, timeframe FROM model_versions WHERE active = 1")
    per_model: dict[str, dict[str, list]] = {}
    per_tf: dict[str, dict[str, Any]] = {}
    series_out, skipped = 0, []
    for r in rows:
        if time.time() - t0 > budget_s:
            skipped.append(f"{r['symbol']} {r['timeframe']}: time budget")
            continue
        tf = r["timeframe"]
        if tf not in MODEL_TIMEFRAMES:
            continue
        try:
            b = trainer.load_bundle(r["symbol"], tf, db)
        except Exception as exc:          # a model file that cannot be read is reported, never fatal
            skipped.append(f"{r['symbol']} {tf}: {type(exc).__name__}")
            continue
        if not b:
            skipped.append(f"{r['symbol']} {tf}: no bundle")
            continue
        mets = b.get("metrics") or {}
        prior = (mets.get("prior_baseline") or {}).get("brier")
        weights = ((b.get("weights") or {}).get("global") or {})
        best = (b.get("best_model") or {})
        T = per_tf.setdefault(tf, {"series": 0, "ens_skill": [], "best_supported": 0, "best": {}, "ece": []})
        T["series"] += 1
        series_out += 1
        es = _skill(mets.get("ensemble") or {}, prior)
        if es is not None:
            T["ens_skill"].append(es)
        if best.get("supported"):
            T["best_supported"] += 1
        if best.get("name"):
            T["best"][best["name"]] = T["best"].get(best["name"], 0) + 1
        rel = b.get("reliability") or []
        n = sum(x["n"] for x in rel)
        if n:
            T["ece"].append(sum(x["n"] * abs(x["mean_confidence"] - x["accuracy"]) for x in rel) / n)
        for name, m in mets.items():
            if name in ("ensemble", "prior_baseline"):
                continue
            M = per_model.setdefault(name, {"skill": [], "weight": [], "best": [], "tf": []})
            s = _skill(m, prior)
            if s is not None:
                M["skill"].append(s)
                M["tf"].append(tf)
            M["weight"].append(float(weights.get(name, 0.0)))
            M["best"].append(1 if best.get("name") == name else 0)

    def summ(xs: list[float]) -> dict[str, Any]:
        if not xs:
            return {"n": 0}
        return {"n": len(xs), "median": statistics.median(xs), "mean": statistics.fmean(xs),
                "share_positive": sum(x > 0 for x in xs) / len(xs)}

    models = []
    for name, M in per_model.items():
        by_tf = {}
        for tf in MODEL_TIMEFRAMES:
            xs = [s for s, t in zip(M["skill"], M["tf"]) if t == tf]
            if xs:
                by_tf[tf] = summ(xs)
        models.append({
            "model": name, "label": REGISTRY.get(name, {}).get("label", name),
            "baseline": bool(REGISTRY.get(name, {}).get("baseline")),
            "skill_vs_prior": summ(M["skill"]), "by_timeframe": by_tf,
            "mean_weight": statistics.fmean(M["weight"]) if M["weight"] else None,
            "series_with_weight": sum(w > 0.001 for w in M["weight"]),
            "best_in_series": sum(M["best"]),
        })
    models.sort(key=lambda m: -(m["skill_vs_prior"].get("median") or -9))
    tfs = {tf: {"series": T["series"], "ensemble_skill": summ(T["ens_skill"]),
                "best_model_beats_prior_significantly": T["best_supported"],
                "best_model_counts": dict(sorted(T["best"].items(), key=lambda kv: -kv[1])),
                "ensemble_calibration_error": summ(T["ece"])}
           for tf, T in per_tf.items()}
    return {"series": series_out, "skipped": skipped, "models": models, "timeframes": tfs,
            "seconds": round(time.time() - t0, 1),
            "method": __doc__.strip(),
            "reading": "skill_vs_prior.median > 0 and share_positive > 0.5 = the model usually beats the historic class mix "
                       "on bars it never trained on; a model with skill <= 0 almost everywhere and little weight adds "
                       "training time without adding forecast value."}
