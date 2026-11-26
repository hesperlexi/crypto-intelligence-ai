"""V3.4 Stage 3B: transparent opportunity score (context only, never a win probability).

Twelve components, each scored 0-100 from one reading of the coin's own analysis or recorded context, with its reason:

  trend          4h-style engine regime of the coin agrees with the side, ADX, price vs EMA50 / EMA200
  momentum       RSI zone for the side (overextended counts against), MACD histogram sign
  relative       7-day return vs BTC in the side's direction (services/market_intel)
  volume         relative volume, buy pressure in the side's direction
  liquidity      24 h quote volume tier and spread
  volatility     volatility state: normal good, extreme / compressed weaker
  regime         market regime (services/market_regime) agrees with the side
  entry          live price vs the plan's entry zone, in ATR
  reward         blended reward : risk of the plan
  stop           stop distance in ATR (too tight is noise, too wide wastes risk)
  costs          round-trip cost as a share of 1R
  correlation    open same-side record risk in BTC-correlated coins (services/portfolio_risk)

Overall = plain mean of the components that could be measured (equal weights on purpose: no weight was proven better;
`research` below checks each component on its own against what calls really did). `coverage` = measured / 12.
AUTHORITY: none. It never blocks, approves, grades or sizes a trade. Stored as `opportunity` on the analysis and in each
call's private `risk_shadow.opportunity`, so `evaluate()` can test every component on unseen outcomes.
"""
from __future__ import annotations

import math
from typing import Any

COMPONENTS = ("trend", "momentum", "relative", "volume", "liquidity", "volatility", "regime", "entry", "reward", "stop",
              "costs", "correlation")
LABEL = "Opportunity score (0-100): a checklist of the setup's quality, not a chance of winning"
BULL_REGIMES = ("strong_bull", "weak_bull", "breakout")
BEAR_REGIMES = ("strong_bear", "weak_bear", "breakdown")


def _c(score: float | None, reading: str, status: str = "measured") -> dict[str, Any]:
    s = None if score is None else int(round(max(0.0, min(100.0, score))))
    return {"score": s, "reading": reading, "status": status if s is not None else "unavailable"}


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def side_of(a: dict[str, Any]) -> int:
    d = str(a.get("decision") or "")
    if d in ("BUY", "BUY ON PULLBACK"):
        return 1
    if d == "SELL":
        return -1
    st = a.get("setup") or {}
    if st.get("side_int") in (1, -1):
        return int(st["side_int"])
    w = a.get("watch") or {}
    wd = str(w.get("decision") or "")
    return 1 if wd.startswith("BUY") else -1 if wd == "SELL" else 0


