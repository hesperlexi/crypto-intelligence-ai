"""`python -m app.research grades`: grade A only vs grades A + B vs paused, per timeframe (read-only research, 31 Oct 2026).

Owner question: instead of pausing 1d and 3d, open them for grade A only? For every timeframe (15m for reference, 1h,
4h, 12h, 1d, 3d) the models' walk-forward OUT-OF-SAMPLE calls are replayed through the live decision rules
(series_policy.decide - the live grading: A = technical tilt firm, the AI's side agreeing, margin clearing the proven
policy margin and directional confidence >= MIN_DIR_CONFIDENCE_A; B = AI-led / weaker; one higher timeframe against ->
A becomes B; per-member model agreement is not stored out-of-sample and is treated as passed), with the live entry rule
and trade filter per timeframe (chosen / trained on the tuning part), the record's exits (50 / 25 / 25 at 1R / 1.75R /
2.5R, break-even after TP1, TP1 after TP2), the live time limits (1h 200, 4h 100, others 30 candles; 15m also at its
demo-bot 250), RESEARCH_COST_PCT round-trip costs, one call at a time per series plus the re-entry cooldown.
"Paused" = no trades (0 R). Headline: the untouched last 30 % of each series (same split as research_engine); all-data
numbers too (partly in-sample: the A threshold's confidence is measured on the tuning part). Confidence: per-series
bootstrap, share of resamples with expectancy > 0 and share where A-only beats A + B (expectancy and total R).
"""
from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from .config import ENGINE_VERSION, settings
from .ml import series_sim as S
from . import research_horizon as H
from . import research_scalp15 as X
from .research_engine import TUNE_SHARE

log = logging.getLogger("research.grades")
TFS = ["15m", "1h", "4h", "12h", "1d", "3d"]
LIVE_HORIZON = {"1h": 200, "4h": 100}          # others 30 (tracking.HORIZON_BARS; 15m also run at 250)
GRADES = {"A_only": ("A",), "A_plus_B": ("A", "B")}


def horizons(tf: str) -> list[int]:
    return [250, 30] if tf == "15m" else [LIVE_HORIZON.get(tf, 30)]


def boot(res: dict[str, dict[str, list]], cost: float, n_boot: int = 2000, seed: int = 0) -> dict[str, Any]:
    """res: variant -> series -> trades. Share of series resamples with expectancy > 0, and A_only vs A_plus_B."""
    keys = sorted({k for v in res.values() for k in v})
    if not keys:
        return {}
    rng = np.random.default_rng(seed)
    R = {v: {k: np.array([X.net_r(t, cost) for t in res[v].get(k, []) if not t.get("open")], float) for k in keys} for v in res}
    pos = {v: [] for v in res}
    means = {v: [] for v in res}
    better_e, better_t = [], []
    for _ in range(n_boot):
        d = rng.integers(0, len(keys), len(keys))
        cat = {v: np.concatenate([R[v][keys[i]] for i in d]) for v in res}
        for v in res:
            if len(cat[v]):
                pos[v].append(cat[v].mean() > 0)
                means[v].append(cat[v].mean())
        a, b = cat.get("A_only"), cat.get("A_plus_B")
        if a is not None and b is not None and len(b):
            better_t.append(a.sum() > b.sum())
            if len(a):
                better_e.append(a.mean() > b.mean())
    out = {v: {"share_expectancy_above_0": float(np.mean(pos[v])) if pos[v] else None,
               "expectancy_90ci": [float(np.quantile(means[v], 0.05)), float(np.quantile(means[v], 0.95))] if means[v] else None}
           for v in res}
    out["A_only_vs_A_plus_B"] = {"share_better_expectancy": float(np.mean(better_e)) if better_e else None,
                                 "share_better_total_r": float(np.mean(better_t)) if better_t else None}
    return out


