"""Model-set study (audit v2.52, owner 17 Nov 2026: "anything that improves the results") - READ-ONLY on production.

`python -m app.research modelset --timeframes 4h --budget 17000`
For each active coin of the timeframe, on a PRIVATE copy of the engine state:
  1. control  = retrain with today's model set (every available model) - so all variants see the same, latest data;
  2. no_arima = the same without ARIMA (skill < 0 in 91 % of series, 17 Nov models-value study);
  3. rf_only  = Random Forest alone (+ the two baselines, which never carry weight) - it is the best model in 154/233.
Each fresh model is judged exactly like `research_engine.evaluate` judges the live pipeline: its walk-forward
out-of-sample calls through the live decision rules and the record's exits, 0.15 % costs, one call at a time; first 70 %
of the series chooses, the untouched last 30 % is the test. Reported: test trades, avg / total R, win rate, profit factor
per variant, the paired difference to the control per series, and a series bootstrap of that difference.
Aggregates only; nothing is written to the live engine state.
"""
from __future__ import annotations

import random
import time
from typing import Any

VARIANTS = {
    "no_arima": lambda names: [n for n in names if n != "arima"],
    "rf_only": lambda names: [n for n in names if n in ("prior_baseline", "prev_candle", "random_forest")],
}


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = sum(r["n"] for r in rows)
    tot = sum(r["total_r"] for r in rows)
    wins = sum((r.get("win_rate") or 0) * r["n"] for r in rows)
    return {"trades": n, "avg_r": round(tot / n, 4) if n else None, "total_r": round(tot, 2),
            "win_rate": round(wins / n, 3) if n else None, "series": len(rows),
            "drawdown_r_sum": round(sum(r.get("max_drawdown_r") or 0 for r in rows), 2)}


def _boot(diffs: list[tuple[float, int]], reps: int = 2000) -> dict[str, Any]:
    """Series bootstrap of (sum of total-R differences) / (sum of control trades): share of resamples > 0."""
    if len(diffs) < 3:
        return {"n_series": len(diffs)}
    rnd = random.Random(7)
    better = 0
    vals = []
    for _ in range(reps):
        pick = [diffs[rnd.randrange(len(diffs))] for _ in diffs]
        n = sum(p[1] for p in pick) or 1
        v = sum(p[0] for p in pick) / n
        vals.append(v)
        better += v > 0
    vals.sort()
    return {"n_series": len(diffs), "share_better": round(better / reps, 3),
            "ci90_r_per_trade": [round(vals[int(0.05 * reps)], 4), round(vals[int(0.95 * reps)], 4)]}


def run(db_url: str, timeframes: list[str], budget_s: float, cost: float,
        symbols: list[str] | None = None) -> dict[str, Any]:
    from .db import Database
    from .ml import trainer
    from .ml.models import default_models
    from .services import training
    from .services.runtime import Runtime
    from . import research_engine as RE

    class _Prov:
        name = "binance"
    db = Database(db_url)
    ex = db.one("SELECT exchange, COUNT(*) AS n FROM market_data GROUP BY exchange ORDER BY n DESC LIMIT 1")
    if ex:
        _Prov.name = ex["exchange"]
    rt = Runtime(db, _Prov())
    full = default_models(False)
    t0 = time.time()
    deadline = t0 + budget_s
    out: dict[str, Any] = {"timeframes": {}, "models_control": full, "variants": {k: f(full) for k, f in VARIANTS.items()}}
    orig = trainer.default_models
    try:
        for tf in timeframes:
            syms = symbols or [r["symbol"] for r in db.query(
                "SELECT DISTINCT symbol FROM model_versions WHERE active = 1 AND timeframe = ? ORDER BY symbol", (tf,))]
            per: dict[str, dict[str, Any]] = {}
            skipped: list[str] = []
            for s in syms:
                if time.time() > deadline:
                    skipped.append(f"{s}: time budget")
                    continue
                row: dict[str, Any] = {}
                for name, names in [("control", full)] + [(k, f(full)) for k, f in VARIANTS.items()]:
                    if time.time() > deadline:
                        break
                    trainer.default_models = lambda fast=False, _n=names: list(_n)
                    trainer._cache.clear()
                    st = training.train_one(rt, s, tf)
                    if st.get("state") != "done":
                        row[name] = {"error": str(st.get("error") or st.get("message") or st.get("state"))[:120]}
                        continue
                    res = RE.evaluate(rt, [s], [tf], deadline, cost)
                    v = (res.get("series") or {}).get(f"{s} {tf}")
                    row[name] = dict(v["test_old"]) if v else {"error": "not evaluated: " + "; ".join(res.get("skipped") or [])[:120]}
                if all(isinstance(row.get(k), dict) and "n" in row[k] for k in ["control", *VARIANTS]):
                    per[s] = row
                else:
                    skipped.append(f"{s}: " + "; ".join(f"{k} {v.get('error')}" for k, v in row.items() if "error" in v)[:200])
            T: dict[str, Any] = {"coins_done": len(per), "skipped": skipped}
            for k in ["control", *VARIANTS]:
                T[k] = _stats([per[s][k] for s in per])
            for k in VARIANTS:
                diffs = [(per[s][k]["total_r"] - per[s]["control"]["total_r"], per[s]["control"]["n"]) for s in per]
                T[f"{k}_vs_control"] = _boot(diffs)
            out["timeframes"][tf] = T
    finally:
        trainer.default_models = orig
    out["seconds"] = round(time.time() - t0, 1)
    out["method"] = __doc__.strip()
    return out
