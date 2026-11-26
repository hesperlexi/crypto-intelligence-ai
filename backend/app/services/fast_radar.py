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
# V3.4 Stage 3C: two separate, configurable watchlists (verified each scan: a coin with no usable market is listed in
# `not_covered`, never guessed). Setting `fast_radar_watchlists` {"meme": [...], "alt": [...]}, else env FAST_RADAR_MEME /
# FAST_RADAR_ALT, else these defaults. The older single list (`fast_radar_coins` / FAST_RADAR_COINS) still works.
MEME_DEFAULT = ("DOGE", "PEPE", "BONK", "SHIB", "WIF", "FLOKI", "PENGU", "PUMP", "SPX", "FARTCOIN")
ALT_DEFAULT = ("SOL", "HYPE", "SUI", "SEI", "JUP", "INJ", "TIA", "WLD")
DEFAULT_COINS = MEME_DEFAULT + ALT_DEFAULT
KNOWN_MEME = set(MEME_DEFAULT) | {"TRUMP", "BOME", "MEME", "NEIRO", "TURBO", "MOG", "POPCAT", "BRETT", "1000SATS"}
MIN_QUOTE_VOL = 15e6
MAX_SPREAD_BPS = 20.0
BARS = 200
WEIGHTS = {"rs_7d": 0.30, "rs_24h": 0.20, "trend": 0.20, "momentum": 0.15, "volume": 0.15}


def watchlists(db: Any = None) -> dict[str, list[str]]:
    """{"meme": [...], "alt": [...]} (upper case, each at most 30)."""
    v = db.get_setting("fast_radar_watchlists", None) if db is not None else None
    if isinstance(v, dict) and (v.get("meme") or v.get("alt")):
        return {k: [str(x).upper() for x in (v.get(k) or [])][:30] for k in ("meme", "alt")}
    em, ea = os.environ.get("FAST_RADAR_MEME", "").strip(), os.environ.get("FAST_RADAR_ALT", "").strip()
    if em or ea:
        sp = lambda t: [c.strip().upper() for c in t.split(",") if c.strip()][:30]  # noqa: E731
        return {"meme": sp(em), "alt": sp(ea)}
    legacy = db.get_setting("fast_radar_coins", None) if db is not None else None
    env = os.environ.get("FAST_RADAR_COINS", "").strip()
    if (isinstance(legacy, list) and legacy) or env:
        cs = coins(db)
        return {"meme": [c for c in cs if c in KNOWN_MEME], "alt": [c for c in cs if c not in KNOWN_MEME]}
    return {"meme": list(MEME_DEFAULT), "alt": list(ALT_DEFAULT)}


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
        "largest_1h_move_pct": _r(float(moves.max())), "bars": n, "closed_at": int(k[-1, 0]) + H,
        "atr_24": _r(atr24, 10)}


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


# ---- V3.4 Stage 3C: more detections ------------------------------------------------------------------------------------

MEXC_SPOT = "https://api.mexc.com"
TRACK_HOURS = (4, 24, 72)
FLAG_TOP = 5                      # per category: an opportunity "appears" when it ranks in the top 5 with a score > 0
REFLAG_GAP_H = 24                 # the same coin appearing again after 24 h off the list is a new opportunity


def extras(k: np.ndarray, btc: np.ndarray, f: dict[str, Any], spread_bps: float | None, prev_spread: float | None,
           market_regime: str | None) -> dict[str, Any]:
    """Momentum acceleration, relative-strength breakout, trend continuation, liquidity deterioration, sudden spread
    expansion, BTC regime incompatibility (pure, closed candles only)."""
    sig, warn = [], []
    c, l, qv = k[:, 4], k[:, 3], k[:, 5]
    n = len(c)
    if n > 12:
        r6, p6 = (c[-1] / c[-7] - 1) * 100, (c[-7] / c[-13] - 1) * 100
        if r6 > 1.0 and r6 > 2 * max(p6, 0.25):
            sig.append(f"momentum accelerating: {r6:+.1f}% in 6 h after {p6:+.1f}% the 6 h before")
    bt = dict(zip(btc[:, 0].astype(np.int64).tolist(), btc[:, 4].tolist()))
    ratio = np.array([c[i] / bt[int(k[i, 0])] if bt.get(int(k[i, 0])) else np.nan for i in range(n)])
    if n > 170 and np.isfinite(ratio[-1]):
        prior = ratio[-169:-24]
        prior = prior[np.isfinite(prior)]
        if len(prior) > 100 and ratio[-1] > prior.max():
            sig.append("relative-strength breakout: price vs BTC above its high of the previous 6 days")
    if n > 50:
        e50 = _ema(c, 50)
        if f.get("above_ema20") and f.get("above_ema50") and (f.get("ema20_slope_6h_pct") or 0) > 0 and \
                float(l[-24:].min()) > float(e50[-24:].min()):
            sig.append("trend continuation: 24 h pullbacks held above the 1h EMA50")
    ve = f.get("volume_expansion")
    if ve is not None and ve < 0.5:
        warn.append(f"liquidity deteriorating: 24 h volume {ve:.2f}x its recent daily average")
    if spread_bps is not None and prev_spread and spread_bps > max(8.0, 2 * prev_spread):
        warn.append(f"spread expanded suddenly: {spread_bps:.0f} bps vs {prev_spread:.0f} bps an hour ago")
    if market_regime in ("strong_bear", "weak_bear", "breakdown", "unstable"):
        warn.append(f"BTC regime incompatible: market {market_regime.replace('_', ' ')}")
    return {"signals": sig, "warnings": warn}


