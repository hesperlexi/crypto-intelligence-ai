"""v2.6 accuracy upgrades: per coin / timeframe evidence from the models' own walk-forward out-of-sample predictions.

`build_context`  everything known at each out-of-sample bar's close: the ensemble probabilities, the technical tilt, the
                 multi-timeframe matrix (every timeframe aligned to its last candle CLOSED by then), volatility state,
                 ATR / EMA21 / swings for the trade plan, BTC regime. Nothing after the bar's close is used.
`decide`         a vectorised replica of services/analysis.analyze's decision on those bars: signal composite and label
                 (no order book in history), directional view + confidence measured against a REFERENCE set of
                 out-of-sample bars (the tuning part only when proving), grades A / B, trade plan validity (blocker),
                 bigger-trend check, costs check. Model agreement per member is not stored out-of-sample: treated as
                 passing (documented approximation; the live engine still checks it).
`simulate`       the trade under the record's standard rules (series_sim.follow) on 15m candles when they cover the
                 horizon (as the live record), else on the series' own candles; costs in R.
`take`           one call at a time per coin / timeframe plus the re-entry cooldown, as the live record.
`compute`        the nightly policy per series (train-merge): series gate (item 1) and per-series confidence threshold
                 (item 2), cached in app_settings `series_policy1|SYMBOL|TF`.
"""
from __future__ import annotations

import bisect
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

from ..config import DEFAULT_SIGNAL_WEIGHTS, MTF_TIMEFRAMES, MTF_WEIGHTS, TF_SECONDS, settings
from ..data.base import tf_ms
from ..features.structure import sr_zones
from . import series_sim as S
from .direction import MARGINS, MIN_CALLS, MIN_COVERAGE
from .metrics import wilson

log = logging.getLogger(__name__)
HORIZON_BARS = 30
DEADBAND = 0.10                      # engine/mtf.py
THRESHOLDS = (0.15, 0.35, 0.60)      # engine/signal.py
COST_MULT = 3.0
CONF_GRID = (0.505, 0.52, 0.54, 0.56, 0.58, 0.60)
TTL_MS = 30 * 3_600_000              # recomputed nightly; ignored when older than 30 h


def key(symbol: str, tf: str) -> str:
    return f"series_policy1|{symbol}|{tf}"


def cached(db: Any, symbol: str, tf: str, now: int | None = None) -> dict[str, Any] | None:
    try:
        d = db.get_setting(key(symbol, tf), None)
    except Exception:
        return None
    now = now or int(time.time() * 1000)
    return d if d and now - int(d.get("at") or 0) < TTL_MS else None


# ---- context ---------------------------------------------------------------------------------------------------------

def _align(base_close_ts: np.ndarray, other_ts: np.ndarray, other_tf: str) -> np.ndarray:
    """Index into `other` of the last candle CLOSED by each base close time (-1 when none)."""
    close = other_ts + tf_ms(other_tf)
    return np.searchsorted(close, base_close_ts, side="right") - 1


