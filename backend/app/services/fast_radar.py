"""V3.3 Fast Opportunity Radar (Stage 2 phase C; Fable 5.2 audit section I, Stage A "display only").

A ranking of fast-moving altcoins and memecoins on 1h data, with every reason and every warning spelled out.
DISPLAY ONLY: nothing here is a signal. It is never read by the record, the bots, Hesper / Last Stand, auto-trade,
alerts or Telegram (a test checks), and it opens no position. Published inside `views/radar` as `fast`, hourly with the
existing radar step (no new document, no new rule).

Watchlist (configurable): setting `fast_radar_coins` (list of "BASE"), else env FAST_RADAR_COINS, else DEFAULT_COINS.
Binance spot only (one public data path, ~20 requests an hour); coins without a Binance spot pair are listed as
`not_covered` (e.g. MEXC-only perpetuals), never guessed.

Per coin, from CLOSED 1h candles only (no look-ahead) and the 24 h ticker / best bid-ask:
  volume expansion   last 24 h quote volume vs the average day of the 6 before
  volatility exp.    ATR(24) vs ATR(168) of the 1h candles
  relative strength  24 h and 7 d return minus BTC's
  trend              close vs EMA20 / EMA50 (1h) and the EMA20 slope
  momentum           24 h return, RSI(14)
  liquidity          24 h quote volume (>= MIN_QUOTE_VOL) and spread (bps)
  regime             market risk state: HIGH / SEVERE = "incompatible" (fast coins fall hardest in a risk-off market)
Warnings: parabolic, thin liquidity, wide spread, wick-heavy (stop hunting / manipulation risk), one-candle pump,
volume without price (possible wash trading or absorption), short history. Score = transparent weighted points
(each part listed in `points`), warnings subtract. Costs: memecoins cost more than the flat 0.15 % the record uses;
the spread shown is part of that."""
from __future__ import annotations

import json
import os
import time
from typing import Any

import numpy as np

H = 3_600_000
DEFAULT_COINS = ("DOGE", "SHIB", "PEPE", "BONK", "FLOKI", "WIF", "PENGU", "TRUMP", "SOL", "SUI", "AVAX", "NEAR", "APT",
                 "SEI", "INJ", "FET", "TIA", "HYPE", "PUMP", "SPX", "FARTCOIN")
MIN_QUOTE_VOL = 15e6
MAX_SPREAD_BPS = 20.0
BARS = 200
WEIGHTS = {"rs_7d": 0.30, "rs_24h": 0.20, "trend": 0.20, "momentum": 0.15, "volume": 0.15}


def coins(db: Any = None) -> list[str]:
    v = db.get_setting("fast_radar_coins", None) if db is not None else None
    if isinstance(v, list) and v:
        return [str(x).upper() for x in v][:40]
    env = os.environ.get("FAST_RADAR_COINS", "").strip()
    return [c.strip().upper() for c in env.split(",") if c.strip()][:40] if env else list(DEFAULT_COINS)


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    a, out = 2 / (n + 1), np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def _rsi(c: np.ndarray, n: int = 14) -> float:
    d = np.diff(c[-(n * 3):])
    up, dn = np.clip(d, 0, None)[-n:].mean(), np.clip(-d, 0, None)[-n:].mean()
    return 100.0 if dn == 0 else float(100 - 100 / (1 + up / dn))


def _atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int) -> float:
    prev = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))
    return float(tr[-n:].mean())


def closed_rows(rows: list[list[Any]], now: int) -> np.ndarray:
    """Binance klines -> [open_ts, o, h, l, c, quote_volume] of candles that have CLOSED by `now`."""
    out = [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[7])] for r in rows
           if int(r[0]) + H <= now]
    return np.array(out, float) if out else np.zeros((0, 6))


