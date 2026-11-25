"""v2.65 capital-protection veto (owner: "independent veto authority"; research `results/v265-latest.json`, 21 Nov 2026:
the three rules together PASS the standard verdict on 886 unseen calls: +34.9R -> +53.2R, max drawdown 37.4R -> 30.0R,
worst losing streak 14 -> 11, both halves better, bootstrap 98 %, 113 calls differ).

* volatile: the coin's 4h ATR14 is above 1.5 x its ATR100 (closed 4h candles only).
* loss stop: record calls closed today (UTC) total <= -3R net, or this week (Monday UTC) <= -6R net.
* drift: the series' last 100 live forecasts whose next bar has closed hit the direction more than 2 standard errors
  less often than its model's own out-of-sample record.
`analysis.analyze` applies it last, after every other check, to every live call (record, demo bots, Hesper, Last Stand,
auto-trade all take their calls from there): NO TRADE "CAPITAL PROTECTION". Switch `RISK_VETO` (env, default on).

V3.2 (Fable 5.2 audit R-01) fail closed: `assess` lists every rule it could not evaluate in `unavailable` (with
`unavailable_reason`). The volatility rule and the loss stop are required: no 4h candles, fewer than VOL_MIN_BARS of
them, the newest older than VOL_MAX_AGE_BARS bars, or an error = unavailable. The drift rule is required only to run
without error; "not enough live forecasts yet" is its designed warm-up state (`drift_state` = "insufficient_history",
shown, not blocking: on 1d/3d it takes 100-300 days to fill). `analysis.analyze` turns a non-empty `unavailable` into
NO TRADE "CHECK UNAVAILABLE" for new entries only. `would_block` still means "a rule fired"."""
from __future__ import annotations

import time
from typing import Any

import numpy as np

H4 = 4 * 3_600_000
DAY = 86_400_000
VOL_RATIO, DAY_R, WEEK_R = 1.5, 3.0, 6.0
DRIFT_N = 100
VOL_MIN_BARS = 110
VOL_MAX_AGE_BARS = 2
_cache: dict[str, Any] = {}


def vol_check(rt: Any, symbol: str, now: int | None = None) -> tuple[bool | None, str | None]:
    """(volatile, why unavailable). volatile is None exactly when the reason is set."""
    try:
        df = rt.candles(symbol, "4h")
    except Exception as exc:
        return None, f"4h candles unreadable ({type(exc).__name__}: {exc})"[:160]
    if df is None or len(df) == 0:
        return None, "no 4h candles"
    if len(df) < VOL_MIN_BARS:
        return None, f"insufficient 4h history ({len(df)} of {VOL_MIN_BARS} candles)"
    if now is not None:
        age = (int(now) - (int(df["ts"].iloc[-1]) + H4)) / H4
        if age > VOL_MAX_AGE_BARS:
            return None, f"4h data is stale (newest closed candle {age * 4:.1f} h old)"
    try:
        return volatile(rt, symbol), None
    except Exception as exc:
        return None, f"volatility check failed ({type(exc).__name__}: {exc})"[:160]


def volatile(rt: Any, symbol: str) -> bool | None:
    try:
        df = rt.candles(symbol, "4h")
    except Exception:
        return None
    if df is None or len(df) < VOL_MIN_BARS:
        return None
    h, l, c = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
    prev = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))
    a14, a100 = float(tr[-14:].mean()), float(tr[-100:].mean())
    return bool(a100 > 0 and a14 > VOL_RATIO * a100)


def _net_r(r: dict[str, Any]) -> float | None:
    from . import tracking
    net, e, s = tracking.net_pct(r), r.get("entry"), r.get("stop")
    if net is None or not e or not s:
        return None
    risk = abs(float(e) - float(s)) / float(e) * 100
    return net / risk if risk > 0 else None


