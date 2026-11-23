"""v2.80 liquidation study (read-only; owner, 23 Nov 2026: liquidation data from Coinalyze, key in env COINALYZE_API_KEY).

Fetches the liquidation history Coinalyze keeps (4-hour bars ~ 1 year, daily for longer) for every coin into the study's
copy of the state (never saved back), then tests on the same unseen calls as every study. Baseline = TODAY's live pipeline
including the v2.79 liquidity-sweep guard (coin, 6 h).
* `flush` filter: a 4h bar whose long liquidations are >= k x the median of the previous 30 bars (and >= $250k) is a
  long flush (longs wiped out, often a bottom) -> no new SHORT for W hours after it closes; a short flush (shorts
  squeezed) -> no new LONG. k in (3, 5), W in (8, 24), coin-level and BTC-level.
* `sweep+liq`: the live sweep guard only counts a sweep whose 4h bar also had a liquidation spike on the swept side
  (a stricter guard) - does it beat the plain guard?
Judged by research_verdict. python -m app.research_liq --out x.json"""
from __future__ import annotations

import argparse
import json
import time
from typing import Any

import numpy as np

H = 3_600_000
B4 = 4 * H


def flush_events(db: Any, symbol: str, k: float, min_usd: float = 250_000, look: int = 30) -> tuple[np.ndarray, np.ndarray]:
    """(close times of long flushes, close times of short flushes) from the stored 4h liquidation bars."""
    def series(kind):
        rows = db.query("SELECT ts, value FROM derivs WHERE symbol = ? AND kind = ? ORDER BY ts", (symbol, kind))
        return np.array([int(r["ts"]) for r in rows], np.int64), np.array([float(r["value"]) for r in rows])
    out = []
    for kind in ("liq_long_4hour", "liq_short_4hour"):
        ts, v = series(kind)
        ev = []
        for i in range(look, len(v)):
            med = float(np.median(v[i - look:i]))
            if v[i] >= max(min_usd, k * max(med, 1.0)):
                ev.append(int(ts[i]) + B4)
        out.append(np.array(ev, np.int64))
    return out[0], out[1]


def _recent(times: np.ndarray, t: int, hours: float) -> bool:
    i = int(np.searchsorted(times, t, side="right"))
    return i > 0 and times[i - 1] > t - hours * H


def run(db_url: str, budget_s: float) -> dict[str, Any]:
    from .data import coinalyze
    from .research_caps import collect
    from .research_risk import regime_of
    from .research_sweep import sweeps
    from .research_turn import _affected, _slim, live_pipeline
    from .research_v265 import _hook
    from .research_verdict import curve, verdict
    if not coinalyze.key():
        return {"ok": False, "reason": "COINALYZE_API_KEY secret is not set"}
    trades, skipped, t0, rt = collect(db_url, budget_s, hook=_hook)
    cache: dict = {}
    for t in trades:
        t["volatile"] = regime_of(rt, t["sym"], int(t["ts"]), cache).endswith("_volatile")
    syms = sorted({t["sym"] for t in trades} | {"BTC/USDT"})
    fetched = coinalyze.sync(rt.db, syms, intervals=("4hour", "daily"), budget_s=600)
    cover = {}
    for s in syms:
        r = rt.db.one("SELECT MIN(ts) AS a, MAX(ts) AS b, COUNT(*) AS n FROM derivs WHERE symbol = ? AND kind = 'liq_long_4hour'", (s,))
        cover[s] = {"from": r["a"], "to": r["b"], "bars": r["n"]} if r else None
    starts = [c["from"] for c in cover.values() if c and c["from"]]
    if not starts:
        return {"ok": False, "reason": "no liquidation history fetched", "fetch": fetched}
    liq_start = int(np.median(starts)) + 31 * B4          # first time a 30-bar median exists
    sample = [t for t in trades if int(t["ts"]) >= liq_start]
    # today's live pipeline: + the sweep guard (coin, 6 h)
    sw = {s: sweeps(rt, s) for s in syms}

    def sweep_times(sym, side, need_liq=None):
        x = sw.get(sym)
        if not x:
            return np.array([], np.int64)
        evs = [e["ts"] for e in x["events"] if e["side"] == side]
        if need_liq is not None:
            lt = need_liq
            evs = [t for t in evs if len(lt) and _recent(lt, t + B4, 8)]
        return np.array(sorted(evs), np.int64)

    def guard(ts_list, w=6):
        return lambda t: _recent(ts_list(t), int(t["ts"]), w)

    plain = {(s, sd): sweep_times(s, sd) for s in syms for sd in (1, -1)}
    live_now = [t for t in sample if not _recent(plain[(t["sym"], -int(t["side"]))], int(t["ts"]), 6)]
    base = live_pipeline(live_now)
    res: dict[str, Any] = {}
    fl: dict = {}
    for k in (3.0, 5.0):
        for s in syms:
            fl[(s, k)] = flush_events(rt.db, s, k)
        for src in ("coin", "btc"):
            for w in (8, 24):
                kept = []
                for t in live_now:
                    sym = t["sym"] if src == "coin" else "BTC/USDT"
                    longs, shorts = fl[(sym, k)]
                    against = longs if t["side"] < 0 else shorts     # a long flush stands against a new short
                    if _recent(against, int(t["ts"]), w):
                        continue
                    kept.append(t)
                new = live_pipeline(kept)
                v = verdict(base, new, affected=_affected(base, new))
                res[f"flush|{src}|k{k:g}|{w}h"] = {**_slim(v), "blocked": len(live_now) - len(kept)}
    # stricter sweep guard: only sweeps with a liquidation spike on the swept side
    for k in (3.0, 5.0):
        strict = {}
        for s in syms:
            longs, shorts = fl[(s, k)]
            strict[(s, 1)] = sweep_times(s, 1, longs)      # lows swept while longs were liquidated
            strict[(s, -1)] = sweep_times(s, -1, shorts)
        kept = [t for t in sample if not _recent(strict[(t["sym"], -int(t["side"]))], int(t["ts"]), 6)]
        new = live_pipeline(kept)
        v = verdict(base, new, affected=_affected(base, new))
        res[f"sweep_needs_liq|k{k:g}"] = {**_slim(v), "blocked": len(sample) - len(kept)}
    return {"ok": True, "calls_with_liq_history": len(sample), "calls_total": len(trades), "liq_history_from": liq_start,
            "fetch": fetched, "coins_covered": sum(1 for c in cover.values() if c and c["bars"]), "base": curve(base),
            "seconds": round(time.time() - t0, 1), "passes": [k for k, v in res.items() if v.get("verdict") == "PASS"],
            "variants": res}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sqlite:///./data/crypto_ai.db")
    ap.add_argument("--budget", type=float, default=14400)
    ap.add_argument("--out", default="-")
    a = ap.parse_args()
    s = json.dumps(run(a.db, a.budget), indent=1, default=str)
    print(s) if a.out == "-" else open(a.out, "w").write(s)