@dataclass
class Context:
    symbol: str
    tf: str
    ts: np.ndarray                   # bar open times of the out-of-sample rows
    P: np.ndarray                    # (n, 3) down / neutral / up
    rows: np.ndarray                 # positions in frame.ind
    close: np.ndarray
    atr: np.ndarray
    ema21: np.ndarray
    last_sl: np.ndarray
    last_sh: np.ndarray
    vol_state: np.ndarray
    tech: np.ndarray                 # tech_score
    comps: dict[str, np.ndarray]     # sc_* components
    regime_score: np.ndarray
    mtf_dir: dict[str, np.ndarray]   # per timeframe: -1 / 0 / +1, NaN unavailable
    mtf_score: dict[str, np.ndarray]
    btc_regime: np.ndarray
    btc_tech: np.ndarray
    swings: list[dict]
    edge_confirmed: bool
    zone_cache: dict[int, dict] = field(default_factory=dict)
    X: np.ndarray | None = None      # model features of the rows (for the trade filters)
    fwd_sign: np.ndarray | None = None   # sign of the next bar's return (outcome; only used for reference rows)

    @property
    def n(self) -> int:
        return len(self.ts)

    @property
    def decision_ts(self) -> np.ndarray:
        return self.ts + tf_ms(self.tf)

    def zones(self, j: int) -> dict[str, list[dict]]:
        """S/R zones exactly as the live analysis builds them at row j (swings confirmed by then, 400-bar lookback)."""
        if j not in self.zone_cache:
            pos = int(self.rows[j])
            hi = bisect.bisect_right(self._conf, pos)                   # swings confirmed by this bar's close
            lo = bisect.bisect_left(self._posl, pos + 1 - 400, 0, hi)   # sr_zones' own 400-bar lookback
            self.zone_cache[j] = sr_zones(self.swings[lo:hi], float(self.close[j]), float(self.atr[j]), pos + 1)
        return self.zone_cache[j]

    def prepare(self) -> None:
        self.swings = sorted(self.swings, key=lambda s: (s["confirm_pos"], s["pos"]))
        self._conf = [s["confirm_pos"] for s in self.swings]
        # positions are increasing with confirm_pos (fixed confirmation lag): bisect on them is valid
        self._posl = [s["pos"] for s in self.swings]


def build_context(symbol: str, tf: str, bundle: dict[str, Any], frames: dict[str, Any], btc_frame: Any = None,
                  X: np.ndarray | None = None) -> Context | None:
    """frames: timeframe -> Frame for this coin (must include `tf`). Rows of bundle['oos'] whose bar is not in the frame
    are dropped."""
    o = bundle.get("oos") or {}
    ts_all = np.asarray(o.get("ts", []), np.int64)
    P_all = np.asarray(o.get("P_ens", []), float)
    fr = frames.get(tf)
    if fr is None or len(ts_all) < 50:
        return None
    ind = fr.ind
    its = ind["ts"].to_numpy(np.int64)
    pos = np.searchsorted(its, ts_all)
    ok = (pos < len(its)) & (its[np.minimum(pos, len(its) - 1)] == ts_all) & np.isfinite(P_all).all(axis=1)
    ts, P, pos = ts_all[ok], P_all[ok], pos[ok]
    fwd = np.asarray(o.get("fwd_ret", np.zeros(len(ts_all))), float)[ok]
    if X is not None:
        X = X[ok]
    g = lambda c: ind[c].to_numpy(float)[pos]   # noqa: E731
    dts = ts + tf_ms(tf)
    mdir, msc = {}, {}
    for t in MTF_TIMEFRAMES:
        f = frames.get(t)
        if f is None:
            continue
        sc = f.ind["regime_score"].to_numpy(float)
        k = _align(dts, f.ind["ts"].to_numpy(np.int64), t)
        v = np.where(k >= 0, sc[np.maximum(k, 0)], np.nan)
        msc[t] = v
        mdir[t] = np.where(np.isfinite(v), np.where(np.abs(v) < DEADBAND, 0.0, np.sign(v)), np.nan)
    bf = btc_frame if btc_frame is not None else fr
    k = _align(dts, bf.ind["ts"].to_numpy(np.int64), tf)
    breg = np.where(k >= 0, bf.ind["regime_score"].to_numpy(float)[np.maximum(k, 0)], np.nan)
    btech = np.where(k >= 0, bf.ind["tech_score"].to_numpy(float)[np.maximum(k, 0)], np.nan)
    ctx = Context(symbol=symbol, tf=tf, ts=ts, P=P, rows=pos, close=g("close"), atr=g("atr"), ema21=g("ema_21"),
                  last_sl=g("last_sl"), last_sh=g("last_sh"), vol_state=g("vol_state"), tech=g("tech_score"),
                  comps={c: g(c) for c in ("sc_trend", "sc_momentum", "sc_volume", "sc_structure", "sc_volatility")},
                  regime_score=g("regime_score"), mtf_dir=mdir, mtf_score=msc, btc_regime=breg, btc_tech=btech,
                  swings=list(fr.swings), edge_confirmed=bool((bundle.get("edge") or {}).get("edge_confirmed")), X=X,
                  fwd_sign=np.sign(fwd))
    ctx.prepare()
    return ctx


