"""Best-opportunities ranking test (owner, 14 Nov 2026) - read-only replay (python -m app.research rank).

Same calls and method as research_ideas: the models' walk-forward out-of-sample calls of every series through the live
decision rules, honest entry, the record's exits, 0.15 % round trip + funding, one call at a time per series; first 70 %
of each series = tune, last 30 % = untouched test.

Question: can a score known AT THE CALL say which calls will pay best, so a "best opportunities" list ranks them?
Candidate features (all from data before the decision): AI lean |margin|, directional confidence, grade, technical score
in the trade's direction, regime score in the trade's direction, higher-timeframe agreement, BTC technical score in the
trade's direction, volatility state, stop distance in %.
  * per feature: Spearman correlation with the trade's net R on tune and on test (same sign on both = stable);
  * composite = sum of the z-scored features, each signed by its TUNE correlation, only features with |rho| >= 0.03 on
    tune (z from tune means / stds) - nothing is fitted on the test;
  * test: average R by composite quintile (Q5 = best ranked), top 40 % vs all, and a portfolio that each UTC day takes
    only the top-ranked calls (at most 3 a day) vs every call.
Aggregates only (public results branch)."""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

import numpy as np

from .config import MODEL_TIMEFRAMES, settings

log = logging.getLogger(__name__)

FEATURES = ("lean", "confidence", "grade_a", "tech", "regime", "htf_agree", "btc_tech", "vol_state", "stop_pct")
MIN_RHO = 0.03


def _rank(x: np.ndarray) -> np.ndarray:
    o = np.argsort(x, kind="mergesort")
    r = np.empty(len(x))
    r[o] = np.arange(len(x))
    # average ties
    xs = x[o]
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[j + 1] == xs[i]:
            j += 1
        if j > i:
            r[o[i:j + 1]] = (i + j) / 2
        i = j + 1
    return r


def spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 30 or np.std(a[m]) == 0:
        return None
    return float(np.corrcoef(_rank(a[m]), _rank(b[m]))[0, 1])


def _stats(r: list[float]) -> dict[str, Any]:
    if not r:
        return {"n": 0}
    a = np.array(r)
    c = np.cumsum(a)
    dd = float(np.max(np.maximum.accumulate(np.r_[0.0, c])[1:] - c))
    return {"n": len(a), "avg_r": round(float(a.mean()), 4), "total_r": round(float(a.sum()), 2),
            "win_rate": round(float((a > 0).mean()), 3), "max_dd_r": round(max(dd, 0.0), 2)}


def features_of(ctx, d, j: int) -> dict[str, float]:
    side = float(d["side"][j])
    pl = d["plan"][j] or {}
    htf = [v[j] for t, v in ctx.mtf_dir.items() if np.isfinite(v[j])]
    stop = abs(float(ctx.close[j]) - float(pl["stop"])) / float(ctx.close[j]) * 100 if pl.get("stop") else np.nan
    conf = d["confidence"][j]
    return {"lean": abs(float(d["margin"][j])) if np.isfinite(d["margin"][j]) else np.nan,
            "confidence": float(conf) if conf is not None and np.isfinite(conf) else np.nan,
            "grade_a": 1.0 if d["grade"][j] == "A" else 0.0,
            "tech": side * float(ctx.tech[j]) if np.isfinite(ctx.tech[j]) else np.nan,
            "regime": side * float(ctx.regime_score[j]) if np.isfinite(ctx.regime_score[j]) else np.nan,
            "htf_agree": float(np.mean([side * v for v in htf])) if htf else np.nan,
            "btc_tech": side * float(ctx.btc_tech[j]) if np.isfinite(ctx.btc_tech[j]) else np.nan,
            "vol_state": float(ctx.vol_state[j]) if np.isfinite(ctx.vol_state[j]) else np.nan,
            "stop_pct": stop}


def composite(rows: list[dict[str, Any]], spec: dict[str, Any]) -> np.ndarray:
    s = np.zeros(len(rows))
    for f, (mu, sd, sign) in spec.items():
        v = np.array([r["f"][f] for r in rows], float)
        z = (v - mu) / sd if sd > 0 else np.zeros(len(v))
        s += sign * np.nan_to_num(z, nan=0.0)
    return s


