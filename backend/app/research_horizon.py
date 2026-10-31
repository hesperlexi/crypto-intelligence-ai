"""`python -m app.research horizon`: how the trade time limit changes the results (read-only research).

Today a call is followed for SP.HORIZON_BARS = 30 candles of its timeframe and then closes at market ("EXPIRED").
This replays the same calls as `python -m app.research engine` - the models' walk-forward OUT-OF-SAMPLE predictions
turned into calls by the live decision rules (series_policy.decide) with the CURRENT settings (ENTRY_RULES on: the
entry rule per timeframe chosen on the tuning part as the nightly job does; TRADE_FILTER2 on: pooled filter per
timeframe trained on tuning trades, used only where its own exam passes; SERIES_GATE / SERIES_CONF / STRUCT_STOPS off;
15m paused, so it is left out unless asked for) - simulated with the record's exit rules and RESEARCH_COST_PCT
round-trip costs, one call at a time per series with the re-entry cooldown, under several horizons: 30, 60, 90 candles
and no limit (followed to the end of the stored candles).

Each call keeps the candle source the 30-candle run uses (15m when they cover the first 30 candles, else the
timeframe's own candles), so a longer horizon only adds candles after the old limit: every difference comes from the
time limit, not from a change of candle resolution. A call still open at the end of the stored candles is not scored;
it is counted (`open_at_data_end`) and, in the sequential pipeline, blocks its series until the end (as live).

Two views per horizon:
  (a) identical entries: exactly the calls the 30-candle pipeline took, each followed under the longer horizon;
  (b) sequential pipeline: a longer trade blocks the series longer (one call at a time), so the set of calls changes.
Headline: the untouched last 30 % of each series (same split as research_engine); all-data numbers are given too
(the entry rule and filter were chosen on the first 70 %, so all-data is partly in-sample for those choices).
Confidence: per-series bootstrap (series resampled with replacement), share of resamples where a horizon's expectancy
(and total R) beats the 30-candle one.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

import numpy as np

from .config import ENGINE_VERSION, settings
from .data.base import tf_ms
from .ml import series_policy as SP, series_sim as S, trade_filter2 as TF2
from .research_engine import ENTRY_OPTIONS, TUNE_SHARE, _news_fn, _split, build

log = logging.getLogger("research.horizon")
HORIZONS = (30, 60, 90, 0)                 # 0 = no limit
DEFAULT_TFS = ["1h", "4h", "12h", "1d", "3d"]
TF_ORDER = ["3d", "1d", "12h", "4h", "1h", "15m"]
OPEN = 2 ** 62                              # closed_ts of a call still open at the end of the data


def hname(h: int) -> str:
    return f"h{h}" if h else "no_limit"


# ---- simulation with a horizon ------------------------------------------------------------------------------------------

def simulate_h(ctx: SP.Context, paths: SP.Paths, j: int, side: int, pl: dict[str, Any], entry_mode: str = "old",
               k: float = 0.0, cost_pct: float | None = None, horizon: int = SP.HORIZON_BARS) -> dict[str, Any] | None:
    """series_policy.simulate with a horizon in candles (0 = no limit). horizon = 30 gives exactly SP.simulate's result
    (plus `open`, `filled_ts`, `src`). Returns None when there are no candles; {"filled": True, "open": True, ...} when
    the call is still open at the end of the stored candles."""
    step = tf_ms(ctx.tf)
    start = int(ctx.decision_ts[j])
    base = paths.window(start, start + SP.HORIZON_BARS * step)     # candle source fixed by the 30-candle window
    if base is None:
        return None
    ms = base[4]
    a = paths._a["p15" if ms else "own"]
    end = start + horizon * step if horizon else None
    i = int(np.searchsorted(a[0], start))
    e = int(np.searchsorted(a[0], end)) if end is not None else len(a[0])
    if e <= i:
        return None
    ts, hi, lo, cl = a[0][i:e], a[1][i:e], a[2][i:e], a[3][i:e]
    bar = ms or step
    window = max(1, int(round(settings.fill_window_bars * step / bar)))
    f = S.fill(entry_mode, side, float(ctx.close[j]), float(ctx.atr[j]), pl, hi, lo, cl, window, k)
    if f is None:
        return {"filled": False}
    i0, entry, first_is_fill = f
    stop = pl["stop"]
    if side * (entry - stop) <= 0:
        return {"filled": False}
    tps = S.ladder(side, entry, stop)
    complete = end is not None and int(ts[-1]) + bar >= end
    out = S.follow(side, entry, stop, tps, hi[i0:], lo[i0:], cl[i0:], first_is_fill=first_is_fill, complete=complete)
    if out is None:
        return {"filled": True, "open": True, "entry": entry, "filled_ts": int(ts[i0]), "src": "15m" if ms else "own"}
    c = settings.research_cost_pct if cost_pct is None else cost_pct
    return {"filled": True, "open": False, "r": out.net_r(c), "status": out.status, "exit": out.exit_reason,
            "risk_pct": out.risk_pct, "closed_ts": int(ts[i0 + out.exit_idx]) + bar, "entry": entry,
            "filled_ts": int(ts[i0]), "src": "15m" if ms else "own"}


def candidates_h(ctx, paths, mask, decision, entry_mode="old", k=0.0, cost_pct=None, news=None,
                 horizon: int = SP.HORIZON_BARS) -> list[dict[str, Any]]:
    """series_policy.candidates with a horizon. Unlike the 30-candle research (which skips a call that is unfinished at
    the end of the data), an open call is kept with closed_ts = OPEN so it blocks its series to the end."""
    res = []
    for j in np.flatnonzero(mask & decision["trade"]):
        if news is not None and news(int(ctx.decision_ts[j])):
            continue
        pl = decision["plan"][j]
        mode = entry_mode
        if mode == "old" and decision["decision"][j] != "BUY ON PULLBACK":
            mode = "market"
        r = simulate_h(ctx, paths, int(j), int(decision["side"][j]), pl, mode, k, cost_pct, horizon)
        if r is None:
            continue
        if not r["filled"]:
            r = {"filled": False, "closed_ts": int(ctx.decision_ts[j]) + settings.fill_window_bars * tf_ms(ctx.tf)}
        elif r["open"]:
            r["closed_ts"] = OPEN
        res.append({"j": int(j), "ts": int(ctx.decision_ts[j]), **r})
    return res


def taken_h(ctx, cands, keep: Callable[[dict], bool] | None = None) -> list[dict[str, Any]]:
    """series_policy.taken, but open calls are returned too (flag `open`); unfilled pullbacks are dropped."""
    cs = [c for c in cands if keep is None or keep(c)]
    if not cs:
        return []
    idx = SP.take(np.array([c["ts"] for c in cs], np.int64), np.array([c["closed_ts"] for c in cs], np.int64), tf_ms(ctx.tf))
    return [cs[i] for i in idx if cs[i]["filled"]]


# ---- statistics ----------------------------------------------------------------------------------------------------------

def block_stats(trades: list[dict[str, Any]], step_of: Callable[[dict], int], weeks: float | None) -> dict[str, Any]:
    scored = sorted((t for t in trades if not t.get("open")), key=lambda t: t["ts"])
    st = S.stats([t["r"] for t in scored], weeks)
    n = len(scored)
    if n:
        hold = np.array([(t["closed_ts"] - t["filled_ts"]) / step_of(t) for t in scored], float)
        days = np.array([(t["closed_ts"] - t["filled_ts"]) / 86_400_000 for t in scored], float)
        st.update({"expired_share": float(np.mean([t["exit"] == "expired" for t in scored])),
                   "hold_candles_median": float(np.median(hold)), "hold_candles_p90": float(np.quantile(hold, 0.9)),
                   "hold_days_median": float(np.median(days)), "hold_days_p90": float(np.quantile(days, 0.9)),
                   "status": {s: int(sum(t["status"] == s for t in scored)) for s in ("STOPPED", "TP1", "TP2", "TP3", "EXPIRED")},
                   "exits": {x: int(sum(t["exit"] == x for t in scored)) for x in ("stop", "break_even", "trail", "tp3", "expired")},
                   "on_15m_candles": float(np.mean([t.get("src") == "15m" for t in scored]))})
    else:
        st.update({"expired_share": None, "hold_candles_median": None, "hold_candles_p90": None,
                   "hold_days_median": None, "hold_days_p90": None})
    st["open_at_data_end"] = int(sum(1 for t in trades if t.get("open")))
    return st


def table(res: dict[str, list], weeks: dict[str, float]) -> dict[str, Any]:
    steps = {k: tf_ms(k.split(" ")[1]) for k in res}

    def blk(keys):
        trades = [dict(t, _k=k) for k in keys for t in res.get(k, [])]
        wk = max((weeks[k] for k in keys), default=None) if keys else None
        return block_stats(trades, lambda t: steps[t["_k"]], wk)
    keys = list(res)
    tfs = [t for t in ["15m", "1h", "4h", "12h", "1d", "3d"] if any(k.endswith(f" {t}") for k in keys)]
    by = {tf: blk([k for k in keys if k.endswith(f" {tf}")]) for tf in tfs}
    overall = blk(keys)
    overall["trades_per_week"] = float(sum(b["trades_per_week"] or 0.0 for b in by.values()))
    return {"overall": overall, "by_timeframe": by}


def bootstrap_vs(res: dict[str, dict[str, list]], base: str, n_boot: int = 1000, seed: int = 0,
                 tf: str | None = None) -> dict[str, Any]:
    """Per-series bootstrap: share of resamples where each variant's expectancy / total R beats `base`."""
    keys = [k for k in res[base] if tf is None or k.endswith(f" {tf}")]
    out: dict[str, Any] = {}
    if not keys:
        return out
    rng = np.random.default_rng(seed)
    R = {v: {k: np.array([t["r"] for t in res[v].get(k, []) if not t.get("open")], float) for k in keys} for v in res}
    draws = [rng.integers(0, len(keys), len(keys)) for _ in range(n_boot)]
    for v in res:
        if v == base:
            continue
        de, dt = [], []
        for d in draws:
            ks = [keys[i] for i in d]
            a = np.concatenate([R[base][k] for k in ks]) if ks else np.array([])
            b = np.concatenate([R[v][k] for k in ks]) if ks else np.array([])
            if len(a) and len(b):
                de.append(b.mean() - a.mean())
                dt.append(b.sum() - a.sum())
        de, dt = np.array(de), np.array(dt)
        out[v] = {"mean_gain_expectancy_r": float(de.mean()) if len(de) else None,
                  "share_better_expectancy": float((de > 0).mean()) if len(de) else None,
                  "expectancy_gain_90ci": [float(np.quantile(de, 0.05)), float(np.quantile(de, 0.95))] if len(de) else None,
                  "mean_gain_total_r": float(dt.mean()) if len(dt) else None,
                  "share_better_total_r": float((dt > 0).mean()) if len(dt) else None}
    return out


