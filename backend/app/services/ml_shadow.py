"""V3.3 ML shadow monitoring (Stage 2 phase E). Reporting only: nothing here changes a call, a filter or a model.

Since V3.2 the per-model trade filter (v1), the pooled filter (filter2) and the runner model run in SHADOW: they score
every live call, record what they would have done, and do not block or change exits (analysis.filter_bypass /
runner_enforced; enforcement needs `validated` bundles AND the owner's switch). This report answers whether they would
have helped, on the real record:

* predictions      live forecasts logged per timeframe (last 30 days) and the shadow models' scored candles
                   (`filter_shadow_stats|<model>|<tf>`: rows, observed kept share vs the intended keep fraction)
* would-block      published calls a shadowed filter would have blocked (payload `filter_shadow`) and how they ended,
                   against the calls it let through (net R after costs, by timeframe and by market regime at publication)
* would-run        calls the runner model would have let run (payload `runner_shadow`) and how they ended under the
                   standard exits
* freshness        active model age per timeframe; add-on validation status from the bundle summaries
A shadow model is NOT shown as better or worse until enough calls closed (MIN_N); the figures carry n and a 95 %
interval. Model scores are never presented as win probabilities."""
from __future__ import annotations

import math
import time
from typing import Any

from ..db import loads

MIN_N = 30
DAY = 86_400_000
H = 3_600_000
MODELS = ("trade_filter", "trade_filter2", "runner_model")


def _stats(v: list[float]) -> dict[str, Any]:
    n = len(v)
    if not n:
        return {"n": 0}
    m = sum(v) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1)) if n > 1 else None
    se = sd / math.sqrt(n) if sd is not None else None
    return {"n": n, "avg_r": round(m, 3), "total_r": round(sum(v), 2), "win_rate": round(sum(1 for x in v if x > 0) / n, 3),
            "ci95_avg_r": [round(m - 1.96 * se, 3), round(m + 1.96 * se, 3)] if se is not None and n >= 10 else None,
            "enough": n >= MIN_N}


def _net_r(r: dict[str, Any]) -> float | None:
    from . import risk_shadow
    return risk_shadow._net_r(r)


