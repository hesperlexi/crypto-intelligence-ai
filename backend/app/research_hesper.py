"""`python -m app.research hesper`: how often would a 30-day Hesper challenge ($100 -> $1,000) have succeeded?

Read-only research (3 Nov 2026, owner question). Two call sources:

1. REPLAY - the models' walk-forward OUT-OF-SAMPLE calls of every coin / public timeframe (15m, 1h, 4h, 12h, 1d, 3d)
   turned into calls by the live decision rules (series_policy.decide: live grading, bigger-trend, plan and cost rules;
   reference for the directional policy / confidence = the first 70 % of the series), the live entry rule per timeframe
   (chosen on the first 70 % as the nightly job does) and the pooled trade filter (trained on the first 70 %, used only
   where its own exam passes), the news guard, then the RECORD's publication rules: the timeframe's public grades
   (A only on 15m / 1h / 1d / 3d, A + B on 4h / 12h), one open call per coin / timeframe followed with the live time
   limit (tracking.horizon_for) plus the re-entry cooldown. Hesper only sees the published grade-A calls.
   Reported for all out-of-sample history ("full") and for calls of the untouched last 30 % of each series only ("test").
2. RECORD - the real recorded grade-A calls in `signals` (public timeframes), with their own levels and time limits.

Each 30-day window (one every 7 days) is one run starting at $100 that mirrors services/hesper.py: one trade at a time;
when flat, the best call published in the last FRESH_MS (highest confidence, tie -> newer) that is still OPEN in the
record and whose plan still makes sense at the current price; market entry at the next 15m candle (BUY ON PULLBACK above
its entry: a limit at the call's entry for PENDING_BARS candles of its timeframe); isolated margin, leverage <= 25 lowered
by futures.safe_leverage; the bots' futures fees, slippage, 8-hourly funding at the default rate and liquidation check
(before the stop, unless the stop protects); exits = the bots' rules (50 / 25 / 25, break-even after TP1, TP1 after TP2,
the call's time limit from opening, reversal on an opposite grade-A call except 15m). A run ends SUCCESS when the realised
balance reaches $1,000, FAIL on a liquidation or a balance below $1, TIME UP at day 30 (an open trade is closed at market).

Variants: A = all-in (Hesper today); B25 / B35 = position sized so a stop loses 25 % / 35 % of the balance (never more
than all-in; leverage the same safe leverage, so the margin is smaller); each with and without "skip calls whose time
limit would run past day 30".
"""
from __future__ import annotations

import logging
import math
import time
from bisect import bisect_left, bisect_right
from typing import Any, Callable

import numpy as np

from .config import ENGINE_VERSION, settings
from .data.base import tf_ms
from .engine import futures as F
from .ml import series_policy as SP, series_sim as S, trade_filter2 as TF2
from .research_engine import ENTRY_OPTIONS, TUNE_SHARE, _news_fn, _split, build
from .services import hesper as HZ

log = logging.getLogger("research.hesper")

DAY = 86_400_000
STEP15 = 900_000
WINDOW_DAYS = 30
WINDOW_EVERY_DAYS = 7
TFS = ["15m", "1h", "4h", "12h", "1d", "3d"]
TF_ORDER = ["3d", "1d", "12h", "4h", "1h", "15m"]
OPEN = 2 ** 62
NO_FLIP_TFS = ("15m",)                         # services/bots.NO_FLIP_TFS
VARIANTS: dict[str, dict[str, Any]] = {
    "A_all_in": {"risk": None, "skip_horizon": False},
    "A_all_in_skip_long": {"risk": None, "skip_horizon": True},
    "B25_risk": {"risk": 0.25, "skip_horizon": False},
    "B25_risk_skip_long": {"risk": 0.25, "skip_horizon": True},
    "B35_risk": {"risk": 0.35, "skip_horizon": False},
    "B35_risk_skip_long": {"risk": 0.35, "skip_horizon": True},
}


def _public_grades(tf: str) -> tuple[str, ...]:
    from .services import analysis
    return ("A",) if tf in analysis.A_ONLY_TFS else ("A", "B")


def _horizon(tf: str) -> int:
    from .services import tracking
    return tracking.horizon_for(tf)


# ---- market data: 15m candles where they exist, else the trade timeframe's own candles -------------------------------