def _mexc_get(provider: Any, path: str, params: dict[str, Any]) -> Any:
    """MEXC spot (Binance-compatible paths) for coins Binance spot does not list. Only with a real HTTP session (tests
    and offline runs simply report the coin as not covered)."""
    fn = getattr(provider, "mexc_get", None)
    if fn:
        return fn(path, params)
    sess = getattr(provider, "session", None)
    if sess is None:
        raise RuntimeError("no MEXC access")
    r = sess.get(MEXC_SPOT + path, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _mexc_coin(provider: Any, coin: str, now: int) -> tuple[np.ndarray, dict, dict] | None:
    s = f"{coin}USDT"
    try:
        t = _mexc_get(provider, "/api/v3/ticker/24hr", {"symbol": s})
        b = _mexc_get(provider, "/api/v3/ticker/bookTicker", {"symbol": s})
        k = closed_rows(_mexc_get(provider, "/api/v3/klines", {"symbol": s, "interval": "60m", "limit": BARS}), now)
    except Exception:
        return None
    if not isinstance(t, dict) or not t.get("quoteVolume"):
        return None
    return k, t, b if isinstance(b, dict) else {}


# ---- opportunity tracking (SQLite, never deleted) ----------------------------------------------------------------------

def ensure(db: Any) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS radar_opportunities (
        id INTEGER PRIMARY KEY AUTOINCREMENT, coin TEXT NOT NULL, category TEXT, source TEXT, first_seen INTEGER NOT NULL,
        last_seen INTEGER NOT NULL, bar_ts INTEGER, price REAL, btc_price REAL, score REAL, rank INTEGER, reasons TEXT,
        warnings TEXT, regime TEXT, status TEXT DEFAULT 'tracking', ret_4h REAL, rs_4h REAL, ret_24h REAL, rs_24h REAL,
        ret_72h REAL, rs_72h REAL, max_up_72h REAL, max_down_72h REAL, worked INTEGER)""")
    db.execute("CREATE INDEX IF NOT EXISTS radar_opp_coin ON radar_opportunities (coin, last_seen)")


def track(db: Any, items: list[dict[str, Any]], series: dict[str, np.ndarray], btc: np.ndarray, now: int,
          regime: str | None = None) -> dict[str, Any]:
    """Record new appearances and fill in what happened 4 / 24 / 72 h later (closed 1h closes; vs BTC). `worked` =
    beat BTC over 24 h. A record of the radar's own quality: not a trade, before costs."""
    import json as _j
    ensure(db)
    added = 0
    bt = dict(zip(btc[:, 0].astype(np.int64).tolist(), btc[:, 4].tolist())) if len(btc) else {}
    for x in items:
        if not x.get("flagged"):
            continue
        last = db.one("SELECT id, last_seen FROM radar_opportunities WHERE coin = ? ORDER BY last_seen DESC LIMIT 1", (x["coin"],))
        bar = int(x["closed_at"]) - H
        if last and now - int(last["last_seen"]) <= REFLAG_GAP_H * H:
            db.execute("UPDATE radar_opportunities SET last_seen = ? WHERE id = ?", (now, last["id"]))
            continue
        db.execute("INSERT INTO radar_opportunities (coin, category, source, first_seen, last_seen, bar_ts, price, btc_price, "
                   "score, rank, reasons, warnings, regime) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (x["coin"], x.get("category"), x.get("source"), now, now, bar, x["price"], bt.get(bar), x["score"],
                    x.get("category_rank"), _j.dumps(x.get("reasons") or []), _j.dumps(x.get("warnings") or []), regime))
        added += 1
    filled = 0
    for r in db.query("SELECT * FROM radar_opportunities WHERE status = 'tracking'"):
        k = series.get(r["coin"])
        if k is None or not len(k) or not r["price"]:
            if now - int(r["first_seen"]) > 9 * 24 * H:
                db.execute("UPDATE radar_opportunities SET status = 'no_data' WHERE id = ?", (r["id"],))
            continue
        closes = dict(zip(k[:, 0].astype(np.int64).tolist(), k[:, 4].tolist()))
        upd: dict[str, Any] = {}
        for h in TRACK_HOURS:
            if r[f"ret_{h}h"] is not None:
                continue
            t = int(r["bar_ts"]) + h * H
            if t in closes:
                ret = (closes[t] / r["price"] - 1) * 100
                upd[f"ret_{h}h"] = round(ret, 3)
                if r["btc_price"] and bt.get(t):
                    upd[f"rs_{h}h"] = round(ret - (bt[t] / r["btc_price"] - 1) * 100, 3)
        if "rs_24h" in upd:
            upd["worked"] = int(upd["rs_24h"] > 0)
        if r["ret_72h"] is None and "ret_72h" in upd:
            win = k[(k[:, 0] > r["bar_ts"]) & (k[:, 0] <= r["bar_ts"] + 72 * H)]
            if len(win):
                upd["max_up_72h"] = round((float(win[:, 2].max()) / r["price"] - 1) * 100, 3)
                upd["max_down_72h"] = round((float(win[:, 3].min()) / r["price"] - 1) * 100, 3)
            upd["status"] = "done"
        elif now - int(r["first_seen"]) > 9 * 24 * H:
            upd["status"] = "no_data"
        if upd:
            db.execute(f"UPDATE radar_opportunities SET {', '.join(f'{c} = ?' for c in upd)} WHERE id = ?",
                       (*upd.values(), r["id"]))
            filled += 1
    return {"added": added, "updated": filled}


