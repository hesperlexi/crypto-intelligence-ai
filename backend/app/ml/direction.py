"""Directional view of a forecast (engine v2).

The ensemble predicts three classes (down / neutral / up). For a long-or-short decision what matters is the
direction: is UP more likely than DOWN, and how often has the model been right when it leaned that way by a similar
margin? Everything here is measured on the model's own walk-forward out-of-sample predictions (bundle["oos"]),
so no figure is fitted on the bars it describes.

* `direction_policy(oos)` picks, once per model, the smallest UP-vs-DOWN margin at which the out-of-sample hit
  rate is reliably above a coin flip (best lower 95% Wilson bound with enough calls). It is cached per model version.
* `directional_confidence(...)` is the realised hit rate of comparable past calls (same side, similar margin).
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .metrics import wilson

MARGINS = (0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.18, 0.22, 0.26, 0.30)
MIN_CALLS = 40
MIN_COVERAGE = 0.04
_policy_cache: dict[str, dict[str, Any] | None] = {}


def _arrays(oos: dict[str, Any]):
    P = np.asarray(oos.get("P_ens", []), float)
    fwd = np.asarray(oos.get("fwd_ret", []), float)
    if P.ndim != 2 or len(P) != len(fwd) or len(P) < 150:
        return None
    side = np.where(P[:, 2] >= P[:, 0], 1.0, -1.0)
    margin = np.abs(P[:, 2] - P[:, 0])
    hit = (np.sign(fwd) == side) & (fwd != 0)
    return side, margin, hit


def direction_policy(oos: dict[str, Any], version: str | None = None) -> dict[str, Any] | None:
    if version is not None and version in _policy_cache:
        return _policy_cache[version]
    arr = _arrays(oos)
    out = None
    if arr is not None:
        side, margin, hit = arr
        n_all = len(side)
        base_k = int(hit.sum())
        rows, best = [], None
        for m in MARGINS:
            sel = margin >= m
            n = int(sel.sum())
            if n < MIN_CALLS or n / n_all < MIN_COVERAGE:
                continue
            k = int(hit[sel].sum())
            lo, hi = wilson(k, n)
            row = {"margin": m, "n": n, "coverage": n / n_all, "hit_rate": k / n, "ci95": [lo, hi]}
            rows.append(row)
            if best is None or lo > best["ci95"][0]:
                best = row
        out = {"base_hit_rate": base_k / n_all, "n": n_all, "best": best, "curve": rows,
               # an edge only when the chosen operating point is reliably better than a coin flip
               "edge": bool(best and best["ci95"][0] > 0.5)}
    if version is not None:
        _policy_cache[version] = out
        if len(_policy_cache) > 400:
            _policy_cache.pop(next(iter(_policy_cache)))
    return out


def directional_confidence(oos: dict[str, Any], side: int, margin: float) -> dict[str, Any]:
    """Hit rate of past out-of-sample calls on the same side with a similar UP-vs-DOWN margin."""
    arr = _arrays(oos)
    if arr is None:
        return {"confidence": None, "n": 0, "basis": "too few out-of-sample predictions"}
    s, mg, hit = arr
    similar = (s == side) & (mg >= 0.6 * margin) & (mg <= max(1.6 * margin, margin + 0.02))
    for sel, basis in ((similar, "same side, similar margin"), (s == side, "same side")):
        n = int(sel.sum())
        if n >= 30:
            k = int(hit[sel].sum())
            lo, hi = wilson(k, n)
            return {"confidence": k / n, "n": n, "basis": basis, "ci95": [lo, hi]}
    return {"confidence": None, "n": 0, "basis": "too few comparable out-of-sample calls"}


def view(fc: dict[str, Any], bundle: dict[str, Any] | None) -> dict[str, Any] | None:
    """Side, margin, directional confidence and whether the margin clears the model's own policy."""
    if not fc or not fc.get("available"):
        return None
    p = fc["probabilities"]
    side = 1 if p["up"] >= p["down"] else -1
    margin = abs(p["up"] - p["down"])
    oos = (bundle or {}).get("oos") or {}
    pol = direction_policy(oos, (bundle or {}).get("version"))
    conf = directional_confidence(oos, side, margin)
    need = (pol or {}).get("best", {}) or {}
    return {"side": side, "margin": margin, "p_side": p["up"] if side > 0 else p["down"],
            "confidence": conf.get("confidence"), "confidence_detail": conf,
            "policy_margin": need.get("margin"), "policy_hit_rate": need.get("hit_rate"),
            "policy_edge": bool((pol or {}).get("edge")),
            "clears_policy": bool(need.get("margin") is not None and margin >= need["margin"]),
            "base_hit_rate": (pol or {}).get("base_hit_rate")}