# ---- directional view against a reference set ------------------------------------------------------------------------

def _policy(side: np.ndarray, margin: np.ndarray, hit: np.ndarray) -> dict[str, Any] | None:
    n_all = len(side)
    if n_all < 150:
        return None
    best = None
    for m in MARGINS:
        sel = margin >= m
        n = int(sel.sum())
        if n < MIN_CALLS or n / n_all < MIN_COVERAGE:
            continue
        lo, _ = wilson(int(hit[sel].sum()), n)
        if best is None or lo > best[1]:
            best = (m, lo)
    return {"margin": best[0] if best else None, "edge": bool(best and best[1] > 0.5)}


def _confidence(ref_side, ref_margin, ref_hit, side: np.ndarray, margin: np.ndarray) -> np.ndarray:
    """ml/direction.directional_confidence for many rows at once (same side, similar margin; fallback same side)."""
    out = np.full(len(side), np.nan)
    if len(ref_side) < 150:
        return out
    order = {s: np.sort(ref_margin[ref_side == s]) for s in (1.0, -1.0)}
    hits = {}
    for s in (1.0, -1.0):
        idx = np.argsort(ref_margin[ref_side == s], kind="stable")
        hits[s] = np.concatenate([[0], np.cumsum(ref_hit[ref_side == s][idx])])
    for s in (1.0, -1.0):
        m_sorted, cum = order[s], hits[s]
        sel = side == s
        if not sel.any() or len(m_sorted) == 0:
            continue
        mg = margin[sel]
        lo = np.searchsorted(m_sorted, 0.6 * mg, side="left")
        hi = np.searchsorted(m_sorted, np.maximum(1.6 * mg, mg + 0.02), side="right")
        n = hi - lo
        k = cum[hi] - cum[lo]
        n_all = len(m_sorted)
        res = np.where(n >= 30, k / np.maximum(n, 1), np.nan)
        res = np.where((n < 30) & (n_all >= 30), cum[-1] / max(n_all, 1), res)
        out[sel] = res
    return out


# ---- decisions ---------------------------------------------------------------------------------------------------------

def _label(comp: np.ndarray) -> np.ndarray:
    a = np.abs(comp)
    lvl = np.where(a >= THRESHOLDS[2], 3, np.where(a >= THRESHOLDS[1], 2, np.where(a >= THRESHOLDS[0], 1, 0)))
    return 3 + np.sign(comp).astype(int) * lvl


def round_trip() -> float:
    from ..engine.futures import FUTURES_FEE_RATE
    return 2 * (FUTURES_FEE_RATE + (settings.slippage_bps + settings.spread_bps / 2) / 1e4)