# ---- the research ----------------------------------------------------------------------------------------------------------

def _choose_entry(series: dict, tfs: list[str]) -> dict[str, dict]:
    """research_engine's entry choice per timeframe (early 70 % / late 30 % of the tuning trades)."""
    out = {}
    for tf in tfs:
        rows = [v for k, v in series.items() if k.endswith(f" {tf}")]
        tbl = {}
        for mode, k in ENTRY_OPTIONS:
            e = sum((v["entry_tune"][f"{mode}:{k}"]["early"] for v in rows), [])
            l_ = sum((v["entry_tune"][f"{mode}:{k}"]["late"] for v in rows), [])
            tbl[f"{mode}:{k}"] = {"n_early": len(e), "mean_early": float(np.mean(e)) if e else None,
                                  "lb80_early": S.bootstrap_lb(e, 0.8) if len(e) >= 30 else None,
                                  "n_late": len(l_), "mean_late": float(np.mean(l_)) if l_ else None}
        old = tbl["old:0.0"]
        cand = [(k, v) for k, v in tbl.items() if v["lb80_early"] is not None and v["n_early"] >= 0.3 * max(old["n_early"], 1)]
        best = max(cand, key=lambda kv: kv[1]["lb80_early"])[0] if cand else "old:0.0"
        b = tbl[best]
        confirmed = bool(best != "old:0.0" and b["mean_late"] is not None and old["mean_late"] is not None
                         and b["mean_late"] > old["mean_late"])
        out[tf] = {"chosen": best if confirmed else "old:0.0", "best_early": best, "confirmed_late": confirmed}
    return out


