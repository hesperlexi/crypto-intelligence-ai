"""v2.79 liquidity-sweep study (read-only; owner, 23 Nov 2026: "institutional supply zone -> liquidity fishing -> stop-loss
pool -> stop run / liquidity grab -> that's where things change").

A SWEEP on a coin's 1h chart: the candle pokes beyond the pool of stops under the lowest low (over the highest high) of
the previous 48 hours by >= 0.1 ATR and CLOSES back inside the range (the grab and the reclaim in one candle). A bullish
sweep takes the lows' stops and reclaims (buyers absorbed the forced selling); a bearish one is the mirror. Confirmations:
* `vol`  the sweep candle's volume >= 1.5x its 20-candle average;
* `flow` big-money footprint from Binance's public archive (the `derivs` table, history up to 400 days): open interest
         FELL over the sweep hour (forced closes / stop flush, <= -0.3 %) and the taker buy/sell ratio of that hour points
         the reclaim way (> 1 bullish, < 1 bearish). Live, the same numbers come hourly from OKX (`mkt_okx`).

Uses tested on the same unseen calls as every study (research_caps.collect, baseline = the live pipeline):
* FILTER - no new short within `w` hours after a bullish sweep on the coin (or on BTC), no new long after a bearish one;
* SIGNAL - trade the reclaim: enter at the sweep candle's close, stop 0.1 ATR beyond the sweep extreme, targets 1 / 1.75 /
           2.5R, 50/25/25, break-even after TP1, 30-hour limit, followed on 15m candles, 0.15 % costs + funding; added to
           the live calls (same-side limit and loss stops apply).
Judged by research_verdict (PASS = better in both halves, drawdown <= 15 % deeper, bootstrap >= 80 %, >= 100 calls differ).
python -m app.research_sweep --budget 14400 --out x.json"""
from __future__ import annotations

import argparse
import json
import time
from typing import Any

import numpy as np
import pandas as pd

H = 3_600_000
POOL = 48
POKE_ATR = 0.1
VOL_X = 1.5
OI_FLUSH = -0.003
HORIZON_H = 30
COST = 0.15


def _atr(h, l, c, n=14):
    prev = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))
    return pd.Series(tr).rolling(n, min_periods=1).mean().to_numpy()


def derivs_hourly(db: Any, symbol: str, kind: str) -> dict[int, float]:
    try:
        return {int(r["ts"]): float(r["value"]) for r in db.query("SELECT ts, value FROM derivs WHERE symbol = ? AND kind = ?", (symbol, kind))}
    except Exception:
        return {}