def decide(ctx: Context, ref: np.ndarray, conf_b: float | np.ndarray | None = None,
           weights: dict[str, float] | None = None, stop_mode: str = "current") -> dict[str, np.ndarray]:
    """Decision of the live pipeline on every row. `ref`: boolean mask of the rows whose outcomes may be used as the
    reference for the directional policy / confidence (rows before the split when proving; all rows in production).
    Returns arrays: trade (bool), side, grade ('A' / 'B' / ''), confidence, decision ('BUY' / 'BUY ON PULLBACK' /
    'SELL' / ''), reason, plan (list of dicts or None)."""
    w = {**DEFAULT_SIGNAL_WEIGHTS, **(weights or {})}
    n = ctx.n
    tf = ctx.tf
    P = ctx.P
    ml = (P[:, 2] - P[:, 0]) if (ctx.edge_confirmed or not settings.require_edge_for_ml) else np.full(n, np.nan)
    higher = [t for t in ctx.mtf_score if TF_SECONDS[t] > TF_SECONDS[tf]]
    if higher:
        hw = np.array([MTF_WEIGHTS[t] for t in higher])
        hs = np.vstack([ctx.mtf_score[t] for t in higher])
        av = np.isfinite(hs)
        htf_score = np.where(av.any(axis=0), np.nansum(np.where(av, hs, 0) * hw[:, None], axis=0) /
                             np.maximum((av * hw[:, None]).sum(axis=0), 1e-12), np.nan)
    else:
        htf_score = np.full(n, np.nan)
    values = {"trend": ctx.comps["sc_trend"], "momentum": ctx.comps["sc_momentum"], "volume": ctx.comps["sc_volume"],
              "structure": ctx.comps["sc_structure"], "ml": ml, "volatility": ctx.comps["sc_volatility"], "htf": htf_score}
    num = np.zeros(n)
    den = np.zeros(n)
    for k, v in values.items():
        if w.get(k, 0) <= 0:
            continue
        av = np.isfinite(v)
        num += np.where(av, v, 0) * w[k]
        den += av * w[k]
    core = np.isfinite(values["trend"]) & np.isfinite(values["momentum"])
    composite = np.clip(np.where(den > 0, num / np.maximum(den, 1e-12), 0.0), -1, 1)
    idx = _label(composite)
    # multi-timeframe alignment with the tech lean and short / long conflict (engine/mtf.py)
    tfs = list(ctx.mtf_dir)
    D = np.vstack([ctx.mtf_dir[t] for t in tfs])
    Wt = np.array([MTF_WEIGHTS[t] for t in tfs])[:, None] * np.isfinite(D)
    Wn = Wt / np.maximum(Wt.sum(axis=0), 1e-12)
    lean = np.sign(np.nan_to_num(ctx.tech))
    Dz = np.nan_to_num(D)
    align = (Wn * (Dz == lean)).sum(axis=0) + 0.5 * (Wn * (Dz == 0)).sum(axis=0)
    net = (Wn * Dz).sum(axis=0)
    dom = np.where(np.abs(net) >= 0.05, np.sign(net), 0)
    align_dom = np.where(dom == 0, (Wn * (Dz == 0)).sum(axis=0) + 0.5 * (Wn * (Dz != 0)).sum(axis=0),
                         (Wn * (Dz == dom)).sum(axis=0) + 0.5 * (Wn * (Dz == 0)).sum(axis=0))
    align = np.where(lean == 0, align_dom, align)
    sc = {t: ctx.mtf_score[t] for t in tfs}
    short = [sc[t] for t in tfs if TF_SECONDS[t] <= 3600]
    long_ = [sc[t] for t in tfs if TF_SECONDS[t] >= 86400]
    if short and long_:
        ms, ml_ = np.nanmean(np.vstack(short), axis=0), np.nanmean(np.vstack(long_), axis=0)
        conflict = np.nan_to_num(ms * ml_) < 0
        conflict &= (np.abs(np.nan_to_num(ms)) > 0.3) & (np.abs(np.nan_to_num(ml_)) > 0.3)
    else:
        conflict = np.zeros(n, bool)
    down = (idx != 3) & (conflict | (align < 0.5))
    idx = np.where(down, idx - np.sign(idx - 3), idx)
    direction = np.sign(idx - 3).astype(int)
    weak = np.isin(idx, (2, 4))
    # directional view against the reference rows
    side_m = np.where(P[:, 2] >= P[:, 0], 1.0, -1.0)
    margin = np.abs(P[:, 2] - P[:, 0])
    fwd_sign = getattr(ctx, "fwd_sign", None)
    if fwd_sign is None:
        raise ValueError("context needs fwd_sign (sign of the next bar's return) for the directional reference")
    hit = (fwd_sign == side_m) & (fwd_sign != 0)
    pol = _policy(side_m[ref], margin[ref], hit[ref]) or {"margin": None, "edge": False}
    conf = _confidence(side_m[ref], margin[ref], hit[ref].astype(float), side_m, margin)
    conf = np.where(ctx.vol_state == 2, 0.5 + (conf - 0.5) * 0.85, conf)
    clears = (margin >= pol["margin"]) if pol["margin"] is not None else np.zeros(n, bool)
    model_led = (direction == 0) & clears & bool(pol["edge"])
    side = np.where((direction != 0) & (side_m == direction), direction, np.where(model_led, side_m, 0)).astype(int)
    cb = settings.min_dir_confidence_b if conf_b is None else conf_b
    cb = np.broadcast_to(np.asarray(cb, float), (n,))
    firm = (direction != 0) & ~weak
    ok_a = np.nan_to_num(conf, nan=-1) >= np.maximum(settings.min_dir_confidence_a, cb)
    ok_b = np.nan_to_num(conf, nan=-1) >= cb
    gA = (side != 0) & firm & clears & ok_a
    gB = (side != 0) & ~gA & ok_b & (clears | firm)
    grade = np.where(gA, "A", np.where(gB, "B", ""))
    reason = np.where(core, "", "insufficient")
    reason = np.where((reason == "") & (ctx.vol_state == 3), "extreme_vol", reason)
    reason = np.where((reason == "") & (grade == ""), "no_grade", reason)
    # higher-timeframe check: the next two higher timeframes with a direction
    order = sorted([t for t in tfs if TF_SECONDS[t] > TF_SECONDS[tf]], key=lambda t: TF_SECONDS[t])
    against = np.zeros(n, int)
    if order:
        Dh = np.vstack([ctx.mtf_dir[t] for t in order])
        for j in range(n):
            if not side[j] or reason[j]:
                continue
            col = Dh[:, j]
            used = col[np.isfinite(col)][:2]
            against[j] = int((used == -side[j]).sum())
    reason = np.where((reason == "") & (against >= 2), "bigger_trend", reason)
    grade = np.where((against == 1) & (grade == "A"), "B", grade)
    plans: list[dict | None] = [None] * n
    rt = round_trip()
    for j in np.flatnonzero(reason == ""):
        pl = S.plan(int(side[j]), float(ctx.close[j]), float(ctx.atr[j]), float(ctx.ema21[j]), ctx.zones(j),
                    float(ctx.last_sl[j]), float(ctx.last_sh[j]), stop_mode=stop_mode)
        plans[j] = pl
        if not pl["valid"]:
            reason[j] = "no_setup"
        elif pl["dist"] / pl["ideal"] < COST_MULT * rt:
            reason[j] = "costs"
    trade = reason == ""
    dec = np.where(~trade, "", np.where(side > 0, "BUY", "SELL")).astype(object)
    for j in np.flatnonzero(trade & (side > 0)):
        if plans[j]["extended"]:
            dec[j] = "BUY ON PULLBACK"
    return {"trade": trade, "side": side, "grade": grade, "confidence": conf, "decision": dec, "reason": reason,
            "plan": plans, "margin": margin, "side_model": side_m}


