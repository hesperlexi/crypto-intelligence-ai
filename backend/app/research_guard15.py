"""v2.39 guard study (owner, 15 Nov 2026: "15min signals are blocked by guard which are mostly good signals - test it").

Two parts, read-only, aggregates only (public results branch):

1. LIVE  - every 15m call the live filters blocked (`rejected_signals`, the v2.24 filter check: the call as formed, then
   followed with the record's own rules) next to the 15m calls that were published (`signals`), since the record start:
   per filter how many, closed, win rate, average and total net R (net % / stop distance %). Small samples, but real.
2. REPLAY - the models' walk-forward out-of-sample calls of every series (research_engine method, honest entry, record
   exits, 0.15 % + funding), last 30 % of each series untouched. Variants for 15m, each removing ONE guard from the live
   set (grade A only on 15m/1h/1d/3d, bigger-trend check, volume-profile wall 0.5 ATR, same-side cap 8 over all
   timeframes; the fee filter is off on 15m live): what the guard blocked and how those blocked calls would have done.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from .config import MODEL_TIMEFRAMES

A_ONLY = ("15m", "1h", "1d", "3d")


def _r(row: dict[str, Any]) -> float | None:
    from .services import tracking
    net = tracking.net_pct(row)
    e, s = row.get("entry"), row.get("stop")
    if net is None or not e or not s:
        return None
    risk = abs(float(e) - float(s)) / float(e) * 100
    return net / risk if risk > 0 else None


def _stats(rs: list[float]) -> dict[str, Any]:
    if not rs:
        return {"n": 0}
    a = np.array(rs, float)
    return {"n": len(a), "win_rate": round(float((a > 0).mean()), 3), "avg_r": round(float(a.mean()), 4),
            "total_r": round(float(a.sum()), 2)}


def live(db) -> dict[str, Any]:
    from . import views
    from .services import tracking
    from .services.runtime import Runtime

    class _P:
        name = "binance"
    rt = Runtime(db, _P())
    since = views.record_since(rt)
    closed = tuple(tracking.CLOSED_STATUSES)
    q = ",".join("?" * len(closed))
    pub = db.query(f"SELECT * FROM signals WHERE timeframe = '15m' AND side != 0 AND created_at >= ? AND status IN ({q})",
                   (since, *closed))
    out: dict[str, Any] = {"since": since, "published_15m": _stats([x for x in map(_r, pub) if x is not None]),
                           "published_15m_open_or_unfilled": db.one(
                               "SELECT COUNT(*) AS n FROM signals WHERE timeframe = '15m' AND side != 0 AND created_at >= ?",
                               (since,))["n"] - len(pub)}
    try:
        rej = db.query(f"SELECT * FROM rejected_signals WHERE timeframe = '15m' AND created_at >= ?", (since,))
    except Exception as exc:
        return {**out, "rejected": None, "error": str(exc)[:120]}
    by: dict[str, dict[str, Any]] = {}
    for flag in sorted({r.get("reject_flag") or "?" for r in rej}):
        rows = [r for r in rej if (r.get("reject_flag") or "?") == flag]
        done = [r for r in rows if r.get("status") in closed and r.get("fill_status") != "NOT_FILLED"]
        by[flag] = {"blocked": len(rows), "closed": len(done), **{k: v for k, v in _stats([x for x in map(_r, done) if x is not None]).items() if k != "n"}}
    out["rejected_by_filter"] = by
    allc = [r for r in rej if r.get("status") in closed and r.get("fill_status") != "NOT_FILLED"]
    out["rejected_all_15m"] = {"blocked": len(rej), **_stats([x for x in map(_r, allc) if x is not None])}
    return out


def replay(db_url: str, budget_s: float) -> dict[str, Any]:
    from . import research_engine as RE
    from . import research_v213 as V
    from .db import Database
    from .ml import series_policy as SP
    from .research_ideas import Profiles, _cap, _curve, _masked
    from .services.runtime import Runtime

    class _Prov:
        name = "binance"
    db = Database(db_url)
    rt = Runtime(db, _Prov())
    ex = db.one("SELECT exchange, COUNT(*) AS n FROM market_data GROUP BY exchange ORDER BY n DESC LIMIT 1")
    if ex:
        _Prov.name = ex["exchange"]
    t0 = time.time()
    syms = [r["symbol"] for r in db.query("SELECT DISTINCT symbol FROM model_versions WHERE active = 1 ORDER BY symbol")]
    news = RE._news_fn(rt.db)
    frames: dict = {}
    names = ("live", "no_grade_rule", "no_bigger_trend", "no_vp", "no_guards")
    res: dict[str, list] = {k: [] for k in names}
    skipped = []
    for s, tf in [(s, tf) for tf in RE.TF_ORDER if tf in MODEL_TIMEFRAMES for s in syms]:
        if time.time() > t0 + budget_s:
            skipped.append(f"{s} {tf}: time budget")
            continue
        try:
            b = RE.build(rt, s, tf, frames)
        except Exception as exc:
            skipped.append(f"{s} {tf}: {type(exc).__name__}")
            continue
        if b is None:
            continue
        ctx, paths = b
        tune, test, _ = RE._split(ctx)
        if tune.sum() < 150 or test.sum() < 30:
            continue
        d = SP.decide(ctx, tune, require_edge=False)
        dn = SP.decide(ctx, tune, require_edge=False, htf_check=False)
        prof = Profiles(rt, s, tf)

        def vp_mask(dd):
            m = np.ones(ctx.n, bool)
            for j in np.flatnonzero(dd["trade"]):
                p = prof.at(int(ctx.ts[j]))
                if p is None:
                    continue
                px, atr, sd = float(ctx.close[j]), float(ctx.atr[j]), int(dd["side"][j])
                lv = (p["poc"], p["vah"]) if sd > 0 else (p["poc"], p["val"])
                if any(0 < sd * (L - px) <= 0.5 * atr for L in lv):
                    m[j] = False
            return m
        a_only = tf in A_ONLY
        gA, gAn = (d["grade"] == "A"), (dn["grade"] == "A")
        vp_d, vp_dn = vp_mask(d), vp_mask(dn)
        variants = {
            "live": _masked(d, (gA if a_only else True) & vp_d),
            "no_grade_rule": _masked(d, vp_d),
            "no_bigger_trend": _masked(dn, (gAn if a_only else True) & vp_dn),
            "no_vp": _masked(d, gA if a_only else np.ones(ctx.n, bool)),
            "no_guards": dn,
        }
        for k, dd in variants.items():
            tr = V._with_funding(ctx, dd, SP.run_series(ctx, paths, test, dd, entry_mode="old", news=news))
            res[k] += [{**t, "side": int(dd["side"][t["j"]]), "tf": tf, "sym": s} for t in tr]
    out: dict[str, Any] = {}
    capped = {k: _cap(v, 8, False) for k, v in res.items()}
    capped["no_cap"] = res["live"]
    for k in list(capped):
        if k == "no_guards":
            capped[k] = res[k]               # no guards at all: not capped either
    key = lambda t: (t["sym"], t["tf"], int(t["ts"]))   # noqa: E731
    live15 = {key(t) for t in capped["live"] if t["tf"] == "15m"}
    for k, v in capped.items():
        v15 = [t for t in v if t["tf"] == "15m"]
        extra = [t for t in v15 if key(t) not in live15]          # the calls this guard blocked
        out[k] = {"all_15m": _curve(v15), "blocked_by_this_guard_15m": _curve(extra),
                  "all_timeframes": _curve(v)}
    return {"variants": out, "skipped": skipped[:20], "skipped_n": len(skipped), "seconds": round(time.time() - t0, 1),
            "notes": ["live = grade A only (15m/1h/1d/3d) + bigger-trend check + VP wall 0.5 ATR + same-side cap 8 (all TFs)",
                      "each other variant removes one guard; 'blocked_by_this_guard_15m' = the 15m calls it adds back",
                      "no_cap = live without the cap; no_guards = none of them (grades A and B, no cap)"]}


def run(db_url: str, budget_s: float) -> dict[str, Any]:
    from .db import Database
    return {"live": live(Database(db_url)), "replay": replay(db_url, budget_s)}
