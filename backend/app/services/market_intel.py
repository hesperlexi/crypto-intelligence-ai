"""V3.3 market intelligence (Stage 2 phase B): one context for the market and for each coin, built only from data the
engine already records, with every field marked by how far it can be trusted.

Each field = {"value", "status", "as_of", "age_h", "source"}; status:
  confirmed    - measured from closed candles / records that are fresh (no look-ahead: closed candles only, records only
                 once their `known_at` / publication lag has passed)
  delayed      - real but late (the Binance crowd archive arrives ~2 days late; a feed older than its normal cadence)
  unavailable  - missing, too short or too old to say anything
CONTEXT ONLY. Nothing here may block, approve, grade or size a trade: it is stored with every live call (private payload
`risk_shadow.intel`) and shown to the admin, so a later study (research_verdict, forward holdout) can test whether any of it
would have helped. Promoting a field to an entry rule needs that verdict first.

Market (worker step `market_intel`, every tick before the analyses, setting `market_intel`): BTC regime (4h and 1d),
BTC trend, BTC volatility (4h ATR14 / ATR100, 24 h realised), breadth (watchlist coins above their 4h EMA50), the market
risk state. Coin (`coin_context`, per live trade call): relative strength vs BTC (24 h, 7 d), spot volume and spread,
funding, open interest (OKX hourly, else the delayed Binance archive), liquidations (Coinalyze)."""
from __future__ import annotations

import time
from typing import Any

import numpy as np

H = 3_600_000
DAY = 24 * H
CROWD_LAG_MS = 2 * DAY
FRESH_H = {"funding": 3.0, "oi": 3.0, "liq": 3.0, "ticker": 300 / 3600}
STEP = {"15m": 15 * 60_000, "1h": H, "4h": 4 * H, "12h": 12 * H, "1d": DAY}


def field(value: Any, status: str, as_of: int | None = None, source: str | None = None, now: int | None = None,
          **extra: Any) -> dict[str, Any]:
    now = int(time.time() * 1000) if now is None else now
    out = {"value": value if status != "unavailable" else None, "status": status, "as_of": as_of,
           "age_h": round((now - as_of) / H, 2) if as_of else None, "source": source}
    out.update(extra)
    return out


def _na(source: str, why: str, now: int | None = None) -> dict[str, Any]:
    return field(None, "unavailable", None, source, now, why=why)


def _closed(rt: Any, symbol: str, tf: str, now: int) -> Any:
    df = rt.candles(symbol, tf)
    if df is None or len(df) == 0:
        return None
    return df[df["ts"].astype("int64") + STEP[tf] <= now]            # closed candles only


def _fresh_candles(df: Any, tf: str, now: int, bars: float = 2.0) -> bool:
    return df is not None and len(df) > 0 and now - (int(df["ts"].iloc[-1]) + STEP[tf]) <= bars * STEP[tf]


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    a = 2 / (n + 1)
    out = np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def _atr(df: Any, n: int) -> float | None:
    if df is None or len(df) < n + 1:
        return None
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    prev = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))
    return float(tr[-n:].mean())


# ---- market -----------------------------------------------------------------------------------------------------------

def btc_trend(rt: Any, tf: str, now: int) -> dict[str, Any]:
    src = f"BTC {tf} closed candles"
    try:
        df = _closed(rt, "BTC/USDT", tf, now)
    except Exception as exc:
        return _na(src, type(exc).__name__, now)
    if df is None or len(df) < 60:
        return _na(src, "fewer than 60 closed candles", now)
    c = df["close"].to_numpy(float)
    e = _ema(c, 50)
    slope = (e[-1] / e[-6] - 1) * 100
    above = c[-1] > e[-1]
    label = "up" if above and slope > 0 else "down" if not above and slope < 0 else "mixed"
    st = "confirmed" if _fresh_candles(df, tf, now) else "delayed"
    return field(label, st, int(df["ts"].iloc[-1]) + STEP[tf], src, now, close_vs_ema50_pct=round((c[-1] / e[-1] - 1) * 100, 2),
                 ema50_slope_5bars_pct=round(float(slope), 3))