# ---- outcomes ----------------------------------------------------------------------------------------------------------

@dataclass
class Paths:
    """15m and own-timeframe candles of one coin as arrays (ts = candle open)."""
    p15: pd.DataFrame | None
    own: pd.DataFrame | None

    def __post_init__(self):
        self._a = {}
        for k, d in (("p15", self.p15), ("own", self.own)):
            if d is not None and len(d):
                self._a[k] = tuple(d[c].to_numpy(np.int64 if c == "ts" else float) for c in ("ts", "high", "low", "close"))

    def window(self, start: int, end: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int] | None:
        """Candles opened in [start, end) - 15m when they cover the whole window, else own-timeframe ones."""
        for k, ms in (("p15", 900_000), ("own", None)):
            a = self._a.get(k)
            if a is None:
                continue
            ts = a[0]
            i, j = np.searchsorted(ts, start), np.searchsorted(ts, end)
            if j <= i:
                continue
            if k == "p15" and (ts[i] > start + ms or ts[j - 1] + ms < end):
                continue
            return a[0][i:j], a[1][i:j], a[2][i:j], a[3][i:j], (ms or 0)
        return None


def simulate(ctx: Context, paths: Paths, j: int, side: int, pl: dict[str, Any], entry_mode: str = "old",
             k: float = 0.0, cost_pct: float | None = None) -> dict[str, Any] | None:
    """Result of the call at row j, or None when it never filled / is not finished on the stored candles."""
    step = tf_ms(ctx.tf)
    start = int(ctx.decision_ts[j])
    end = start + HORIZON_BARS * step
    w = paths.window(start, end)
    if w is None:
        return None
    ts, hi, lo, cl, ms = w
    bar = ms or step
    window = max(1, int(round(settings.fill_window_bars * step / bar)))
    f = S.fill(entry_mode, side, float(ctx.close[j]), float(ctx.atr[j]), pl, hi, lo, cl, window, k)
    if f is None:
        return {"filled": False}
    i0, entry, first_is_fill = f
    stop = pl["stop"]
    if side * (entry - stop) <= 0:
        return {"filled": False}
    tps = S.ladder(side, entry, stop)
    complete = int(ts[-1]) + bar >= end
    out = S.follow(side, entry, stop, tps, hi[i0:], lo[i0:], cl[i0:], first_is_fill=first_is_fill, complete=complete)
    if out is None:
        return None
    c = settings.research_cost_pct if cost_pct is None else cost_pct
    return {"filled": True, "r": out.net_r(c), "status": out.status, "exit": out.exit_reason, "risk_pct": out.risk_pct,
            "closed_ts": int(ts[i0 + out.exit_idx]) + bar, "entry": entry}