def features(k: np.ndarray, btc: np.ndarray) -> dict[str, Any] | None:
    """k, btc: closed 1h rows aligned on time. None when the history is too short to say anything."""
    if len(k) < 50 or len(btc) < 50:
        return None
    o, h, l, c, qv = (k[:, i] for i in (1, 2, 3, 4, 5))
    n = len(c)
    bt = dict(zip(btc[:, 0].astype(np.int64).tolist(), btc[:, 4].tolist()))
    def btc_ret(bars: int) -> float | None:
        a, b = bt.get(int(k[-1, 0])), bt.get(int(k[-1 - bars, 0])) if n > bars else None
        return (a / b - 1) * 100 if a and b else None
    ret24 = (c[-1] / c[-25] - 1) * 100 if n > 24 else None
    ret7 = (c[-1] / c[-169] - 1) * 100 if n > 168 else None
    b24, b7 = btc_ret(24), btc_ret(168)
    day = qv[-24:].sum()
    prior = [qv[-24 * (i + 1):-24 * i].sum() for i in range(1, 7) if n >= 24 * (i + 1)]
    vol_exp = day / np.mean(prior) if prior and np.mean(prior) > 0 else None
    atr24, atr168 = _atr(h, l, c, 24), (_atr(h, l, c, 168) if n > 168 else None)
    e20, e50 = _ema(c, 20), _ema(c, 50)
    rng_ = np.maximum(h[-24:] - l[-24:], 1e-12)
    wick = float(np.mean(((h[-24:] - np.maximum(o[-24:], c[-24:])) + (np.minimum(o[-24:], c[-24:]) - l[-24:])) / rng_))
    moves = np.abs(c[-24:] / o[-24:] - 1) * 100
    return {
        "price": float(c[-1]), "ret_24h_pct": _r(ret24), "ret_7d_pct": _r(ret7),
        "rs_24h_pct": _r(ret24 - b24) if ret24 is not None and b24 is not None else None,
        "rs_7d_pct": _r(ret7 - b7) if ret7 is not None and b7 is not None else None,
        "volume_expansion": _r(vol_exp), "volatility_expansion": _r(atr24 / atr168) if atr168 else None,
        "above_ema20": bool(c[-1] > e20[-1]), "above_ema50": bool(c[-1] > e50[-1]),
        "ema20_slope_6h_pct": _r((e20[-1] / e20[-7] - 1) * 100), "rsi14": _r(_rsi(c)), "wick_share_24h": _r(wick),
        "largest_1h_move_pct": _r(float(moves.max())), "bars": n, "closed_at": int(k[-1, 0]) + H}


def _r(x: Any, d: int = 3) -> float | None:
    return round(float(x), d) if x is not None and np.isfinite(x) else None


def judge(f: dict[str, Any], quote_vol: float | None, spread_bps: float | None, regime: str | None) -> dict[str, Any]:
    """Points, reasons and warnings for one coin (pure)."""
    pts: dict[str, float] = {}
    reasons, warnings = [], []
    clip = lambda x, lo, hi: float(min(hi, max(lo, x)))  # noqa: E731
    if f.get("rs_7d_pct") is not None:
        pts["rs_7d"] = clip(f["rs_7d_pct"] / 20, -1, 1)
        if f["rs_7d_pct"] >= 5:
            reasons.append(f"{f['rs_7d_pct']:+.1f}% vs BTC over 7 days")
    if f.get("rs_24h_pct") is not None:
        pts["rs_24h"] = clip(f["rs_24h_pct"] / 8, -1, 1)
        if f["rs_24h_pct"] >= 2:
            reasons.append(f"{f['rs_24h_pct']:+.1f}% vs BTC in 24 h")
    tr = (0.4 if f["above_ema20"] else -0.4) + (0.3 if f["above_ema50"] else -0.3) + clip((f["ema20_slope_6h_pct"] or 0) / 2, -0.3, 0.3)
    pts["trend"] = tr
    if f["above_ema20"] and f["above_ema50"] and (f["ema20_slope_6h_pct"] or 0) > 0:
        reasons.append("1h uptrend: above EMA20 and EMA50, EMA20 rising")
    rsi = f.get("rsi14") or 50
    pts["momentum"] = clip(((f.get("ret_24h_pct") or 0) / 10) * 0.6 + ((rsi - 50) / 30) * 0.4, -1, 1)
    ve = f.get("volume_expansion")
    if ve is not None:
        pts["volume"] = clip((ve - 1) / 2, -0.5, 1)
        if ve >= 1.8:
            reasons.append(f"volume {ve:.1f}x its recent daily average")
    vx = f.get("volatility_expansion")
    if vx is not None and vx >= 1.5:
        reasons.append(f"volatility expanding ({vx:.1f}x its 7-day range)")
    # warnings
    if (f.get("ret_24h_pct") or 0) >= 25 or rsi >= 80:
        warnings.append("parabolic: chasing this move is the classic way to buy the top")
    if quote_vol is None or quote_vol < MIN_QUOTE_VOL:
        warnings.append("thin liquidity: under $15M traded in 24 h")
    if spread_bps is None:
        warnings.append("spread unknown")
    elif spread_bps > MAX_SPREAD_BPS:
        warnings.append(f"wide spread: {spread_bps:.0f} bps just to get in and out")
    if (f.get("wick_share_24h") or 0) >= 0.6:
        warnings.append("wick-heavy candles: stop hunting / manipulation risk")
    if (f.get("largest_1h_move_pct") or 0) >= 8 and abs(f.get("ret_24h_pct") or 0) > 0 and \
            f["largest_1h_move_pct"] >= 0.5 * abs(f["ret_24h_pct"]):
        warnings.append("one-candle pump: most of the day's move came in a single hour")
    if ve is not None and ve >= 3 and abs(f.get("ret_24h_pct") or 0) < 2:
        warnings.append("volume without price: possible wash trading or absorption")
    if f["bars"] < 169:
        warnings.append("short history: under 7 days of 1h candles")
    compat = "incompatible" if regime in ("HIGH", "SEVERE") else "unknown" if regime in (None, "UNKNOWN") else "compatible"
    if compat == "incompatible":
        warnings.append(f"market risk is {regime}: fast coins tend to fall hardest in risk-off markets")
    score = sum(WEIGHTS[k] * v for k, v in pts.items()) - 0.15 * len(warnings)
    return {"score": round(score, 4), "points": {k: round(v, 3) for k, v in pts.items()}, "reasons": reasons,
            "warnings": warnings, "regime_compatibility": compat}