def btc_regime(rt: Any, tf: str, now: int) -> dict[str, Any]:
    src = f"engine regime, BTC {tf}"
    try:
        from ..engine.regime import describe_regime
        fr = rt.frame("BTC/USDT", tf)
        r = describe_regime(fr.ind)
        last_ts = int(fr.df["ts"].iloc[-1])
    except Exception as exc:
        return _na(src, type(exc).__name__, now)
    if r.get("regime") in (None, "INSUFFICIENT DATA"):
        return _na(src, "insufficient history", now)
    close_at = last_ts + STEP[tf] if last_ts else None
    st = "confirmed" if close_at and now - close_at <= 2 * STEP[tf] else "delayed"
    return field(r["regime"], st, close_at, src, now, score=r.get("score"), confidence=r.get("confidence"))


def btc_volatility(rt: Any, now: int) -> dict[str, Any]:
    src = "BTC 4h ATR14 / ATR100, 1h realised 24 h"
    try:
        d4, d1 = _closed(rt, "BTC/USDT", "4h", now), _closed(rt, "BTC/USDT", "1h", now)
    except Exception as exc:
        return _na(src, type(exc).__name__, now)
    a14, a100 = _atr(d4, 14), _atr(d4, 100)
    if not a14 or not a100 or d1 is None or len(d1) < 25:
        return _na(src, "not enough closed candles", now)
    lr = np.diff(np.log(d1["close"].to_numpy(float)[-25:]))
    rv = float(np.std(lr) * np.sqrt(8760) * 100)
    ratio = a14 / a100
    label = "extreme" if ratio >= 2.0 else "high" if ratio >= 1.5 else "low" if ratio <= 0.7 else "normal"
    st = "confirmed" if _fresh_candles(d4, "4h", now) and _fresh_candles(d1, "1h", now) else "delayed"
    return field(label, st, int(d1["ts"].iloc[-1]) + H, src, now, atr_ratio=round(ratio, 3), realised_vol_24h_pct=round(rv, 1))


def breadth(rt: Any, symbols: list[str], now: int) -> dict[str, Any]:
    src = "watchlist coins above their 4h EMA50 (closed candles)"
    up = n = stale = 0
    for s in symbols:
        try:
            df = _closed(rt, s, "4h", now)
        except Exception:
            df = None
        if df is None or len(df) < 60:
            continue
        if not _fresh_candles(df, "4h", now):
            stale += 1
            continue
        c = df["close"].to_numpy(float)
        n += 1
        up += int(c[-1] > _ema(c, 50)[-1])
    if n < max(3, 0.5 * len(symbols)):
        return _na(src, f"only {n} of {len(symbols)} coins have fresh 4h candles", now)
    share = up / n
    st = "confirmed" if stale <= 0.2 * (n + stale) else "delayed"
    return field(round(share, 3), st, now - now % (4 * H), src, now, coins=n, above=up, stale=stale,
                 label="broad up" if share >= 0.65 else "broad down" if share <= 0.35 else "mixed")


def risk_state_field(rt: Any, now: int) -> dict[str, Any]:
    try:
        from . import risk_state
        rs = risk_state.current(rt.db)
    except Exception as exc:
        return _na("market risk state", type(exc).__name__, now)
    if not rs:
        return _na("market risk state", "missing or older than 2 h", now)
    return field(rs.get("state"), "confirmed", int(rs.get("at") or now), "market risk state (services/risk_state)", now,
                 score=rs.get("score"))


