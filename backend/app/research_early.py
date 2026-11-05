"""Early profit-taking before TP1 (owner question, 5 Nov 2026) - read-only replay (python -m app.research early).

Question: a call that is in profit but has not reached TP1 turns back. Should it close (or protect the profit) before the
stop? Variants, applied ONLY before TP1 (after TP1 the live rules run unchanged: break-even, TP1 after TP2, 50/25/25):
  * lock:     once the best move so far reaches `arm` R, the stop moves to entry + `lock` R (lock 0 = break-even);
  * giveback: once the best move reaches `arm` R, a trailing stop keeps (1 - frac) of the best move.
The best move is measured on candles BEFORE the current one (no look-ahead); inside a candle the stop is checked first,
gap opens fill at the open - as the live rules. Same calls as the live pipeline (current grading, honest market entry,
pullback limits as live), 0.15 % round-trip cost + funding, one call at a time per series. The variant is chosen on the
first 70 % of each series (tune) and judged on the untouched last 30 % (test)."""
from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from .config import MODEL_TIMEFRAMES, settings
from .ml import series_sim as S

log = logging.getLogger(__name__)

VARIANTS: dict[str, dict[str, Any] | None] = {"standard (live rules)": None}
for arm in (0.5, 0.7):
    for lock in (0.0, 0.2, 0.4):
        if lock < arm:
            VARIANTS[f"lock {lock}R at {arm}R"] = {"mode": "lock", "arm": arm, "lock": lock}
    for frac in (0.4, 0.5, 0.6):
        VARIANTS[f"giveback {int(frac * 100)}% after {arm}R"] = {"mode": "giveback", "arm": arm, "frac": frac}

_ORIG_FOLLOW = S.follow
_RULE: dict[str, Any] | None = None
_LAST_PEAK = [0.0]                               # best move (R) before the exit candle of the last follow_rule call


def follow_rule(side, entry, stop, tps, high, low, close, first_is_fill=False, complete=True, open_=None,
                rule: dict[str, Any] | None = None):
    """Candle loop with the live rules + an optional pre-TP1 rule. With rule None it equals series_sim.follow."""
    n = len(high)
    if n == 0 or side == 0 or entry <= 0:
        return None
    s = 1 if side > 0 else -1
    R = abs(entry - stop)
    risk_pct = R / entry * 100
    tp = [float(t) for t in tps]
    legs: list[float | None] = [None, None, None]
    hit = [False, False, False]
    peak = 0.0                                   # best favourable move so far in R (candles before the current one)
    early = False

    def done(status, reason, idx, fallback):
        _LAST_PEAK[0] = peak
        px = [legs[k] if legs[k] is not None else fallback for k in range(3)]
        ret = sum(w * s * (p / entry - 1) for w, p in zip(S.TP_SPLIT, px)) * 100
        return S.Outcome(status, reason, float(ret), float(risk_pct), int(idx))

    for i in range(n):
        hi, lo = float(high[i]), float(low[i])
        # stop in force for this candle
        if hit[1]:
            lvl, why = tp[0], "trail"
        elif hit[0]:
            lvl, why = entry, "break_even"
        else:
            lvl, why, early = stop, "stop", False
            if rule and peak >= rule["arm"]:
                keep = rule["lock"] if rule["mode"] == "lock" else (1 - rule["frac"]) * peak
                cand = entry + s * keep * R
                if s * (cand - lvl) > 0:
                    lvl, why, early = cand, "early", True
        adv = lo <= lvl if s > 0 else hi >= lvl
        if adv:
            px = lvl
            if open_ is not None and not (first_is_fill and i == 0):
                o = float(open_[i])
                if (s > 0 and o < lvl) or (s < 0 and o > lvl):
                    px = o
            if not hit[0]:
                return done("EARLY" if early else "STOPPED", why, i, px)
            return done("TP2" if hit[1] else "TP1", why, i, px)
        if not (first_is_fill and i == 0):
            for k in range(3):
                if not hit[k] and ((s > 0 and hi >= tp[k]) or (s < 0 and lo <= tp[k])):
                    hit[k], legs[k] = True, tp[k]
            if hit[2]:
                return done("TP3", "tp3", i, tp[2])
        fav = (hi - entry) / R if s > 0 else (entry - lo) / R
        peak = max(peak, fav)
    if not complete:
        return None
    st = "TP2" if hit[1] else "TP1" if hit[0] else "EXPIRED"
    return done(st, "expired", n - 1, float(close[-1]))


def _patched(*a, **k):
    return follow_rule(*a, rule=_RULE, **k)


