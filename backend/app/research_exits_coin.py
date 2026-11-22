"""v2.68 per-coin exits study (read-only). The same unseen 15m / 1h / 4h calls as the v2.40 exit study, followed with
each exit rule (research_exits.VARIANTS: live base, early break-even, lock, give-back close, nearer TP1). For every coin
and timeframe the rule is CHOSEN on the first 70 % of its calls (tuning: at least MIN_TUNE calls and +MIN_GAIN R a call
better than the live rule, else the live rule stays) and JUDGED on the untouched last 30 %, with the live direction limit
of 12. Verdict by research_verdict (affected = calls whose result differs).  python -m app.research_exits_coin"""
from __future__ import annotations

import argparse
import json
from typing import Any

import numpy as np

from .research_exits import VARIANTS, replay
from .research_ideas import _cap
from .research_verdict import verdict

MIN_TUNE, MIN_GAIN = 30, 0.03


def run(db_url: str, budget_s: float) -> dict[str, Any]:
    r = replay(db_url, budget_s, raw=True)
    res = r["res"]
    series = sorted({(t["sym"], t["tf"]) for t in res["base"]["tune"]})
    choice: dict[str, str] = {}
    for s, tf in series:
        def avg(name):
            v = [t["r"] for t in res[name]["tune"] if t["sym"] == s and t["tf"] == tf]
            return (float(np.mean(v)) if v else None), len(v)
        b, n = avg("base")
        best, best_avg = "base", b
        if b is not None and n >= MIN_TUNE:
            for name in VARIANTS:
                a, _ = avg(name)
                if name != "base" and a is not None and a > (best_avg or -9) and a >= b + MIN_GAIN:
                    best, best_avg = name, a
        choice[f"{s}|{tf}"] = best
    base = [t for t in res["base"]["test"]]
    new: list[dict[str, Any]] = []
    for (s, tf) in series:
        name = choice[f"{s}|{tf}"]
        new += [t for t in res[name]["test"] if t["sym"] == s and t["tf"] == tf]
    base, new = _cap(base, 12, False), _cap(new, 12, False)
    kb = {(t["sym"], t["tf"], int(t["ts"])): round(t["r"], 4) for t in base}
    kn = {(t["sym"], t["tf"], int(t["ts"])): round(t["r"], 4) for t in new}
    affected = sum(1 for k in set(kb) | set(kn) if kb.get(k) != kn.get(k))
    out = {"overall": verdict(base, new, affected=affected)}
    for tf in sorted({t["tf"] for t in base}):
        b = [t for t in base if t["tf"] == tf]
        n = [t for t in new if t["tf"] == tf]
        aff = sum(1 for k in set(kb) | set(kn) if k[1] == tf and kb.get(k) != kn.get(k))
        out[tf] = verdict(b, n, affected=aff)
    counts: dict[str, int] = {}
    for v in choice.values():
        counts[v] = counts.get(v, 0) + 1
    return {"ok": True, "series": len(series), "chosen": counts, "choice": choice, "verdict": out,
            "seconds": r["seconds"], "skipped_n": len(r["skipped"])}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sqlite:///./data/crypto_ai.db")
    ap.add_argument("--budget", type=float, default=14400)
    ap.add_argument("--out", default="-")
    a = ap.parse_args()
    s = json.dumps(run(a.db, a.budget), indent=1, default=str)
    print(s) if a.out == "-" else open(a.out, "w").write(s)