class Market:
    """Candles per symbol as arrays. `path` gives the candles opened at/after `start` (15m when the 15m history covers
    `start`, else the call's own timeframe); `price` is the close of the last candle closed by `t`."""

    def __init__(self) -> None:
        self.c: dict[tuple[str, str], tuple[np.ndarray, ...]] = {}

    def add(self, symbol: str, tf: str, ts, high, low, close, open_=None) -> None:
        """open_ None: each candle opens at the previous close (no gaps)."""
        if ts is None or len(ts) == 0:
            return
        cl = np.asarray(close, float)
        op = np.asarray(open_, float) if open_ is not None else np.concatenate([[cl[0]], cl[:-1]])
        self.c[(symbol, tf)] = (np.asarray(ts, np.int64), np.asarray(high, float), np.asarray(low, float), cl, op)

    def add_df(self, symbol: str, tf: str, df) -> None:
        if df is not None and len(df):
            self.add(symbol, tf, df["ts"].to_numpy(np.int64), df["high"].to_numpy(float), df["low"].to_numpy(float),
                     df["close"].to_numpy(float), df["open"].to_numpy(float) if "open" in df else None)

    def _src(self, symbol: str, tf: str, t: int) -> tuple[tuple[np.ndarray, ...], int] | None:
        a = self.c.get((symbol, "15m"))
        if a is not None and a[0][0] <= t and a[0][-1] + STEP15 >= t:
            return a, STEP15
        b = self.c.get((symbol, tf))
        if b is not None and b[0][0] <= t:
            return b, tf_ms(tf)
        return (a, STEP15) if a is not None and a[0][0] <= t + STEP15 else None

    def path(self, symbol: str, tf: str, start: int):
        s = self._src(symbol, tf, start)
        if s is None:
            return None
        (ts, hi, lo, cl, op), bar = s
        i = int(np.searchsorted(ts, start))
        return ts[i:], hi[i:], lo[i:], cl[i:], op[i:], bar

    def price(self, symbol: str, tf: str, t: int) -> float | None:
        s = self._src(symbol, tf, t)
        if s is None:
            return None
        (ts, _, _, cl, _), bar = s
        k = int(np.searchsorted(ts + bar, t, side="right")) - 1
        return float(cl[k]) if k >= 0 else None

    def end(self) -> int:
        return max((int(a[0][-1]) + (STEP15 if tf == "15m" else tf_ms(tf)) for (s, tf), a in self.c.items()), default=0)


# ---- one 30-day window -------------------------------------------------------------------------------------------------

def _ceil15(t: int) -> int:
    return t if t % STEP15 == 0 else t - t % STEP15 + STEP15


def _size(variant: dict[str, Any], cash: float, px: float, stop: float, lev: float) -> float:
    fee = F.FUTURES_FEE_RATE
    adverse = (settings.slippage_bps + settings.spread_bps / 2) / 1e4
    q_all = cash * HZ.ALL_IN / (px * (1 / lev + fee))
    risk = variant.get("risk")
    if not risk:
        return q_all
    fill = px * (1 + adverse)
    per_unit = abs(fill - stop) + fill * fee + stop * (fee + settings.slippage_bps / 1e4)
    return float(min(q_all, risk * cash / per_unit)) if per_unit > 0 else q_all


def run_window(calls: list[dict[str, Any]], market: Market, t0: int, variant: dict[str, Any],
               flips: dict[tuple[str, str, int], np.ndarray] | None = None, days: int = WINDOW_DAYS,
               trade_log: bool = False) -> dict[str, Any]:
    """One run of `days` days from t0 at $100. `calls`: published grade-A calls sorted by publication `ts`, each
    {id, symbol, tf, ts, side, conf, decision, entry, stop, tps, horizon, rec_close}. `flips[(symbol, tf, side)]`: sorted
    times at which an opposite grade-A call of that series appears (reversal exit)."""
    flips = flips or {}
    end = t0 + days * DAY
    fee = F.FUTURES_FEE_RATE
    slip = settings.slippage_bps / 1e4
    adverse = (settings.slippage_bps + settings.spread_bps / 2) / 1e4
    cash, peak = HZ.START_BALANCE, HZ.START_BALANCE
    t = t0
    taken: set = set()
    trades: list[dict[str, Any]] = []
    ts_list = [c["ts"] for c in calls]
    result, reason, at = None, None, None
    seen = calls[bisect_left(ts_list, t0 - HZ.FRESH_MS):bisect_left(ts_list, end)]
    while True:
        if cash >= HZ.GOAL - 1e-9:
            result, reason, at = "SUCCESS", "goal", t
            break
        if cash < HZ.MIN_BALANCE:
            result, reason, at = "FAIL", "busted", t
            break
        if t >= end:
            result, reason, at = "TIME_UP", "day_30", end
            break
        lo_i, hi_i = bisect_left(ts_list, t - HZ.FRESH_MS), bisect_right(ts_list, t)
        fresh = [c for c in calls[lo_i:hi_i] if c["id"] not in taken]
        nxt = calls[hi_i]["ts"] if hi_i < len(calls) else None
        if not fresh:
            if nxt is None or nxt >= end:
                t = end
                continue
            t = nxt
            continue
        te = _ceil15(t)
        fresh.sort(key=lambda c: (-(c["conf"] if c["conf"] is not None and np.isfinite(c["conf"]) else 0.0), -c["ts"]))
        entered = None
        for c in fresh:
            if c["rec_close"] <= te:                     # no longer OPEN in the record
                continue
            px = market.price(c["symbol"], c["tf"], te)
            if px is None:
                continue
            side, stop, tps = c["side"], c["stop"], c["tps"]
            if side * (px - stop) <= 0 or side * (tps[0] - px) <= 0:
                continue
            step = tf_ms(c["tf"])
            if variant.get("skip_horizon") and te + c["horizon"] * step > end:
                continue
            pullback = c["decision"] == "BUY ON PULLBACK" and c["entry"] is not None and side * (px - c["entry"]) > 0
            entry = float(c["entry"]) if pullback else px
            if side * (entry - stop) <= 0:
                continue
            lev = float(min(HZ.MAX_LEVERAGE, F.safe_leverage(entry, stop, HZ.MAX_LEVERAGE)))
            qty = _size(variant, cash, entry, stop, lev)
            if qty <= 0:
                continue
            entered = (c, px, pullback, entry, lev, qty)
            break
        if entered is None:
            # nothing usable now: try again on the next candle while calls are still fresh, or at the next call
            still = [c["ts"] + HZ.FRESH_MS for c in fresh if c["ts"] + HZ.FRESH_MS > te]
            cand = [x for x in (te + STEP15 if still else None, nxt if nxt is not None and nxt > t else None) if x]
            t = min(cand) if cand else end
            continue
        c, px, pullback, entry, lev, qty = entered
        taken.add(c["id"])
        out = _trade(c, market, te, pullback, entry, lev, qty, cash, end, flips, fee, slip, adverse)
        if out is None:                                  # no candles: skip the call
            continue
        cash = out["cash"]
        peak = max(peak, cash)
        t = max(out["t_end"], te)
        if out.get("filled"):
            trades.append({k: out[k] for k in ("symbol", "tf", "side", "lev", "opened_at", "closed_at", "pnl", "reason",
                                               "balance_after", "tp_hit")})
        if out.get("reason") == "liquidated":
            result, reason, at = "FAIL", "liquidated", out["t_end"]
            break
        if out.get("reason") == "time_up":
            result, reason, at = "TIME_UP", "day_30", end
            break
    res = {"start": t0, "result": result, "reason": reason, "end_balance": float(cash), "peak": float(peak),
           "days": (at - t0) / DAY, "trades": len(trades), "wins": sum(1 for x in trades if x["pnl"] > 0),
           "calls_published": len(seen)}
    if trade_log:
        res["trade_list"] = trades
    return res


