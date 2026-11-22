"""v2.68 slot study (read-only; owner, 22 Nov 2026: "the longer timeframes take the quota - keep a free slot for each
timeframe, or 20 with 5 per timeframe"). Same unseen calls and live guards as the v2.65 study, with today's live
capital-protection package (drift + abnormal volatility + loss stop 3R / 6R). Compares the live direction limit (12 per
side over all timeframes) with:
  reserve1   12 per side, but a timeframe with no running call on that side may always open one
  tf4        12 per side and at most 4 per timeframe
  cap20_tf5  20 per side and at most 5 per timeframe
  cap16_tf4  16 per side and at most 4 per timeframe
Each judged by research_verdict (overall and per timeframe). python -m app.research_slots --budget 14400 --out x.json"""
from __future__ import annotations

import argparse
import json
import time
from typing import Any

from .research_caps import collect
from .research_v265 import _by_tf, _hook, _slim
from .research_verdict import verdict


def slots(trades: list[dict[str, Any]], total: int, per_tf: int | None = None, reserve: bool = False) -> list[dict[str, Any]]:
    """Walk calls in time order; refuse one when `total` same-side calls run (unless `reserve` and its timeframe has none
    running on that side) or when its timeframe already has `per_tf` same-side calls running."""
    kept, open_ = [], []
    for t in sorted(trades, key=lambda t: t["ts"]):
        open_ = [o for o in open_ if o["closed_ts"] > t["ts"]]
        same = [o for o in open_ if o["side"] == t["side"]]
        same_tf = [o for o in same if o["tf"] == t["tf"]]
        if per_tf is not None and len(same_tf) >= per_tf:
            continue
        if len(same) >= total and not (reserve and not same_tf):
            continue
        kept.append(t)
        open_.append(t)
    return kept


def run(db_url: str, budget_s: float) -> dict[str, Any]:
    trades, skipped, t0, rt = collect(db_url, budget_s, hook=_hook)
    from .research_risk import loss_stop, regime_of
    cache: dict = {}
    for t in trades:
        t["volatile"] = regime_of(rt, t["sym"], int(t["ts"]), cache).endswith("_volatile")
    calm = [t for t in trades if not t.get("drift_block") and not t["volatile"]]
    pack = lambda kept: loss_stop(kept, 3, 6)                       # noqa: E731 - today's live package after the limit
    live = pack(slots(calm, 12))
    variants = {"reserve1": pack(slots(calm, 12, reserve=True)), "tf4": pack(slots(calm, 12, per_tf=4)),
                "cap20_tf5": pack(slots(calm, 20, per_tf=5)), "cap16_tf4": pack(slots(calm, 16, per_tf=4))}
    out = {k: {"overall": _slim(verdict(live, v)), "by_tf": {tf: _slim(x) for tf, x in _by_tf(live, v).items()},
               "calls_by_tf": {tf: sum(1 for t in v if t["tf"] == tf) for tf in sorted({t["tf"] for t in calm})}}
           for k, v in variants.items()}
    return {"ok": True, "calls": len(trades), "seconds": round(time.time() - t0, 1), "skipped_n": len(skipped),
            "live_calls_by_tf": {tf: sum(1 for t in live if t["tf"] == tf) for tf in sorted({t["tf"] for t in calm})},
            "variants": out}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sqlite:///./data/crypto_ai.db")
    ap.add_argument("--budget", type=float, default=14400)
    ap.add_argument("--out", default="-")
    a = ap.parse_args()
    s = json.dumps(run(a.db, a.budget), indent=1, default=str)
    print(s) if a.out == "-" else open(a.out, "w").write(s)
