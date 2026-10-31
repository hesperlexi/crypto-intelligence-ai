"""`python -m app.research scalp15`: the owner's 15m restart proposal (read-only research, 31 Oct 2026).

Proposal: 15m calls of grade A only, TP1 as near as possible with the stop moved to break-even immediately after TP1 (to
raise the win rate), traded at 20x-25x leverage. Replayed on the same calls as `python -m app.research horizon`: the
models' walk-forward OUT-OF-SAMPLE predictions turned into calls by the live decision rules (series_policy.decide, which
reproduces the live grading: A = technical tilt firm and the AI's side agreeing, margin clearing the proven policy
margin and directional confidence >= MIN_DIR_CONFIDENCE_A; B = AI-led / weaker; bigger-trend check A -> B), with the live
15m entry rule and trade filter chosen on the tuning part, one call at a time per series plus the re-entry cooldown.

Variants (each on the 15m series, grade A only):
  TP1 at 0.3R / 0.5R / 0.75R / 1.0R (current)  x  exits (i) `ladder`: 50 % at TP1, stop -> break-even, 25 % at TP2 1.75R,
  25 % at TP3 2.5R, stop -> TP1 after TP2 (the current ladder) or (ii) `all_tp1`: 100 % closed at TP1
  x  horizon 30 or 250 candles (then EXPIRED at the last close).
Baselines: the current rules (grades A + B, TP1 1R ladder) at 30 and 250 candles.
Costs: RESEARCH_COST_PCT (0.15 %) round trip headline, also 0.10 % and 0.20 %; every R and % is after costs.
Leverage: liquidation distance from engine/futures.liquidation_price (1/lev - 0.5 % maintenance margin): 4.5 % at 20x,
3.5 % at 25x. A trade is `liquidated` when its adverse excursion from the entry, up to its exit (or up to TP1, after
which the stop is at break-even or better), reaches that distance; stop first inside a candle (conservative). ROI on margin
= net price return x leverage, a liquidated trade = -100 % of margin. Also reported: the share of trades whose stop lies
beyond the liquidation price (they can be liquidated before the stop).
Headline: the untouched last 30 % of each series (same split as research_engine); all-data numbers too. Confidence:
per-series bootstrap, share of resamples with expectancy > 0, and share beating the current rules.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from .config import ENGINE_VERSION, settings
from .data.base import tf_ms
from .engine.futures import MAINTENANCE_MARGIN, liquidation_price
from .ml import series_policy as SP, series_sim as S
from . import research_horizon as H
from .research_engine import TUNE_SHARE

log = logging.getLogger("research.scalp15")
TP1_OPTIONS = (0.3, 0.5, 0.75, 1.0)
EXITS = {"ladder": (0.5, 0.25, 0.25), "all_tp1": (1.0, 0.0, 0.0)}
HORIZONS = (30, 250)
COSTS = (0.10, 0.15, 0.20)
LEVERAGES = (20, 25)


def liq_dist_pct(lev: float) -> float:
    """Distance from the entry to the liquidation price, % of the entry (same for long and short)."""
    return abs(liquidation_price(100.0, 1, lev, MAINTENANCE_MARGIN) - 100.0)


# ---- exits ---------------------------------------------------------------------------------------------------------------

def follow_x(side: int, entry: float, stop: float, tps, split, high, low, close, first_is_fill: bool = False,
             complete: bool = True) -> dict[str, Any] | None:
    """series_sim.follow with a free target ladder and split (split (1, 0, 0): everything closes at TP1). Also returns
    the worst adverse excursion (% of entry) up to the exit or TP1, for the liquidation check. Identical to
    series_sim.follow for split 50/25/25 (unit test)."""
    n = len(high)
    if n == 0 or side == 0 or entry <= 0:
        return None
    s = 1 if side > 0 else -1
    fav, adv = (high, low) if s > 0 else (low, high)
    hit_adv = (lambda lvl: adv <= lvl) if s > 0 else (lambda lvl: adv >= lvl)
    hit_fav = (lambda lvl: fav >= lvl) if s > 0 else (lambda lvl: fav <= lvl)
    tp1, tp2, tp3 = (float(t) for t in tps)
    risk_pct = abs(entry - stop) / entry * 100
    legs = [None, None, None]
    t0 = 1 if first_is_fill else 0
    advx = s * (entry - adv) / entry * 100                       # adverse excursion per candle, % of entry

    def mae(upto: int) -> float:
        return float(max(0.0, advx[: upto + 1].max())) if upto >= 0 else 0.0

    def done(status, reason, idx, fallback, m) -> dict[str, Any]:
        px = [legs[k] if legs[k] is not None else fallback for k in range(3)]
        ret = sum(w * s * (p / entry - 1) for w, p in zip(split, px)) * 100
        return {"status": status, "exit": reason, "return_pct": float(ret), "risk_pct": float(risk_pct),
                "exit_idx": int(idx), "mae_pct": m}

    ts_ = S._first(hit_adv(stop), 0)
    t1 = S._first(hit_fav(tp1), t0)
    if t1 is None or (ts_ is not None and ts_ <= t1):
        if ts_ is not None:
            return done("STOPPED", "stop", ts_, stop, mae(ts_))
        return done("EXPIRED", "expired", n - 1, float(close[-1]), mae(n - 1)) if complete else None
    legs[0] = tp1
    m1 = mae(t1)
    if split[1] == 0 and split[2] == 0:
        return done("TP1", "tp1", t1, tp1, m1)
    if hit_fav(tp2)[t1]:
        t2 = t1
    else:
        tb = S._first(hit_adv(entry), t1 + 1)
        t2 = S._first(hit_fav(tp2), t1 + 1)
        if t2 is None or (tb is not None and tb <= t2):
            if tb is not None:
                return done("TP1", "break_even", tb, entry, m1)
            return done("TP1", "expired", n - 1, float(close[-1]), m1) if complete else None
    legs[1] = tp2
    if hit_fav(tp3)[t2]:
        legs[2] = tp3
        return done("TP3", "tp3", t2, tp3, m1)
    tb = S._first(hit_adv(tp1), t2 + 1)
    t3 = S._first(hit_fav(tp3), t2 + 1)
    if t3 is None or (tb is not None and tb <= t3):
        if tb is not None:
            return done("TP2", "trail", tb, tp1, m1)
        return done("TP2", "expired", n - 1, float(close[-1]), m1) if complete else None
    legs[2] = tp3
    return done("TP3", "tp3", t3, tp3, m1)


def simulate_x(ctx: SP.Context, paths: SP.Paths, j: int, side: int, pl: dict[str, Any], entry_mode: str, k: float,
               horizon: int, tp_mult: tuple[float, float, float], split) -> dict[str, Any] | None:
    """research_horizon.simulate_h with a free ladder / split; gross return kept so costs can be applied later."""
    step = tf_ms(ctx.tf)
    start = int(ctx.decision_ts[j])
    base = paths.window(start, start + SP.HORIZON_BARS * step)
    if base is None:
        return None
    ms = base[4]
    a = paths._a["p15" if ms else "own"]
    end = start + horizon * step
    i = int(np.searchsorted(a[0], start))
    e = int(np.searchsorted(a[0], end))
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
    tps = S.ladder(side, entry, stop, tp_mult)
    complete = int(ts[-1]) + bar >= end
    out = follow_x(side, entry, stop, tps, split, hi[i0:], lo[i0:], cl[i0:], first_is_fill=first_is_fill, complete=complete)
    if out is None:
        return {"filled": True, "open": True, "filled_ts": int(ts[i0])}
    out.update(filled=True, open=False, closed_ts=int(ts[i0 + out["exit_idx"]]) + bar, filled_ts=int(ts[i0]), entry=entry)
    return out


def candidates_x(ctx, paths, mask, decision, entry_mode, k, news, horizon, tp_mult, split, grades=("A", "B")):
    res = []
    trade = decision["trade"] & np.isin(decision["grade"], list(grades))
    for j in np.flatnonzero(mask & trade):
        if news is not None and news(int(ctx.decision_ts[j])):
            continue
        mode = entry_mode
        if mode == "old" and decision["decision"][j] != "BUY ON PULLBACK":
            mode = "market"
        r = simulate_x(ctx, paths, int(j), int(decision["side"][j]), decision["plan"][j], mode, k, horizon, tp_mult, split)
        if r is None:
            continue
        if not r["filled"]:
            r = {"filled": False, "closed_ts": int(ctx.decision_ts[j]) + settings.fill_window_bars * tf_ms(ctx.tf)}
        elif r["open"]:
            r["closed_ts"] = H.OPEN
        res.append({"j": int(j), "ts": int(ctx.decision_ts[j]), "grade": str(decision["grade"][j]), **r})
    return res


# ---- statistics ----------------------------------------------------------------------------------------------------------

def net_r(t: dict[str, Any], cost: float) -> float:
    return (t["return_pct"] - cost) / t["risk_pct"] if t["risk_pct"] else 0.0


def stats_x(trades: list[dict[str, Any]], cost: float, weeks: float) -> dict[str, Any]:
    sc = sorted((t for t in trades if not t.get("open")), key=lambda t: t["ts"])
    st = S.stats([net_r(t, cost) for t in sc], weeks)
    st["open_at_data_end"] = int(sum(1 for t in trades if t.get("open")))
    if not sc:
        return st
    net_pct = np.array([t["return_pct"] - cost for t in sc])
    risk = np.array([t["risk_pct"] for t in sc])
    mae = np.array([t["mae_pct"] for t in sc])
    st.update({"tp1_hit_rate": float(np.mean([t["status"] in ("TP1", "TP2", "TP3") for t in sc])),
               "expectancy_pct_of_price": float(net_pct.mean()),
               "expired_share": float(np.mean([t["exit"] == "expired" for t in sc])),
               "risk_pct_median": float(np.median(risk)), "risk_pct_p90": float(np.quantile(risk, 0.9)),
               "grade_A_share": float(np.mean([t["grade"] == "A" for t in sc])),
               "hold_hours_median": float(np.median([(t["closed_ts"] - t["filled_ts"]) / 3_600_000 for t in sc])),
               "exits": {x: int(sum(t["exit"] == x for t in sc)) for x in ("stop", "tp1", "break_even", "trail", "tp3", "expired")}})
    for lev in LEVERAGES:
        ld = liq_dist_pct(lev)
        liq = mae >= ld
        roi = np.where(liq, -100.0, net_pct * lev)
        st[f"stop_beyond_liq_{lev}x"] = float(np.mean(risk >= ld))
        st[f"liquidated_{lev}x"] = float(np.mean(liq))
        st[f"roi_margin_avg_{lev}x"] = float(roi.mean())
        st[f"roi_margin_median_{lev}x"] = float(np.median(roi))
    return st


def bootstrap_x(res: dict[str, dict[str, list]], cost: float, base: str, n_boot: int = 2000, seed: int = 0) -> dict[str, Any]:
    keys = sorted({k for v in res.values() for k in v})
    if not keys:
        return {}
    rng = np.random.default_rng(seed)
    R = {v: {k: np.array([net_r(t, cost) for t in res[v].get(k, []) if not t.get("open")], float) for k in keys} for v in res}
    draws = [rng.integers(0, len(keys), len(keys)) for _ in range(n_boot)]
    out = {}
    for v in res:
        pos, better, means = [], [], []
        for d in draws:
            b = np.concatenate([R[v][keys[i]] for i in d])
            a = np.concatenate([R[base][keys[i]] for i in d])
            if len(b):
                pos.append(b.mean() > 0)
                means.append(b.mean())
                if len(a):
                    better.append(b.mean() > a.mean())
        out[v] = {"share_expectancy_above_0": float(np.mean(pos)) if pos else None,
                  "expectancy_90ci": [float(np.quantile(means, 0.05)), float(np.quantile(means, 0.95))] if means else None,
                  "share_better_than_base": float(np.mean(better)) if better and v != base else None}
    return out


# ---- the research ----------------------------------------------------------------------------------------------------------

def variants() -> dict[str, dict[str, Any]]:
    out = {f"AB_current_h{h}": {"grades": ("A", "B"), "tp1": 1.0, "exit": "ladder", "horizon": h} for h in HORIZONS}
    for h in HORIZONS:
        for ex in EXITS:
            for x in TP1_OPTIONS:
                out[f"A_tp{x}_{ex}_h{h}"] = {"grades": ("A",), "tp1": x, "exit": ex, "horizon": h}
    return out


def evaluate(rt, symbols: list[str], t_start: float, budget_s: float, cost_head: float) -> dict[str, Any]:
    V = variants()
    base = "AB_current_h30"
    prep = H.prepare(rt, symbols, ["15m"], t_start + 0.5 * budget_s)
    series, skipped = prep["series"], prep["skipped"]
    scopes = {sc: {v: {} for v in V} for sc in ("test", "all")}
    weeks = {"test": {}, "all": {}}
    grade_counts = {"test": {"A": 0, "B": 0}, "all": {"A": 0, "B": 0}}
    done = []
    for key_, s in series.items():
        if time.time() > t_start + budget_s:
            skipped.append(f"{key_}: time budget (variant runs)")
            continue
        ctx, paths, d = s["ctx"], s["paths"], s["d"]
        mode, k, keep = H.entry_and_keep(prep, s)
        allrows = np.ones(ctx.n, bool)
        cands = {}
        for vn, spec in V.items():
            tpm = (spec["tp1"], *S.TP_LADDER[1:])
            ck = (spec["grades"], tpm, spec["exit"], spec["horizon"])
            if ck not in cands:
                cands[ck] = candidates_x(ctx, paths, allrows, d, mode, k, prep["news"], spec["horizon"], tpm,
                                         EXITS[spec["exit"]], spec["grades"])
            for sc, mask in (("test", s["test"]), ("all", allrows)):
                scopes[sc][vn][key_] = H.taken_h(ctx, [c for c in cands[ck] if mask[c["j"]]], keep)
        for sc, mask in (("test", s["test"]), ("all", allrows)):
            ts_m = ctx.ts[mask]
            weeks[sc][key_] = max((int(ts_m[-1]) - int(ts_m[0])) / (7 * 86_400_000), 1e-9) if len(ts_m) > 1 else 1e-9
            sel = mask & d["trade"]
            for g in ("A", "B"):
                grade_counts[sc][g] += int((sel & (d["grade"] == g)).sum())
        done.append(key_)
    out: dict[str, Any] = {}
    for sc in scopes:
        wk = max((weeks[sc][k] for k in done), default=1e-9)       # series run in parallel: weeks of the longest span
        out[sc] = {"weeks": wk, "calls_by_grade_before_one_at_a_time": grade_counts[sc], "by_cost": {}}
        for c in COSTS:
            res = {vn: {k: x for k, x in r.items() if k in done} for vn, r in scopes[sc].items()}
            out[sc]["by_cost"][f"{c:.2f}"] = {
                "variants": {vn: stats_x([t for k in done for t in res[vn].get(k, [])], c, wk) for vn in V},
                "bootstrap": bootstrap_x(res, c, base)}
    return {"results": out, "variants": {k: {**v, "grades": list(v["grades"])} for k, v in V.items()}, "base": base,
            "series": {k: {"oos_bars": int(v["ctx"].n), "tune_bars": int(v["tune"].sum()), "test_bars": int(v["test"].sum()),
                           "cut": v["cut"]} for k, v in series.items()},
            "skipped": skipped, "entry_choice_15m": prep["entry_choice"].get("15m"),
            "filter_15m": {k: x for k, x in (prep["filters"].get("15m") or {}).items() if k not in ("model", "features")},
            "liquidation_distance_pct": {f"{lev}x": liq_dist_pct(lev) for lev in LEVERAGES}}


def headline(body: dict[str, Any], cost: float) -> dict[str, Any]:
    keys = ("n", "trades_per_week", "win_rate", "tp1_hit_rate", "expectancy_r", "expectancy_pct_of_price", "total_r",
            "profit_factor", "max_drawdown_r", "expired_share", "risk_pct_median", "stop_beyond_liq_20x",
            "stop_beyond_liq_25x", "liquidated_20x", "liquidated_25x", "roi_margin_avg_20x", "roi_margin_avg_25x",
            "open_at_data_end")
    r = body["results"]["test"]["by_cost"][f"{cost:.2f}"]
    rows = {vn: {k: t.get(k) for k in keys} for vn, t in r["variants"].items()}
    for vn in rows:
        b = r["bootstrap"].get(vn) or {}
        rows[vn]["boot_share_exp_gt_0"] = b.get("share_expectancy_above_0")
        rows[vn]["boot_share_better_than_current"] = b.get("share_better_than_base")
    best = max((vn for vn in rows if rows[vn]["n"]), key=lambda vn: rows[vn]["expectancy_r"] if rows[vn]["expectancy_r"] is not None else -9,
               default=None)
    return {"cost_pct": cost, "table": rows, "best_by_expectancy": best}


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
    body["headline_test"] = headline(body, cost)
    body.update({"engine_version": ENGINE_VERSION, "cost_pct_round_trip_headline": cost, "costs": list(COSTS),
                 "tune_share": TUNE_SHARE, "symbols": syms, "timeframe": "15m",
                 "settings": {"entry_rules": settings.entry_rules, "trade_filter2": settings.trade_filter2,
                              "min_dir_confidence_a": settings.min_dir_confidence_a,
                              "min_dir_confidence_b": settings.min_dir_confidence_b,
                              "fill_window_bars": settings.fill_window_bars,
                              "reentry_cooldown_bars": settings.reentry_cooldown_bars},
                 "seconds": round(time.time() - t0, 1),
                 "method": __doc__.strip().split("\n\n", 1)[1] if __doc__ else None,
                 "approximations": [
                     "grading is the live logic replayed by series_policy.decide; per-member model agreement is not "
                     "stored out-of-sample and is treated as passed (as in research_engine), no order book",
                     "TP2 / TP3 on the fixed ladder 1.75R / 2.5R (live picks them from history within [1.25, 2] / [2, 3]R)",
                     "the live costs rule (1R >= 3x round trip) is kept for every TP1 option; a 0.3R TP1 is not re-checked",
                     "the entry rule and trade filter are chosen / trained once on the tuning part with the 30-candle "
                     "current rules (as live) and kept for every variant",
                     "liquidation uses a flat 0.5 % maintenance margin (engine/futures.py); funding not charged",
                     "15m paths are 15m candles: the order of high / low inside one candle is unknown, stop first"]})
    return body