def _trade(c, market: Market, te: int, pullback: bool, entry: float, lev: float, qty: float, cash: float, end: int,
           flips, fee: float, slip: float, adverse: float) -> dict[str, Any] | None:
    """One Hesper trade (or pending limit) from te. Returns the new cash, when Hesper is flat again and the trade."""
    sym, tf, side = c["symbol"], c["tf"], c["side"]
    step = tf_ms(tf)
    p = market.path(sym, tf, te)
    if p is None or len(p[0]) == 0:
        return None
    ts, hi, lo, cl, opn, bar = p
    fl = flips.get((sym, tf, side))
    fl = fl if fl is not None and tf not in NO_FLIP_TFS else None
    i = 0
    if pullback:
        reserved = qty * entry * (1 / lev + fee)
        expires = te + HZ.PENDING_BARS * step
        fill_i = None
        for k in range(len(ts)):
            if ts[k] + bar > expires or ts[k] >= end:
                break
            if fl is not None:
                f = fl[bisect_right(fl, te):]
                if len(f) and f[0] <= ts[k]:
                    return {"cash": cash, "t_end": int(f[0]), "filled": False, "reason": "reversed_pending"}
            if (lo[k] <= entry) if side > 0 else (hi[k] >= entry):
                fill_i = k
                break
        if fill_i is None:
            return {"cash": cash, "t_end": int(min(expires, end)), "filled": False, "reason": "not_filled"}
        del reserved
        opened, i = int(ts[fill_i]), fill_i
        op = float(opn[fill_i])
        fill = min(op, entry) if side > 0 else max(op, entry)      # limit fill (fill_raw), better when it opens through
    else:
        fill = entry * (1 + side * adverse)
        opened = te
        op = entry
    fee0 = qty * fill * fee
    cost = qty * fill / lev + fee0
    if cost > cash + 1e-9:
        qty = max(0.0, (cash - 1e-9) / (fill / lev + fill * fee))
        fee0 = qty * fill * fee
        cost = qty * fill / lev + fee0
    if qty <= 0:
        return None
    coll = fill / lev
    cash -= cost
    liq = F.liquidation_price(fill, side, lev)
    stop, tps = float(c["stop"]), list(c["tps"])
    qty_open, tp_hit, realized = qty, 0, -fee0
    funded_until = opened
    rate = F.DEFAULT_FUNDING_RATE
    horizon_end = opened + int(c["horizon"]) * step
    flip_at = None
    if fl is not None:
        k = bisect_right(fl, opened)
        flip_at = int(fl[k]) if k < len(fl) else None

    def reduce(q: float, raw: float, at_level: bool) -> None:
        nonlocal cash, qty_open, realized
        px = raw * (1 - side * (slip if at_level else adverse))
        f_ = q * px * fee
        cash += q * coll + side * q * (px - fill) - f_
        realized += side * q * (px - fill) - f_
        qty_open -= q

    def funding(upto: int, px: float) -> None:
        nonlocal cash, realized, funded_until
        times = F.funding_times(funded_until, upto)
        if times:
            amt = len(times) * side * qty_open * px * rate
            cash -= amt
            realized -= amt
            funded_until = times[-1]

    reason, t_end = None, None
    last_cl = op
    for k in range(i, len(ts)):
        t_open, ce = int(ts[k]), int(ts[k]) + bar
        if t_open >= end:                               # day 30: close at market
            funding(end, last_cl)
            reduce(qty_open, last_cl, False)
            reason, t_end = "time_up", end
            break
        if flip_at is not None and flip_at <= t_open and k > i:
            funding(flip_at, last_cl)
            reduce(qty_open, last_cl, False)
            reason, t_end = "reversal", flip_at
            break
        o = float(opn[k])
        funding(ce, float(cl[k]))
        # liquidation first, unless a stop between the price and the liquidation level protects (bots._liq_hit)
        if (lo[k] <= liq) if side > 0 else (hi[k] >= liq):
            protected = side * (stop - liq) > 0 and side * (o - liq) > 0 and side * (o - stop) > 0
            if not protected:
                realized -= qty_open * coll
                qty_open = 0.0
                reason, t_end = "liquidated", ce
                break
        if (lo[k] <= stop) if side > 0 else (hi[k] >= stop):
            px = min(o, stop) if side > 0 else max(o, stop)
            reduce(qty_open, px, True)
            reason, t_end = ("trailing stop" if tp_hit >= 2 else "breakeven stop" if tp_hit else "stop"), ce
            break
        while tp_hit < len(tps):
            tp = tps[tp_hit]
            if not ((hi[k] >= tp) if side > 0 else (lo[k] <= tp)):
                break
            px = max(o, tp) if side > 0 else min(o, tp)
            leg = qty_open if tp_hit == len(tps) - 1 else qty * S.TP_SPLIT[tp_hit]
            reduce(min(leg, qty_open), px, True)
            tp_hit += 1
            if tp_hit == 1:
                stop = fill
            elif tp_hit == 2:
                stop = tps[0]
        if qty_open <= qty * 1e-9:
            reason, t_end = f"TP{tp_hit}", ce
            break
        if ce >= horizon_end:
            reduce(qty_open, float(cl[k]), False)
            reason, t_end = "time exit", ce
            break
        last_cl = float(cl[k])
    if reason is None:                                   # data ended: close at the last price
        reduce(qty_open, last_cl, False)
        reason, t_end = "data_end", int(ts[-1]) + bar
    return {"cash": cash, "t_end": int(t_end), "filled": True, "reason": reason, "symbol": sym, "tf": tf, "side": side,
            "lev": lev, "opened_at": opened, "closed_at": int(t_end), "pnl": realized, "balance_after": cash,
            "tp_hit": tp_hit}