def evaluate(rt, symbols: list[str], tfs: list[str], t_start: float, budget_s: float, cost: float,
             horizons: tuple[int, ...] = HORIZONS) -> dict[str, Any]:
    news = _news_fn(rt.db)
    frames_cache: dict = {}
    series: dict[str, dict] = {}
    skipped: list[str] = []
    pool: dict[str, dict[str, list]] = {}
    deadline1 = t_start + 0.55 * budget_s          # phase 1 (build + tuning); the rest is for the horizon runs
    for tf in [t for t in TF_ORDER if t in tfs]:
        for s in symbols:
            if time.time() > deadline1:
                skipped.append(f"{s} {tf}: time budget")
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
            d = SP.decide(ctx, tune)          # current settings: default confidence, current stops, no series gate
            entry_tune = {}
            t_early = int(ctx.ts[0]) + int((cut - int(ctx.ts[0])) * 0.7)
            cands_old = None
            for mode, k in ENTRY_OPTIONS:
                cands = SP.candidates(ctx, paths, tune, d, entry_mode=mode, k=k, news=news)
                if (mode, k) == ("old", 0.0):
                    cands_old = cands
                tr = SP.taken(ctx, cands)
                entry_tune[f"{mode}:{k}"] = {"early": [t["r"] for t in tr if t["ts"] < t_early],
                                             "late": [t["r"] for t in tr if t["ts"] >= t_early]}
            P = pool.setdefault(tf, {"F": [], "R": [], "ts": []})
            for c in cands_old or []:
                if c["filled"] and c["closed_ts"] < cut:
                    P["F"].append(TF2.features(ctx, d, c["j"]))
                    P["R"].append(c["r"])
                    P["ts"].append(c["ts"])
            series[f"{s} {tf}"] = {"ctx": ctx, "paths": paths, "tune": tune, "test": test, "cut": cut, "d": d,
                                   "entry_tune": entry_tune, "secs": round(time.time() - t0, 1)}
            log.info("%s %s: %d oos bars, %.1fs", s, tf, ctx.n, time.time() - t0)
    entry_choice = _choose_entry(series, tfs)
    filters = {}
    for tf, P in pool.items():
        filters[tf] = TF2.train(np.array(P["F"]) if P["F"] else np.zeros((0, len(TF2.FEATURES))), np.array(P["R"]), np.array(P["ts"]))
    # ---- horizon runs ---------------------------------------------------------------------------------------------------
    scopes = {"test": {}, "all": {}}
    for sc in scopes:
        scopes[sc] = {"sequential": {hname(h): {} for h in horizons}, "identical_entries": {hname(h): {} for h in horizons}}
    weeks = {"test": {}, "all": {}}
    deadline2 = t_start + budget_s
    done = []
    for key_, v in series.items():
        if time.time() > deadline2:
            skipped.append(f"{key_}: time budget (horizon runs)")
            continue
        t0 = time.time()
        ctx, paths, d = v["ctx"], v["paths"], v["d"]
        tf = ctx.tf
        mode, k = (entry_choice[tf]["chosen"].split(":") if settings.entry_rules else ("old", "0"))
        f = filters.get(tf) if settings.trade_filter2 else None
        keep = None
        if f and f.get("enabled"):
            keep = lambda c, f=f, ctx=ctx, d=d: TF2.score(f, TF2.features(ctx, d, c["j"])) >= f["threshold"]  # noqa: E731
        allrows = np.ones(ctx.n, bool)
        by_h = {h: candidates_h(ctx, paths, allrows, d, mode, float(k), cost, news, h) for h in horizons}
        for sc, mask in (("test", v["test"]), ("all", allrows)):
            ts_m = ctx.ts[mask]
            weeks[sc][key_] = max((int(ts_m[-1]) - int(ts_m[0])) / (7 * 86_400_000), 1e-9) if len(ts_m) > 1 else 1e-9
            seq = {h: taken_h(ctx, [c for c in by_h[h] if mask[c["j"]]], keep) for h in horizons}
            for h in horizons:
                scopes[sc]["sequential"][hname(h)][key_] = seq[h]
            base_js = [t["j"] for t in seq[SP.HORIZON_BARS]] if SP.HORIZON_BARS in seq else []
            for h in horizons:
                idx = {c["j"]: c for c in by_h[h]}
                scopes[sc]["identical_entries"][hname(h)][key_] = [idx[j] for j in base_js if j in idx and idx[j]["filled"]]
        v["secs_h"] = round(time.time() - t0, 1)
        done.append(key_)
    for sc in scopes:
        for view in scopes[sc]:
            for h in list(scopes[sc][view]):
                scopes[sc][view][h] = {k: x for k, x in scopes[sc][view][h].items() if k in done}
    out: dict[str, Any] = {}
    b30 = hname(SP.HORIZON_BARS)
    for sc in scopes:
        out[sc] = {}
        for view, res in scopes[sc].items():
            tfs_present = sorted({k.split(" ")[1] for k in done}, key=lambda t: TF_ORDER[::-1].index(t))
            out[sc][view] = {
                "variants": {h: table(r, weeks[sc]) for h, r in res.items()},
                "bootstrap_vs_h30": {"overall": bootstrap_vs(res, b30),
                                     "by_timeframe": {tf: bootstrap_vs(res, b30, tf=tf) for tf in tfs_present}},
            }
    return {"results": out,
            "series": {k: {"oos_bars": int(v["ctx"].n), "tune_bars": int(v["tune"].sum()), "test_bars": int(v["test"].sum()),
                           "cut": v["cut"], "seconds_tune": v["secs"], "seconds_horizons": v.get("secs_h")}
                       for k, v in series.items()},
            "skipped": skipped, "entry_choice": entry_choice,
            "filters": {tf: {k: x for k, x in f.items() if k not in ("model", "features")} for tf, f in filters.items()}}


