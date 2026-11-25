"""v2.65 portfolio risk controller + regime study (read-only). Same unseen calls as research_caps (live guards,
honest entry, record exits, costs + funding), the live direction limit (12) applied first = BASE. Variants on top:

* btc_shock_X: no new altcoin call against a BTC move of X % or more in the last closed hour, for 4 hours
  (longs after a drop, shorts after a rise).
* loss_stop_D_W: no new call for the rest of the UTC day once calls closed that day total <= -D R, or the rest of
  the ISO week once they total <= -W R.
* corr_cap_N: altcoin calls count as BTC exposure weighted by their 168-hour return correlation with BTC (BTC = 1);
  a new call is refused when same-side open exposure would exceed N.
Each compared with research_verdict.verdict (PASS / FAIL / INCONCLUSIVE). Regime: each base call tagged with its coin's
4h regime at the call time (trend up / trend down / range, plus volatile when ATR14 > 1.5 x ATR100), from 4h candles
closed before the call; results per timeframe x regime with both halves. No look-ahead: only data before `ts`.
python -m app.research_risk --budget 14400 --out x.json"""
from __future__ import annotations

import argparse
import json
import time
from typing import Any

import numpy as np

from .research_caps import collect
from .research_ideas import _cap
from .research_verdict import curve, verdict

H = 3_600_000
DAY = 86_400_000
BTC = "BTC/USDT"


def _hourly(rt: Any, sym: str):
    df = rt.candles(sym, "1h")
    return df["ts"].to_numpy(np.int64), df["close"].to_numpy(float)


def btc_shock(trades, bts, bclose, pct: float, hold_h: int = 4):
    rets = np.r_[np.nan, bclose[1:] / bclose[:-1] - 1] * 100
    close_ts = bts + H                                   # an hourly candle is known at its close
    out = []
    for t in trades:
        if t["sym"] == BTC:
            out.append(t)
            continue
        lo = np.searchsorted(close_ts, t["ts"] - hold_h * H, side="left")
        hi = np.searchsorted(close_ts, t["ts"], side="right")
        win = rets[lo:hi]
        if t["side"] > 0 and np.nanmin(win, initial=0) <= -pct:
            continue
        if t["side"] < 0 and np.nanmax(win, initial=0) >= pct:
            continue
        out.append(t)
    return out


def loss_stop(trades, day_r: float, week_r: float):
    kept, closed = [], []
    for t in sorted(trades, key=lambda t: t["ts"]):
        d0 = t["ts"] // DAY * DAY
        w0 = d0 - ((d0 // DAY + 3) % 7) * DAY          # Monday 00:00 UTC (1970-01-01 was a Thursday)
        done = [c for c in closed if c["closed_ts"] <= t["ts"]]
        dsum = sum(c["r"] for c in done if c["closed_ts"] >= d0)
        wsum = sum(c["r"] for c in done if c["closed_ts"] >= w0)
        if dsum <= -day_r or wsum <= -week_r:
            continue
        kept.append(t)
        closed.append(t)
    return kept


def corr_cap(trades, corr_of, cap: float):
    kept, open_ = [], []
    for t in sorted(trades, key=lambda t: t["ts"]):
        open_ = [o for o in open_ if o["closed_ts"] > t["ts"]]
        w = corr_of(t)
        exp = sum(o["_w"] for o in open_ if o["side"] == t["side"])
        if exp + w > cap:
            continue
        t2 = {**t, "_w": w}
        kept.append(t2)
        open_.append(t2)
    return kept


def regime_of(rt: Any, sym: str, ts: int, cache: dict) -> str:
    if sym not in cache:
        df = rt.candles(sym, "4h")
        c, h, l = df["close"].to_numpy(float), df["high"].to_numpy(float), df["low"].to_numpy(float)
        prev = np.r_[c[0], c[:-1]]
        tr = np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))
        ema = c.copy()
        k = 2 / 51
        for i in range(1, len(c)):
            ema[i] = c[i] * k + ema[i - 1] * (1 - k)
        atr14 = np.convolve(tr, np.ones(14) / 14, mode="full")[:len(tr)]
        atr100 = np.convolve(tr, np.ones(100) / 100, mode="full")[:len(tr)]
        cache[sym] = (df["ts"].to_numpy(np.int64) + 4 * H, c, ema, atr14, atr100)
    close_ts, c, ema, a14, a100 = cache[sym]
    i = int(np.searchsorted(close_ts, ts, side="right")) - 1
    if i < 110:
        return "unknown"
    slope = ema[i] - ema[i - 6]
    if c[i] > ema[i] + 0.5 * a14[i] and slope > 0:
        base = "trend_up"
    elif c[i] < ema[i] - 0.5 * a14[i] and slope < 0:
        base = "trend_down"
    else:
        base = "range"
    return base + ("_volatile" if a100[i] > 0 and a14[i] > 1.5 * a100[i] else "")