def components(a: dict[str, Any], side: int, ctx: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    ctx = ctx or {}
    ind = a.get("indicators") or {}
    out: dict[str, dict[str, Any]] = {}
    # trend
    reg = a.get("regime") or {}
    grp = reg.get("group")
    adx = _num(reg.get("adx") if reg.get("adx") is not None else ind.get("adx"))
    px, e50, e200 = _num(a.get("last_close") or a.get("price")), _num(ind.get("ema_50")), _num(ind.get("ema_200"))
    if grp is None and adx is None:
        out["trend"] = _c(None, "no regime")
    else:
        s = 50.0
        if grp in ("Bull", "Bear"):
            s += 25 if (grp == "Bull") == (side > 0) else -30
        elif grp == "Unstable":
            s -= 15
        if adx is not None:
            s += 10 if adx >= 25 else -5 if adx < 18 else 0
        if px and e50 and e200:
            s += 15 if side * (px - e50) > 0 and side * (e50 - e200) > 0 else -10 if side * (px - e200) < 0 else 0
        out["trend"] = _c(s, f"{reg.get('regime') or grp}" + (f", ADX {adx:.0f}" if adx is not None else ""))
    # momentum
    rsi, mh = _num(ind.get("rsi")), _num(ind.get("macd_hist"))
    if rsi is None:
        out["momentum"] = _c(None, "no RSI")
    else:
        r = rsi if side > 0 else 100 - rsi
        s = 80 if 52 <= r <= 68 else 60 if 45 <= r < 52 or 68 < r <= 74 else 30 if r > 74 else 25
        if mh is not None:
            s += 10 if side * mh > 0 else -10
        out["momentum"] = _c(s, f"RSI {rsi:.0f}" + (" (overextended)" if r > 74 else ""))
    # relative strength
    rs = (ctx.get("intel") or {}).get("relative_strength") or {}
    rv = _num(rs.get("rs_7d_pct") if rs.get("status") in ("confirmed", "delayed") else None)
    out["relative"] = (_c(None, "not measurable") if rv is None else
                       _c(50 + max(-40, min(40, side * rv * 4)), f"{rv:+.1f}% vs BTC over 7 d",
                          "measured" if rs.get("status") == "confirmed" else "delayed"))
    # volume
    lq = a.get("liquidity") or {}
    rvol, bp = _num(lq.get("relative_volume")), _num(lq.get("buy_pressure"))
    if rvol is None:
        out["volume"] = _c(None, "no volume data")
    else:
        s = 75 if rvol >= 1.3 else 55 if rvol >= 0.9 else 35
        if bp is not None:
            s += 10 if side * (bp - 0.5) > 0.05 else -10 if side * (bp - 0.5) < -0.05 else 0
        out["volume"] = _c(s, f"{rvol:.2f}x relative volume")
    # liquidity
    qv = _num(a.get("quote_volume_24h"))
    book = lq.get("order_book") or {}
    spread = _num(book.get("spread_bps"))
    if qv is None and spread is None:
        out["liquidity"] = _c(None, "no ticker")
    else:
        s = 85 if (qv or 0) >= 100e6 else 65 if (qv or 0) >= 15e6 else 25
        if spread is not None:
            s -= 30 if spread > 20 else 10 if spread > 8 else 0
        out["liquidity"] = _c(s, (f"${qv / 1e6:,.0f}M 24 h" if qv else "volume unknown")
                              + (f", spread {spread:.1f} bps" if spread is not None else ""))
    # volatility suitability
    vs = str((a.get("volatility") or {}).get("state") or "")
    out["volatility"] = (_c(None, "no volatility state") if not vs else
                         _c({"normal": 80, "elevated": 60, "high": 45, "low": 55, "compressed": 50, "extreme": 15}
                            .get(vs.lower(), 50), vs))
    # market regime compatibility
    mr = ctx.get("regime") or {}
    prim = mr.get("primary") or mr.get("regime")
    if not prim or prim == "uncertain":
        out["regime"] = _c(None if not prim else 40, "market regime uncertain" if prim else "no market regime",
                           "measured" if prim else "unavailable")
    else:
        agree = (prim in BULL_REGIMES and side > 0) or (prim in BEAR_REGIMES and side < 0)
        against = (prim in BULL_REGIMES and side < 0) or (prim in BEAR_REGIMES and side > 0)
        s = (85 if agree else 20 if against else 50) - (15 if prim == "unstable" else 0)
        out["regime"] = _c(s, f"market {prim.replace('_', ' ')}")
    # plan-based components
    st = a.get("setup") or {}
    entry, stop, atr = _num(st.get("ideal_entry")), _num(st.get("stop")), _num(st.get("atr") or ind.get("atr"))
    zone = st.get("entry_zone") or []
    live = _num(a.get("price"))
    if not entry or not stop:
        for k in ("entry", "reward", "stop", "costs"):
            out[k] = _c(None, "no trade plan")
    else:
        if live and atr and len(zone) == 2:
            lo, hi = float(zone[0]), float(zone[1])
            dist = 0.0 if lo <= live <= hi else min(abs(live - lo), abs(live - hi)) / atr
            chased = side * (live - entry) > 0 and not (lo <= live <= hi)
            s = 90 if dist == 0 else max(10, 80 - dist * 40) - (15 if chased else 0)
            out["entry"] = _c(s, "inside entry zone" if dist == 0 else f"{dist:.1f} ATR {'past' if chased else 'before'} the zone")
        else:
            out["entry"] = _c(None, "no live price")
        rr = _num(st.get("risk_reward"))
        out["reward"] = (_c(None, "no reward : risk") if rr is None else
                         _c(90 if rr >= 2.2 else 70 if rr >= 1.6 else 50 if rr >= 1.25 else 20, f"1 : {rr:.2f}"))
        risk_pct = abs(entry - stop) / entry * 100
        if atr:
            k = abs(entry - stop) / atr
            out["stop"] = _c(80 if 1.0 <= k <= 2.5 else 55 if 0.7 <= k <= 3.5 else 25,
                             f"{k:.1f} ATR ({risk_pct:.2f}%)")
        else:
            out["stop"] = _c(None, f"{risk_pct:.2f}% (no ATR)")
        try:
            from .analysis import round_trip_cost
            cost = round_trip_cost(True) * 100
            share = cost / risk_pct if risk_pct > 0 else 1.0
            out["costs"] = _c(90 if share <= 0.1 else 70 if share <= 0.2 else 45 if share <= 1 / 3 else 15,
                              f"costs {share:.0%} of 1R")
        except Exception:
            out["costs"] = _c(None, "cost model unavailable")
    # correlation with open positions
    corr = ctx.get("correlation")
    if not corr:
        out["correlation"] = _c(None, "portfolio not readable")
    else:
        same = float(corr.get("same_side_corr_r") or 0)
        lim = float(corr.get("limit_r") or 5)
        out["correlation"] = _c(90 - 70 * min(1.0, same / lim), f"{same:.1f}R open on the same side in BTC-linked coins")
    return out


def score(a: dict[str, Any], ctx: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The whole opportunity card for one analysis (None when there is no side to judge)."""
    if not isinstance(a, dict) or a.get("status") not in (None, "OK"):
        return None
    side = side_of(a)
    if side == 0:
        return None
    comps = components(a, side, ctx)
    vals = [c["score"] for c in comps.values() if c["score"] is not None]
    if not vals:
        return None
    overall = int(round(sum(vals) / len(vals)))
    ranked = sorted(((k, c) for k, c in comps.items() if c["score"] is not None), key=lambda kv: -kv[1]["score"])
    positive = [f"{k}: {c['reading']}" for k, c in ranked if c["score"] >= 70][:5]
    negative = [f"{k}: {c['reading']}" for k, c in reversed(ranked) if c["score"] <= 35][:5]
    trade = str(a.get("decision") or "") in ("BUY", "BUY ON PULLBACK", "SELL")
    rejection = [] if trade else [f for f in (a.get("flags") or []) if f != "NO TRADE"][:6]
    pq = a.get("price_quality") or {}
    warnings = [f"{k}: {c['reading']}" for k, c in comps.items() if k in ("liquidity", "volatility", "regime", "costs")
                and c["score"] is not None and c["score"] <= 25]
    if pq.get("quality") not in (None, "live"):
        warnings.append(f"price {pq.get('quality')}")
    return {"score": overall, "label": LABEL, "side": "LONG" if side > 0 else "SHORT", "is_trade_call": trade,
            "coverage": round(len(vals) / len(COMPONENTS), 2), "components": comps, "positive": positive,
            "negative": negative, "rejection": rejection,
            "rejection_reason": None if trade else a.get("decision_reason"),
            "freshness": {"bar_close_ts": a.get("bar_close_ts"), "price": pq.get("quality"), "price_age_s": pq.get("age_s"),
                          "stale": bool(a.get("stale"))},
            "warnings": warnings, "weights": "equal (no weighting proven better)"}


def context(rt: Any, symbol: str, side: int, risk_check: dict[str, Any] | None = None) -> dict[str, Any]:
    """Context for `components` from what the engine already has (never raises)."""
    rc = risk_check or {}
    ctx: dict[str, Any] = {"intel": rc.get("intel"), "regime": rc.get("regime")}
    try:
        from . import portfolio_risk as PR
        corr = PR.btc_corr(rt, symbol)
        same = 0.0
        for p in PR.record_positions(rt.db):
            if p["symbol"] == symbol or p["side"] != side:
                continue
            c = PR.btc_corr(rt, p["symbol"])
            if c is None or c >= PR.LIMITS["corr_min"]:
                same += float(p["risk_r"])
        ctx["correlation"] = {"same_side_corr_r": round(same, 2), "limit_r": PR.LIMITS["max_corr_r"],
                              "coin_btc_corr": corr}
    except Exception:
        ctx["correlation"] = None
    return ctx


def compact(op: dict[str, Any] | None) -> dict[str, Any] | None:
    """What a call stores (risk_shadow.opportunity): overall + every component score."""
    if not op:
        return None
    return {"score": op["score"], "coverage": op["coverage"], "side": op["side"],
            "components": {k: c["score"] for k, c in op["components"].items()}}


# ---- independent validation of each component ---------------------------------------------------------------------------

def evaluate(rows: list[dict[str, Any]], min_n: int = 30) -> dict[str, Any]:
    """rows: {"opportunity": compact, "net_r": float}. For the overall score and EACH component on its own: average net R
    of the top third vs the bottom third, with 95 % intervals. `enough` False below `min_n` per third."""
    import numpy as np

    def ci(x):
        x = np.asarray(x, float)
        if len(x) < 2:
            return None
        h = 1.96 * x.std(ddof=1) / math.sqrt(len(x))
        return [round(float(x.mean() - h), 3), round(float(x.mean() + h), 3)]

    out: dict[str, Any] = {"n": len(rows), "basis": "net R of closed calls; terciles of each score"}
    for key in ("score", *COMPONENTS):
        pts = []
        for r in rows:
            op = r.get("opportunity") or {}
            v = op.get("score") if key == "score" else (op.get("components") or {}).get(key)
            if v is not None and r.get("net_r") is not None:
                pts.append((float(v), float(r["net_r"])))
        if len(pts) < 3:
            out[key] = {"n": len(pts), "enough": False}
            continue
        pts.sort()
        k = len(pts) // 3
        lo, hi = [p[1] for p in pts[:k]], [p[1] for p in pts[-k:]]
        out[key] = {"n": len(pts), "enough": k >= min_n,
                    "top_third_avg_r": round(float(np.mean(hi)), 3) if hi else None, "top_ci95": ci(hi),
                    "bottom_third_avg_r": round(float(np.mean(lo)), 3) if lo else None, "bottom_ci95": ci(lo),
                    "spread_r": round(float(np.mean(hi) - np.mean(lo)), 3) if hi and lo else None}
    return out