def take(ts: np.ndarray, closed: np.ndarray, step: int, cooldown_bars: int | None = None) -> np.ndarray:
    """Indices (time order) of the calls the record would have taken: one at a time per series, plus the cooldown."""
    cd = (settings.reentry_cooldown_bars if cooldown_bars is None else cooldown_bars) * step
    out, free = [], -1
    for i in np.argsort(ts, kind="stable"):
        if ts[i] >= free:
            out.append(int(i))
            free = closed[i] + cd
    return np.array(out, int)


def candidates(ctx: Context, paths: Paths, mask: np.ndarray, decision: dict[str, np.ndarray], entry_mode: str = "old",
               k: float = 0.0, cost_pct: float | None = None, news: Callable[[int], bool] | None = None,
               plans: list | None = None) -> list[dict[str, Any]]:
    """Every call the pipeline would have made among rows in `mask`, each simulated on its own (time order).
    entry_mode "old": the v2.5 rule (BUY ON PULLBACK = limit at the ideal entry, everything else at market)."""
    res = []
    for j in np.flatnonzero(mask & decision["trade"]):
        if news is not None and news(int(ctx.decision_ts[j])):
            continue
        pl = (plans or decision["plan"])[j]
        mode = entry_mode
        if mode == "old" and decision["decision"][j] != "BUY ON PULLBACK":
            mode = "market"
        r = simulate(ctx, paths, int(j), int(decision["side"][j]), pl, mode, k, cost_pct)
        if r is None:
            continue
        if not r["filled"]:
            # a pending entry that never filled blocks the series for the fill window only
            r = {"filled": False, "closed_ts": int(ctx.decision_ts[j]) + settings.fill_window_bars * tf_ms(ctx.tf)}
        res.append({"j": int(j), "ts": int(ctx.decision_ts[j]), **r})
    return res


