"""v2.65 one standard verdict for every study: the current system vs a change on the SAME unseen calls.

PASS only when all hold: total net R better in both halves of the test period (split at the median call time of the
base); max drawdown no more than `MAX_DD_WORSE` deeper; the change is better in at least `MIN_SHARE` of week-block
bootstrap resamples; and at least `MIN_AFFECTED` calls differ between the two (else INCONCLUSIVE). Anything else FAIL.
Trades need `ts`, `closed_ts` (ms) and `r` (net R).

V3.2 (Fable 5.2 audit R-03, 25 Nov 2026). Since 21 Nov more than 122 variants were scored on the same ~900 unseen calls
with an 80 % bootstrap bar and no correction, so the historical test split is SPENT: it can still rank ideas, never
prove one. From V3.2:
* MIN_SHARE = 0.95 (bootstrap); each verdict carries `p_value` = 1 - bootstrap share (one-sided).
* `finalize(out, study, variants)` is applied to every study result before it is written: it records the variant list
  and `n_variants` (fixed before outcomes are computed when the study registers them with `register`), applies the
  Holm correction over every verdict in the study (`corrected_verdict`), stamps the data fingerprint, seed and engine
  version (reproducible), and the forward-holdout status.
* A historical PASS is at most "PROVISIONAL": `promotable` stays False until the frozen FORWARD HOLDOUT confirms it.
* Forward holdout = record calls published from HOLDOUT_START (26 Nov 2026 00:00 UTC). No study may read it
  (`read_holdout` raises HoldoutLocked) until HOLDOUT_MIN_CLOSED (300) of them have closed; `verdict` refuses trades
  dated inside it unless `holdout=True`, and research_engine._split ends the replay test split before it."""
from __future__ import annotations

from typing import Any

import numpy as np

import hashlib
import json
import time

MAX_DD_WORSE = 0.15
MIN_SHARE = 0.95            # V3.2 (audit R-03): was 0.80
ALPHA = 1 - MIN_SHARE       # family-wise error rate for the Holm correction
MIN_AFFECTED = 100
WEEK_MS = 7 * 86_400_000
SEED, N_BOOT = 7, 2000
HOLDOUT_START = 1_795_651_200_000          # 2026-11-26 00:00:00 UTC: record calls from here are the forward holdout
HOLDOUT_MIN_CLOSED = 300


_CALLS = [0]            # verdicts computed in this process (reset_count() at the start of a study)


def reset_count() -> None:
    _CALLS[0] = 0


class HoldoutLocked(Exception):
    """The forward holdout may not be read yet."""


def _check_holdout(trades: list[dict[str, Any]], holdout: bool) -> None:
    if holdout:
        return
    late = [t for t in trades if int(t["ts"]) >= HOLDOUT_START]
    if late:
        raise HoldoutLocked(f"{len(late)} trades fall inside the forward holdout (from 2026-11-26 UTC); "
                            "research must stop before it (research_engine._split) or use read_holdout() once unlocked")


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


def verdict(base: list[dict[str, Any]], new: list[dict[str, Any]], seed: int = SEED, n_boot: int = N_BOOT,
            affected: int | None = None, holdout: bool = False) -> dict[str, Any]:
    """affected: number of calls that differ, when the study changes outcomes of the same calls (e.g. exits).
    holdout=True only for the confirmation run on the unlocked forward holdout (read_holdout)."""
    _check_holdout(base, holdout)
    _check_holdout(new, holdout)
    _CALLS[0] += 1
    if not base:
        return {"verdict": "INCONCLUSIVE", "reason": "no calls"}
    mid = float(np.median([t["ts"] for t in base]))
    halves = {}
    for name, cond in (("first_half", lambda t: t["ts"] < mid), ("second_half", lambda t: t["ts"] >= mid)):
        halves[name] = {"base": curve([t for t in base if cond(t)]), "new": curve([t for t in new if cond(t)])}
    cb, cn = curve(base), curve(new)
    kb, kn = {_key(t) for t in base}, {_key(t) for t in new}
    affected = len(kb ^ kn) if affected is None else affected
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
            "bootstrap_better_share": round(share, 3), "p_value": round(1.0 - share, 4),
            "bootstrap_gain_r_5_50_95": [round(float(np.percentile(boots, q)), 2) for q in (5, 50, 95)]}


# ---- V3.2 (audit R-03): multiple testing, reproducibility, forward holdout ---------------------------------------------

def holm(pvals: dict[str, float], alpha: float = ALPHA) -> dict[str, dict[str, Any]]:
    """Holm step-down over a family of tests. {name: {'p', 'p_adj', 'reject'}}; reject = significant after correction."""
    items = sorted(((float(p), k) for k, p in pvals.items()), key=lambda x: (x[0], x[1]))
    m = len(items)
    out: dict[str, dict[str, Any]] = {}
    running, stop = 0.0, False
    for i, (p, k) in enumerate(items):
        adj = min(1.0, (m - i) * p)
        running = max(running, adj)                 # adjusted p-values are monotone
        rej = (not stop) and p <= alpha / (m - i)
        if not rej:
            stop = True
        out[k] = {"p": round(p, 5), "p_adj": round(running, 5), "reject": rej}
    return out


_REGISTRY: dict[str, dict[str, Any]] = {}


def register(study: str, variants: list[str]) -> dict[str, Any]:
    """Fix a study's variant list BEFORE any outcome is computed. `finalize` refuses verdicts for unregistered
    variants of a registered study, and counts every registered variant (scored or not) in n_variants."""
    names = list(dict.fromkeys(str(v) for v in variants))
    entry = {"study": study, "variants": names, "n_variants": len(names), "registered_at": int(time.time() * 1000),
             "variants_sha1": hashlib.sha1(json.dumps(names).encode()).hexdigest()[:12]}
    _REGISTRY[study] = entry
    return entry


