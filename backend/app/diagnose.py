"""Why are there no trade signals, and where is a better operating point?

    python -m app.diagnose --days 3 --out report.json

1. Gate replay: for every coin / timeframe, the last `days` of closed bars are re-analysed with the active model and
   the gate that stopped each bar from becoming a trade is counted.
2. Policy study on the models' own walk-forward out-of-sample predictions (no look-ahead): for each probability
   threshold, how many directional calls there would be, their hit rate (with a 95% interval) and the average
   result of a simple bracket trade (stop 1 sigma, target 1.5 sigma).
Read-only: nothing is published or saved to the engine state.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import time
from collections import Counter
from typing import Any

import numpy as np

from .config import MODEL_TIMEFRAMES, settings
from .db import get_db
from .ml import trainer
from .ml.metrics import wilson
from .services import analysis, market
from .services.runtime import Runtime
from .data.base import tf_ms

log = logging.getLogger("diagnose")


def _reason_key(a: dict[str, Any]) -> str:
    d = a.get("decision")
    if d in analysis.TRADE_DECISIONS:
        return f"TRADE {d}"
    why = (a.get("decision_reason") or d or "?").lower()
    why = re.sub(r"\d+(\.\d+)?%?", "#", why)
    return f"{d}: {why[:80]}"


def gate_replay(rt: Runtime, symbol: str, tf: str, days: float) -> dict[str, Any]:
    bundle = trainer.load_bundle(symbol, tf, rt.db)
    df = rt.candles(symbol, tf)
    if df.empty or bundle is None:
        return {"error": "no candles" if df.empty else "no active model"}
    step = tf_ms(tf)
    n = max(1, int(days * 86_400_000 / step))
    reasons: Counter = Counter()
    rows = []
    for ts in df["ts"].to_numpy()[-n:]:
        try:
            a = analysis.analyze(rt, symbol, tf, as_of=int(ts) + step, bundle=bundle, detail=False, use_cache=False)
        except Exception as exc:          # one bad bar must not stop the report
            reasons[f"ERROR {type(exc).__name__}"] += 1
            continue
        reasons[_reason_key(a)] += 1
        fc = a.get("forecast") or {}
        p = fc.get("probabilities") or {}
        rows.append({"ts": int(ts), "decision": a.get("decision"), "signal": (a.get("signal") or {}).get("signal"),
                     "p_up": p.get("up"), "p_down": p.get("down"), "predicted": fc.get("predicted"),
                     "agreement": fc.get("model_agreement"), "confidence": a.get("confidence"),
                     "setup_valid": (a.get("setup") or {}).get("valid")})
    pu = np.array([r["p_up"] for r in rows if r["p_up"] is not None], float)
    pdn = np.array([r["p_down"] for r in rows if r["p_down"] is not None], float)
    conf = np.array([r["confidence"] for r in rows if r["confidence"] is not None], float)
    return {"bars": len(rows), "reasons": dict(reasons.most_common()),
            "p_dir_median": float(np.median(np.maximum(pu, pdn))) if len(pu) else None,
            "p_dir_max": float(np.max(np.maximum(pu, pdn))) if len(pu) else None,
            "predicted": dict(Counter(r["predicted"] for r in rows)),
            "confidence_median": float(np.median(conf)) if len(conf) else None,
            "edge_confirmed": bool(bundle["edge"]["edge_confirmed"]), "edge_failed": bundle["edge"].get("failed_checks"),
            "last": rows[-3:]}


def policy_study(bundle: dict[str, Any], tf: str) -> dict[str, Any]:
    o = bundle.get("oos") or {}
    P = np.asarray(o.get("P_ens", []), float)
    if len(P) < 200:
        return {"error": "too few out-of-sample predictions"}
    fwd = np.asarray(o["fwd_ret"], float)
    mfe, mae = np.asarray(o["z_mfe"], float), np.asarray(o["z_mae"], float)
    days = (int(o["ts"][-1]) - int(o["ts"][0])) / 86_400_000 or 1
    side = np.where(P[:, 2] >= P[:, 0], 1.0, -1.0)
    pdir = np.maximum(P[:, 2], P[:, 0])
    margin = np.abs(P[:, 2] - P[:, 0])
    # one-bar bracket trade in sigma units: stop 1, target 1.5; the stop counts first when both were reached
    z_res, exp_ret = np.asarray(o["z_res"], float), np.asarray(o["exp_ret"], float)
    sigma = np.where(np.abs(z_res) > 1e-6, (fwd - exp_ret) / np.where(np.abs(z_res) > 1e-6, z_res, 1.0), np.nan)
    sigma = np.where(np.isfinite(sigma) & (sigma > 0), sigma, np.nanmedian(sigma[sigma > 0]) if (sigma > 0).any() else 0.01)
    favour = np.where(side > 0, mfe, -mae)
    adverse = np.where(side > 0, -mae, mfe)
    r = np.where(adverse >= 1.0, -1.0, np.where(favour >= 1.5, 1.5, np.clip(side * fwd / sigma, -1.0, 1.5)))
    grid = []
    for m in (0.0, 0.05, 0.10, 0.15, 0.20):
        for t in np.round(np.arange(0.30, 0.66, 0.02), 2):
            sel = (pdir >= t) & (margin >= m)
            n = int(sel.sum())
            if n < 20:
                continue
            k = int((np.sign(fwd[sel]) == side[sel]).sum())
            lo, hi = wilson(k, n)
            grid.append({"margin": m, "p_dir": float(t), "n": n, "per_day": round(n / days, 2), "hit": round(k / n, 4),
                         "ci95": [round(lo, 4), round(hi, 4)], "avg_r": round(float(r[sel].mean()), 4)})
    best = max((g for g in grid if g["n"] >= 40), key=lambda g: g["ci95"][0], default=None)
    return {"oos_bars": int(len(P)), "days": round(days, 1), "base_hit": round(float((np.sign(fwd) == side).mean()), 4),
            "best_by_lower_ci": best, "grid": grid, "selective": bundle.get("selective")}


def run(rt: Runtime, symbols: list[str], tfs: list[str], days: float, deadline: float) -> dict[str, Any]:
    out: dict[str, Any] = {"generated_at": int(time.time() * 1000), "days": days,
                           "settings": {"min_confidence": settings.min_confidence, "min_model_agreement": settings.min_model_agreement,
                                        "require_edge_for_trade": settings.require_edge_for_trade, "min_risk_reward": settings.min_risk_reward},
                           "series": {}}
    since = int(time.time() * 1000) - int(days * 86_400_000)
    out["signals_logged"] = [dict(r) for r in rt.db.query(
        "SELECT timeframe, decision, COUNT(*) AS n FROM signals WHERE created_at >= ? GROUP BY timeframe, decision ORDER BY timeframe", (since,))]
    total = Counter()
    for s in symbols:
        for tf in tfs:
            if time.time() > deadline:
                out["truncated"] = True
                return out
            key = f"{s} {tf}"
            try:
                g = gate_replay(rt, s, tf, days)
                b = trainer.load_bundle(s, tf, rt.db)
                p = policy_study(b, tf) if b else {"error": "no active model"}
            except Exception as exc:
                g, p = {"error": f"{type(exc).__name__}: {exc}"[:200]}, {}
            out["series"][key] = {"gates": g, "policy": p}
            for k, v in (g.get("reasons") or {}).items():
                total[k] += v
            log.info("%s: %s", key, dict(Counter(g.get("reasons") or {}).most_common(3)))
    out["reasons_total"] = dict(total.most_common())
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="python -m app.diagnose")
    ap.add_argument("--days", type=float, default=3)
    ap.add_argument("--timeframes", default=",".join(MODEL_TIMEFRAMES))
    ap.add_argument("--budget", type=float, default=2400)
    ap.add_argument("--out", default="diagnose.json")
    a = ap.parse_args()
    rt = Runtime(get_db(), market.make_provider())
    rep = run(rt, rt.symbols(), [t for t in a.timeframes.split(",") if t], a.days, time.time() + a.budget)
    with open(a.out, "w") as f:
        json.dump(rep, f, indent=1, default=float)
    print(json.dumps(rep["reasons_total"], indent=1))


if __name__ == "__main__":
    main()
