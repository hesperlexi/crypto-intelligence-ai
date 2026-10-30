"""v2.6: out-of-sample trade simulation per coin / timeframe (pure functions, no database).

Used by the nightly series policy (ml/series_policy.py) and by the proof harness (`python -m app.research engine`).

* `follow`      the standard exit rules of the live record (engine/manage.follow with managed exits off): 50 / 25 / 25
                at TP1 / TP2 / TP3, stop first inside a candle, break-even after TP1, TP1 after TP2, expiry at the last
                close of the horizon. Vectorised per phase; a unit test proves it equal to manage.follow.
* `plan`        entry / stop of a call as engine/setup.build_setup makes them (`stop_mode="current"`), or the v2.6
                structure stop (`"struct"`: beyond the nearest confirmed swing / S-R level + an ATR buffer, bounded to
                [0.8, 3.5] ATR). Targets are re-derived in R from the actual entry on the fixed ladder 1R / 1.75R / 2.5R.
* `fill`        how the entry happens: market at the decision close, the v2.5 pullback limit at the ideal entry
                (`"old"`), a v2.6 confirmation (a path candle closing beyond close + k ATR in the trade direction) or a
                pullback limit at close - k ATR - each within the fill window.
* `bootstrap_lb` / `gate_decision`  is a series' expectancy credibly positive?
Everything is causal: a decision at bar i only uses values known at its close; the path starts with the first candle
opened at/after that close.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

TP_LADDER = (1.0, 1.75, 2.5)
TP_SPLIT = (0.5, 0.25, 0.25)
STRUCT_BOUNDS = (0.8, 3.5)          # v2.6 structure stop: distance from the entry, in ATR
CURRENT_BOUNDS = (1.0, 3.0)         # engine/setup.py
EXTENDED_ATR = 0.4


# ---- exits -------------------------------------------------------------------------------------------------------

def _first(mask: np.ndarray, frm: int) -> int | None:
    if frm >= len(mask):
        return None
    idx = np.flatnonzero(mask[frm:])
    return int(frm + idx[0]) if len(idx) else None


@dataclass
class Outcome:
    status: str             # STOPPED / TP1 / TP2 / TP3 / EXPIRED
    exit_reason: str        # stop / break_even / trail / tp3 / expired
    return_pct: float       # gross, % of the entry (all legs)
    risk_pct: float
    exit_idx: int           # index in the path of the candle that closed the call

    def net_r(self, cost_pct: float) -> float:
        return (self.return_pct - cost_pct) / self.risk_pct if self.risk_pct else 0.0


def follow(side: int, entry: float, stop: float, tps: tuple[float, float, float] | list[float], high: np.ndarray,
           low: np.ndarray, close: np.ndarray, first_is_fill: bool = False, complete: bool = True) -> Outcome | None:
    """Standard rules on a path that starts at the entry candle. None when the call is still open at the path's end
    (and `complete` is False) or the path is empty."""
    n = len(high)
    if n == 0 or side == 0 or entry <= 0:
        return None
    s = 1 if side > 0 else -1
    fav, adv = (high, low) if s > 0 else (low, high)
    hit_adv = (lambda lvl: adv <= lvl) if s > 0 else (lambda lvl: adv >= lvl)
    hit_fav = (lambda lvl: fav >= lvl) if s > 0 else (lambda lvl: fav <= lvl)
    tp1, tp2, tp3 = (float(t) for t in tps)
    risk_pct = abs(entry - stop) / entry * 100
    legs = [None, None, None]
    t0 = 1 if first_is_fill else 0

    def done(status: str, reason: str, idx: int, fallback: float) -> Outcome:
        px = [legs[k] if legs[k] is not None else fallback for k in range(3)]
        ret = sum(w * s * (p / entry - 1) for w, p in zip(TP_SPLIT, px)) * 100
        return Outcome(status, reason, float(ret), float(risk_pct), int(idx))

    ts_ = _first(hit_adv(stop), 0)
    t1 = _first(hit_fav(tp1), t0)
    if t1 is None or (ts_ is not None and ts_ <= t1):
        if ts_ is not None:
            return done("STOPPED", "stop", ts_, stop)
        return done("EXPIRED", "expired", n - 1, float(close[-1])) if complete else None
    legs[0] = tp1
    if hit_fav(tp2)[t1]:
        t2 = t1
    else:
        tb = _first(hit_adv(entry), t1 + 1)
        t2 = _first(hit_fav(tp2), t1 + 1)
        if t2 is None or (tb is not None and tb <= t2):
            if tb is not None:
                return done("TP1", "break_even", tb, entry)
            return done("TP1", "expired", n - 1, float(close[-1])) if complete else None
    legs[1] = tp2
    if hit_fav(tp3)[t2]:
        legs[2] = tp3
        return done("TP3", "tp3", t2, tp3)
    tb = _first(hit_adv(tp1), t2 + 1)
    t3 = _first(hit_fav(tp3), t2 + 1)
    if t3 is None or (tb is not None and tb <= t3):
        if tb is not None:
            return done("TP2", "trail", tb, tp1)
        return done("TP2", "expired", n - 1, float(close[-1])) if complete else None
    legs[2] = tp3
    return done("TP3", "tp3", t3, tp3)


def ladder(side: int, entry: float, stop: float, mult: tuple[float, ...] = TP_LADDER) -> list[float]:
    d = abs(entry - stop)
    return [float(entry + side * m * d) for m in mult]


# ---- plan (entry / stop) -------------------------------------------------------------------------------------------

def plan(side: int, price: float, atr: float, ema21: float | None, zones: dict[str, list[dict]], last_sl: float,
         last_sh: float, stop_mode: str = "current", buffer_atr: float = 0.25) -> dict[str, Any]:
    """Ideal entry, stop and validity as engine/setup.build_setup computes them (the historical base-rate check and the
    data-chosen TP2 / TP3 are left out: targets use the fixed ladder)."""
    if not np.isfinite(atr) or atr <= 0 or side == 0:
        return {"valid": False, "reason": "atr"}
    behind = zones["support"] if side > 0 else zones["resistance"]
    ahead = zones["resistance"] if side > 0 else zones["support"]
    near = behind[0] if behind else None
    edge = (near["high"] if side > 0 else near["low"]) if near else None
    conservative = edge if edge is not None and abs(price - edge) <= 2.0 * atr else price - side * 1.0 * atr
    ideal = price - side * 0.5 * atr
    if ema21 is not None and np.isfinite(ema21) and side * (price - ema21) > 0 and abs(price - ema21) <= 1.5 * atr:
        ideal = side * max(side * ideal, side * ema21)
    ideal = side * max(side * ideal, side * conservative)
    ideal = side * min(side * ideal, side * price)
    swing = last_sl if side > 0 else last_sh
    struct = []
    if near:
        struct.append(near["low"] if side > 0 else near["high"])
    if np.isfinite(swing) and side * (ideal - swing) > 0:
        struct.append(float(swing))
    if stop_mode == "struct":
        # nearest protective level beyond the entry (the closest one, not the farthest), plus a buffer
        beyond = [x for x in struct if side * (ideal - x) > 0]
        if beyond:
            lvl = max(beyond) if side > 0 else min(beyond)
            dist = float(np.clip(side * (ideal - (lvl - side * buffer_atr * atr)), STRUCT_BOUNDS[0] * atr, STRUCT_BOUNDS[1] * atr))
        else:
            dist = 1.5 * atr
    elif stop_mode.startswith("atr"):
        dist = float(stop_mode[3:] or 1.5) * atr
    else:
        raw = (min(struct) if side > 0 else max(struct)) - side * 0.25 * atr if struct else ideal - side * 1.5 * atr
        dist = float(np.clip(side * (ideal - raw), CURRENT_BOUNDS[0] * atr, CURRENT_BOUNDS[1] * atr))
    stop = ideal - side * dist
    out = {"ideal": float(ideal), "stop": float(stop), "dist": float(dist), "extended": bool(abs(price - ideal) >= EXTENDED_ATR * atr),
           "valid": True, "reason": None}
    if ahead:
        first = ahead[0]["low"] if side > 0 else ahead[0]["high"]
        if side * (first - price) < 1.0 * dist:
            out.update(valid=False, reason="blocker")
    return out


# ---- entry -----------------------------------------------------------------------------------------------------------

def fill(mode: str, side: int, price: float, atr: float, p: dict[str, Any], high: np.ndarray, low: np.ndarray,
         close: np.ndarray, window: int, k: float = 0.0) -> tuple[int, float, bool] | None:
    """(start index in the path, entry price, first_is_fill) or None when the entry never happened.

    mode "market":   at the decision close (the path starts with its first candle).
    mode "old":      v2.5 - long and extended: limit at the ideal entry; otherwise market.
    mode "confirm":  a path candle within `window` candles closes beyond price + side * k * ATR; entry at that close
                     (the trade starts with the next candle). Cancelled if the stop trades first.
    mode "pullback": limit at price - side * k * ATR within `window` candles (never at / through the stop)."""
    if len(high) == 0:
        return None
    stop = p["stop"]
    w = min(window, len(high))
    if mode == "market" or (mode == "old" and not (side > 0 and p["extended"])):
        return 0, float(price), False
    if mode == "old" or mode == "pullback":
        lim = p["ideal"] if mode == "old" else price - side * k * atr
        if side * (lim - stop) <= 0:
            return None
        touch = (low[:w] <= lim) if side > 0 else (high[:w] >= lim)
        i = _first(touch, 0)
        return None if i is None else (i, float(lim), True)
    if mode == "confirm":
        lvl = price + side * k * atr
        conf = (close[:w] > lvl) if side > 0 else (close[:w] < lvl)
        bad = (low[:w] <= stop) if side > 0 else (high[:w] >= stop)
        i, b = _first(conf, 0), _first(bad, 0)
        if i is None or (b is not None and b <= i) or i + 1 >= len(high):
            return None
        if side * (close[i] - stop) <= 0:
            return None
        return i + 1, float(close[i]), False
    raise ValueError(mode)


# ---- statistics --------------------------------------------------------------------------------------------------------

def bootstrap_lb(r: np.ndarray | list[float], q: float, n_boot: int = 2000, seed: int = 0) -> float | None:
    """One-sided lower bound of the mean at confidence q (q = 0.5: the plain mean)."""
    x = np.asarray(r, float)
    if len(x) == 0:
        return None
    if q <= 0.5:
        return float(x.mean())
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), size=(n_boot, len(x)))].mean(axis=1)
    return float(np.quantile(means, 1 - q))


def gate_decision(r: list[float], min_n: int, q: float) -> dict[str, Any]:
    """Proven-only series gate. Fewer than `min_n` closed trades: no verdict (current behaviour kept). Otherwise the
    series trades only when the lower bound of its expectancy is above zero."""
    n = len(r)
    if n < min_n:
        return {"blocked": False, "verdict": "too_few", "n": n, "mean_r": float(np.mean(r)) if n else None, "lb": None, "q": q}
    lb = bootstrap_lb(r, q)
    return {"blocked": bool(lb is None or lb <= 0), "verdict": "proven" if lb and lb > 0 else "no_edge", "n": n,
            "mean_r": float(np.mean(r)), "lb": lb, "q": q}


def stats(rs: list[float], weeks: float | None = None) -> dict[str, Any]:
    n = len(rs)
    if not n:
        return {"n": 0, "win_rate": None, "expectancy_r": None, "profit_factor": None, "max_drawdown_r": 0.0,
                "total_r": 0.0, "trades_per_week": 0.0 if weeks else None}
    r = np.asarray(rs, float)
    eq = np.concatenate([[0.0], np.cumsum(r)])
    dd = float(np.max(np.maximum.accumulate(eq) - eq))
    gains, losses = r[r > 0].sum(), -r[r <= 0].sum()
    return {"n": n, "win_rate": float((r > 0).mean()), "expectancy_r": float(r.mean()),
            "profit_factor": float(gains / losses) if losses > 0 else None, "max_drawdown_r": dd, "total_r": float(r.sum()),
            "trades_per_week": float(n / weeks) if weeks else None}