def model_freshness(db: Any, now: int | None = None) -> dict[str, Any]:
    now = int(time.time() * 1000) if now is None else now
    rows = db.query("SELECT symbol, timeframe, created_at, summary FROM model_versions WHERE active = 1", ())
    by_tf: dict[str, list[float]] = {}
    addons: dict[str, dict[str, int]] = {m: {"enabled": 0, "validated": 0, "in_sample_threshold": 0, "unknown": 0}
                                         for m in ("trade_filter", "runner_model")}
    for r in rows:
        by_tf.setdefault(r["timeframe"], []).append((now - int(r["created_at"])) / H)
        summ = loads(r.get("summary"), {}) or {}
        a = summ.get("addons")
        for m in addons:
            x = (a or {}).get(m) if a else None
            if not x:
                addons[m]["unknown"] += 1
                continue
            if x.get("enabled"):
                addons[m]["enabled"] += 1
                if x.get("validated"):
                    addons[m]["validated"] += 1
                elif x.get("threshold_method") != "oof_embargo":
                    addons[m]["in_sample_threshold"] += 1
    ages = {tf: {"n": len(v), "median_h": round(sorted(v)[len(v) // 2], 1), "max_h": round(max(v), 1),
                 "older_than_48h": sum(1 for x in v if x > 48)} for tf, v in by_tf.items()}
    f2 = {}
    for tf in ages:
        s = db.get_setting(f"trade_filter2|{tf}", None) or {}
        f2[tf] = {k: s.get(k) for k in ("enabled", "validated", "threshold_method", "kept_share_unseen", "keep_fraction", "at")}
    return {"ages": ages, "addons": addons, "filter2": f2,
            "note": "'unknown' = trained before V3.3 (status recorded from the next nightly retrain)"}


def build(rt: Any, now: int | None = None) -> dict[str, Any]:
    """The ML shadow report over the public record (record_clause)."""
    from .. import views
    from . import analysis, tracking
    now = int(time.time() * 1000) if now is None else now
    db = rt.db
    rc, rp = views.record_clause(rt)
    rows = db.query(f"SELECT * FROM signals WHERE side != 0 AND status != 'INFO' AND {rc}", rp)
    closed_st = set(tracking.CLOSED_STATUSES)
    groups: dict[str, list[float]] = {"would_block": [], "allowed": [], "would_run": [], "standard": []}
    by_tf: dict[str, dict[str, list[float]]] = {}
    by_regime: dict[str, dict[str, list[float]]] = {}
    by_model: dict[str, list[float]] = {m: [] for m in MODELS}
    counts = {"calls": len(rows), "would_block": 0, "would_run": 0}
    for r in rows:
        p = loads(r.get("payload"), {}) or {}
        fs = p.get("filter_shadow") or []
        blocked = bool(fs) or bool(p.get("filter_bypassed"))
        runs = bool((p.get("runner_shadow") or {}).get("would_run"))
        counts["would_block"] += int(blocked)
        counts["would_run"] += int(runs)
        if r.get("status") not in closed_st or r.get("fill_status") == "NOT_FILLED":
            continue
        x = _net_r(r)
        if x is None:
            continue
        key = "would_block" if blocked else "allowed"
        groups[key].append(x)
        groups["would_run" if runs else "standard"].append(x)
        by_tf.setdefault(r["timeframe"], {"would_block": [], "allowed": []})[key].append(x)
        reg = ((p.get("risk_shadow") or {}).get("state")) or "unknown"
        by_regime.setdefault(reg, {"would_block": [], "allowed": []})[key].append(x)
        for f in fs:
            if f.get("filter") in by_model:
                by_model[f["filter"]].append(x)
    stats_tf = {tf: {k: _stats(v) for k, v in g.items()} for tf, g in sorted(by_tf.items())}
    stats_reg = {k: {kk: _stats(vv) for kk, vv in g.items()} for k, g in sorted(by_regime.items())}
    preds = {}
    try:
        for r in db.query("SELECT timeframe, COUNT(*) AS n FROM predictions WHERE created_at >= ? GROUP BY timeframe",
                          (now - 30 * DAY,)):
            preds[r["timeframe"]] = int(r["n"])
    except Exception:
        preds = {}
    kept = {}
    for m in MODELS:
        for tf in ("15m", "1h", "4h", "12h", "1d", "3d"):
            s = db.get_setting(f"filter_shadow_stats|{m}|{tf}", None)
            if s:
                kept[f"{m}|{tf}"] = {k: s.get(k) for k in ("n", "kept_share", "keep_fraction", "at")}
    wb, al = _stats(groups["would_block"]), _stats(groups["allowed"])
    verdict = "too few closed calls to judge"
    if wb.get("enough") and al.get("enough"):
        verdict = ("blocked calls did worse: the filters would have helped" if wb["avg_r"] < al["avg_r"]
                   else "blocked calls did as well or better: the filters would have cost R")
    return {
        "generated_at": now, "mode": {"trade_filter_enforce": analysis.FILTER_ENFORCE,
                                      "runner_enforce": analysis.RUNNER_ENFORCE},
        "counts": counts, "predictions_30d": preds, "shadow_scored": kept,
        "would_block": wb, "allowed": al, "would_run": _stats(groups["would_run"]), "standard": _stats(groups["standard"]),
        "by_filter": {m: _stats(v) for m, v in by_model.items()}, "by_tf": stats_tf, "by_regime": stats_reg,
        "verdict": verdict, "min_n": MIN_N, "freshness": model_freshness(db, now),
        "note": "Net R after the record's costs. Model scores are rankings, not win probabilities.",
    }
