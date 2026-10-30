"""`python -m app.research engine`: proof of the v2.6 accuracy upgrades on the restored engine state (read-only).

For every coin / timeframe with an active model, the model's own walk-forward OUT-OF-SAMPLE predictions (bundle["oos"],
up to 6000 bars, never fitted on the bars they describe) are turned into the calls the live pipeline would have made
(series_policy.decide - same signal, grading, bigger-trend, plan and cost rules) and each call is simulated with the
record's rules (50/25/25, break-even after TP1, TP1 after TP2, stop first in a candle, 30-bar horizon) on 15m candles,
after RESEARCH_COST_PCT round-trip costs, one call at a time per series with the re-entry cooldown.

Time split, per series: the first 70 % of its out-of-sample span chooses every threshold / option (and is the only
reference for the directional policy and confidence); the last 30 % is the untouched test set. Pooled filters are
trained on tuning trades only. Each change is run alone against OLD and then all PROVEN changes together; a change is
"proven" when on the test set it raised expectancy without making max drawdown worse.

Budget: series are processed heaviest-last until the deadline; anything not reached is listed as skipped.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from .config import ENGINE_VERSION, MODEL_TIMEFRAMES, settings
from .data.base import tf_ms
from .ml import series_policy as SP, series_sim as S, trade_filter2 as TF2

log = logging.getLogger("research.engine")
TUNE_SHARE = 0.7
ENTRY_OPTIONS = [("old", 0.0), ("market", 0.0), ("confirm", 0.0), ("confirm", 0.1), ("confirm", 0.25),
                 ("pullback", 0.25), ("pullback", 0.5)]
STOP_OPTIONS = ["current", "struct"]
TF_ORDER = ["3d", "1d", "12h", "4h", "1h", "15m"]


def _news_fn(db) -> Any:
    try:
        rows = db.query("SELECT ts FROM econ_events WHERE impact = 'High' AND country = 'USD' ORDER BY ts")
    except Exception:
        return None
    ev = np.array([int(r["ts"]) for r in rows], np.int64)
    if not len(ev):
        return None
    from .services.news import AFTER_MS, BEFORE_MS

    def f(ts: int) -> bool:
        k = np.searchsorted(ev, ts - AFTER_MS)
        return bool(k < len(ev) and ev[k] <= ts + BEFORE_MS)
    return f


def _record_r(db, symbol: str, tf: str, before: int, cost: float) -> list[float]:
    """Closed live calls (record + shadow) of the series that closed before `before` (in R after costs)."""
    out = []
    for table in ("signals", "shadow_signals"):
        try:
            rows = db.query(f"SELECT entry, stop, return_pct, closed_at FROM {table} WHERE symbol = ? AND timeframe = ? AND side != 0 "
                            "AND return_pct IS NOT NULL AND status IN ('STOPPED','TP1','TP2','TP3','EXPIRED') AND closed_at < ?",
                            (symbol, tf, before))
        except Exception:
            continue
        for r in rows:
            rp = abs(r["entry"] - r["stop"]) / r["entry"] * 100 if r["entry"] and r["stop"] else 0
            if rp:
                out.append((r["return_pct"] - cost) / rp)
    return out


def _series_frames(rt, symbol: str, tf: str) -> dict[str, Any]:
    from .config import MTF_TIMEFRAMES
    from .features.dataset import InsufficientData
    out = {}
    for t in dict.fromkeys(MTF_TIMEFRAMES + [tf]):
        try:
            out[t] = rt.frame(symbol, t)
        except InsufficientData:
            pass
    return out


def build(rt, symbol: str, tf: str, cache: dict) -> tuple[Any, Any] | None:
    from .ml import trainer
    bundle = trainer.load_bundle(symbol, tf, rt.db)
    if bundle is None:
        return None
    frames = cache.get(symbol)
    if frames is None:
        frames = cache[symbol] = _series_frames(rt, symbol, tf)
    if tf not in frames:
        return None
    btc = cache.get("BTC/USDT", {}).get(tf) if symbol != "BTC/USDT" else frames.get(tf)
    if btc is None and symbol != "BTC/USDT":
        try:
            btc = rt.frame("BTC/USDT", tf)
        except Exception:
            btc = None
    ctx = SP.build_context(symbol, tf, bundle, frames, btc)
    if ctx is None or ctx.n < 200:
        return None
    paths = SP.Paths(rt.candles(symbol, "15m"), rt.candles(symbol, tf))
    return ctx, paths


def _split(ctx) -> tuple[np.ndarray, np.ndarray, int]:
    t0, t1 = int(ctx.ts[0]), int(ctx.ts[-1])
    cut = t0 + int((t1 - t0) * TUNE_SHARE)
    tune = ctx.ts < cut
    # the last tuning calls must have closed before the test begins: drop the horizon before the cut from the test start
    test = ctx.ts >= cut + SP.HORIZON_BARS * tf_ms(ctx.tf)
    return tune, test, cut


def _weeks(ctx, mask) -> float:
    ts = ctx.ts[mask]
    return max((int(ts[-1]) - int(ts[0])) / (7 * 86_400_000), 1e-9) if len(ts) > 1 else 1e-9


def evaluate(rt, symbols: list[str], tfs: list[str], deadline: float, cost: float) -> dict[str, Any]:
    news = _news_fn(rt.db)
    frames_cache: dict = {}
    series: dict[str, dict] = {}
    skipped: list[str] = []
    pool: dict[str, dict[str, list]] = {}            # per timeframe: filter training rows from tuning trades
    order = [(s, tf) for tf in TF_ORDER if tf in tfs for s in symbols]
    for s, tf in order:
        if time.time() > deadline:
            skipped.append(f"{s} {tf}")
            continue
        t0 = time.time()
        try:
            b = build(rt, s, tf, frames_cache)
        except Exception as exc:
            log.warning("build %s %s: %s", s, tf, exc)
            skipped.append(f"{s} {tf}: {type(exc).__name__}")
            continue
        if b is None:
            skipped.append(f"{s} {tf}: no model / too few out-of-sample bars")
            continue
        ctx, paths = b
        tune, test, cut = _split(ctx)
        if tune.sum() < 150 or test.sum() < 30:
            skipped.append(f"{s} {tf}: span too short to split")
            continue
        ref = tune                                           # directional policy / confidence: tuning outcomes only
        base = SP.decide(ctx, ref)
        # ---- tuning-side choices -------------------------------------------------------------------------------
        old_tune = SP.run_series(ctx, paths, tune, base, news=news)
        rec_tune = _record_r(rt.db, s, tf, cut, cost)
        gate = S.gate_decision([t["r"] for t in old_tune] + rec_tune, settings.series_gate_min_n, settings.series_gate_q)
        conf = SP.choose_conf(ctx, paths, tune, ref, max(10, settings.series_gate_min_n // 2), news=news)
        dec_conf = SP.decide(ctx, ref, conf_b=conf["conf_b"] if conf["conf_b"] is not None else settings.series_conf_default)
        struct = SP.decide(ctx, ref, stop_mode="struct")
        entry_tune = {}
        cands_by_entry = {}
        for mode, k in ENTRY_OPTIONS:
            cands = SP.candidates(ctx, paths, tune | test, base, entry_mode=mode, k=k, news=news)
            cands_by_entry[(mode, k)] = cands
            tr = SP.taken(ctx, [c for c in cands if tune[c["j"]]])
            entry_tune[f"{mode}:{k}"] = [t["r"] for t in tr]
        # filter rows (tuning trades of the OLD pipeline, plus every candidate call - the filter learns all calls)
        cands_old = cands_by_entry[("old", 0.0)]
        P = pool.setdefault(tf, {"F": [], "R": [], "ts": [], "test": []})
        for c in cands_old:
            if c["filled"] and tune[c["j"]] and c["closed_ts"] < cut:
                P["F"].append(TF2.features(ctx, base, c["j"]))
                P["R"].append(c["r"])
                P["ts"].append(c["ts"])
        series[f"{s} {tf}"] = {"ctx": ctx, "paths": paths, "tune": tune, "test": test, "cut": cut, "base": base,
                               "gate": gate, "conf": conf, "dec_conf": dec_conf, "struct": struct, "entry_tune": entry_tune,
                               "cands": cands_by_entry, "secs": round(time.time() - t0, 1)}
        log.info("%s %s: %d oos bars, %d tuning trades, %.1fs", s, tf, ctx.n, len(old_tune), time.time() - t0)
    # ---- entry rule per timeframe, chosen on tuning trades pooled over coins ---------------------------------------
    entry_choice = {}
    for tf in tfs:
        rows = [v for k, v in series.items() if k.endswith(f" {tf}")]
        best, table = None, {}
        for mode, k in ENTRY_OPTIONS:
            r = sum((v["entry_tune"][f"{mode}:{k}"] for v in rows), [])
            table[f"{mode}:{k}"] = {"n": len(r), "mean_r": float(np.mean(r)) if r else None,
                                    "lb80": S.bootstrap_lb(r, 0.8) if len(r) >= 30 else None}
        old = table.get("old:0.0", {})
        cand = [(k, v) for k, v in table.items() if v["lb80"] is not None and v["n"] >= 0.3 * max(old.get("n") or 0, 1)]
        if cand:
            best = max(cand, key=lambda kv: kv[1]["lb80"])[0]
        entry_choice[tf] = {"chosen": best or "old:0.0", "table": table}
    # ---- pooled trade filter per timeframe (trained on tuning trades only) ------------------------------------------
    filters = {}
    for tf, P in pool.items():
        f = TF2.train(np.array(P["F"]) if P["F"] else np.zeros((0, len(TF2.FEATURES))), np.array(P["R"]), np.array(P["ts"]))
        filters[tf] = f
    # ---- test-set runs ---------------------------------------------------------------------------------------------
    variants = ["old", "gate", "conf", "entry", "struct", "filter"]
    results: dict[str, dict[str, list]] = {v: {} for v in variants}
    weeks: dict[str, float] = {}
    for key_, v in series.items():
        ctx, paths, test, base = v["ctx"], v["paths"], v["test"], v["base"]
        tf = ctx.tf
        weeks[key_] = _weeks(ctx, test)
        old = SP.taken(ctx, [c for c in v["cands"][("old", 0.0)] if test[c["j"]]])
        results["old"][key_] = old
        results["gate"][key_] = [] if v["gate"]["blocked"] else old
        results["conf"][key_] = SP.run_series(ctx, paths, test, v["dec_conf"], news=news)
        mode, k = entry_choice[tf]["chosen"].split(":")
        results["entry"][key_] = SP.taken(ctx, [c for c in v["cands"][(mode, float(k))] if test[c["j"]]])
        results["struct"][key_] = SP.run_series(ctx, paths, test, v["struct"], news=news)
        f = filters.get(tf)
        if f and f.get("enabled"):
            keep = lambda c, f=f, ctx=ctx, base=base: TF2.score(f, TF2.features(ctx, base, c["j"])) >= f["threshold"]  # noqa: E731
            results["filter"][key_] = SP.taken(ctx, [c for c in v["cands"][("old", 0.0)] if test[c["j"]]], keep)
        else:
            results["filter"][key_] = old
    out_tables = {name: _table(results[name], weeks) for name in variants}
    base_all = out_tables["old"]["overall"]
    proven = {}
    for name in variants[1:]:
        o = out_tables[name]["overall"]
        ok = bool(o["n"] and base_all["n"] and o["expectancy_r"] is not None and base_all["expectancy_r"] is not None
                  and o["expectancy_r"] > base_all["expectancy_r"] and o["max_drawdown_r"] <= base_all["max_drawdown_r"] + 1e-9)
        proven[name] = ok
    # ---- all proven changes together ----------------------------------------------------------------------------------
    combined: dict[str, list] = {}
    for key_, v in series.items():
        ctx, paths, test = v["ctx"], v["paths"], v["test"]
        if proven.get("gate") and v["gate"]["blocked"]:
            combined[key_] = []
            continue
        cb = None
        if proven.get("conf"):
            cb = v["conf"]["conf_b"] if v["conf"]["conf_b"] is not None else settings.series_conf_default
        d = SP.decide(ctx, v["tune"], conf_b=cb, stop_mode="struct" if proven.get("struct") else "current")
        mode, k = (entry_choice[ctx.tf]["chosen"].split(":") if proven.get("entry") else ("old", "0"))
        cands = SP.candidates(ctx, paths, test, d, entry_mode=mode, k=float(k), news=news)
        f = filters.get(ctx.tf) if proven.get("filter") else None
        keep = None
        if f and f.get("enabled"):
            keep = lambda c, f=f, ctx=ctx, d=d: TF2.score(f, TF2.features(ctx, d, c["j"])) >= f["threshold"]  # noqa: E731
        combined[key_] = SP.taken(ctx, cands, keep)
    out_tables["all_proven"] = _table(combined, weeks)
    return {
        "series": {k: {"oos_bars": int(v["ctx"].n), "tune_bars": int(v["tune"].sum()), "test_bars": int(v["test"].sum()),
                       "cut": v["cut"], "gate": v["gate"], "conf_b": v["conf"]["conf_b"], "conf_table": v["conf"]["table"],
                       "seconds": v["secs"]} for k, v in series.items()},
        "skipped": skipped, "entry_choice": entry_choice,
        "filters": {tf: {k: x for k, x in f.items() if k != "model"} for tf, f in filters.items()},
        "test": out_tables, "proven_on_test": proven,
    }


def _table(res: dict[str, list], weeks: dict[str, float]) -> dict[str, Any]:
    def block(keys):
        trades = sorted((t for k in keys for t in res.get(k, [])), key=lambda t: t["ts"])
        # trades per week: summed over the series' own test spans (all series run in parallel)
        wk = max((weeks[k] for k in keys), default=None) if keys else None
        return S.stats([t["r"] for t in trades], wk)
    keys = list(weeks)
    tfs = sorted({k.split(" ")[1] for k in keys}, key=lambda t: MODEL_TIMEFRAMES.index(t) if t in MODEL_TIMEFRAMES else 99)
    return {"overall": block(keys), "by_timeframe": {tf: block([k for k in keys if k.endswith(f" {tf}")]) for tf in tfs}}


def run(db_url: str, budget_s: float, cost: float, symbols: list[str] | None = None, tfs: list[str] | None = None) -> dict[str, Any]:
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
    body = evaluate(rt, syms, tfs or list(MODEL_TIMEFRAMES), t0 + budget_s, cost)
    body.update({"engine_version": ENGINE_VERSION, "cost_pct_round_trip": cost, "tune_share": TUNE_SHARE,
                 "symbols": syms, "seconds": round(time.time() - t0, 1),
                 "method": __doc__.strip().split("\n\n", 1)[1] if __doc__ else None,
                 "approximations": [
                     "model agreement per member is not stored out-of-sample: the agreement checks are treated as passed",
                     "no order book in history: the liquidity component is left out (as when the live book is missing)",
                     "targets use the fixed ladder 1R / 1.75R / 2.5R (live TP2 / TP3 are chosen in [1.25, 2] / [2, 3] R)",
                     "the historical base-rate validity check of the plan is not replayed",
                     "the safety switch and per-member auto-trade limits are not replayed (the same for every variant)"]})
    return body