def track_summary(db: Any, limit: int = 20) -> dict[str, Any]:
    """How the radar's appearances did, per category (24 h vs BTC), with 95 % intervals."""
    import json as _j
    import math
    ensure(db)
    out: dict[str, Any] = {"basis": "price move after the coin first appeared, vs BTC, before costs; not a trade result"}
    for cat in ("meme", "alt", None):
        rows = db.query("SELECT rs_24h, worked FROM radar_opportunities WHERE rs_24h IS NOT NULL"
                        + (" AND category = ?" if cat else ""), (cat,) if cat else ())
        x = np.array([float(r["rs_24h"]) for r in rows], float)
        m = float(x.mean()) if len(x) else None
        h = 1.96 * float(x.std(ddof=1)) / math.sqrt(len(x)) if len(x) > 1 else None
        out[cat or "all"] = {"n": len(x), "worked_share": round(float(np.mean([r["worked"] for r in rows])), 3) if rows else None,
                             "avg_rs_24h_pct": round(m, 3) if m is not None else None,
                             "ci95": [round(m - h, 3), round(m + h, 3)] if h is not None else None, "enough": len(x) >= 30}
    out["recent"] = [{**{k: r[k] for k in ("coin", "category", "source", "first_seen", "price", "score", "status", "ret_4h",
                                          "rs_4h", "ret_24h", "rs_24h", "ret_72h", "rs_72h", "max_up_72h", "max_down_72h",
                                          "worked")},
                      "reasons": _j.loads(r["reasons"] or "[]")[:3]}
                     for r in db.query("SELECT * FROM radar_opportunities ORDER BY first_seen DESC LIMIT ?", (limit,))]
    out["tracking"] = (db.one("SELECT COUNT(*) AS n FROM radar_opportunities WHERE status = 'tracking'") or {}).get("n", 0)
    return out


