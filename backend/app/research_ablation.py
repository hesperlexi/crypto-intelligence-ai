"""Model ablation study (owner, 24 Nov 2026: "concentrate on how many models actually improve the final decision").
READ-ONLY on production: runs on a private copy of the engine state, never saves it, never activates anything live.

`python -m app.research ablation --timeframes 4h --variants g1 --budget 18000`

For every active coin of the timeframe the model bundle is retrained several ways on the SAME, latest data and each one is
judged on the untouched test split with the live decision rules and the record's exits + costs (research_engine.evaluate):

  control         today's live model set for that timeframe (settings.model_exclude applied, deep models off as live)
  no_<model>      the live set without one model                       -> does that model add anything?
  <model>_only    one model alone (+ the two baselines, which carry no weight) -> is the ensemble better than its parts?
  with_deep       the live set + LSTM / GRU / Transformer               -> do deep models add anything?

Groups (one CI job each, so every job fits in the 6-hour limit):
  g1  no_random_forest, no_logistic, no_technical_rules, logistic_only
  g2  no_xgboost, no_lightgbm, no_hist_gbm, xgboost_only
  g3  no_arima, random_forest_only, boosting_only, with_deep

Per variant: trading result (net R, per trade, win rate), the ensemble's out-of-sample Brier score and log loss from the
walk-forward, and a series bootstrap of the R difference vs control (share of resamples better, 90 % interval).
The champion / challenger guard is switched OFF inside the study (otherwise a variant could be refused and the old model
evaluated in its place).
"""
from __future__ import annotations

import random
import time
from typing import Any

BASE = ("prior_baseline", "prev_candle")
BOOST = ("hist_gbm", "xgboost", "lightgbm")


def _drop(m: str):
    return lambda names: [n for n in names if n != m]


def _only(*ms: str):
    return lambda names: [n for n in names if n in BASE or n in ms]


GROUPS: dict[str, dict[str, Any]] = {
    "g1": {"no_random_forest": _drop("random_forest"), "no_logistic": _drop("logistic"),
           "no_technical_rules": _drop("technical_rules"), "logistic_only": _only("logistic")},
    "g2": {"no_xgboost": _drop("xgboost"), "no_lightgbm": _drop("lightgbm"), "no_hist_gbm": _drop("hist_gbm"),
           "xgboost_only": _only("xgboost")},
    "g3": {"no_arima": _drop("arima"), "random_forest_only": _only("random_forest"), "boosting_only": _only(*BOOST),
           "with_deep": "deep"},
    # v3.1 confirm (owner, 25 Nov 2026): 1d without Random Forest, judged on BOTH windows (earlier 70 % and last 30 %)
    "rf": {"no_random_forest": _drop("random_forest")},
}


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = sum(r["n"] for r in rows)
    tot = sum(r["total_r"] for r in rows)
    wins = sum((r.get("win_rate") or 0) * r["n"] for r in rows)
    bs = [r["brier"] for r in rows if r.get("brier") is not None]
    ll = [r["log_loss"] for r in rows if r.get("log_loss") is not None]
    return {"trades": n, "avg_r": round(tot / n, 4) if n else None, "total_r": round(tot, 2),
            "win_rate": round(wins / n, 3) if n else None, "series": len(rows),
            "brier_mean": round(sum(bs) / len(bs), 5) if bs else None,
            "log_loss_mean": round(sum(ll) / len(ll), 5) if ll else None,
            "drawdown_r_sum": round(sum(r.get("max_drawdown_r") or 0 for r in rows), 2)}


def _boot(diffs: list[tuple[float, int]], reps: int = 2000) -> dict[str, Any]:
    if len(diffs) < 3:
        return {"n_series": len(diffs)}
    rnd = random.Random(7)
    vals = []
    for _ in range(reps):
        pick = [diffs[rnd.randrange(len(diffs))] for _ in diffs]
        n = sum(p[1] for p in pick) or 1
        vals.append(sum(p[0] for p in pick) / n)
    vals.sort()
    better = sum(v > 0 for v in vals)
    return {"n_series": len(diffs), "share_better": round(better / reps, 3),
            "ci90_r_per_trade": [round(vals[int(0.05 * reps)], 4), round(vals[int(0.95 * reps)], 4)]}