# ---- windows and statistics -----------------------------------------------------------------------------------------

def window_starts(first: int, last_end: int, every_days: int = WINDOW_EVERY_DAYS, days: int = WINDOW_DAYS) -> list[int]:
    t = first - first % DAY + DAY
    out = []
    while t + days * DAY <= last_end:
        out.append(t)
        t += every_days * DAY
    return out


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(runs)
    if not n:
        return {"windows": 0}
    end = np.array([r["end_balance"] for r in runs])
    peak = np.array([r["peak"] for r in runs])
    succ = [r for r in runs if r["result"] == "SUCCESS"]
    fail = [r for r in runs if r["result"] == "FAIL"]
    return {"windows": n,
            "success_pct": 100 * len(succ) / n,
            "fail_pct": 100 * len(fail) / n,
            "fail_liquidated_pct": 100 * sum(r["reason"] == "liquidated" for r in fail) / n,
            "fail_busted_pct": 100 * sum(r["reason"] == "busted" for r in fail) / n,
            "time_up_pct": 100 * sum(r["result"] == "TIME_UP" for r in runs) / n,
            "end_balance_median": float(np.median(end)), "end_balance_p25": float(np.quantile(end, 0.25)),
            "end_balance_p75": float(np.quantile(end, 0.75)),
            "time_up_end_balance_median": float(np.median([r["end_balance"] for r in runs if r["result"] == "TIME_UP"]))
            if any(r["result"] == "TIME_UP" for r in runs) else None,
            "days_to_success_median": float(np.median([r["days"] for r in succ])) if succ else None,
            "avg_trades": float(np.mean([r["trades"] for r in runs])),
            "avg_calls_published_in_window": float(np.mean([r["calls_published"] for r in runs])),
            "reached_250_pct": 100 * float(np.mean(peak >= 250)), "reached_500_pct": 100 * float(np.mean(peak >= 500)),
            "reached_1000_pct": 100 * float(np.mean(peak >= 1000)),
            "ended_above_100_pct": 100 * float(np.mean(end > HZ.START_BALANCE))}