def headline(body: dict[str, Any]) -> dict[str, Any]:
    """A compact comparison: test split, both views, overall + per timeframe, key numbers only."""
    keys = ("n", "win_rate", "expectancy_r", "total_r", "profit_factor", "max_drawdown_r", "expired_share",
            "hold_candles_median", "hold_candles_p90", "hold_days_median", "hold_days_p90", "trades_per_week",
            "open_at_data_end")
    out = {}
    for view in ("sequential", "identical_entries"):
        r = body["results"]["test"][view]
        rows = {}
        for h, t in r["variants"].items():
            rows[h] = {"overall": {k: t["overall"].get(k) for k in keys},
                       **{tf: {k: b.get(k) for k in keys} for tf, b in t["by_timeframe"].items()}}
        out[view] = {"table": rows, "share_better_expectancy_vs_h30":
                     {h: x.get("share_better_expectancy") for h, x in r["bootstrap_vs_h30"]["overall"].items()}}
    return out


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
    body = evaluate(rt, syms, tfs or DEFAULT_TFS, t0, budget_s, cost)
    body["headline_test"] = headline(body)
    body.update({"engine_version": ENGINE_VERSION, "cost_pct_round_trip": cost, "tune_share": TUNE_SHARE,
                 "horizons": [hname(h) for h in HORIZONS], "symbols": syms, "timeframes": tfs or DEFAULT_TFS,
                 "settings": {"entry_rules": settings.entry_rules, "trade_filter2": settings.trade_filter2,
                              "series_gate": False, "series_conf": False, "struct_stops": False,
                              "fill_window_bars": settings.fill_window_bars,
                              "reentry_cooldown_bars": settings.reentry_cooldown_bars},
                 "seconds": round(time.time() - t0, 1),
                 "method": __doc__.strip().split("\n\n", 1)[1] if __doc__ else None,
                 "approximations": [
                     "same as research_engine: model agreement treated as passed, no order book, fixed target ladder "
                     "1R / 1.75R / 2.5R, plan base-rate check and safety switch not replayed",
                     "the entry rule and the trade filter are chosen / trained once with the 30-candle horizon (as live) "
                     "and kept fixed for every horizon",
                     "the test split starts 30 candles after the tuning cut for every horizon"]})
    return body
