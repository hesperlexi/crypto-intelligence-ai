"""Engine ideas (owner, 14 Nov 2026) - read-only replay (python -m app.research ideas).

Same calls and method as research_early: the models' walk-forward out-of-sample calls of every series through the live
decision rules (current grading), honest entry (market; v2.5 pullback limit for BUY ON PULLBACK), the record's exits,
0.15 % round trip + funding, one call at a time per series. Each variant is chosen on the first 70 % of every series
(tune) and judged on the untouched last 30 % (test). A refused call never blocks its series (live: NO TRADE).
  1. BTC trend filter      skip (or keep only grade A) calls against BTC's 4h / 1d trend (close vs EMA, closed bars only).
  2. Exposure cap          portfolio level: refuse a call while N calls of the same side are open (per timeframe / all).
  3. Volume profile        profile of the coin's last 200 bars (50 bins, typical price): (a) skip a long with POC / VAH
                           just above within k ATR (a short with POC / VAL just below); (b) TP2 / TP3 capped at the next
                           profile level beyond TP1.
  4. Fee filter            skip calls whose stop distance is below X % of the price.
Aggregates only (public results branch)."""
from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from .config import MODEL_TIMEFRAMES, settings
from .data.base import tf_ms
from .ml import series_sim as S

log = logging.getLogger(__name__)

BTC_VARIANTS = {
    "against 4h EMA50: skip": ("4h", 50, "skip"),
    "against 4h EMA200: skip": ("4h", 200, "skip"),
    "against 1d EMA50: skip": ("1d", 50, "skip"),
    "against 1d EMA200: skip": ("1d", 200, "skip"),
    "against 4h EMA50: grade A only": ("4h", 50, "a_only"),
    "against 1d EMA50: grade A only": ("1d", 50, "a_only"),
    "against both 4h+1d EMA50: skip": ("both", 50, "skip"),
}
VP_FILTER = {f"VP filter k={k} ATR": k for k in (0.5, 1.0, 1.5)}
FEE_X = (0.6, 0.8, 1.0, 1.5)
CAPS = (3, 5, 8)
VP_LOOKBACK, VP_BINS, VP_AREA = 200, 50, 0.70


# ---- helpers -------------------------------------------------------------------------------------------------------

def _ema(x: np.ndarray, n: int) -> np.ndarray:
    a = 2.0 / (n + 1)
    out = np.empty_like(x, dtype=float)
    m = float(x[0])
    for i, v in enumerate(x):
        m = a * float(v) + (1 - a) * m
        out[i] = m
    return out


class BtcTrend:
    """BTC trend (+1 / -1 / 0) at a decision time from CLOSED bars only."""

    def __init__(self, rt):
        self.t: dict[tuple[str, int], tuple[np.ndarray, np.ndarray]] = {}
        for tf in ("4h", "1d"):
            try:
                df = rt.candles("BTC/USDT", tf)
            except Exception:
                continue
            if df is None or len(df) < 250:
                continue
            ts = df["ts"].to_numpy(np.int64) + tf_ms(tf)          # close time of each bar
            cl = df["close"].to_numpy(float)
            for n in (50, 200):
                self.t[(tf, n)] = (ts, np.sign(cl - _ema(cl, n)))

    def at(self, tf: str, n: int, t: int) -> float:
        v = self.t.get((tf, n))
        if v is None:
            return 0.0
        i = int(np.searchsorted(v[0], t, side="right")) - 1
        return float(v[1][i]) if i >= 200 else 0.0


def _profile(h: np.ndarray, l: np.ndarray, c: np.ndarray, v: np.ndarray) -> dict[str, float] | None:
    lo, hi = float(np.min(l)), float(np.max(h))
    if not np.isfinite(lo) or hi <= lo or v.sum() <= 0:
        return None
    tp = (h + l + c) / 3
    bins = np.clip(((tp - lo) / (hi - lo) * VP_BINS).astype(int), 0, VP_BINS - 1)
    vol = np.bincount(bins, weights=v, minlength=VP_BINS)
    centers = lo + (np.arange(VP_BINS) + 0.5) * (hi - lo) / VP_BINS
    p = int(np.argmax(vol))
    a, b, tot = p, p, vol[p]
    while tot < VP_AREA * vol.sum() and (a > 0 or b < VP_BINS - 1):
        up = vol[b + 1] if b < VP_BINS - 1 else -1
        dn = vol[a - 1] if a > 0 else -1
        if up >= dn:
            b += 1
            tot += vol[b]
        else:
            a -= 1
            tot += vol[a]
    return {"poc": float(centers[p]), "vah": float(centers[b]), "val": float(centers[a])}