def simulate_scope(calls: list[dict[str, Any]], market: Market, flips, data_end: int, first: int | None = None,
                   variants: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Every variant on every window of a call list. Also the non-overlapping subset (every 5th window: 35 days apart)."""
    variants = variants or VARIANTS
    calls = sorted(calls, key=lambda c: c["ts"])
    if not calls:
        return {"windows": 0, "note": "no calls"}
    starts = window_starts(first if first is not None else calls[0]["ts"], data_end)
    out: dict[str, Any] = {"windows": len(starts), "first_window": starts[0] if starts else None,
                           "last_window": starts[-1] if starts else None, "variants": {}}
    for name, v in variants.items():
        runs = [run_window(calls, market, s, v, flips) for s in starts]
        no = runs[::5]
        trades = sum(r["trades"] for r in runs)
        out["variants"][name] = {"overlapping": summarize(runs), "non_overlapping": summarize(no),
                                 "win_rate_trades": (sum(r["wins"] for r in runs) / trades) if trades else None,
                                 "windows_detail": [{"start": r["start"], "result": r["result"], "reason": r["reason"],
                                                     "end": round(r["end_balance"], 2), "peak": round(r["peak"], 2),
                                                     "days": round(r["days"], 1), "trades": r["trades"]} for r in runs]}
    return out


def calls_per_month(calls: list[dict[str, Any]], spans: dict[str, float]) -> dict[str, Any]:
    """Grade-A calls per 30 days by timeframe over each timeframe's own span (days), and their sum."""
    by: dict[str, Any] = {}
    for tf in TFS:
        n = sum(1 for c in calls if c["tf"] == tf)
        d = spans.get(tf)
        by[tf] = {"calls": n, "span_days": round(d, 1) if d else None, "per_month": (n / d * 30) if d else None}
    by["total_per_month"] = float(sum(x["per_month"] or 0.0 for x in by.values() if isinstance(x, dict)))
    return by


# ---- source 1: the replay -------------------------------------------------------------------------------------------

def _choose_entry(series: dict, tfs: list[str]) -> dict[str, dict]:
    out = {}
    for tf in tfs:
        rows = [v for k, v in series.items() if k.endswith(f" {tf}")]
        tbl = {}
        for mode, k in ENTRY_OPTIONS:
            e = sum((v["entry_tune"][f"{mode}:{k}"]["early"] for v in rows), [])
            l_ = sum((v["entry_tune"][f"{mode}:{k}"]["late"] for v in rows), [])
            tbl[f"{mode}:{k}"] = {"n_early": len(e), "lb80_early": S.bootstrap_lb(e, 0.8) if len(e) >= 30 else None,
                                  "mean_late": float(np.mean(l_)) if l_ else None}
        old = tbl["old:0.0"]
        cand = [(k, v) for k, v in tbl.items() if v["lb80_early"] is not None and v["n_early"] >= 0.3 * max(old["n_early"], 1)]
        best = max(cand, key=lambda kv: kv[1]["lb80_early"])[0] if cand else "old:0.0"
        b = tbl[best]
        ok = bool(best != "old:0.0" and b["mean_late"] is not None and old["mean_late"] is not None
                  and b["mean_late"] > old["mean_late"])
        out[tf] = {"chosen": best if ok else "old:0.0", "best_early": best, "confirmed_late": ok}
    return out


def prepare(rt, symbols: list[str], deadline: float) -> dict[str, Any]:
    """Build every series; decide with the first 70 % as reference; choose the entry rule per timeframe and train the
    pooled filter on tuning trades (30-candle horizon, as the nightly job)."""
    news = _news_fn(rt.db)
    frames_cache: dict = {}
    series: dict[str, dict] = {}
    skipped: list[str] = []
    pool: dict[str, dict[str, list]] = {}
    for tf in TF_ORDER:
        for s in symbols:
            if time.time() > deadline:
                skipped.append(f"{s} {tf}: time budget")
                continue
            try:
                b = build(rt, s, tf, frames_cache)
            except Exception as exc:
                skipped.append(f"{s} {tf}: {type(exc).__name__}")
                continue
            if b is None:
                skipped.append(f"{s} {tf}: no model / too few out-of-sample bars")
                continue
            ctx, paths = b
            tune, test, cut = _split(ctx)
            if tune.sum() < 150 or test.sum() < 30:
                skipped.append(f"{s} {tf}: span too short to split")
                continue
            d = SP.decide(ctx, tune)
            t_early = int(ctx.ts[0]) + int((cut - int(ctx.ts[0])) * 0.7)
            entry_tune, cands_old = {}, None
            for mode, k in ENTRY_OPTIONS:
                cands = SP.candidates(ctx, paths, tune, d, entry_mode=mode, k=k, news=news)
                if (mode, k) == ("old", 0.0):
                    cands_old = cands
                tr = SP.taken(ctx, cands)
                entry_tune[f"{mode}:{k}"] = {"early": [t["r"] for t in tr if t["ts"] < t_early],
                                             "late": [t["r"] for t in tr if t["ts"] >= t_early]}
            P = pool.setdefault(tf, {"F": [], "R": [], "ts": []})
            for c in cands_old or []:
                if c["filled"] and c["closed_ts"] < cut:
                    P["F"].append(TF2.features(ctx, d, c["j"]))
                    P["R"].append(c["r"])
                    P["ts"].append(c["ts"])
            series[f"{s} {tf}"] = {"ctx": ctx, "paths": paths, "tune": tune, "test": test, "cut": cut, "d": d,
                                   "entry_tune": entry_tune}
            log.info("hesper prep %s %s: %d oos bars", s, tf, ctx.n)
    entry_choice = _choose_entry(series, TFS)
    filters = {tf: TF2.train(np.array(P["F"]) if P["F"] else np.zeros((0, len(TF2.FEATURES))), np.array(P["R"]),
                             np.array(P["ts"])) for tf, P in pool.items()}
    return {"series": series, "skipped": skipped, "entry_choice": entry_choice, "filters": filters, "news": news}


def _record_close(ctx, paths: SP.Paths, j: int, side: int, pl: dict, mode: str, k: float, horizon: int) -> int | None:
    """When the RECORD's call made at row j stops being OPEN (closed, expired or not filled); OPEN when unfinished at the
    end of the data; None without candles."""
    step = tf_ms(ctx.tf)
    start = int(ctx.decision_ts[j])
    end = start + horizon * step
    a15, aown = paths._a.get("p15"), paths._a.get("own")
    if a15 is not None and a15[0][0] <= start + STEP15 and a15[0][-1] + STEP15 > start:
        a, bar = a15, STEP15
    elif aown is not None:
        a, bar = aown, step
    else:
        return None
    i, e = int(np.searchsorted(a[0], start)), int(np.searchsorted(a[0], end))
    if e <= i:
        return OPEN if a[0][-1] < start else None
    ts, hi, lo, cl = a[0][i:e], a[1][i:e], a[2][i:e], a[3][i:e]
    window = max(1, int(round(settings.fill_window_bars * step / bar)))
    f = S.fill(mode, side, float(ctx.close[j]), float(ctx.atr[j]), pl, hi, lo, cl, window, k)
    if f is None:
        return start + settings.fill_window_bars * step
    i0, entry, first = f
    if side * (entry - pl["stop"]) <= 0:
        return start + settings.fill_window_bars * step
    complete = int(ts[-1]) + bar >= end
    out = S.follow(side, entry, pl["stop"], S.ladder(side, entry, pl["stop"]), hi[i0:], lo[i0:], cl[i0:],
                   first_is_fill=first, complete=complete)
    if out is None:
        return OPEN
    return int(ts[i0 + out.exit_idx]) + bar


def published_calls(key_: str, v: dict[str, Any], prep: dict[str, Any]) -> tuple[list[dict], dict]:
    """The calls the record would have published for one series (public grades, filter, news, one at a time with the live
    time limit + cooldown), as Hesper sees them; plus the opposite-grade-A times for reversals."""
    ctx, paths, d = v["ctx"], v["paths"], v["d"]
    tf, sym = ctx.tf, ctx.symbol
    mode, k = (prep["entry_choice"][tf]["chosen"].split(":") if settings.entry_rules else ("old", "0"))
    k = float(k)
    f = prep["filters"].get(tf) if settings.trade_filter2 else None
    keep: Callable[[int], bool] = (lambda j: TF2.score(f, TF2.features(ctx, d, j)) >= f["threshold"]) \
        if f and f.get("enabled") else (lambda j: True)
    grades = _public_grades(tf)
    horizon = _horizon(tf)
    news = prep["news"]
    rows = []
    for j in np.flatnonzero(d["trade"] & np.isin(d["grade"], grades)):
        if news is not None and news(int(ctx.decision_ts[j])):
            continue
        if not keep(int(j)):
            continue
        pl = d["plan"][j]
        m = mode
        if m == "old" and d["decision"][j] != "BUY ON PULLBACK":
            m = "market"
        rc = _record_close(ctx, paths, int(j), int(d["side"][j]), pl, m, k, horizon)
        if rc is None:
            continue
        rows.append((int(j), rc))
    flips: dict = {}
    for s in (1, -1):
        sel = d["trade"] & (d["grade"] == "A") & (d["side"] == -s)
        js = [int(j) for j in np.flatnonzero(sel) if keep(int(j))]
        flips[(sym, tf, s)] = np.array(sorted(int(ctx.decision_ts[j]) for j in js), np.int64)
    if not rows:
        return [], flips
    idx = SP.take(np.array([int(ctx.decision_ts[j]) for j, _ in rows], np.int64),
                  np.array([rc for _, rc in rows], np.int64), tf_ms(tf))
    out = []
    for i in idx:
        j, rc = rows[i]
        if d["grade"][j] != "A":
            continue                                     # published B calls block the series but Hesper skips them
        pl = d["plan"][j]
        side = int(d["side"][j])
        close = float(ctx.close[j])
        if mode == "market":
            entry, base = close, close
        elif mode == "pullback":
            entry, base = close - side * k * float(ctx.atr[j]), pl["ideal"]
        else:
            entry, base = pl["ideal"], pl["ideal"]
        out.append({"id": f"{key_}|{j}", "symbol": sym, "tf": tf, "ts": int(ctx.decision_ts[j]), "side": side,
                    "conf": float(d["confidence"][j]) if np.isfinite(d["confidence"][j]) else None,
                    "decision": str(d["decision"][j]), "entry": float(entry), "stop": float(pl["stop"]),
                    "tps": S.ladder(side, base, pl["stop"]), "horizon": horizon, "rec_close": int(rc),
                    "test": bool(v["test"][j])})
    return out, flips


# ---- source 2: the real record -------------------------------------------------------------------------------------------

def record_calls(db) -> list[dict[str, Any]]:
    from .db import loads
    from .services import analysis
    rows = db.query("SELECT * FROM signals WHERE side != 0 AND decision IN ('BUY', 'BUY ON PULLBACK', 'SELL') "
                    "AND stop IS NOT NULL AND tp1 IS NOT NULL ORDER BY created_at")
    out = []
    for r in rows:
        p = loads(r.get("payload"), {}) or {}
        if p.get("grade") != "A" or p.get("shadow") or p.get("scalp") or r["timeframe"] not in TFS:
            continue
        if r["timeframe"] in analysis.DEMO_ONLY_TFS or r["timeframe"] in analysis.PAUSED_TFS:
            continue
        tps = [float(x) for x in (r.get("tp1"), r.get("tp2"), r.get("tp3")) if x is not None]
        closed = r.get("closed_at")
        rc = int(closed) if closed and r["status"] not in ("OPEN",) else OPEN
        out.append({"id": r["id"], "symbol": r["symbol"], "tf": r["timeframe"], "ts": int(r["created_at"]),
                    "side": int(r["side"]), "conf": r.get("confidence"), "decision": r["decision"],
                    "entry": float(r["entry"]) if r.get("entry") is not None else None, "stop": float(r["stop"]),
                    "tps": tps, "horizon": int(p.get("horizon_bars") or 30), "rec_close": rc,
                    "status": r["status"], "return_pct": r.get("return_pct")})
    return out


def record_source(rt, sims: bool = True) -> dict[str, Any]:
    db = rt.db
    calls = record_calls(db)
    since = db.get_setting("record_since", None)
    out: dict[str, Any] = {"grade_a_calls": len(calls), "record_since": since}
    if not calls:
        return out
    m = Market()
    for sym in sorted({c["symbol"] for c in calls}):
        m.add_df(sym, "15m", rt.candles(sym, "15m"))
        for tf in sorted({c["tf"] for c in calls if c["symbol"] == sym}):
            if tf != "15m":
                m.add_df(sym, tf, rt.candles(sym, tf))
    data_end = m.end()
    span = max((data_end - calls[0]["ts"]) / DAY, 1e-9)
    by_tf = {tf: sum(1 for c in calls if c["tf"] == tf) for tf in TFS}
    out.update({"first_call": calls[0]["ts"], "data_end": data_end, "span_days": round(span, 1),
                "per_month": len(calls) / span * 30, "by_timeframe": by_tf,
                "closed": sum(1 for c in calls if c["status"] not in ("OPEN",)),
                "status_counts": {s: sum(1 for c in calls if c["status"] == s) for s in sorted({c["status"] for c in calls})}})
    if sims:
        out["complete_windows"] = simulate_scope(calls, m, {}, data_end)
        # windows that have not reached day 30 yet: run to the end of the data (labelled partial)
        starts = window_starts(calls[0]["ts"], data_end + WINDOW_DAYS * DAY)
        part = {}
        for name, v in VARIANTS.items():
            rs = []
            for s in starts:
                if s >= data_end:
                    continue
                days = max(1, int((data_end - s) // DAY))
                r = run_window(calls, m, s, v, None, days=min(days, WINDOW_DAYS), trade_log=True)
                r["days_available"] = min(days, WINDOW_DAYS)
                rs.append(r)
            part[name] = rs
        out["partial_windows_to_data_end"] = part
    try:
        runs = db.query("SELECT run, started_at, ended_at, result, reason, end_balance, peak, trades, wins FROM hesper_runs "
                        "ORDER BY run")
        out["live_hesper_runs"] = runs
    except Exception:
        out["live_hesper_runs"] = None
    return out


# ---- the research -----------------------------------------------------------------------------------------------------

def evaluate(rt, symbols: list[str], watchlist: list[str], t_start: float, budget_s: float) -> dict[str, Any]:
    prep = prepare(rt, symbols, t_start + 0.7 * budget_s)
    series = prep["series"]
    calls: list[dict] = []
    flips: dict = {}
    spans_full: dict[str, float] = {}
    spans_test: dict[str, float] = {}
    first_full: dict[str, int] = {}
    m = Market()
    added = set()
    for key_, v in series.items():
        ctx = v["ctx"]
        try:
            cs, fl = published_calls(key_, v, prep)
        except Exception as exc:
            prep["skipped"].append(f"{key_}: calls {type(exc).__name__}: {exc}"[:160])
            continue
        calls += cs
        flips.update(fl)
        tf = ctx.tf
        spans_full[tf] = max(spans_full.get(tf, 0.0), (int(ctx.ts[-1]) - int(ctx.ts[0])) / DAY)
        tts = ctx.ts[v["test"]]
        if len(tts) > 1:
            spans_test[tf] = max(spans_test.get(tf, 0.0), (int(tts[-1]) - int(tts[0])) / DAY)
        first_full[tf] = min(first_full.get(tf, 2 ** 62), int(ctx.ts[0]))
        if ctx.symbol not in added and v["paths"].p15 is not None:
            m.add_df(ctx.symbol, "15m", v["paths"].p15)
            added.add(ctx.symbol)
        if v["paths"].own is not None:
            m.add_df(ctx.symbol, tf, v["paths"].own)
    data_end = m.end()
    universes = {"watchlist": set(watchlist), "all_model_coins": {c["symbol"] for c in calls}}
    out: dict[str, Any] = {"data_end": data_end, "universes": {k: sorted(v) for k, v in universes.items()},
                           "first_oos_by_timeframe": first_full, "results": {}}
    for uname, uni in universes.items():
        if not uni:
            continue
        cu = [c for c in calls if c["symbol"] in uni]
        ct = [c for c in cu if c["test"]]
        fu = {k: x for k, x in flips.items() if k[0] in uni}
        if time.time() > t_start + budget_s:
            out["results"][uname] = {"skipped": "time budget"}
            continue
        # windows where every public timeframe up to 1d has out-of-sample calls (the call mix of today)
        mix_start = max([first_full.get(tf, 0) for tf in ("1h", "4h", "12h", "1d")] or [0])
        out["results"][uname] = {
            "calls_per_month_full": calls_per_month(cu, spans_full),
            "calls_per_month_test": calls_per_month(ct, spans_test),
            "full": simulate_scope(cu, m, fu, data_end),
            "test": simulate_scope(ct, m, fu, data_end),
            "full_since_1h_history": simulate_scope([c for c in cu if c["ts"] >= mix_start], m, fu, data_end, mix_start),
        }
    out["series"] = {k: {"oos_bars": int(v["ctx"].n), "test_bars": int(v["test"].sum())} for k, v in series.items()}
    out["skipped"] = prep["skipped"]
    out["entry_choice"] = prep["entry_choice"]
    out["filters"] = {tf: {k: x for k, x in f.items() if k not in ("model", "features")} for tf, f in prep["filters"].items()}
    return out


def headline(body: dict[str, Any]) -> dict[str, Any]:
    keys = ("windows", "success_pct", "fail_pct", "time_up_pct", "end_balance_median", "end_balance_p25",
            "end_balance_p75", "days_to_success_median", "avg_trades", "reached_250_pct", "reached_500_pct",
            "reached_1000_pct", "avg_calls_published_in_window")
    out = {}
    for uname, r in (body.get("results") or {}).items():
        if not isinstance(r, dict) or "full" not in r:
            continue
        out[uname] = {}
        for sc in ("full", "test", "full_since_1h_history"):
            vs = (r.get(sc) or {}).get("variants") or {}
            out[uname][sc] = {vn: {k: (x["overlapping"].get(k)) for k in keys} | {"non_overlapping_windows":
                              x["non_overlapping"].get("windows"), "non_overlapping_success_pct":
                              x["non_overlapping"].get("success_pct")} for vn, x in vs.items()}
        out[uname]["calls_per_month"] = {"full": r["calls_per_month_full"]["total_per_month"],
                                         "test": r["calls_per_month_test"]["total_per_month"]}
    return out


def run(db_url: str, budget_s: float, symbols: list[str] | None = None) -> dict[str, Any]:
    from .db import Database
    from .services.runtime import Runtime

    class _Prov:
        name = "binance"

    db = Database(db_url)
    rt = Runtime(db, _Prov())
    ex = db.one("SELECT exchange, COUNT(*) AS n FROM market_data GROUP BY exchange ORDER BY n DESC LIMIT 1")
    if ex:
        _Prov.name = ex["exchange"]
    syms = symbols or [r["symbol"] for r in db.query("SELECT DISTINCT symbol FROM model_versions WHERE active = 1 ORDER BY symbol")]
    try:
        watch = [s for s in rt.symbols() if s in syms]
    except Exception:
        watch = []
    t0 = time.time()
    body: dict[str, Any] = {}
    try:
        body["record"] = record_source(rt)
    except Exception as exc:
        log.exception("record source")
        body["record"] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
    body["replay"] = evaluate(rt, syms, watch, t0, budget_s)
    body["headline"] = headline(body["replay"])
    body.update({"engine_version": ENGINE_VERSION, "tune_share": TUNE_SHARE, "symbols": syms, "watchlist": watch,
                 "window_days": WINDOW_DAYS, "window_every_days": WINDOW_EVERY_DAYS,
                 "hesper": {"start": HZ.START_BALANCE, "goal": HZ.GOAL, "min_balance": HZ.MIN_BALANCE,
                            "max_leverage": HZ.MAX_LEVERAGE, "all_in": HZ.ALL_IN, "fresh_ms": HZ.FRESH_MS,
                            "pending_bars": HZ.PENDING_BARS},
                 "costs": {"futures_fee_rate": F.FUTURES_FEE_RATE, "slippage_bps": settings.slippage_bps,
                           "spread_bps": settings.spread_bps, "funding_rate_per_8h": F.DEFAULT_FUNDING_RATE},
                 "settings": {"entry_rules": settings.entry_rules, "trade_filter2": settings.trade_filter2},
                 "variants": VARIANTS, "seconds": round(time.time() - t0, 1),
                 "method": __doc__.strip().split("\n\n", 1)[1] if __doc__ else None,
                 "approximations": [
                     "grading = series_policy.decide replay of the live logic (per-member model agreement treated as "
                     "passed, no order book); directional confidence measured against the first 70 % of each series",
                     "TP2 / TP3 on the fixed ladder 1.75R / 2.5R (live picks them in [1.25, 2] / [2, 3] R); no runner",
                     "publication at the bar close, entry at the next 15m candle (live: within one 5-minute tick)",
                     "entry price = close of the last closed candle; candle open = previous close (gaps ignored)",
                     "funding at the default 0.01 % per 8 h (longs pay), not the historical rate",
                     "before the 15m history begins, trades are followed on the call's own timeframe candles",
                     "re-entry cap and safety switch not replayed; record calls still open at the data end block their "
                     "series to the end",
                     "record source: no reversal exits (the past analyses are not stored), admin changes not replayed",
                     "'full' is partly in-sample for the grading reference, entry rule and filter (chosen on the first "
                     "70 %); 'test' is only calls of the untouched last 30 % of each series"]})
    return body
