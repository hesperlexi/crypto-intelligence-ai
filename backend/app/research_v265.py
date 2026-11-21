"""v2.65 studies (read-only), every one judged by research_verdict on the same unseen calls (live guards, direction
limit 12, honest entry, record exits, costs + funding):

1. trade_filter_v1: the per-model AI trade filter, re-trained on each series' TUNING calls only (the live bundles'
   filters saw the test rows) and applied to its test calls. base = with the filter (live), new = without.
2. drift_downgrade: block a call when the series' direction hit rate over its last 100 out-of-sample bars is more than
   2 standard errors below its tuning-period rate (only bars whose outcome was known at the call). base = live, new = with it.
Per timeframe and overall. python -m app.research_v265 --budget 14400 --out x.json"""
from __future__ import annotations

import argparse
import json
import time
from typing import Any

import numpy as np

from .research_caps import collect
from .research_ideas import _cap
from .research_verdict import curve, verdict

WINDOW = 100
REASONS: dict[str, int] = {}


def _hook(rt: Any, sym: str, tf: str, ctx: Any, tune: np.ndarray, test: np.ndarray, trades: list[dict[str, Any]]) -> None:
    from .ml import trade_filter as TF
    from .ml.trainer import _cost
    # ---- 1. per-model trade filter trained on tuning rows only -------------------------------------------------------
    if ctx.X is not None:
        ind = rt.frame(sym, tf).ind
        ti = np.flatnonzero(tune)
        f = TF.train(ctx.X[ti], ctx.P[ti], ctx.rows[ti], ind["high"].to_numpy(float), ind["low"].to_numpy(float),
                     ind["close"].to_numpy(float), ind["atr"].to_numpy(float), _cost())
        on = bool(f.get("enabled") and f.get("model") is not None)
        why = "on" if on else str(f.get("reason") or "off").split(" labelled")[0][:40]
        REASONS[why] = REASONS.get(why, 0) + 1
        for t in trades:
            j = int(t["j"])
            t["v1_on"] = on
            if not on or not np.isfinite(ctx.X[j]).all():
                t["v1_block"] = False
                continue
            F = TF._features(ctx.X[j:j + 1], ctx.P[j:j + 1], np.array([int(t["side"])]))
            t["v1_block"] = bool(f["model"].predict_proba(F)[:, 1][0] < f["threshold"])
    # ---- 2. drift: recent direction hit rate vs the tuning period ---------------------------------------------------
    if ctx.fwd_sign is not None:
        call = np.sign(ctx.P[:, 2] - ctx.P[:, 0])
        known = np.isfinite(ctx.fwd_sign) & (ctx.fwd_sign != 0) & (call != 0)
        hit = (call == ctx.fwd_sign) & known
        tk = tune & known
        ref = float(hit[tk].sum() / max(1, tk.sum()))
        se = np.sqrt(max(ref * (1 - ref), 1e-6) / WINDOW)
        kidx = np.flatnonzero(known)
        for t in trades:
            j = int(t["j"])
            prev = kidx[kidx < j][-WINDOW:]        # bar j-1's outcome is known when bar j closes
            if len(prev) < WINDOW:
                t["drift_block"] = False
                continue
            t["drift_block"] = bool(hit[prev].mean() < ref - 2 * se)


def _by_tf(base, new):
    out = {}
    for tf in sorted({t["tf"] for t in base} | {t["tf"] for t in new}):
        b = [t for t in base if t["tf"] == tf]
        n = [t for t in new if t["tf"] == tf]
        out[tf] = verdict(b, n) if b else {"verdict": "INCONCLUSIVE", "new": curve(n)}
    return out


def _slim(v):
    return {k: v.get(k) for k in ("verdict", "reason", "base", "new", "affected", "bootstrap_better_share",
                                  "bootstrap_gain_r_5_50_95")} | {"halves": {h: {"base": x["base"].get("total_r"), "new": x["new"].get("total_r")}
                                                                              for h, x in (v.get("halves") or {}).items()}}


def run(db_url: str, budget_s: float) -> dict[str, Any]:
    trades, skipped, t0, _rt = collect(db_url, budget_s, hook=_hook)
    from .research_risk import loss_stop, regime_of
    cache: dict = {}
    for t in trades:
        t["volatile"] = regime_of(_rt, t["sym"], int(t["ts"]), cache).endswith("_volatile")
    live = _cap(trades, 12, False)                                                 # today, without any v1 filter
    with_v1 = _cap([t for t in trades if not t.get("v1_block")], 12, False)
    with_drift = _cap([t for t in trades if not t.get("drift_block")], 12, False)
    calm_drift = [t for t in trades if not t.get("drift_block") and not t["volatile"]]
    veto = loss_stop(_cap(calm_drift, 12, False), 3, 6)          # the capital-protection package: drift + volatility + loss stop
    v1_series = len({(t["sym"], t["tf"]) for t in trades if t.get("v1_on")})
    return {"ok": True, "calls": len(trades), "seconds": round(time.time() - t0, 1), "skipped": skipped[:20],
            "skipped_n": len(skipped),
            "trade_filter_v1": {"series_with_filter_on": v1_series, "blocked": sum(1 for t in trades if t.get("v1_block")),
                                "overall_remove_filter": _slim(verdict(with_v1, live)),
                                "by_tf_remove_filter": {k: _slim(v) for k, v in _by_tf(with_v1, live).items()}},
            "v1_train_outcomes": REASONS,
            "veto_package": {"overall": _slim(verdict(live, veto)), "by_tf": {k: _slim(v) for k, v in _by_tf(live, veto).items()}},
            "drift_downgrade": {"blocked": sum(1 for t in trades if t.get("drift_block")),
                                "overall": _slim(verdict(live, with_drift)),
                                "by_tf": {k: _slim(v) for k, v in _by_tf(live, with_drift).items()}}}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sqlite:///./data/crypto_ai.db")
    ap.add_argument("--budget", type=float, default=14400)
    ap.add_argument("--out", default="-")
    a = ap.parse_args()
    s = json.dumps(run(a.db, a.budget), indent=1, default=str)
    print(s) if a.out == "-" else open(a.out, "w").write(s)