def self_check(trials: int = 3000, seed: int = 7) -> dict[str, Any]:
    """With no rule the loop must give the same results as series_sim.follow (random paths, gaps included)."""
    rng = np.random.default_rng(seed)
    bad = 0
    for _ in range(trials):
        n = int(rng.integers(1, 60))
        side = int(rng.choice([-1, 1]))
        cl = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
        op = np.r_[100.0, cl[:-1]] * (1 + rng.normal(0, 0.003, n))
        hi = np.maximum(cl, op) * (1 + np.abs(rng.normal(0, 0.006, n)))
        lo = np.minimum(cl, op) * (1 - np.abs(rng.normal(0, 0.006, n)))
        entry, stop = 100.0, 100.0 - side * float(rng.uniform(0.5, 3))
        tps = S.ladder(side, entry, stop)
        ff, comp = bool(rng.integers(0, 2)), bool(rng.integers(0, 2))
        a = _ORIG_FOLLOW(side, entry, stop, tps, hi, lo, cl, first_is_fill=ff, complete=comp, open_=op)
        b = follow_rule(side, entry, stop, tps, hi, lo, cl, first_is_fill=ff, complete=comp, open_=op)
        if (a is None) != (b is None) or (a and (a.status != b.status or abs(a.return_pct - b.return_pct) > 1e-9
                                                    or a.exit_idx != b.exit_idx)):
            bad += 1
    return {"trials": trials, "mismatches": bad}


def run(db_url: str, budget_s: float, symbols: list[str] | None = None, tfs: list[str] | None = None) -> dict[str, Any]:
    global _RULE
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
    out: dict[str, Any] = {"method": __doc__.strip(), "self_check": self_check()}
    syms = symbols or [r["symbol"] for r in db.query("SELECT DISTINCT symbol FROM model_versions WHERE active = 1 ORDER BY symbol")]
    news = RE._news_fn(rt.db)
    frames: dict = {}
    res = {"tune": {v: {} for v in VARIANTS}, "test": {v: {} for v in VARIANTS}}
    weeks = {"tune": {}, "test": {}}
    exits: dict[str, dict[str, int]] = {v: {} for v in VARIANTS}
    skipped = []
    paired: list[dict[str, Any]] = []
    S.follow = _patched
    try:
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
            key = f"{s} {tf}"
            weeks["tune"][key], weeks["test"][key] = RE._weeks(ctx, tune), RE._weeks(ctx, test)
            d = SP.decide(ctx, tune, require_edge=False)
            for name, rule in VARIANTS.items():
                _RULE = rule
                for part, mask in (("tune", tune), ("test", test)):
                    tr = V._with_funding(ctx, d, SP.run_series(ctx, paths, mask, d, entry_mode="old", news=news))
                    res[part][name][key] = tr
                    if part == "test":
                        for t in tr:
                            exits[name][t.get("exit") or "?"] = exits[name].get(t.get("exit") or "?", 0) + 1
            # v2 (owner, 5 Nov 2026: "check it on the trades in loss only"): the SAME standard test trades, each
            # replayed with every variant (paired) - losers and winners kept apart
            try:
                for t in res["test"]["standard (live rules)"][key]:
                    _RULE = None
                    SP.simulate(ctx, paths, t["j"], int(d["side"][t["j"]]), d["plan"][t["j"]],
                                "market" if d["decision"][t["j"]] != "BUY ON PULLBACK" else "old")
                    row = {"tf": tf, "r": t["r"], "peak": float(_LAST_PEAK[0]), "alt": {}}
                    for name, rule in VARIANTS.items():
                        if rule is None:
                            continue
                        _RULE = rule
                        mode = "market" if d["decision"][t["j"]] != "BUY ON PULLBACK" else "old"
                        o = SP.simulate(ctx, paths, t["j"], int(d["side"][t["j"]]), d["plan"][t["j"]], mode)
                        if o and o.get("filled"):
                            o = V._with_funding(ctx, d, [{**o, "j": t["j"], "ts": t["ts"]}])[0]
                            row["alt"][name] = o["r"]
                    paired.append(row)
            except Exception as exc:
                skipped.append(f"{key} paired: {type(exc).__name__}")
            log.info("%s: done", key)
    finally:
        S.follow = _ORIG_FOLLOW
        _RULE = None
    tables = {part: {v: RE._table(res[part][v], weeks[part]) for v in VARIANTS} for part in res}
    base = "standard (live rules)"
    # choose on tune (overall mean R, at least 80 % of the standard's trades), judge on test
    tune_rank = sorted(VARIANTS, key=lambda v: -(tables["tune"][v]["overall"].get("expectancy_r") or -9))
    best = tune_rank[0]
    per_tf_best = {}
    for tf in MODEL_TIMEFRAMES:
        cand = [v for v in VARIANTS if tf in tables["tune"][v]["by_timeframe"]]
        if cand:
            b_ = max(cand, key=lambda v: tables["tune"][v]["by_timeframe"][tf].get("expectancy_r") or -9)
            per_tf_best[tf] = {"chosen_on_tune": b_,
                               "tune_mean_r": tables["tune"][b_]["by_timeframe"][tf].get("expectancy_r"),
                               "test_mean_r": tables["test"][b_]["by_timeframe"][tf].get("expectancy_r"),
                               "test_standard_mean_r": tables["test"][base]["by_timeframe"][tf].get("expectancy_r"),
                               "test_n": tables["test"][b_]["by_timeframe"][tf].get("n")}
    out.update({
        "summary_test": {v: {k: tables["test"][v]["overall"].get(k) for k in ("n", "expectancy_r", "total_r", "win_rate", "max_drawdown_r")}
                         for v in VARIANTS},
        "summary_tune": {v: {k: tables["tune"][v]["overall"].get(k) for k in ("n", "expectancy_r", "total_r", "win_rate")}
                         for v in VARIANTS},
        "chosen_on_tune": best, "tune_rank": tune_rank[:5],
        "verdict_test": {"chosen": best, "chosen_mean_r": tables["test"][best]["overall"].get("expectancy_r"),
                         "standard_mean_r": tables["test"][base]["overall"].get("expectancy_r")},
        "losers_only": losers_report(paired), "live_record_losses": live_losses(db),
        "per_timeframe": per_tf_best, "exits_test": exits, "tables": tables, "skipped": skipped,
        "costs": {"round_trip_pct": settings.research_cost_pct, "funding": "0.01% per 8 h (longs pay), over the hold"},
        "seconds": round(time.time() - t0, 1)})
    return out