def evaluate(rt, symbols: list[str], t_start: float, budget_s: float, cost: float) -> dict[str, Any]:
    prep = H.prepare(rt, symbols, TFS, t_start + 0.5 * budget_s)
    series, skipped = prep["series"], prep["skipped"]
    runs: dict[str, dict] = {}          # f"{tf} h{h}" -> scope -> variant -> series -> trades
    weeks: dict[str, dict[str, float]] = {}
    counts: dict[str, dict] = {}
    for key_, s in series.items():
        if time.time() > t_start + budget_s:
            skipped.append(f"{key_}: time budget (grade runs)")
            continue
        ctx, paths, d = s["ctx"], s["paths"], s["d"]
        tf = ctx.tf
        mode, k, keep = H.entry_and_keep(prep, s)
        allrows = np.ones(ctx.n, bool)
        for h in horizons(tf):
            rk = f"{tf} h{h}"
            R = runs.setdefault(rk, {"test": {v: {} for v in GRADES}, "all": {v: {} for v in GRADES}})
            for vn, gs in GRADES.items():
                c = X.candidates_x(ctx, paths, allrows, d, mode, k, prep["news"], h, S.TP_LADDER, S.TP_SPLIT, gs)
                for sc, mask in (("test", s["test"]), ("all", allrows)):
                    R[sc][vn][key_] = H.taken_h(ctx, [x for x in c if mask[x["j"]]], keep)
        for sc, mask in (("test", s["test"]), ("all", allrows)):
            ts_m = ctx.ts[mask]
            w = max((int(ts_m[-1]) - int(ts_m[0])) / (7 * 86_400_000), 1e-9) if len(ts_m) > 1 else 1e-9
            weeks.setdefault(tf, {}).setdefault(sc, 0.0)
            weeks[tf][sc] = max(weeks[tf][sc], w)
            sel = mask & d["trade"]
            cc = counts.setdefault(tf, {}).setdefault(sc, {"A": 0, "B": 0, "series": 0})
            cc["A"] += int((sel & (d["grade"] == "A")).sum())
            cc["B"] += int((sel & (d["grade"] == "B")).sum())
            cc["series"] += 1
    out: dict[str, Any] = {}
    for rk, R in runs.items():
        tf = rk.split(" ")[0]
        out[rk] = {}
        for sc in ("test", "all"):
            wk = weeks[tf][sc]
            st = {vn: X.stats_x([t for tr in R[sc][vn].values() for t in tr], cost, wk) for vn in GRADES}
            st["paused"] = {"n": 0, "trades_per_week": 0.0, "expectancy_r": 0.0, "total_r": 0.0, "max_drawdown_r": 0.0}
            out[rk][sc] = {"weeks": wk, "calls_by_grade_before_one_at_a_time": counts[tf][sc], "variants": st,
                           "bootstrap": boot(R[sc], cost)}
    return {"results": out, "series": {k: {"oos_bars": int(v["ctx"].n), "test_bars": int(v["test"].sum())}
                                       for k, v in series.items()},
            "skipped": skipped, "entry_choice": prep["entry_choice"],
            "filters": {tf: {k: x for k, x in f.items() if k not in ("model", "features")} for tf, f in prep["filters"].items()}}


def headline(body: dict[str, Any]) -> dict[str, Any]:
    keys = ("n", "trades_per_week", "win_rate", "expectancy_r", "total_r", "profit_factor", "max_drawdown_r",
            "expired_share", "open_at_data_end")
    rows = {}
    for rk, r in body["results"].items():
        t = r["test"]
        rows[rk] = {vn: {**{k: t["variants"][vn].get(k) for k in keys},
                         "boot_share_exp_gt_0": (t["bootstrap"].get(vn) or {}).get("share_expectancy_above_0")}
                    for vn in GRADES}
        rows[rk]["A_only_vs_A_plus_B"] = t["bootstrap"].get("A_only_vs_A_plus_B")
        rows[rk]["calls"] = t["calls_by_grade_before_one_at_a_time"]
    return rows


def run(db_url: str, budget_s: float, cost: float, symbols: list[str] | None = None) -> dict[str, Any]:
    from .db import Database
    from .services.runtime import Runtime

    class _Prov:
        name = "binance"

    db = Database(db_url)
    rt = Runtime(db, _Prov())
    ex = db.one("SELECT exchange, COUNT(*) AS n FROM market_data GROUP BY exchange ORDER BY n DESC LIMIT 1")
    if ex:
        _Prov.name = ex["exchange"]
    syms = symbols or [r["symbol"] for r in db.query("SELECT DISTINCT symbol FROM model_versions WHERE active = 1 ORDER BY symbol")]
    t0 = time.time()
    body = evaluate(rt, syms, t0, budget_s, cost)
    body["headline_test"] = headline(body)
    body.update({"engine_version": ENGINE_VERSION, "cost_pct_round_trip": cost, "tune_share": TUNE_SHARE, "symbols": syms,
                 "settings": {"entry_rules": settings.entry_rules, "trade_filter2": settings.trade_filter2,
                              "min_dir_confidence_a": settings.min_dir_confidence_a,
                              "min_dir_confidence_b": settings.min_dir_confidence_b},
                 "seconds": round(time.time() - t0, 1),
                 "method": __doc__.strip().split("\n\n", 1)[1] if __doc__ else None,
                 "approximations": [
                     "grading = series_policy.decide replay of the live logic; per-member model agreement treated as "
                     "passed, no order book; directional confidence measured against the tuning part",
                     "TP2 / TP3 on the fixed ladder 1.75R / 2.5R (live picks them from history)",
                     "entry rule and trade filter chosen / trained with the 30-candle current rules on the tuning part",
                     "plan base-rate check and safety switch not replayed"]})
    return body