def run(db_url: str, budget_s: float, symbols: list[str] | None = None, tfs: list[str] | None = None) -> dict[str, Any]:
    from . import research_engine as RE
    from . import research_v213 as V
    from .db import Database
    from .ml import series_policy as SP
    from .services.runtime import Runtime

    class _Prov:
        name = "binance"

    db = Database(db_url)
    rt = Runtime(db, _Prov())
    ex = db.one("SELECT exchange, COUNT(*) AS n FROM market_data GROUP BY exchange ORDER BY n DESC LIMIT 1")
    if ex:
        _Prov.name = ex["exchange"]
    t0 = time.time()
    syms = symbols or [r["symbol"] for r in db.query("SELECT DISTINCT symbol FROM model_versions WHERE active = 1 ORDER BY symbol")]
    news = RE._news_fn(rt.db)
    frames: dict = {}
    rows: dict[str, list[dict[str, Any]]] = {"tune": [], "test": []}
    skipped: list[str] = []
    for s, tf in [(s, tf) for tf in RE.TF_ORDER if tf in (tfs or MODEL_TIMEFRAMES) for s in syms]:
        if time.time() > t0 + budget_s:
            skipped.append(f"{s} {tf}: time budget")
            continue
        try:
            b = RE.build(rt, s, tf, frames)
        except Exception as exc:
            skipped.append(f"{s} {tf}: {type(exc).__name__}")
            continue
        if b is None:
            skipped.append(f"{s} {tf}: no model / too few out-of-sample bars")
            continue
        ctx, paths = b
        tune, test, _ = RE._split(ctx)
        if tune.sum() < 150 or test.sum() < 30:
            skipped.append(f"{s} {tf}: span too short to split")
            continue
        d = SP.decide(ctx, tune, require_edge=False)
        for part, mask in (("tune", tune), ("test", test)):
            tr = V._with_funding(ctx, d, SP.run_series(ctx, paths, mask, d, entry_mode="old", news=news))
            for t in tr:
                rows[part].append({"r": float(t["r"]), "ts": int(t["ts"]), "tf": tf, "f": features_of(ctx, d, t["j"])})
        log.info("%s %s: done", s, tf)

    tune, test = rows["tune"], rows["test"]
    rt_, rs_ = np.array([x["r"] for x in tune]), np.array([x["r"] for x in test])
    feat = {}
    spec = {}
    for f in FEATURES:
        a = np.array([x["f"][f] for x in tune], float)
        b = np.array([x["f"][f] for x in test], float)
        rho_t, rho_s = spearman(a, rt_), spearman(b, rs_)
        feat[f] = {"rho_tune": None if rho_t is None else round(rho_t, 4), "rho_test": None if rho_s is None else round(rho_s, 4),
                   "stable": bool(rho_t is not None and rho_s is not None and np.sign(rho_t) == np.sign(rho_s) and abs(rho_s) >= MIN_RHO)}
        if rho_t is not None and abs(rho_t) >= MIN_RHO:
            m = np.isfinite(a)
            spec[f] = (float(np.mean(a[m])), float(np.std(a[m])), float(np.sign(rho_t)))
    out: dict[str, Any] = {"method": __doc__.strip(), "trades": {"tune": len(tune), "test": len(test)}, "features": feat,
                           "composite_uses": {f: v[2] for f, v in spec.items()}}

    def evaluate(part_rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not part_rows or not spec:
            return {"n": len(part_rows)}
        sc = composite(part_rows, spec)
        r = np.array([x["r"] for x in part_rows])
        q = np.quantile(sc, [0.2, 0.4, 0.6, 0.8])
        qi = np.searchsorted(q, sc, side="right")
        res = {"rho": None if spearman(sc, r) is None else round(spearman(sc, r), 4),
               "quintiles": [{"q": i + 1, **_stats(list(r[qi == i]))} for i in range(5)],
               "all": _stats(list(r)), "top40": _stats(list(r[qi >= 3])), "bottom60": _stats(list(r[qi < 3]))}
        by_tf = {}
        for tf in MODEL_TIMEFRAMES:
            m = np.array([x["tf"] == tf for x in part_rows])
            if m.sum() >= 30:
                by_tf[tf] = {"all": _stats(list(r[m])), "top40": _stats(list(r[m & (qi >= 3)])), "rho": spearman(sc[m], r[m])}
        res["by_tf"] = by_tf
        # daily portfolio: each UTC day only the top-3 ranked calls vs every call
        days: dict[int, list[int]] = defaultdict(list)
        for i, x in enumerate(part_rows):
            days[x["ts"] // 86_400_000].append(i)
        top = [i for idx in days.values() for i in sorted(idx, key=lambda i: -sc[i])[:3]]
        res["daily_top3"] = _stats([float(r[i]) for i in sorted(top, key=lambda i: part_rows[i]["ts"])])
        return res

    out["tune"] = evaluate(tune)
    out["test"] = evaluate(test)
    te = out["test"]
    if te.get("quintiles"):
        q5, q1, allr = te["quintiles"][4].get("avg_r"), te["quintiles"][0].get("avg_r"), te["all"].get("avg_r")
        works = bool(q5 is not None and q1 is not None and allr is not None and q5 > allr and q5 > q1 and (te["rho"] or 0) > 0.02)
        out["verdict"] = ("the ranking separates better calls from worse on unseen data" if works
                          else "the ranking does not reliably separate better calls on unseen data")
        out["ranking_works"] = works
    out.update({"skipped": skipped, "seconds": round(time.time() - t0, 1),
                "costs": {"round_trip_pct": settings.research_cost_pct, "funding": "0.01% per 8 h (longs pay), over the hold"}})
    return out