def taken(ctx: Context, cands: list[dict[str, Any]], keep: Callable[[dict[str, Any]], bool] | None = None) -> list[dict[str, Any]]:
    """The calls the record would have kept: `keep` filters first (a refused call never blocks the series), then one
    call at a time per series plus the re-entry cooldown; unfilled pullbacks occupy the series but are not trades."""
    cs = [c for c in cands if keep is None or keep(c)]
    if not cs:
        return []
    idx = take(np.array([c["ts"] for c in cs]), np.array([c["closed_ts"] for c in cs]), tf_ms(ctx.tf))
    return [cs[i] for i in idx if cs[i]["filled"]]


def run_series(ctx: Context, paths: Paths, mask: np.ndarray, decision: dict[str, np.ndarray], entry_mode: str = "old",
               k: float = 0.0, cost_pct: float | None = None, news: Callable[[int], bool] | None = None,
               plans: list | None = None) -> list[dict[str, Any]]:
    """Trades the pipeline would have recorded among rows in `mask` (time order, one at a time)."""
    return taken(ctx, candidates(ctx, paths, mask, decision, entry_mode, k, cost_pct, news, plans))


# ---- nightly policy (items 1 and 2) --------------------------------------------------------------------------------------

def choose_conf(ctx: Context, paths: Paths, rows: np.ndarray, ref: np.ndarray, min_n: int, news=None,
                grid: tuple[float, ...] = CONF_GRID) -> dict[str, Any]:
    """Per-series grade-B confidence threshold chosen on `rows` by the lower bound of the expectancy (80% one-sided
    bootstrap); None when no option has at least `min_n` trades."""
    table = []
    for c in grid:
        d = decide(ctx, ref, conf_b=c)
        tr = run_series(ctx, paths, rows, d, news=news)
        r = [t["r"] for t in tr]
        table.append({"conf_b": c, "n": len(r), "mean_r": float(np.mean(r)) if r else None,
                      "lb80": S.bootstrap_lb(r, 0.8) if len(r) >= min_n else None})
    ok = [t for t in table if t["lb80"] is not None]
    best = max(ok, key=lambda t: (t["lb80"], -t["conf_b"])) if ok else None
    return {"conf_b": best["conf_b"] if best else None, "table": table}


def compute(ctx: Context, paths: Paths, record_r: list[float] | None = None, min_n: int | None = None,
            q: float | None = None, news=None) -> dict[str, Any]:
    """Production policy of one series on ALL its out-of-sample history (+ the live record)."""
    min_n = settings.series_gate_min_n if min_n is None else min_n
    q = settings.series_gate_q if q is None else q
    allrows = np.ones(ctx.n, bool)
    d = decide(ctx, allrows)
    tr = run_series(ctx, paths, allrows, d, news=news)
    r = [t["r"] for t in tr] + list(record_r or [])
    gate = S.gate_decision(r, min_n, q)
    conf = choose_conf(ctx, paths, allrows, allrows, max(10, min_n // 2), news=news)
    return {"at": int(time.time() * 1000), "symbol": ctx.symbol, "timeframe": ctx.tf, "gate": gate,
            "conf_b": conf["conf_b"], "conf_table": conf["table"], "oos_trades": len(tr),
            "record_trades": len(record_r or []),
            "span": [int(ctx.ts[0]), int(ctx.ts[-1])] if ctx.n else None}


def apply(policy: dict[str, Any] | None) -> dict[str, Any]:
    """What the live analysis does with a cached policy: {'blocked', 'reason', 'conf_b'} (all off when settings say so)."""
    out = {"blocked": False, "reason": None, "conf_b": None}
    if not policy:
        return out
    g = policy.get("gate") or {}
    if settings.series_gate and g.get("blocked"):
        out.update(blocked=True, reason="this coin/timeframe has no proven edge yet "
                   f"(expected {g.get('mean_r', 0):+.2f}R per trade over {g.get('n')} out-of-sample and live trades; "
                   "the lower bound is not above zero)")
    if settings.series_conf and policy.get("conf_b") is not None:
        out["conf_b"] = float(policy["conf_b"])
    elif settings.series_conf:
        out["conf_b"] = settings.series_conf_default
    return out