def _verdicts(node: Any, path: str = "") -> list[tuple[str, dict[str, Any]]]:
    """Every verdict dict inside a study result (any nesting), with a path name."""
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        if isinstance(node.get("verdict"), str) and "p_value" in node:
            found.append((path or "result", node))
            return found
        for k, v in node.items():
            if k in ("multiple_testing", "holdout", "reproducibility"):
                continue
            found += _verdicts(v, f"{path}/{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found += _verdicts(v, f"{path}[{i}]")
    return found


def fingerprint(trades: list[dict[str, Any]]) -> str:
    rows = sorted((str(t.get("sym")), str(t.get("tf")), int(t["ts"]), round(float(t["r"]), 6)) for t in trades)
    return hashlib.sha1(json.dumps(rows).encode()).hexdigest()[:16]


def finalize(out: dict[str, Any], study: str, base: list[dict[str, Any]] | None = None, db: Any = None) -> dict[str, Any]:
    """Annotate a study result before it is written (in place, also returned):
    corrected_verdict per verdict (Holm over the whole study), n_variants, reproducibility, holdout status."""
    if not isinstance(out, dict):
        return out
    found = _verdicts(out)
    reg = _REGISTRY.get(study)
    names = [p for p, _ in found]
    if reg is not None and len(found) > reg["n_variants"]:
        raise ValueError(f"{study}: {len(found)} verdicts but only {reg['n_variants']} registered variants")
    # every verdict computed in this process counts, also those a study left out of its output
    n_variants = max(len(found), reg["n_variants"] if reg else 0, _CALLS[0])
    # untested registered variants count as p = 1 (they were looked at; they cannot be dropped to ease the bar)
    pv = {p: float(v["p_value"]) for p, v in found}
    for i in range(n_variants - len(found)):
        pv[f"__untested_{i}"] = 1.0
    corr = holm(pv) if pv else {}
    status = holdout_status(db) if db is not None else {"start_utc": "2026-11-26T00:00:00Z", "needed": HOLDOUT_MIN_CLOSED,
                                                         "locked": True, "closed": None}
    for p, v in found:
        raw = v["verdict"]
        c = corr[p]
        if raw == "PASS" and c["reject"]:
            v["corrected_verdict"] = "PROVISIONAL PASS"
            v["corrected_reason"] = (f"passes after Holm correction over {n_variants} variants (p_adj {c['p_adj']:.3f}); "
                                     "the historical test split is spent: confirm on the forward holdout")
        elif raw == "PASS":
            v["corrected_verdict"] = "FAIL"
            v["corrected_reason"] = (f"raw PASS does not survive Holm correction over {n_variants} variants "
                                     f"(p_adj {c['p_adj']:.3f} > {ALPHA:.2f})")
        else:
            v["corrected_verdict"] = raw
            v["corrected_reason"] = v.get("reason")
        v["p_adj_holm"] = c["p_adj"]
        v["promotable"] = False                         # only a forward-holdout confirmation can make it True
    out["multiple_testing"] = {"method": "holm", "alpha": ALPHA, "min_bootstrap_share": MIN_SHARE,
                               "n_variants": n_variants, "n_scored": len(found), "n_computed": _CALLS[0],
                               "variants": reg["variants"] if reg else names,
                               "variants_registered_before_outcomes": bool(reg),
                               "variants_sha1": reg["variants_sha1"] if reg else None}
    try:
        from .config import ENGINE_VERSION
    except Exception:
        ENGINE_VERSION = None
    out["reproducibility"] = {"seed": SEED, "n_boot": N_BOOT, "engine_version": ENGINE_VERSION,
                              "base_fingerprint": fingerprint(base) if base else None,
                              "evidence": "historical test split (spent since 21 Nov 2026: exploratory only)"}
    out["holdout"] = status
    out["study"] = study
    return out


def _holdout_rows(db: Any) -> list[dict[str, Any]]:
    from .services import tracking
    closed = tuple(tracking.CLOSED_STATUSES)
    rows = db.query(f"SELECT * FROM signals WHERE created_at >= ? AND status IN ({','.join('?' * len(closed))})",
                    (HOLDOUT_START, *closed))
    return [r for r in rows if r.get("fill_status") != "NOT_FILLED"]


def holdout_status(db: Any) -> dict[str, Any]:
    """How full the forward holdout is - counts only, never outcomes."""
    try:
        n = len(_holdout_rows(db))
    except Exception:
        n = None
    return {"start_utc": "2026-11-26T00:00:00Z", "closed": n, "needed": HOLDOUT_MIN_CLOSED,
            "locked": not (n is not None and n >= HOLDOUT_MIN_CLOSED)}


def read_holdout(db: Any) -> list[dict[str, Any]]:
    """The forward-holdout record calls - only once HOLDOUT_MIN_CLOSED of them have closed."""
    rows = _holdout_rows(db)
    if len(rows) < HOLDOUT_MIN_CLOSED:
        raise HoldoutLocked(f"forward holdout locked: {len(rows)} of {HOLDOUT_MIN_CLOSED} closed calls since 2026-11-26 UTC")
    return rows


def run_study(study: str, fn: Any, db_url: str | None = None) -> dict[str, Any]:
    """Run one study and annotate its result (count reset first, so n_variants is this study's own)."""
    reset_count()
    out = fn()
    db = None
    if db_url:
        try:
            from .db import Database
            db = Database(db_url)
        except Exception:
            db = None
    return finalize(out, study, db=db)