def run(db_url: str, timeframes: list[str], group: str, budget_s: float, cost: float,
        symbols: list[str] | None = None) -> dict[str, Any]:
    from .config import settings
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
    variants = GROUPS[group]
    t0 = time.time()
    deadline = t0 + budget_s
    out: dict[str, Any] = {"group": group, "timeframes": {}}
    orig_models, orig_save = trainer.default_models, trainer.save_bundle
    orig_enforce, orig_deep = settings.challenger_enforce, settings.enable_deep_models
    last: dict[str, Any] = {}

    def save_spy(bundle, *a, **k):                       # keep the ensemble's walk-forward scores of the bundle just trained
        ens = (bundle.get("metrics") or {}).get("ensemble") or {}
        last.clear()
        last.update(brier=ens.get("brier"), log_loss=ens.get("log_loss"), models=list(bundle.get("models") or {}))
        return orig_save(bundle, *a, **k)

    try:
        object.__setattr__(settings, "challenger_enforce", False)
        trainer.save_bundle = save_spy
        for tf in timeframes:
            object.__setattr__(settings, "enable_deep_models", False)
            live = default_models(False, tf)
            plan = [("control", live, False)] + [(k, live if f == "deep" else f(live), f == "deep") for k, f in variants.items()]
            # a variant identical to the live set (e.g. no_arima on 12h, where ARIMA is already excluded) is not retrained
            same = [k for k, m, d in plan[1:] if not d and sorted(m) == sorted(live)]
            plan = [p for p in plan if p[0] not in same]
            out.setdefault("same_as_control", {})[tf] = same
            out.setdefault("models", {})[tf] = {k: m for k, m, _ in plan}
            syms = symbols or [r["symbol"] for r in db.query(
                "SELECT DISTINCT symbol FROM model_versions WHERE active = 1 AND timeframe = ? ORDER BY symbol", (tf,))]
            per: dict[str, dict[str, Any]] = {}
            skipped: list[str] = []
            for s in syms:
                if time.time() > deadline:
                    skipped.append(f"{s}: time budget")
                    continue
                row: dict[str, Any] = {}
                for name, names, deep in plan:
                    if time.time() > deadline:
                        break
                    object.__setattr__(settings, "enable_deep_models", deep)
                    extra = ["lstm", "gru", "transformer"] if deep else []
                    trainer.default_models = lambda fast=False, *a, _n=names + extra, **k: list(_n)
                    trainer._cache.clear()
                    last.clear()
                    st = training.train_one(rt, s, tf)
                    if st.get("state") != "done":
                        row[name] = {"error": str(st.get("error") or st.get("message") or st.get("state"))[:120]}
                        continue
                    scores = dict(last)
                    res = RE.evaluate(rt, [s], [tf], deadline, cost)
                    v = (res.get("series") or {}).get(f"{s} {tf}")
                    row[name] = ({**dict(v["test_old"]), "tune": dict(v.get("tune_old") or {}),
                                  "brier": scores.get("brier"), "log_loss": scores.get("log_loss"),
                                  "trained": scores.get("models")} if v
                                 else {"error": "not evaluated: " + "; ".join(res.get("skipped") or [])[:120]})
                if all(isinstance(row.get(k), dict) and "n" in row[k] for k, _, _ in plan):
                    per[s] = row
                else:
                    skipped.append(f"{s}: " + "; ".join(f"{k} {v.get('error')}" for k, v in row.items() if "error" in v)[:200])
            T: dict[str, Any] = {"coins_done": len(per), "skipped": skipped}
            for k, _, _ in plan:
                T[k] = _stats([per[s][k] for s in per])
            for k in [p[0] for p in plan[1:]]:
                T[f"{k}_vs_control"] = _boot([(per[s][k]["total_r"] - per[s]["control"]["total_r"], per[s]["control"]["n"])
                                              for s in per])
                if group == "rf":            # the earlier window too: a change must hold in both
                    tw = lambda s, kk: per[s][kk].get("tune") or {}
                    T[f"{k}_tune"] = _stats([{**tw(s, k), "n": tw(s, k).get("n", 0), "total_r": tw(s, k).get("total_r", 0.0),
                                              "win_rate": tw(s, k).get("win_rate")} for s in per])
                    T["control_tune"] = _stats([{**tw(s, "control"), "n": tw(s, "control").get("n", 0),
                                                 "total_r": tw(s, "control").get("total_r", 0.0),
                                                 "win_rate": tw(s, "control").get("win_rate")} for s in per])
                    T[f"{k}_tune_vs_control"] = _boot([(tw(s, k).get("total_r", 0.0) - tw(s, "control").get("total_r", 0.0),
                                                        tw(s, "control").get("n", 0) or 1) for s in per])
                b = [(per[s][k]["brier"], per[s]["control"]["brier"]) for s in per
                     if per[s][k].get("brier") is not None and per[s]["control"].get("brier") is not None]
                T[f"{k}_vs_control"]["brier_better_share"] = round(sum(x < y for x, y in b) / len(b), 3) if b else None
            out["timeframes"][tf] = T
    finally:
        trainer.default_models, trainer.save_bundle = orig_models, orig_save
        object.__setattr__(settings, "challenger_enforce", orig_enforce)
        object.__setattr__(settings, "enable_deep_models", orig_deep)
    out["seconds"] = round(time.time() - t0, 1)
    out["method"] = __doc__.strip()
    return out
