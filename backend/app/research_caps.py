"""v2.64 cap study (read-only): the same-side cap (live: 8 running calls of one side over all timeframes) at other sizes.

The models' walk-forward out-of-sample calls of every series (research_engine method, the live guards: grade A only on
`analysis.A_ONLY_TFS`, bigger-trend check, volume-profile wall; honest entry, record exits, costs + funding), last 30 % of
each series untouched; then the cap applied in time order at 8 (live) / 12 / 16 / 24 / 8 per timeframe / none. Per
variant: all timeframes and each timeframe (n, avg R, total R, win rate, max drawdown R), and the two halves of the test
period, so a change has to help in both. python -m app.research_caps --budget 14400 --out x.json
"""
from __future__ import annotations

import argparse
import json
import time
from typing import Any

import numpy as np

from .config import MODEL_TIMEFRAMES
from .research_ideas import Profiles, _cap, _curve, _masked


def replay(db_url: str, budget_s: float) -> dict[str, Any]:
    trades, skipped, t0, _rt = collect(db_url, budget_s)
    return summarize(trades, skipped, t0)


def collect(db_url: str, budget_s: float) -> tuple[list[dict[str, Any]], list[str], float, Any]:
    """The live-guarded out-of-sample test calls of every series (before any cap), with the runtime used."""
    from . import research_engine as RE
    from . import research_v213 as V
    from .db import Database
    from .ml import series_policy as SP
    from .services import analysis
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
    trades: list[dict[str, Any]] = []
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
        prof = Profiles(rt, s, tf)
        m = np.ones(ctx.n, bool)
        for j in np.flatnonzero(d["trade"]):
            p = prof.at(int(ctx.ts[j]))
            if p is None:
                continue
            px, atr, sd = float(ctx.close[j]), float(ctx.atr[j]), int(d["side"][j])
            lv = (p["poc"], p["vah"]) if sd > 0 else (p["poc"], p["val"])
            if any(0 < sd * (L - px) <= 0.5 * atr for L in lv):
                m[j] = False
        if tf in analysis.A_ONLY_TFS:
            m &= (d["grade"] == "A")
        dd = _masked(d, m)
        tr = V._with_funding(ctx, dd, SP.run_series(ctx, paths, test, dd, entry_mode="old", news=news))
        trades += [{**t, "side": int(dd["side"][t["j"]]), "tf": tf, "sym": s} for t in tr]
    return trades, skipped, t0, rt


def summarize(trades: list[dict[str, Any]], skipped: list[str], t0: float) -> dict[str, Any]:
    variants = {"cap8_live": _cap(trades, 8, False), "cap12": _cap(trades, 12, False), "cap16": _cap(trades, 16, False),
                "cap24": _cap(trades, 24, False), "cap8_per_tf": _cap(trades, 8, True), "no_cap": list(trades)}
    mid = float(np.median([t["ts"] for t in trades])) if trades else 0.0
    out: dict[str, Any] = {}
    for k, v in variants.items():
        out[k] = {"all": _curve(v), "first_half": _curve([t for t in v if t["ts"] < mid]),
                  "second_half": _curve([t for t in v if t["ts"] >= mid]),
                  "by_tf": {tf: _curve([t for t in v if t["tf"] == tf]) for tf in sorted({t["tf"] for t in trades})}}
    return {"ok": True, "variants": out, "trades": len(trades), "skipped": skipped[:20], "skipped_n": len(skipped),
            "seconds": round(time.time() - t0, 1)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sqlite:///./data/crypto_ai.db")
    ap.add_argument("--budget", type=float, default=14400)
    ap.add_argument("--out", default="-")
    a = ap.parse_args()
    s = json.dumps(replay(a.db, a.budget), indent=1, default=str)
    print(s) if a.out == "-" else open(a.out, "w").write(s)