def market(rt: Any, now: int | None = None) -> dict[str, Any]:
    now = int(time.time() * 1000) if now is None else int(now)
    syms = rt.symbols() if hasattr(rt, "symbols") else []
    out = {"at": now, "btc_regime_4h": btc_regime(rt, "4h", now), "btc_regime_1d": btc_regime(rt, "1d", now),
           "btc_trend_4h": btc_trend(rt, "4h", now), "btc_trend_1d": btc_trend(rt, "1d", now),
           "btc_volatility": btc_volatility(rt, now), "breadth": breadth(rt, syms, now),
           "risk_state": risk_state_field(rt, now), "authority": "context only - never blocks or approves a trade"}
    out["summary"] = {k: v["status"] for k, v in out.items() if isinstance(v, dict) and "status" in v}
    return out


def run(rt: Any, now: int | None = None) -> dict[str, Any]:
    """Worker step: compute and store the market context (setting `market_intel`)."""
    m = market(rt, now)
    rt.db.set_setting("market_intel", m)
    return m["summary"]


def current(db: Any, now: int | None = None, max_age_ms: int = 30 * 60_000) -> dict[str, Any] | None:
    now = int(time.time() * 1000) if now is None else now
    m = db.get_setting("market_intel", None)
    return m if m and now - int(m.get("at") or 0) <= max_age_ms else None


# ---- coin -------------------------------------------------------------------------------------------------------------

def relative_strength(rt: Any, symbol: str, now: int) -> dict[str, Any]:
    src = "1h closed candles: coin return minus BTC return"
    if symbol == "BTC/USDT":
        return field(0.0, "confirmed", now, src, now, note="BTC itself")
    try:
        a, b = _closed(rt, symbol, "1h", now), _closed(rt, "BTC/USDT", "1h", now)
    except Exception as exc:
        return _na(src, type(exc).__name__, now)
    if a is None or b is None or len(a) < 169 or len(b) < 169:
        return _na(src, "fewer than 7 days of 1h candles", now)
    m = a[["ts", "close"]].merge(b[["ts", "close"]], on="ts", suffixes=("_c", "_b"))
    if len(m) < 169:
        return _na(src, "coin and BTC candles do not line up", now)
    ca, cb = m["close_c"].to_numpy(float), m["close_b"].to_numpy(float)
    rs24 = ((ca[-1] / ca[-25]) - (cb[-1] / cb[-25])) * 100
    rs7 = ((ca[-1] / ca[-169]) - (cb[-1] / cb[-169])) * 100
    st = "confirmed" if _fresh_candles(a, "1h", now) and _fresh_candles(b, "1h", now) else "delayed"
    return field(round(rs7, 2), st, int(m["ts"].iloc[-1]) + H, src, now, rs_24h_pct=round(rs24, 2), rs_7d_pct=round(rs7, 2))


def liquidity(rt: Any, symbol: str, now: int) -> dict[str, Any]:
    src = "exchange ticker (24 h quote volume, bid/ask spread)"
    try:
        tk = rt.ticker(symbol)
    except Exception:
        tk = None
    if not tk or tk.get("quote_volume") is None:
        return _na(src, "no ticker", now)
    ts = int(tk.get("ts") or 0) or None
    age_s = (now - ts) / 1000 if ts else None
    st = "confirmed" if age_s is not None and -60 <= age_s <= 300 else "delayed"
    return field(float(tk["quote_volume"]), st, ts, src, now, spread_bps=tk.get("spread_bps"),
                 tier="deep" if tk["quote_volume"] >= 100e6 else "ok" if tk["quote_volume"] >= 15e6 else "thin")


def _latest(db: Any, symbol: str, kind: str, until: int) -> dict[str, Any] | None:
    return db.one("SELECT ts, value FROM derivs WHERE symbol = ? AND kind = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
                  (symbol, kind, until))


