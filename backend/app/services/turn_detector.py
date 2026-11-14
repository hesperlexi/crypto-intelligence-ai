"""v2.22 market turn detector (owner, 14 Nov 2026) - ADMIN ONLY, RECOMMEND-ONLY: it never changes a call.

Question it answers: "is the current trend still intact, or is the market starting to turn?" - per coin and market-wide
(BTC counts half, the watchlist breadth the other half). Deterministic points from data the engine already has plus the
live OKX numbers recorded by services/market_data.py (constants below). For a coin whose 4h trend is DOWN, the points
count evidence of a turn UP, and the other way round:

  structure break   4h close beyond the last confirmed 4h swing high (downtrend) / swing low (uptrend)   up to 30
                    1d close beyond the last 1d swing                                                   up to 20
  value-area break  4h close outside the 200-bar volume profile value area, on the turn side            up to 15
  taker flow flip   last 24 h taker buy/sell ratio against the trend (OKX)                              up to 15
  open interest     price against the trend with open interest rising (new positions behind the move)   up to 10
  liquidations      last 24 h liquidations of the trend side >= 3x their 7-day hourly average           up to 10
  funding extreme   funding z-score >= 2 on the trend side (crowded) over the last 30 days              up to 10

The trend is judged without the newest 3 bars (the move under test must not hide the trend it breaks).
Score >= 50 -> "turning up/down", 25-49 -> "weakening", else "trend intact". No trend (4h EMA50 within 0.3 ATR, or 4h and
1d disagree) -> "range". Every point comes with its reason and numbers. Published as `views/market_turn` (admin only).
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from ..db import now_ms
from . import market_data as MD

log = logging.getLogger(__name__)

HOUR, DAY = 3_600_000, 86_400_000
SWING_K = 2                 # a swing high = higher than the 2 bars on each side
VP_BARS, VP_BINS, VP_AREA = 200, 50, 0.70
TURN, WEAK = 50, 25
TREND_LAG = 3              # bars left out when judging the established trend
PUBLISH_EVERY_S = 1800
MAX_COINS = 40


def ema(x: np.ndarray, n: int) -> np.ndarray:
    a = 2.0 / (n + 1)
    out = np.empty(len(x), float)
    m = float(x[0]) if len(x) else 0.0
    for i, v in enumerate(x):
        m = a * float(v) + (1 - a) * m
        out[i] = m
    return out


def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = 14) -> float:
    if len(c) < n + 1:
        return float("nan")
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return float(np.mean(tr[-n:]))


def trend_of(c: np.ndarray, h: np.ndarray, l: np.ndarray) -> int:
    """+1 up / -1 down / 0 flat: close vs EMA50 by more than 0.3 ATR and EMA50 sloping the same way over 5 bars."""
    if len(c) < 60:
        return 0
    e = ema(c, 50)
    a = atr(h, l, c)
    if not np.isfinite(a) or a <= 0:
        return 0
    d, slope = c[-1] - e[-1], e[-1] - e[-6]
    if d > 0.3 * a and slope > 0:
        return 1
    if d < -0.3 * a and slope < 0:
        return -1
    return 0


def last_swings(h: np.ndarray, l: np.ndarray, k: int = SWING_K) -> tuple[float | None, float | None]:
    """Most recent CONFIRMED swing high / low (k bars on each side, so the newest k bars cannot be swings)."""
    sh = sl = None
    for i in range(len(h) - k - 1, k - 1, -1):
        if sh is None and h[i] == max(h[i - k:i + k + 1]) and h[i] > max(h[i - k:i]) :
            sh = float(h[i])
        if sl is None and l[i] == min(l[i - k:i + k + 1]) and l[i] < min(l[i - k:i]):
            sl = float(l[i])
        if sh is not None and sl is not None:
            break
    return sh, sl


def value_area(h: np.ndarray, l: np.ndarray, c: np.ndarray, v: np.ndarray) -> dict[str, float] | None:
    """Volume profile of the bars given (typical price bins): POC, VAH, VAL."""
    if len(c) < 20 or v.sum() <= 0:
        return None
    lo, hi = float(np.min(l)), float(np.max(h))
    if hi <= lo:
        return None
    tp = (h + l + c) / 3
    b = np.clip(((tp - lo) / (hi - lo) * VP_BINS).astype(int), 0, VP_BINS - 1)
    vol = np.bincount(b, weights=v, minlength=VP_BINS)
    centers = lo + (np.arange(VP_BINS) + 0.5) * (hi - lo) / VP_BINS
    p = int(np.argmax(vol))
    a_, z, tot = p, p, vol[p]
    while tot < VP_AREA * vol.sum() and (a_ > 0 or z < VP_BINS - 1):
        up = vol[z + 1] if z < VP_BINS - 1 else -1
        dn = vol[a_ - 1] if a_ > 0 else -1
        if up >= dn:
            z += 1
            tot += vol[z]
        else:
            a_ -= 1
            tot += vol[a_]
    return {"poc": float(centers[p]), "vah": float(centers[z]), "val": float(centers[a_])}


def _sum(rows: list[tuple[int, float]], since: int, until: int | None = None) -> float:
    return float(sum(v for t, v in rows if t >= since and (until is None or t < until)))


def score_coin(c4: dict[str, np.ndarray], c1d: dict[str, np.ndarray] | None, okx: dict[str, list] | None,
               liq: dict[str, list] | None, funding: np.ndarray | None, now: int) -> dict[str, Any]:
    """Pure scoring of one coin. c4 / c1d: arrays o h l c v (closed candles). Returns state, trend, points, reasons."""
    h, l, c, v = c4["h"], c4["l"], c4["c"], c4["v"]
    # the ESTABLISHED trend: judged without the newest TREND_LAG bars, so a breakout candle cannot hide the trend it breaks
    L = TREND_LAG
    t4 = trend_of(c[:-L], h[:-L], l[:-L])
    t1 = trend_of(c1d["c"][:-L], c1d["h"][:-L], c1d["l"][:-L]) if c1d is not None and len(c1d["c"]) >= 60 + L else t4
    trend = t4 if t4 == t1 or t1 == 0 else 0
    out: dict[str, Any] = {"trend": {1: "up", -1: "down", 0: "range"}[trend], "trend_4h": t4, "trend_1d": t1,
                           "points": 0, "reasons": [], "price": float(c[-1]) if len(c) else None}
    if trend == 0 or len(c) < 60 + L:
        out["state"] = "range"
        return out
    turn = -trend                      # the direction a turn would go
    pts, why = 0, []
    a = atr(h, l, c)
    sh, sl = last_swings(h[:-1], l[:-1])
    lvl = sh if turn > 0 else sl
    if lvl is not None and turn * (c[-1] - lvl) > 0:
        p = 30 if a and turn * (c[-1] - lvl) >= 0.25 * a else 20
        pts += p
        why.append({"code": "structure_4h", "points": p, "text": f"4h closed {'above the last swing high' if turn > 0 else 'below the last swing low'} {lvl:.6g}"})
    if c1d is not None and len(c1d["c"]) >= 10:
        sh1, sl1 = last_swings(c1d["h"][:-1], c1d["l"][:-1])
        l1 = sh1 if turn > 0 else sl1
        if l1 is not None and turn * (c1d["c"][-1] - l1) > 0:
            pts += 20
            why.append({"code": "structure_1d", "points": 20, "text": f"1d closed {'above' if turn > 0 else 'below'} its last swing {l1:.6g}"})
    if len(c) >= VP_BARS:
        va = value_area(h[-VP_BARS:], l[-VP_BARS:], c[-VP_BARS:], v[-VP_BARS:])
        if va:
            edge = va["vah"] if turn > 0 else va["val"]
            if turn * (c[-1] - edge) > 0:
                pts += 15
                why.append({"code": "value_area", "points": 15, "text": f"4h closed {'above the value-area high' if turn > 0 else 'below the value-area low'} {edge:.6g} (POC {va['poc']:.6g})"})
    if okx:
        buy, sell = okx.get("taker_buy") or [], okx.get("taker_sell") or []
        b24, s24 = _sum(buy, now - DAY), _sum(sell, now - DAY)
        if b24 > 0 and s24 > 0:
            ratio = b24 / s24
            if (turn > 0 and ratio >= 1.08) or (turn < 0 and ratio <= 1 / 1.08):
                p = 15 if abs(np.log(ratio)) >= np.log(1.15) else 10
                pts += p
                why.append({"code": "taker_flow", "points": p, "text": f"24h taker buy/sell {ratio:.2f} (OKX) against the {out['trend']}trend"})
        oi = okx.get("oi_usd") or []
        if len(oi) >= 25:
            o_now, o_then = oi[-1][1], next((x for t, x in reversed(oi) if t <= oi[-1][0] - DAY), None)
            if o_then and len(c) >= 7:
                d_oi = o_now / o_then - 1
                d_px = c[-1] / c[-7] - 1             # ~24 h on 4h candles
                if turn * d_px > 0 and d_oi > 0.03:
                    pts += 10
                    why.append({"code": "open_interest", "points": 10, "text": f"price {d_px * 100:+.1f}% with open interest {d_oi * 100:+.1f}% in 24 h (new positions behind the move)"})
    if liq:
        side = "short" if turn > 0 else "long"     # a turn up squeezes shorts
        rows = liq.get(side) or []
        last24 = _sum(rows, now - DAY)
        prior = _sum(rows, now - 8 * DAY, now - DAY) / 7.0
        if last24 > 0 and prior > 0 and last24 >= 3 * prior:
            pts += 10
            why.append({"code": "liquidations", "points": 10, "text": f"{side} liquidations ${last24:,.0f} in 24 h = {last24 / prior:.1f}x the daily average"})
    if funding is not None and len(funding) >= 48:
        f = funding[-720:]
        sd = float(np.std(f))
        if sd > 0:
            z = (float(np.mean(f[-8:])) - float(np.mean(f))) / sd
            if (trend > 0 and z >= 2) or (trend < 0 and z <= -2):
                pts += 10
                why.append({"code": "funding", "points": 10, "text": f"funding z {z:+.1f}: the {out['trend']}trend side is crowded"})
    out["points"] = int(min(100, pts))
    out["reasons"] = why
    out["state"] = (f"turning {'up' if turn > 0 else 'down'}" if pts >= TURN else "weakening" if pts >= WEAK else "trend intact")
    return out


def market_state(coins: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """BTC half, breadth half. Breadth = share of trending coins whose state is turning / weakening against their trend."""
    btc = coins.get("BTC/USDT") or {}
    trending = [x for x in coins.values() if x.get("trend") in ("up", "down")]
    turning = [x for x in trending if str(x.get("state", "")).startswith("turning")]
    weak = [x for x in trending if x.get("state") == "weakening"]
    breadth = (len(turning) + 0.5 * len(weak)) / len(trending) if trending else 0.0
    score = int(round(0.5 * (btc.get("points") or 0) + 0.5 * 100 * breadth))
    trend = btc.get("trend") or "range"
    if trend == "range":
        downs = sum(1 for x in trending if x["trend"] == "down")
        trend = "down" if downs > len(trending) / 2 else "up" if trending and downs < len(trending) / 2 else "range"
    turn = "up" if trend == "down" else "down" if trend == "up" else None
    state = ("range" if turn is None else f"turning {turn}" if score >= TURN else "weakening" if score >= WEAK else "trend intact")
    return {"state": state, "trend": trend, "score": score, "btc_points": btc.get("points"), "btc_state": btc.get("state"),
            "breadth": {"trending": len(trending), "turning": len(turning), "weakening": len(weak)},
            "reasons": (btc.get("reasons") or [])[:4]}


def _arrays(df) -> dict[str, np.ndarray] | None:
    if df is None or len(df) == 0:
        return None
    return {k: df[col].to_numpy(float) for k, col in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume"))}


def run(rt, symbols: list[str], now: int | None = None) -> dict[str, Any]:
    """Score every watchlist coin (closed candles; missing data = fewer points, never an error)."""
    from ..data import derivs
    now = now or now_ms()
    coins: dict[str, dict[str, Any]] = {}
    for s in symbols[:MAX_COINS]:
        try:
            c4 = _arrays(rt.candles(s, "4h"))
            if c4 is None or len(c4["c"]) < 60:
                continue
            c1 = _arrays(rt.candles(s, "1d"))
            coin = MD.coin_of(s)
            okx = {k: MD.series(rt.db, coin, k, now - 3 * DAY) for k in ("taker_buy", "taker_sell", "oi_usd")}
            liq = MD.liquidations(rt.db, coin, now - 8 * DAY)
            try:
                fdf = derivs.load(rt.db, s)
                fund = fdf["funding"].dropna().to_numpy(float) if len(fdf) else None
            except Exception:
                fund = None
            coins[s] = score_coin(c4, c1, okx, liq, fund, now)
        except Exception as exc:
            log.info("turn detector %s: %s", s, exc)
    stables = MD.stablecoins(rt.db, 30)
    stable = None
    if len(stables) >= 8:
        stable = {"usd": stables[-1][1], "chg_7d_pct": (stables[-1][1] / stables[-8][1] - 1) * 100, "day": stables[-1][0]}
    return {"generated_at": now, "market": market_state(coins), "stablecoins": stable, "data": MD.status(rt.db),
            "coins": [{"symbol": s, **{k: v for k, v in x.items() if k not in ("trend_4h", "trend_1d")}}
                      for s, x in sorted(coins.items(), key=lambda kv: -kv[1].get("points", 0))],
            "note": "Recommend-only context for the admin. It never changes a call; it is not proven to predict turns yet."}


def view_core(v: dict[str, Any]) -> list[Any]:
    """What goes out at once: the market state and each coin's state (scores move every hour; states rarely)."""
    return [v["market"]["state"], [(c["symbol"], c.get("state")) for c in v.get("coins", [])]]


def publish(rt, sink, symbols: list[str], now: int | None = None) -> dict[str, Any]:
    if getattr(sink, "lean", False):
        return {"skipped": "lean"}
    v = run(rt, symbols, now)
    sink.view("market_turn", v, volatile=("generated_at",), min_interval_s=PUBLISH_EVERY_S, core=view_core(v))
    return {"market": v["market"]["state"], "coins": len(v["coins"])}