def scan(db: Any, provider: Any, now: int | None = None) -> dict[str, Any]:
    """Hourly scan (provider = BinancePublicProvider: `_get_sync`, `session`). Never raises for one coin; a total failure
    returns {'available': False, 'reason'}. Binance spot first; a coin Binance does not list is tried on MEXC spot."""
    now = int(time.time() * 1000) if now is None else int(now)
    lists = watchlists(db)
    wanted = list(dict.fromkeys(lists["meme"] + lists["alt"]))
    cat = {c: "meme" for c in lists["meme"]} | {c: "alt" for c in lists["alt"] if c not in lists["meme"]}
    regime = mregime = None
    try:
        from . import risk_state
        regime = (risk_state.current(db) or {}).get("state")
    except Exception:
        pass
    try:
        mr = db.get_setting("market_regime", None) or {}
        if mr and now - int(mr.get("at") or 0) <= 2 * H:
            mregime = mr.get("regime")
    except Exception:
        pass
    try:
        btc = closed_rows(provider._get_sync("/api/v3/klines", {"symbol": "BTCUSDT", "interval": "1h", "limit": BARS}), now)
        syms = [f"{c}USDT" for c in wanted]
        tick = provider._get_sync("/api/v3/ticker/24hr", {"symbols": json.dumps(syms, separators=(",", ":"))}) \
            if syms else []
    except Exception:
        # one unknown symbol fails the batch: retry one by one
        try:
            tick = []
            for s_ in [f"{c}USDT" for c in wanted]:
                try:
                    tick.append(provider._get_sync("/api/v3/ticker/24hr", {"symbol": s_}))
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
    state = db.get_setting("fast_radar_state", {}) or {}
    prev_spread = state.get("spread", {}) if isinstance(state, dict) else {}
    items, not_covered, series = [], [], {}
    for c in wanted:
        s_ = f"{c}USDT"
        src = "Binance spot"
        if s_ in tmap:
            t, b = tmap[s_], bmap.get(s_) or {}
            try:
                k = closed_rows(provider._get_sync("/api/v3/klines", {"symbol": s_, "interval": "1h", "limit": BARS}), now)
            except Exception:
                items.append({"coin": c, "symbol": f"{c}/USDT", "category": cat[c], "source": src, "score": None,
                              "status": "unavailable", "reason": "candles unavailable"})
                continue
        else:
            got = _mexc_coin(provider, c, now)
            if got is None:
                not_covered.append(c)
                continue
            k, t, b = got
            src = "MEXC spot"
        series[c] = k
        f = features(k, btc)
        qv = float(t.get("quoteVolume") or 0)
        bid, ask = float(b.get("bidPrice") or 0), float(b.get("askPrice") or 0)
        spread = (ask - bid) / ((ask + bid) / 2) * 1e4 if bid > 0 and ask > 0 else None
        if f is None:
            items.append({"coin": c, "symbol": f"{c}/USDT", "category": cat[c], "source": src, "score": None,
                          "status": "unavailable", "reason": "fewer than 50 closed 1h candles", "quote_volume_24h": qv})
            continue
        j = judge(f, qv, spread, regime)
        ex = extras(k, btc, f, spread, prev_spread.get(c), mregime)
        j["reasons"] = j["reasons"] + ex["signals"]
        j["warnings"] = j["warnings"] + ex["warnings"]
        j["score"] = round(j["score"] - 0.15 * len(ex["warnings"]), 4)
        items.append({"coin": c, "symbol": f"{c}/USDT", "category": cat[c], "source": src, "status": "ok", **f, **j,
                      "detections": ex["signals"], "quote_volume_24h": round(qv, 0), "spread_bps": _r(spread, 2),
                      "liquidity_ok": qv >= MIN_QUOTE_VOL and spread is not None and spread <= MAX_SPREAD_BPS})
    ranked = rank(items)
    for cname in ("meme", "alt"):
        for i_, x in enumerate([x for x in ranked if x.get("category") == cname], 1):
            x["category_rank"] = i_
            x["flagged"] = bool(i_ <= FLAG_TOP and x["score"] > 0)
    try:
        tr = track(db, ranked, series, btc, now, mregime)
        summary = track_summary(db)
    except Exception as exc:
        tr, summary = {"error": type(exc).__name__}, None
    try:
        db.set_setting("fast_radar_state", {"at": now, "spread": {x["coin"]: x.get("spread_bps") for x in ranked
                                                                  if x.get("spread_bps") is not None}})
        # compact copy for the isolated paper strategy (services/fast_strategy reads this setting, never this module)
        db.set_setting("radar_fast_snapshot", {"at": now, "regime": regime, "market_regime": mregime, "coins": [
            {k: x.get(k) for k in ("coin", "symbol", "category", "source", "score", "category_rank", "flagged", "price",
                                   "closed_at", "warnings", "liquidity_ok", "spread_bps", "quote_volume_24h",
                                   "volatility_expansion", "rs_24h_pct", "rs_7d_pct", "above_ema20", "above_ema50", "atr_24")}
            | {"recent_bars": [[int(b[0]), float(b[2]), float(b[3]), float(b[4])] for b in series.get(x["coin"], np.zeros((0, 6)))[-6:]]}
            for x in ranked]})
    except Exception:
        pass
    return {"available": True, "generated_at": now, "display_only": True, "regime": regime, "market_regime": mregime,
            "note": "Display only: a ranked list of fast movers with reasons and warnings. Not a signal, never traded.",
            "coins": ranked + [x for x in items if x.get("score") is None], "not_covered": not_covered,
            "categories": {k: [x["coin"] for x in ranked if x.get("category") == k] for k in ("meme", "alt")},
            "tracking": summary, "tracked": tr,
            "config": {"watchlists": lists, "watchlist": wanted, "min_quote_volume": MIN_QUOTE_VOL,
                       "max_spread_bps": MAX_SPREAD_BPS, "weights": WEIGHTS, "timeframe": "1h",
                       "source": "Binance spot, else MEXC spot", "flag_top": FLAG_TOP}}