class Profiles:
    def __init__(self, rt, symbol: str, tf: str):
        try:
            df = rt.candles(symbol, tf)
        except Exception:
            df = None
        self.ok = df is not None and len(df) > VP_LOOKBACK and "volume" in df
        if self.ok:
            self.ts = df["ts"].to_numpy(np.int64)
            self.h, self.l = df["high"].to_numpy(float), df["low"].to_numpy(float)
            self.c, self.v = df["close"].to_numpy(float), df["volume"].to_numpy(float)
        self.cache: dict[int, dict | None] = {}

    def at(self, bar_ts: int) -> dict[str, float] | None:
        """Profile of the last VP_LOOKBACK bars up to and including the decision bar (opened at bar_ts)."""
        if not self.ok:
            return None
        if bar_ts not in self.cache:
            i = int(np.searchsorted(self.ts, bar_ts, side="right"))
            s = i - VP_LOOKBACK
            self.cache[bar_ts] = _profile(self.h[s:i], self.l[s:i], self.c[s:i], self.v[s:i]) if s >= 0 else None
        return self.cache[bar_ts]


def _masked(d: dict, keep: np.ndarray) -> dict:
    return {**d, "trade": d["trade"] & keep}


def _curve(trades: list[dict[str, Any]]) -> dict[str, Any]:
    r = [t["r"] for t in sorted(trades, key=lambda t: t["closed_ts"])]
    if not r:
        return {"n": 0}
    c = np.cumsum(r)
    dd = float(np.max(np.maximum.accumulate(np.r_[0.0, c])[1:] - c)) if len(c) else 0.0
    return {"n": len(r), "avg_r": round(float(np.mean(r)), 4), "total_r": round(float(np.sum(r)), 2),
            "win_rate": round(float(np.mean(np.array(r) > 0)), 3), "max_dd_r": round(max(dd, 0.0), 2)}


def _cap(trades: list[dict[str, Any]], n: int, per_tf: bool) -> list[dict[str, Any]]:
    """Walk all trades in time order; refuse one while `n` trades of the same side (same timeframe if per_tf) are open."""
    kept, open_ = [], []
    for t in sorted(trades, key=lambda t: t["ts"]):
        open_ = [o for o in open_ if o["closed_ts"] > t["ts"]]
        same = [o for o in open_ if o["side"] == t["side"] and (not per_tf or o["tf"] == t["tf"])]
        if len(same) >= n:
            continue
        kept.append(t)
        open_.append(t)
    return kept