def sweeps(rt: Any, symbol: str) -> dict[str, Any] | None:
    """Every sweep on the coin's 1h candles: list of dicts {ts (close), side (+1 bull / -1 bear), extreme, level, close,
    atr, vol (bool), flow (bool or None)}."""
    try:
        d = rt.candles(symbol, "1h").reset_index(drop=True)
    except Exception:
        return None
    if d is None or len(d) < POOL + 30:
        return None
    o, h, l, c, v = (d[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    ts = d["ts"].to_numpy(np.int64)
    atr = _atr(h, l, c)
    lo_pool = pd.Series(l).shift(1).rolling(POOL).min().to_numpy()
    hi_pool = pd.Series(h).shift(1).rolling(POOL).max().to_numpy()
    vavg = pd.Series(v).shift(1).rolling(20).mean().to_numpy()
    oi = derivs_hourly(rt.db, symbol, "oi_1h")
    tk = derivs_hourly(rt.db, symbol, "taker_1h")
    out = []
    for i in range(POOL + 1, len(c)):
        if not np.isfinite(lo_pool[i]) or atr[i] <= 0:
            continue
        side = 0
        if l[i] <= lo_pool[i] - POKE_ATR * atr[i] and c[i] > lo_pool[i]:
            side, ext, lvl = 1, l[i], lo_pool[i]
        elif h[i] >= hi_pool[i] + POKE_ATR * atr[i] and c[i] < hi_pool[i]:
            side, ext, lvl = -1, h[i], hi_pool[i]
        if not side:
            continue
        hr = int(ts[i])
        a, b = oi.get(hr - H), oi.get(hr)
        t = tk.get(hr)
        flow = None
        if a and b and t:
            flow = bool((b / a - 1) <= OI_FLUSH and ((t > 1) if side > 0 else (t < 1)))
        out.append({"ts": hr + H, "side": side, "extreme": float(ext), "level": float(lvl), "close": float(c[i]),
                    "atr": float(atr[i]), "vol": bool(np.isfinite(vavg[i]) and v[i] >= VOL_X * vavg[i]), "flow": flow})
    return {"events": out, "has_flow": bool(oi and tk)}


def follow_sweep(rt: Any, symbol: str, e: dict[str, Any], cache: dict) -> dict[str, Any] | None:
    from .engine.futures import DEFAULT_FUNDING_RATE
    from .ml import series_sim as S
    if symbol not in cache:
        try:
            d = rt.candles(symbol, "15m")
            cache[symbol] = tuple(d[k].to_numpy(np.int64 if k == "ts" else float) for k in ("ts", "open", "high", "low", "close"))
        except Exception:
            cache[symbol] = None
    a = cache[symbol]
    if a is None:
        return None
    ts, op, hi, lo, cl = a
    i, j = np.searchsorted(ts, e["ts"]), np.searchsorted(ts, e["ts"] + HORIZON_H * H)
    if j - i < 4:
        return None
    side, entry = e["side"], e["close"]
    stop = e["extreme"] - side * POKE_ATR * e["atr"]
    if side * (entry - stop) <= entry * 0.002:              # stop too tight for costs
        return None
    out = S.follow(side, entry, stop, S.ladder(side, entry, stop), hi[i:j], lo[i:j], cl[i:j], complete=True, open_=op[i:j])
    if out is None:
        return None
    closed = int(ts[i + out.exit_idx]) + 900_000
    r = out.net_r(COST) - (side * (closed - e["ts"]) / H * DEFAULT_FUNDING_RATE / 8 * 100) / out.risk_pct
    return {"r": float(r), "closed_ts": closed, "status": out.status}


def _recent(times: np.ndarray, t: int, hours: float) -> bool:
    k = int(np.searchsorted(times, t, side="right"))
    return k > 0 and times[k - 1] > t - hours * H


def run(db_url: str, budget_s: float) -> dict[str, Any]:
    from .research_caps import collect
    from .research_risk import regime_of
    from .research_turn import _affected, _slim, live_pipeline
    from .research_v265 import _hook
    from .research_verdict import curve, verdict
    trades, skipped, t0, rt = collect(db_url, budget_s, hook=_hook)
    cache: dict = {}
    for t in trades:
        t["volatile"] = regime_of(rt, t["sym"], int(t["ts"]), cache).endswith("_volatile")
    if not trades:
        return {"ok": False, "reason": "no test calls"}
    test_start = min(int(t["ts"]) for t in trades)
    test_end = max(int(t["ts"]) for t in trades)
    base = live_pipeline(trades)
    syms = sorted({t["sym"] for t in trades} | {"BTC/USDT"})
    ev = {s: sweeps(rt, s) for s in syms}
    has_flow = sorted(s for s, x in ev.items() if x and x["has_flow"])

    def times(sym: str, side: int, conf: str) -> np.ndarray:
        x = ev.get(sym)
        if not x:
            return np.array([], np.int64)
        ok = [e for e in x["events"] if e["side"] == side and (conf == "any" or (conf == "vol" and e["vol"]) or
                                                              (conf == "flow" and e["flow"]))]
        return np.array(sorted(e["ts"] for e in ok), np.int64)

    tcache: dict = {}

    def tget(sym, side, conf):
        k = (sym, side, conf)
        if k not in tcache:
            tcache[k] = times(sym, side, conf)
        return tcache[k]

    res: dict[str, Any] = {}
    # ---- FILTER ----------------------------------------------------------------------------------------------------------
    for src in ("coin", "btc"):
        for conf in ("any", "vol", "flow"):
            for w in (6, 12, 24):
                kept = []
                for t in trades:
                    sym = t["sym"] if src == "coin" else "BTC/USDT"
                    # a bullish sweep (side +1) stands against a new short, a bearish one against a new long
                    if _recent(tget(sym, -int(t["side"]), conf), int(t["ts"]), w):
                        continue
                    kept.append(t)
                new = live_pipeline(kept)
                v = verdict(base, new, affected=_affected(base, new))
                res[f"filter|{src}|{conf}|{w}h"] = {**_slim(v), "blocked": len(trades) - len(kept)}
    # ---- SIGNAL ----------------------------------------------------------------------------------------------------------
    fcache: dict = {}
    standalone: dict[str, Any] = {}
    for conf in ("any", "vol", "flow"):
        st = []
        for s in syms:
            x = ev.get(s)
            if not x:
                continue
            busy = 0
            for e in x["events"]:
                if not (test_start <= e["ts"] <= test_end) or e["ts"] < busy:
                    continue
                if conf == "vol" and not e["vol"] or conf == "flow" and not e["flow"]:
                    continue
                f = follow_sweep(rt, s, e, fcache)
                if f is None:
                    continue
                busy = f["closed_ts"]
                st.append({"sym": s, "tf": "sweep", "ts": e["ts"], "side": e["side"], **f})
        standalone[conf] = {"all": curve(st), "long": curve([t for t in st if t["side"] > 0]),
                            "short": curve([t for t in st if t["side"] < 0])}
        new = live_pipeline(trades + st)
        v = verdict(base, new, affected=_affected(base, new))
        res[f"signal|{conf}"] = {**_slim(v), "sweep_trades": len(st)}
    ranked = sorted(res.items(), key=lambda kv: -((kv[1].get("new") or {}).get("total_r") or -1e9))
    return {"ok": True, "calls": len(trades), "base_calls": len(base), "base": curve(base), "test_start": test_start,
            "seconds": round(time.time() - t0, 1), "coins_with_flow_history": has_flow,
            "sweep_events_in_test": {s: sum(1 for e in (x or {}).get("events", []) if test_start <= e["ts"] <= test_end) for s, x in ev.items()},
            "passes": [k for k, v in res.items() if v.get("verdict") == "PASS"],
            "top5": [{"variant": k, "verdict": v.get("verdict"), "total_r": (v.get("new") or {}).get("total_r"),
                      "max_dd": (v.get("new") or {}).get("max_dd_r"), "boot": v.get("bootstrap_better_share"),
                      "halves": v.get("halves")} for k, v in ranked[:5]],
            "signal_standalone": standalone, "variants": res}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sqlite:///./data/crypto_ai.db")
    ap.add_argument("--budget", type=float, default=14400)
    ap.add_argument("--out", default="-")
    a = ap.parse_args()
    s = json.dumps(run(a.db, a.budget), indent=1, default=str)
    print(s) if a.out == "-" else open(a.out, "w").write(s)