def rank(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ok = sorted((x for x in items if x.get("score") is not None), key=lambda x: -x["score"])
    for i, x in enumerate(ok, 1):
        x["rank"] = i
    return ok


def scan(db: Any, provider: Any, now: int | None = None) -> dict[str, Any]:
    """Hourly scan (provider = BinancePublicProvider: `_get_sync`). Never raises for one coin; a total failure returns
    {'available': False, 'reason'}."""
    now = int(time.time() * 1000) if now is None else int(now)
    wanted = coins(db)
    regime = None
    try:
        from . import risk_state
        regime = (risk_state.current(db) or {}).get("state")
    except Exception:
        pass
    try:
        btc = closed_rows(provider._get_sync("/api/v3/klines", {"symbol": "BTCUSDT", "interval": "1h", "limit": BARS}), now)
        syms = [f"{c}USDT" for c in wanted]
        tick = provider._get_sync("/api/v3/ticker/24hr", {"symbols": json.dumps(syms, separators=(",", ":"))}) \
            if syms else []
    except Exception as exc:
        # one unknown symbol fails the batch: retry one by one
        try:
            tick = []
            for s in [f"{c}USDT" for c in wanted]:
                try:
                    tick.append(provider._get_sync("/api/v3/ticker/24hr", {"symbol": s}))
                except Exception:
                    continue
            btc = closed_rows(provider._get_sync("/api/v3/klines", {"symbol": "BTCUSDT", "interval": "1h", "limit": BARS}), now)
        except Exception as exc2:
            return {"available": False, "reason": f"{type(exc2).__name__}: {exc2}"[:160], "generated_at": now,
                    "display_only": True}
    tmap = {t.get("symbol"): t for t in tick if isinstance(t, dict)}
    try:
        books = provider._get_sync("/api/v3/ticker/bookTicker", {"symbols": json.dumps(list(tmap), separators=(",", ":"))}) \
            if tmap else []
    except Exception:
        books = []
    bmap = {b.get("symbol"): b for b in books if isinstance(b, dict)}
    items, not_covered = [], []
    for c in wanted:
        s = f"{c}USDT"
        if s not in tmap:
            not_covered.append(c)
            continue
        t, b = tmap[s], bmap.get(s) or {}
        try:
            k = closed_rows(provider._get_sync("/api/v3/klines", {"symbol": s, "interval": "1h", "limit": BARS}), now)
        except Exception:
            items.append({"coin": c, "symbol": f"{c}/USDT", "score": None, "status": "unavailable", "reason": "candles unavailable"})
            continue
        f = features(k, btc)
        qv = float(t.get("quoteVolume") or 0)
        bid, ask = float(b.get("bidPrice") or 0), float(b.get("askPrice") or 0)
        spread = (ask - bid) / ((ask + bid) / 2) * 1e4 if bid > 0 and ask > 0 else None
        if f is None:
            items.append({"coin": c, "symbol": f"{c}/USDT", "score": None, "status": "unavailable",
                          "reason": "fewer than 50 closed 1h candles", "quote_volume_24h": qv})
            continue
        j = judge(f, qv, spread, regime)
        items.append({"coin": c, "symbol": f"{c}/USDT", "status": "ok", **f, **j, "quote_volume_24h": round(qv, 0),
                      "spread_bps": _r(spread, 2)})
    ranked = rank(items)
    return {"available": True, "generated_at": now, "display_only": True, "regime": regime,
            "note": "Display only: a ranked list of fast movers with reasons and warnings. Not a signal, never traded.",
            "coins": ranked + [x for x in items if x.get("score") is None], "not_covered": not_covered,
            "config": {"watchlist": wanted, "min_quote_volume": MIN_QUOTE_VOL, "max_spread_bps": MAX_SPREAD_BPS,
                       "weights": WEIGHTS, "timeframe": "1h", "source": "Binance spot"}}