def losers_report(paired: list[dict[str, Any]]) -> dict[str, Any]:
    """Standard test trades that LOST: how far into profit they went first, and what each early rule makes of them -
    next to what the same rule does to the trades that WON (the rule cannot know in advance which is which)."""
    lose = [p for p in paired if p["r"] < 0]
    win = [p for p in paired if p["r"] >= 0]
    out: dict[str, Any] = {"trades": len(paired), "losers": len(lose), "winners": len(win),
                           "losers_reached": {f"+{x}R": sum(1 for p in lose if p["peak"] >= x) for x in (0.3, 0.5, 0.7, 0.9)},
                           "losers_total_r": round(sum(p["r"] for p in lose), 1), "by_rule": {}}
    for name, rule in VARIANTS.items():
        if rule is None:
            continue
        lz = [(p["r"], p["alt"][name]) for p in lose if name in p["alt"]]
        wz = [(p["r"], p["alt"][name]) for p in win if name in p["alt"]]
        out["by_rule"][name] = {
            "losers_saved_r": round(sum(b - a for a, b in lz), 1),
            "losers_turned_into_wins": sum(1 for a, b in lz if b > 0),
            "losers_made_smaller": sum(1 for a, b in lz if a < b <= 0),
            "winners_cost_r": round(sum(b - a for a, b in wz), 1),
            "winners_cut_short": sum(1 for a, b in wz if b < a - 1e-9),
            "net_r": round(sum(b - a for a, b in lz + wz), 1)}
    tfs = sorted({p["tf"] for p in paired}, key=lambda t: MODEL_TIMEFRAMES.index(t) if t in MODEL_TIMEFRAMES else 99)
    out["losers_by_timeframe"] = {tf: {"losers": sum(1 for p in lose if p["tf"] == tf),
                                       "reached_+0.5R": sum(1 for p in lose if p["tf"] == tf and p["peak"] >= 0.5)} for tf in tfs}
    return out


def live_losses(db) -> dict[str, Any]:
    """The live record's own closed losing calls (after fees): how far into profit each went first (peak_r)."""
    from .services.tracking import net_pct
    rows = db.query("SELECT * FROM signals WHERE side != 0 AND status IN ('STOPPED', 'EXPIRED', 'TP1', 'TP2', 'TP3') "
                    "AND return_pct IS NOT NULL AND closed_at IS NOT NULL")
    since = int(db.get_setting("record_since", 0) or 0)
    rows = [r for r in rows if int(r["created_at"]) >= since]
    lose = []
    for r in rows:
        try:
            if float(net_pct(r)) < 0:
                lose.append(r)
        except Exception:
            continue
    pk = [float(r["peak_r"]) for r in lose if r.get("peak_r") is not None]
    return {"closed": len(rows), "losses": len(lose), "with_peak": len(pk),
            "reached": {f"+{x}R": sum(1 for v in pk if v >= x) for x in (0.3, 0.5, 0.7, 0.9)},
            "by_timeframe": {tf: sum(1 for r in lose if r["timeframe"] == tf) for tf in MODEL_TIMEFRAMES}}
