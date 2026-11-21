"""v2.65 one standard verdict for every study: the current system vs a change on the SAME unseen calls.

PASS only when all hold: total net R better in both halves of the test period (split at the median call time of the
base); max drawdown no more than `MAX_DD_WORSE` deeper; the change is better in at least `MIN_SHARE` of week-block
bootstrap resamples; and at least `MIN_AFFECTED` calls differ between the two (else INCONCLUSIVE). Anything else FAIL.
Trades need `ts`, `closed_ts` (ms) and `r` (net R)."""
from __future__ import annotations

from typing import Any

import numpy as np

MAX_DD_WORSE = 0.15
MIN_SHARE = 0.80
MIN_AFFECTED = 100
WEEK_MS = 7 * 86_400_000


def curve(trades: list[dict[str, Any]]) -> dict[str, Any]:
    r = [t["r"] for t in sorted(trades, key=lambda t: t["closed_ts"])]
    if not r:
        return {"n": 0, "total_r": 0.0, "max_dd_r": 0.0}
    a = np.array(r, float)
    c = np.cumsum(a)
    dd = float(np.max(np.maximum.accumulate(np.r_[0.0, c])[1:] - c))
    streak = cur = 0
    for x in a:
        cur = cur + 1 if x < 0 else 0
        streak = max(streak, cur)
    neg = a[a < 0]
    return {"n": len(a), "avg_r": round(float(a.mean()), 4), "total_r": round(float(a.sum()), 2),
            "win_rate": round(float((a > 0).mean()), 3), "max_dd_r": round(max(dd, 0.0), 2),
            "worst_streak": int(streak), "profit_factor": round(float(a[a > 0].sum() / -neg.sum()), 3) if len(neg) and neg.sum() else None,
            "worst_5pct_r": round(float(np.percentile(a, 5)), 3)}


def _key(t: dict[str, Any]) -> tuple:
    return (t.get("sym"), t.get("tf"), int(t["ts"]))


def verdict(base: list[dict[str, Any]], new: list[dict[str, Any]], seed: int = 7, n_boot: int = 2000) -> dict[str, Any]:
    if not base:
        return {"verdict": "INCONCLUSIVE", "reason": "no calls"}
    mid = float(np.median([t["ts"] for t in base]))
    halves = {}
    for name, cond in (("first_half", lambda t: t["ts"] < mid), ("second_half", lambda t: t["ts"] >= mid)):
        halves[name] = {"base": curve([t for t in base if cond(t)]), "new": curve([t for t in new if cond(t)])}
    cb, cn = curve(base), curve(new)
    kb, kn = {_key(t) for t in base}, {_key(t) for t in new}
    affected = len(kb ^ kn)
    t0 = min(t["ts"] for t in base)
    wk = lambda t: int((t["ts"] - t0) // WEEK_MS)   # noqa: E731
    weeks = sorted({wk(t) for t in base} | {wk(t) for t in new})
    sb = {w: 0.0 for w in weeks}
    sn = {w: 0.0 for w in weeks}
    for t in base:
        sb[wk(t)] += t["r"]
    for t in new:
        sn[wk(t)] += t["r"]
    diff = np.array([sn[w] - sb[w] for w in weeks])
    rng = np.random.default_rng(seed)
    boots = diff[rng.integers(0, len(diff), size=(n_boot, len(diff)))].sum(axis=1) if len(diff) else np.zeros(1)
    share = float((boots > 0).mean())
    both = all(h["new"]["total_r"] > h["base"]["total_r"] for h in halves.values())
    dd_ok = cn["max_dd_r"] <= cb["max_dd_r"] * (1 + MAX_DD_WORSE) + 1e-9
    if affected < MIN_AFFECTED:
        v, why = "INCONCLUSIVE", f"only {affected} calls differ (need {MIN_AFFECTED})"
    elif both and dd_ok and share >= MIN_SHARE:
        v, why = "PASS", "better in both halves, drawdown within limit, bootstrap agrees"
    else:
        fails = [x for x, ok in (("not better in both halves", both), ("drawdown too deep", dd_ok),
                                  (f"bootstrap {share:.0%} < {MIN_SHARE:.0%}", share >= MIN_SHARE)) if not ok]
        v, why = "FAIL", "; ".join(fails)
    return {"verdict": v, "reason": why, "base": cb, "new": cn, "halves": halves, "affected": affected,
            "bootstrap_better_share": round(share, 3),
            "bootstrap_gain_r_5_50_95": [round(float(np.percentile(boots, q)), 2) for q in (5, 50, 95)]}