def funding(rt: Any, symbol: str, now: int) -> dict[str, Any]:
    src = "funding rate (Hyperliquid / OKX, hourly)"
    try:
        r = _latest(rt.db, symbol, "funding_1h", now)
    except Exception as exc:
        return _na(src, type(exc).__name__, now)
    if not r:
        return _na(src, "no funding recorded for this coin", now)
    age_h = (now - int(r["ts"])) / H
    st = "confirmed" if age_h <= FRESH_H["funding"] else "delayed" if age_h <= 24 else "unavailable"
    return field(float(r["value"]) * 8 * 100, st, int(r["ts"]), src, now, unit="% per 8 h")


def open_interest(rt: Any, symbol: str, now: int) -> dict[str, Any]:
    coin = symbol.split("/")[0]
    try:
        rows = rt.db.query("SELECT ts, value FROM mkt_okx WHERE coin = ? AND kind = 'oi_usd' AND known_at <= ? "
                           "AND ts >= ? ORDER BY ts", (coin, now, now - 2 * DAY))
    except Exception:
        rows = []
    if rows:
        last = rows[-1]
        age_h = (now - int(last["ts"])) / H
        old = [r for r in rows if int(r["ts"]) <= int(last["ts"]) - DAY]
        chg = (float(last["value"]) / float(old[-1]["value"]) - 1) * 100 if old and old[-1]["value"] else None
        st = "confirmed" if age_h <= FRESH_H["oi"] else "delayed"
        return field(float(last["value"]), st, int(last["ts"]), "OKX open interest (USD, hourly)", now,
                     change_24h_pct=round(chg, 2) if chg is not None else None)
    try:                                          # Binance archive: published about 2 days late
        r = _latest(rt.db, symbol, "oi_1h", now - CROWD_LAG_MS)
    except Exception:
        r = None
    if r:
        return field(float(r["value"]), "delayed", int(r["ts"]), "Binance archive open interest (~2 days late)", now)
    return _na("open interest", "no OKX or archive data for this coin", now)


def liquidations(rt: Any, symbol: str, now: int) -> dict[str, Any]:
    src = "Coinalyze liquidations (1h bars)"
    try:
        rows = rt.db.query("SELECT kind, ts, value FROM derivs WHERE symbol = ? AND kind IN ('liq_long_1hour', 'liq_short_1hour', "
                           "'liq_long_1h', 'liq_short_1h') AND ts >= ? AND ts + ? <= ?", (symbol, now - DAY, H, now))
    except Exception as exc:
        return _na(src, type(exc).__name__, now)
    if not rows:
        return _na(src, "no liquidation bars in the last 24 h", now)
    newest = max(int(r["ts"]) for r in rows) + H
    longs = sum(float(r["value"]) for r in rows if "long" in r["kind"])
    shorts = sum(float(r["value"]) for r in rows if "short" in r["kind"])
    st = "confirmed" if (now - newest) / H <= FRESH_H["liq"] else "delayed"
    return field(round(longs + shorts, 2), st, newest, src, now, longs_24h=round(longs, 2), shorts_24h=round(shorts, 2))


def coin_context(rt: Any, symbol: str, now: int | None = None) -> dict[str, Any]:
    """The coin's context at decision time (never raises). Stored with the call; never decides."""
    now = int(time.time() * 1000) if now is None else int(now)
    out: dict[str, Any] = {"at": now, "authority": "context only"}
    for name, fn in (("relative_strength", relative_strength), ("liquidity", liquidity), ("funding", funding),
                     ("open_interest", open_interest), ("liquidations", liquidations)):
        try:
            out[name] = fn(rt, symbol, now)
        except Exception as exc:
            out[name] = _na(name, type(exc).__name__, now)
    m = current(rt.db, now) if hasattr(rt, "db") else None
    out["market"] = ({k: {"value": v.get("value"), "status": v.get("status")} for k, v in m.items()
                      if isinstance(v, dict) and "status" in v} if m else None)
    out["summary"] = {k: v["status"] for k, v in out.items() if isinstance(v, dict) and "status" in v}
    return out