def run(db_url: str, budget_s: float, symbols: list[str] | None = None, tfs: list[str] | None = None) -> dict[str, Any]:
    from . import research_engine as RE
    from . import research_v213 as V
    from .db import Database
    from .ml import series_policy as SP
    from .services.runtime import Runtime

    class _Prov:
        name = "binance"

    db = Database(db_url)
    rt = Runtime(db, _Prov())
    ex = db.one("SELECT exchange, COUNT(*) AS n FROM market_data GROUP BY exchange ORDER BY n DESC LIMIT 1")
    if ex:
        _Prov.name = ex["exchange"]
    t0 = time.time()
    syms = symbols or [r["symbol"] for r in db.query("SELECT DISTINCT symbol FROM model_versions WHERE active = 1 ORDER BY symbol")]
    news = RE._news_fn(rt.db)
    btc = BtcTrend(rt)
    frames: dict = {}
    names = (["baseline"] + list(BTC_VARIANTS) + list(VP_FILTER) + ["VP target cap"] +
             [f"fee filter {x}%" for x in FEE_X])
    res = {p: {v: {} for v in names} for p in ("tune", "test")}
    weeks = {"tune": {}, "test": {}}
    skipped, check = [], {"series": 0, "baseline_equal": 0}
    orig_sim = SP.simulate
    vp_cur: dict[str, Any] = {"prof": None, "on": False}

    def sim_capped(ctx, paths, j, side, pl, entry_mode="old", k=0.0, cost_pct=None):
        if not vp_cur["on"]:
            return orig_sim(ctx, paths, j, side, pl, entry_mode, k, cost_pct)
        prof = vp_cur["prof"].at(int(ctx.ts[j])) if vp_cur["prof"] else None
        if prof is None:
            return orig_sim(ctx, paths, j, side, pl, entry_mode, k, cost_pct)
        lad = S.ladder

        def capped(sd, entry, stop, mult=S.TP_LADDER):
            tps = lad(sd, entry, stop, mult)
            lv = sorted(x for x in (prof["poc"], prof["vah"], prof["val"]) if sd * (x - tps[0]) > 0 and sd * (tps[2] - x) > 0)
            if lv:
                L = lv[0] if sd > 0 else lv[-1]
                tps[2] = L
                tps[1] = tps[1] if sd * (L - tps[1]) >= 0 else L
            return tps
        S.ladder = capped
        try:
            return orig_sim(ctx, paths, j, side, pl, entry_mode, k, cost_pct)
        finally:
            S.ladder = lad

    def trades(ctx, paths, mask, d, side_arr, tf):
        tr = V._with_funding(ctx, d, SP.run_series(ctx, paths, mask, d, entry_mode="old", news=news))
        return [{**t, "side": int(side_arr[t["j"]]), "tf": tf} for t in tr]

    try:
        for s, tf in [(s, tf) for tf in RE.TF_ORDER if tf in (tfs or MODEL_TIMEFRAMES) for s in syms]:
            if time.time() > t0 + budget_s:
                skipped.append(f"{s} {tf}: time budget")
                continue
            try:
                b = RE.build(rt, s, tf, frames)
            except Exception as exc:
                skipped.append(f"{s} {tf}: {type(exc).__name__}")
                continue
            if b is None:
                skipped.append(f"{s} {tf}: no model / too few out-of-sample bars")
                continue
            ctx, paths = b
            tune, test, _ = RE._split(ctx)
            if tune.sum() < 150 or test.sum() < 30:
                skipped.append(f"{s} {tf}: span too short to split")
                continue
            key = f"{s} {tf}"
            weeks["tune"][key], weeks["test"][key] = RE._weeks(ctx, tune), RE._weeks(ctx, test)
            d = SP.decide(ctx, tune, require_edge=False)
            side = d["side"]
            dts = ctx.decision_ts
            # per-row keep masks of the filters
            keeps: dict[str, np.ndarray] = {}
            for name, (htf, n, mode) in BTC_VARIANTS.items():
                k = np.ones(ctx.n, bool)
                for j in np.flatnonzero(d["trade"]):
                    if htf == "both":
                        against = side[j] * btc.at("4h", n, int(dts[j])) < 0 and side[j] * btc.at("1d", n, int(dts[j])) < 0
                    else:
                        against = side[j] * btc.at(htf, n, int(dts[j])) < 0
                    if against and (mode == "skip" or d["grade"][j] != "A"):
                        k[j] = False
                keeps[name] = k
            prof = Profiles(rt, s, tf)
            for name, kk in VP_FILTER.items():
                k = np.ones(ctx.n, bool)
                for j in np.flatnonzero(d["trade"]):
                    p = prof.at(int(ctx.ts[j]))
                    if p is None:
                        continue
                    px, atr = float(ctx.close[j]), float(ctx.atr[j])
                    lv = (p["poc"], p["vah"]) if side[j] > 0 else (p["poc"], p["val"])
                    if any(0 < side[j] * (L - px) <= kk * atr for L in lv):
                        k[j] = False
                keeps[name] = k
            for x in FEE_X:
                k = np.ones(ctx.n, bool)
                for j in np.flatnonzero(d["trade"]):
                    pl = d["plan"][j]
                    if pl and pl.get("stop") and abs(float(ctx.close[j]) - float(pl["stop"])) / float(ctx.close[j]) * 100 < x:
                        k[j] = False
                keeps[f"fee filter {x}%"] = k
            for part, mask in (("tune", tune), ("test", test)):
                base = trades(ctx, paths, mask, d, side, tf)
                res[part]["baseline"][key] = base
                if part == "test":                       # self-check: the replay of research_early's baseline
                    ref = V._with_funding(ctx, d, SP.run_series(ctx, paths, mask, d, entry_mode="old", news=news))
                    check["series"] += 1
                    check["baseline_equal"] += int(len(ref) == len(base) and all(abs(a["r"] - b_["r"]) < 1e-12 for a, b_ in zip(ref, base)))
                for name, k in keeps.items():
                    res[part][name][key] = trades(ctx, paths, mask, _masked(d, k), side, tf)
                vp_cur.update(prof=prof, on=True)
                SP.simulate = sim_capped
                try:
                    res[part]["VP target cap"][key] = trades(ctx, paths, mask, d, side, tf)
                finally:
                    SP.simulate = orig_sim
                    vp_cur["on"] = False
            log.info("%s: done", key)
    finally:
        SP.simulate = orig_sim
    tables = {p: {v: RE._table(res[p][v], weeks[p]) for v in names} for p in res}

    def pick(group: list[str]) -> dict[str, Any]:
        best = max(group, key=lambda v: tables["tune"][v]["overall"].get("expectancy_r") or -9)
        f = lambda p, v: {k: tables[p][v]["overall"].get(k) for k in ("n", "expectancy_r", "total_r", "win_rate", "max_drawdown_r")}  # noqa: E731
        return {"chosen_on_tune": best, "tune": f("tune", best), "tune_baseline": f("tune", "baseline"),
                "test": f("test", best), "test_baseline": f("test", "baseline"),
                "test_by_tf": {tf: {"chosen": tables["test"][best]["by_timeframe"].get(tf, {}).get("expectancy_r"),
                                    "baseline": tables["test"]["baseline"]["by_timeframe"].get(tf, {}).get("expectancy_r"),
                                    "n": tables["test"][best]["by_timeframe"].get(tf, {}).get("n"),
                                    "n_base": tables["test"]["baseline"]["by_timeframe"].get(tf, {}).get("n")}
                               for tf in MODEL_TIMEFRAMES},
                "all_test": {v: f("test", v) for v in group}}

    out: dict[str, Any] = {"method": __doc__.strip(), "self_check": check}
    out["idea1_btc_trend"] = pick(["baseline"] + list(BTC_VARIANTS))
    out["idea3a_vp_filter"] = pick(["baseline"] + list(VP_FILTER))
    out["idea3b_vp_target_cap"] = pick(["baseline", "VP target cap"])
    out["idea4_fee_filter"] = pick(["baseline"] + [f"fee filter {x}%" for x in FEE_X])
    # fee filter chosen per timeframe on tune
    per_tf = {}
    for tf in MODEL_TIMEFRAMES:
        opts = [v for v in ["baseline"] + [f"fee filter {x}%" for x in FEE_X] if tf in tables["tune"][v]["by_timeframe"]]
        if not opts:
            continue
        b_ = max(opts, key=lambda v: tables["tune"][v]["by_timeframe"][tf].get("expectancy_r") or -9)
        per_tf[tf] = {"chosen": b_, "test_r": tables["test"][b_]["by_timeframe"][tf].get("expectancy_r"),
                      "test_n": tables["test"][b_]["by_timeframe"][tf].get("n"),
                      "baseline_r": tables["test"]["baseline"]["by_timeframe"][tf].get("expectancy_r"),
                      "baseline_n": tables["test"]["baseline"]["by_timeframe"][tf].get("n")}
    out["idea4_fee_filter"]["per_tf_choice"] = per_tf
    # idea 2: portfolio caps on the baseline trades
    caps: dict[str, Any] = {}
    for p in ("tune", "test"):
        allt = [t for v in res[p]["baseline"].values() for t in v]
        caps[p] = {"no cap": _curve(allt)}
        for n in CAPS:
            caps[p][f"global {n} same side"] = _curve(_cap(allt, n, False))
            caps[p][f"per timeframe {n} same side"] = _curve(_cap(allt, n, True))
    best = max(caps["tune"], key=lambda v: caps["tune"][v].get("avg_r") or -9)
    caps["chosen_on_tune"] = best
    caps["test_chosen"], caps["test_no_cap"] = caps["test"][best], caps["test"]["no cap"]
    out["idea2_exposure_cap"] = caps
    out.update({"skipped": skipped, "seconds": round(time.time() - t0, 1),
                "costs": {"round_trip_pct": settings.research_cost_pct, "funding": "0.01% per 8 h (longs pay), over the hold"}})
    return out
