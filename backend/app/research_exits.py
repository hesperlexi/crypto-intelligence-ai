"""v2.40 exit study (owner, 15 Nov 2026: "shall the guard close a signal when it comes back from profit to negative before
TP1? are the TPs well aligned? change the ratio so TP1 is at least hit?"). Read-only, aggregates only.

The models' walk-forward out-of-sample calls of every 15m / 1h / 4h series are replayed through the live decision rules
(research_engine method: honest entry, live grading - 1h grade A, 15m / 4h A+B - VP wall, same-side cap 8, live time
limits 250 / 200 / 100 candles, 0.15 % costs + funding). The SAME calls are then followed with different exit rules:

  base        the live rules: 50/25/25 at 1R / 1.75R / 2.5R, break-even after TP1, TP1 after TP2
  be_05/be_07 stop -> entry once the trade has been +0.5R / +0.7R (before TP1); from the next candle on
  lock_07_03  once +0.7R, stop -> +0.3R (keeps a little profit)
  back_05     once +0.5R, close at a candle CLOSE back at or below the entry (the "returning to negative" rule)
  tp1_07/08   TP1 at 0.7R / 0.8R (TP2 / TP3 unchanged)
Each rule is judged on the first 70 % of each series (choose) and the last 30 % (untouched test); a rule is "better" only
if it beats base on BOTH, in average net R and not with a much deeper drawdown.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from .ml import series_sim as S
from .ml.series_sim import Outcome

TFS = ("15m", "1h", "4h")
A_ONLY = ("1h", "1d", "3d")
VARIANTS: dict[str, dict[str, Any]] = {
    "base": {},
    "be_05": {"arm": 0.5, "lock": 0.0},
    "be_07": {"arm": 0.7, "lock": 0.0},
    "lock_07_03": {"arm": 0.7, "lock": 0.3},
    "back_05": {"back": 0.5},
    "tp1_07": {"ladder": (0.7, 1.75, 2.5)},
    "tp1_08": {"ladder": (0.8, 1.75, 2.5)},
}


def follow_x(side: int, entry: float, stop: float, tps, high, low, close, first_is_fill: bool = False,
             complete: bool = True, open_=None, arm: float | None = None, lock: float = 0.0,
             back: float | None = None) -> Outcome | None:
    """Candle-by-candle version of series_sim.follow (stop first inside a candle, gap fills at the open) plus the
    early-protection rules. With no options it equals series_sim.follow (checked in `_selfcheck`)."""
    n = len(high)
    if n == 0 or side == 0 or entry <= 0:
        return None
    s = 1 if side > 0 else -1
    tp = [float(t) for t in tps]
    risk = abs(entry - stop)
    risk_pct = risk / entry * 100
    legs: list[float | None] = [None, None, None]
    lvl = float(stop)
    peak = 0.0                      # best excursion in R seen on closed candles before this one
    reason_stop = "stop"
    hit = 0
    t0 = 1 if first_is_fill else 0

    def done(status, reason, idx, fallback):
        px = [legs[k] if legs[k] is not None else fallback for k in range(3)]
        ret = sum(w * s * (p / entry - 1) for w, p in zip(S.TP_SPLIT, px)) * 100
        return Outcome(status, reason, float(ret), float(risk_pct), int(idx))

    def gap(i, level):
        if open_ is None or (first_is_fill and i == 0):
            return float(level)
        o = float(open_[i])
        return o if (s > 0 and o < level) or (s < 0 and o > level) else float(level)

    status = lambda: ("STOPPED", "TP1", "TP2", "TP3")[hit]  # noqa: E731
    for i in range(n):
        hi, lo, cl = float(high[i]), float(low[i]), float(close[i])
        adv, fav = (lo, hi) if s > 0 else (hi, lo)
        # stop first
        if s * (adv - lvl) <= 0:
            return done(status(), reason_stop, i, gap(i, lvl))
        if i >= t0:
            while hit < 3 and s * (fav - tp[hit]) >= 0:
                legs[hit] = tp[hit]
                hit += 1
                if hit == 3:
                    return done("TP3", "tp3", i, tp[2])
                if hit == 1:
                    new, reason_stop = entry, "break_even"
                else:
                    new, reason_stop = tp[0], "trail"
                if s * (new - lvl) > 0:
                    lvl = new
                # series_sim: after a fill on this candle, the new level applies from the next candle only
                # except TP1->TP2 in the same candle (handled by the while)
        peak = max(peak, s * (fav - entry) / risk)
        if hit == 0:
            if back is not None and peak >= back and s * (cl - entry) <= 0:
                return done("STOPPED", "give_back", i, cl)
            if arm is not None and peak >= arm:
                new = entry + s * lock * risk
                if s * (new - lvl) > 0:
                    lvl, reason_stop = new, "early_lock"
    if not complete:
        return None
    return done("EXPIRED" if hit == 0 else status(), "expired", n - 1, float(close[-1]))


def _selfcheck(high, low, close, open_) -> dict[str, int]:
    """Agreement of follow_x (no options) with series_sim.follow on random calls of a real path."""
    rng = np.random.default_rng(0)
    same = diff = 0
    for _ in range(300):
        if len(high) < 60:
            break
        a = int(rng.integers(0, len(high) - 50))
        side = 1 if rng.random() < 0.5 else -1
        e = float(close[a])
        st = e * (1 - side * float(rng.uniform(0.004, 0.03)))
        tps = S.ladder(side, e, st)
        sl = slice(a + 1, min(len(high), a + 200))
        o1 = S.follow(side, e, st, tps, high[sl], low[sl], close[sl], open_=open_[sl] if open_ is not None else None)
        o2 = follow_x(side, e, st, tps, high[sl], low[sl], close[sl], open_=open_[sl] if open_ is not None else None)
        if o1 is None or o2 is None:
            continue
        if abs(o1.return_pct - o2.return_pct) < 1e-9 and o1.status == o2.status and o1.exit_idx == o2.exit_idx:
            same += 1
        else:
            diff += 1
    return {"same": same, "diff": diff}


def _stats(tr: list[dict[str, Any]]) -> dict[str, Any]:
    from .research_ideas import _curve
    c = _curve(tr)
    if tr:
        st = [t.get("status") for t in tr]
        c["tp1_hit"] = round(float(np.mean([x in ("TP1", "TP2", "TP3") for x in st])), 3)
        c["early_exits"] = sum(1 for t in tr if t.get("exit") in ("give_back", "early_lock"))
    return c


def replay(db_url: str, budget_s: float, raw: bool = False) -> dict[str, Any]:
    from . import research_engine as RE
    from . import research_v213 as V
    from .config import MODEL_TIMEFRAMES
    from .db import Database
    from .ml import series_policy as SP
    from .research_ideas import Profiles, _cap, _masked
    from .services import tracking
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
    res: dict[str, dict[str, list]] = {k: {"tune": [], "test": []} for k in VARIANTS}
    skipped, check = [], {"same": 0, "diff": 0}
    orig_follow, orig_ladder, orig_h = S.follow, S.ladder, SP.HORIZON_BARS
    try:
        for s, tf in [(s, tf) for tf in TFS if tf in MODEL_TIMEFRAMES for s in syms]:
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
            if check["same"] < 600 and getattr(paths, "last_open", None) is not None:
                w = paths.window(int(ctx.decision_ts[0]), int(ctx.decision_ts[-1]))
                if w is not None:
                    op = paths.last_open
                    c = _selfcheck(w[1], w[2], w[3], op if op is not None and len(op) == len(w[1]) else None)
                    check = {k: check[k] + c[k] for k in check}
            d = SP.decide(ctx, tune, require_edge=False)
            prof = Profiles(rt, s, tf)
            keep = np.ones(ctx.n, bool)
            for j in np.flatnonzero(d["trade"]):
                p = prof.at(int(ctx.ts[j]))
                if p is None:
                    continue
                px, atr, sd = float(ctx.close[j]), float(ctx.atr[j]), int(d["side"][j])
                lv = (p["poc"], p["vah"]) if sd > 0 else (p["poc"], p["val"])
                if any(0 < sd * (L - px) <= 0.5 * atr for L in lv):
                    keep[j] = False
            if tf in A_ONLY:
                keep &= d["grade"] == "A"
            dd = _masked(d, keep)
            SP.HORIZON_BARS = int(tracking.horizon_for(tf))
            for name, v in VARIANTS.items():
                lad = v.get("ladder")
                opts = {k: v[k] for k in ("arm", "lock", "back") if k in v}
                S.follow = (lambda *a, _o=opts, **k: follow_x(*a, **k, **_o)) if name != "base" else orig_follow
                S.ladder = (lambda side, e, st, mult=None, _l=lad: orig_ladder(side, e, st, _l)) if lad else orig_ladder
                for part, m in (("tune", tune), ("test", test)):
                    tr = V._with_funding(ctx, dd, SP.run_series(ctx, paths, m, dd, entry_mode="old", news=news))
                    res[name][part] += [{**t, "side": int(dd["side"][t["j"]]), "tf": tf, "sym": s} for t in tr]
            S.follow, S.ladder, SP.HORIZON_BARS = orig_follow, orig_ladder, orig_h
    finally:
        S.follow, S.ladder, SP.HORIZON_BARS = orig_follow, orig_ladder, orig_h
    if raw:                                    # v2.68 per-coin study: the trades themselves
        return {"res": res, "skipped": skipped, "seconds": round(time.time() - t0, 1)}
    out: dict[str, Any] = {}
    for name, parts in res.items():
        out[name] = {}
        for part, v in parts.items():
            v = _cap(v, 8, False)
            out[name][part] = {"all": _stats(v), **{tf: _stats([t for t in v if t["tf"] == tf]) for tf in TFS}}
    verdict = {}
    for name in VARIANTS:
        if name == "base":
            continue
        row = {}
        for tf in ("all",) + TFS:
            b_tu, b_te = out["base"]["tune"][tf], out["base"]["test"][tf]
            x_tu, x_te = out[name]["tune"][tf], out[name]["test"][tf]
            if not b_te.get("n") or not x_te.get("n"):
                continue
            better = (x_tu["avg_r"] > b_tu["avg_r"] and x_te["avg_r"] > b_te["avg_r"]
                      and x_te["max_dd_r"] <= b_te["max_dd_r"] * 1.1)
            row[tf] = {"test_avg_r": x_te["avg_r"], "base_test_avg_r": b_te["avg_r"],
                       "tune_avg_r": x_tu["avg_r"], "base_tune_avg_r": b_tu["avg_r"], "better": better}
        verdict[name] = row
    return {"variants": out, "verdict": verdict, "selfcheck": check, "skipped": skipped[:20],
            "skipped_n": len(skipped), "seconds": round(time.time() - t0, 1),
            "notes": [__doc__.split("\n\n")[1].replace("\n", " ")]}


def run(db_url: str, budget_s: float) -> dict[str, Any]:
    return {"replay": replay(db_url, budget_s)}