def loss_sums(rt: Any, now: int) -> tuple[float, float]:
    """Net R of record calls closed today and this week (cached 5 minutes)."""
    hit = _cache.get("sums")
    if hit and now - hit[0] < 300_000:
        return hit[1]
    from . import tracking
    d0 = now // DAY * DAY
    w0 = d0 - ((d0 // DAY + 3) % 7) * DAY
    closed = tuple(tracking.CLOSED_STATUSES)
    rows = rt.db.query(f"SELECT * FROM signals WHERE closed_at >= ? AND status IN ({','.join('?' * len(closed))})",
                       (w0, *closed))
    day = week = 0.0
    for r in rows:
        if r.get("fill_status") == "NOT_FILLED":
            continue
        x = _net_r(r)
        if x is None:
            continue
        week += x
        if int(r["closed_at"]) >= d0:
            day += x
    out = (round(day, 3), round(week, 3))
    _cache["sums"] = (now, out)
    return out


def drift(rt: Any, symbol: str, timeframe: str) -> dict[str, Any] | None:
    """Live direction hit rate of the last DRIFT_N resolved forecasts vs the model's out-of-sample record (cached per
    bar). None when there is not enough history."""
    from ..data.base import tf_ms
    from ..ml import trainer
    key = f"drift|{symbol}|{timeframe}"
    df = rt.candles(symbol, timeframe)
    if df is None or df.empty:
        return None
    last_ts = int(df["ts"].iloc[-1])
    hit = _cache.get(key)
    if hit and hit[0] == last_ts:
        return hit[1]
    out = None
    b = trainer.load_bundle(symbol, timeframe, rt.db)
    o = (b or {}).get("oos") or {}
    P, fwd = np.asarray(o.get("P_ens", []), float), np.asarray(o.get("fwd_ret", []), float)
    if len(P) >= 200:
        side = np.sign(P[:, 2] - P[:, 0])
        ok = (side != 0) & (np.sign(fwd) != 0)
        ref = float((np.sign(fwd[ok]) == side[ok]).mean()) if ok.any() else None
        closes = dict(zip(df["ts"].astype("int64").tolist(), df["close"].astype(float).tolist()))
        step = tf_ms(timeframe)
        rows = rt.db.query("SELECT bar_ts, p_up, p_down FROM predictions WHERE symbol = ? AND timeframe = ? "
                           "ORDER BY bar_ts DESC LIMIT ?", (symbol, timeframe, DRIFT_N * 4))
        seen, hits = set(), []
        for r in rows:
            t = int(r["bar_ts"])
            if t in seen or t + step not in closes or t not in closes:
                continue
            seen.add(t)
            s_ = np.sign(float(r["p_up"]) - float(r["p_down"]))
            move = np.sign(closes[t + step] - closes[t])
            if s_ == 0 or move == 0:
                continue
            hits.append(1.0 if s_ == move else 0.0)
            if len(hits) >= DRIFT_N:
                break
        if ref is not None and len(hits) >= DRIFT_N:
            se = float(np.sqrt(max(ref * (1 - ref), 1e-6) / DRIFT_N))
            rate = float(np.mean(hits))
            out = {"n": len(hits), "hit": round(rate, 3), "ref": round(ref, 3), "block": bool(rate < ref - 2 * se)}
    _cache[key] = (last_ts, out)
    return out


def assess(rt: Any, symbol: str, now: int | None = None, timeframe: str | None = None) -> dict[str, Any]:
    now = int(time.time() * 1000) if now is None else int(now)
    unavailable: dict[str, str] = {}
    vol, why_vol = vol_check(rt, symbol, now)
    if why_vol:
        unavailable["volatility"] = why_vol
    try:
        day, week = loss_sums(rt, now)
    except Exception as exc:
        day = week = None
        unavailable["loss_stop"] = f"closed-call totals unreadable ({type(exc).__name__}: {exc})"[:160]
    stop = day is not None and (day <= -DAY_R or week <= -WEEK_R)
    dr, drift_state = None, "off"
    if timeframe:
        try:
            dr = drift(rt, symbol, timeframe)
            drift_state = "ok" if dr else "insufficient_history"
        except Exception as exc:
            dr, drift_state = None, "error"
            unavailable["drift"] = f"drift check failed ({type(exc).__name__}: {exc})"[:160]
    drift_block = bool(dr and dr.get("block"))
    reasons = []
    if vol:
        reasons.append("this coin's volatility is far above normal (4h ATR more than 1.5x its 100-bar average)")
    if stop:
        reasons.append(f"today's or this week's closed signals hit the loss limit ({day:+.1f}R today, {week:+.1f}R this week)")
    if drift_block:
        reasons.append(f"the model's recent direction hits ({dr['hit']:.0%}) fell well below its tested rate ({dr['ref']:.0%})")
    return {"volatile": vol, "day_r": day, "week_r": week, "loss_stop": bool(stop), "drift": dr,
            "drift_block": drift_block, "drift_state": drift_state, "would_block": bool(vol) or bool(stop) or drift_block,
            "reason": "; ".join(reasons) if reasons else None,
            "unavailable": sorted(unavailable),
            "unavailable_reason": "; ".join(f"{k}: {v}" for k, v in sorted(unavailable.items())) or None}