def run(db_url: str, budget_s: float) -> dict[str, Any]:
    trades, skipped, t0, rt = collect(db_url, budget_s)
    base = _cap(trades, 12, False)
    bts, bclose = _hourly(rt, BTC)
    hourly: dict[str, Any] = {}

    def corr_of(t):
        if t["sym"] == BTC:
            return 1.0
        if t["sym"] not in hourly:
            hourly[t["sym"]] = _hourly(rt, t["sym"])
        ts_, cl = hourly[t["sym"]]
        i = int(np.searchsorted(ts_ + H, t["ts"], side="right"))
        j = int(np.searchsorted(bts + H, t["ts"], side="right"))
        if i < 170 or j < 170:
            return 1.0
        a = np.diff(np.log(cl[i - 169:i]))
        b = np.diff(np.log(bclose[j - 169:j]))
        n = min(len(a), len(b))
        if n < 50:
            return 1.0
        cc = float(np.corrcoef(a[-n:], b[-n:])[0, 1])
        return max(0.0, cc) if np.isfinite(cc) else 1.0

    variants = {}
    for pct in (2.0, 3.0):
        variants[f"btc_shock_{pct:g}"] = _cap(btc_shock(trades, bts, bclose, pct), 12, False)
    for d, w in ((3, 6), (2, 5), (4, 8)):
        variants[f"loss_stop_{d}_{w}"] = loss_stop(base, d, w)
    for cap in (6.0, 8.0, 10.0):
        variants[f"corr_cap_{cap:g}"] = corr_cap(trades, corr_of, cap)
    cache: dict = {}
    for t in trades:
        t["regime"] = regime_of(rt, t["sym"], int(t["ts"]), cache)
    # v2.65b: no new call while the coin's 4h ATR14 is above 1.5 x its ATR100 (abnormal volatility)
    calm = [t for t in trades if not t["regime"].endswith("_volatile")]
    variants["no_volatile"] = _cap(calm, 12, False)
    variants["no_volatile_loss_stop_3_6"] = loss_stop(_cap(calm, 12, False), 3, 6)
    results = {k: verdict(base, v) for k, v in variants.items()}
    mid = float(np.median([t["ts"] for t in base])) if base else 0
    regimes: dict[str, Any] = {}
    for tf in sorted({t["tf"] for t in base}):
        regimes[tf] = {}
        for rg in sorted({t["regime"] for t in base if t["tf"] == tf}):
            rows = [t for t in base if t["tf"] == tf and t["regime"] == rg]
            regimes[tf][rg] = {"all": curve(rows), "first_half": curve([t for t in rows if t["ts"] < mid]),
                               "second_half": curve([t for t in rows if t["ts"] >= mid])}
    return {"ok": True, "base": curve(base), "calls_before_cap": len(trades), "variants": results, "regimes": regimes,
            "skipped_n": len(skipped), "seconds": round(time.time() - t0, 1)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sqlite:///./data/crypto_ai.db")
    ap.add_argument("--budget", type=float, default=14400)
    ap.add_argument("--out", default="-")
    a = ap.parse_args()
    from .research_verdict import run_study
    s = json.dumps(run_study("risk", lambda: run(a.db, a.budget), a.db), indent=1, default=str)
    print(s) if a.out == "-" else open(a.out, "w").write(s)
