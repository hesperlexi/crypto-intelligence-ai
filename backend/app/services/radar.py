"""Opportunity radar: coins outside the watchlist that are outperforming the market right now.

Hourly, the whole Binance USDT spot market is screened (liquid coins only, no stablecoins or leveraged tokens) and
ranked by measurable strength: performance against BTC over 7 and 30 days, risk-adjusted momentum, trend structure,
a volume surge and fresh breakouts, with a penalty for coins that already went parabolic (chasing pumps).

Honesty built in:
* a historical check re-runs the same ranking on each of the last ~45 days using only data known that day and
  measures the top picks' next-7-day return against BTC (today's liquid coins only, so it flatters a little);
* every live pick is logged and scored 7 days later against BTC, shown as the radar's own track record.
This is a screen for ideas, not a trade signal: a coin gets AI signals only after it is added and its model is trained.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from ..db import Database, new_id, now_ms

log = logging.getLogger(__name__)
DAY = 86_400_000
MIN_QUOTE_VOL = 15e6
MAX_CANDIDATES = 70
TOP_N = 10
EXCLUDE_BASES = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "EUR", "EURI", "USDE", "PYUSD", "AEUR", "XUSD", "BFUSD",
                 "PAXG", "WBTC", "WBETH", "BNSOL", "USD1", "RLUSD", "USDS"}
LEVERAGED = ("UP", "DOWN", "BULL", "BEAR")
SCHEMA = """CREATE TABLE IF NOT EXISTS radar_picks (
  id TEXT PRIMARY KEY, ts BIGINT NOT NULL, symbol TEXT NOT NULL, rank INTEGER NOT NULL, score DOUBLE PRECISION,
  price DOUBLE PRECISION NOT NULL, btc_price DOUBLE PRECISION NOT NULL, ret_7d DOUBLE PRECISION,
  btc_ret_7d DOUBLE PRECISION, evaluated_at BIGINT)"""


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    a, out = 2 / (n + 1), np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def _rsi(c: np.ndarray, n: int = 14) -> float:
    d = np.diff(c[-(n * 3):])
    up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
    au, ad = up[-n:].mean(), dn[-n:].mean()
    return 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)


def features(k: np.ndarray, btc: np.ndarray, end: int | None = None) -> dict[str, float] | None:
    """k, btc: daily candles [ts, o, h, l, c, quote_volume] aligned on ts; uses only rows < end (default: all)."""
    end = len(k) if end is None else end
    if end < 40:
        return None
    c, h, qv = k[:end, 4], k[:end, 2], k[:end, 5]
    bc = btc[:end, 4]
    r = np.diff(np.log(c))
    vol30 = r[-30:].std() * np.sqrt(30) or 1e-9
    ret7, ret30 = c[-1] / c[-8] - 1, c[-1] / c[-31] - 1
    b7, b30 = bc[-1] / bc[-8] - 1, bc[-1] / bc[-31] - 1
    e20, e50 = _ema(c, 20), _ema(c, min(50, end - 1))
    return {"rs_7d": ret7 - b7, "rs_30d": ret30 - b30, "ret_7d": ret7, "ret_30d": ret30,
            "mom_q": np.log(c[-1] / c[-31]) / vol30,
            "trend": float(c[-1] > e20[-1] > e50[-1]) + float(e20[-1] > e20[-6]) * 0.5,
            "vol_surge": float(qv[-1] / max(qv[-21:-1].mean(), 1e-9)),
            "breakout": float(c[-1] >= h[-31:-1].max()), "rsi": _rsi(c),
            "overheat": float(ret7 > 0.6 or _rsi(c) > 82)}


def score_table(feats: dict[str, dict[str, float]]) -> dict[str, float]:
    """Cross-sectional score: z-scores across the candidates, so it ranks coins against each other."""
    syms = list(feats)
    if len(syms) < 5:
        return {}

    def z(key, f=lambda v: v):
        v = np.array([f(feats[s][key]) for s in syms], float)
        sd = v.std() or 1.0
        return np.clip((v - v.mean()) / sd, -3, 3)

    sc = (0.25 * z("rs_7d") + 0.20 * z("rs_30d") + 0.20 * z("mom_q") + 0.25 * np.array([feats[s]["trend"] for s in syms])
          + 0.10 * z("vol_surge", lambda v: np.log(max(v, 1e-3))) + 0.15 * np.array([feats[s]["breakout"] for s in syms])
          - 0.60 * np.array([feats[s]["overheat"] for s in syms]))
    return dict(zip(syms, sc.tolist()))


def reasons(f: dict[str, float]) -> list[str]:
    out = []
    if f["rs_7d"] > 0.03:
        out.append(f"+{f['rs_7d'] * 100:.0f}% vs BTC this week")
    if f["rs_30d"] > 0.05:
        out.append(f"+{f['rs_30d'] * 100:.0f}% vs BTC in 30 days")
    if f["trend"] >= 1.5:
        out.append("clean uptrend (price above rising averages)")
    if f["breakout"]:
        out.append("broke its 30-day high")
    if f["vol_surge"] > 1.8:
        out.append(f"volume {f['vol_surge']:.1f}x its normal level")
    if f["overheat"]:
        out.append("already very extended: wait for a pullback")
    return out


def _universe(provider, exclude: set[str]) -> list[dict[str, Any]]:
    rows = provider._get_sync("/api/v3/ticker/24hr")
    out = []
    for t in rows:
        s = t.get("symbol", "")
        if not s.endswith("USDT"):
            continue
        b = s[:-4]
        if b in EXCLUDE_BASES or b.endswith(LEVERAGED) or f"{b}/USDT" in exclude:
            continue
        qv = float(t.get("quoteVolume") or 0)
        if qv >= MIN_QUOTE_VOL and float(t.get("lastPrice") or 0) > 0:
            out.append({"symbol": f"{b}/USDT", "quote_volume": qv, "change_pct": float(t.get("priceChangePercent") or 0),
                        "last": float(t["lastPrice"])})
    return sorted(out, key=lambda x: -x["quote_volume"])[:MAX_CANDIDATES]


def _daily(provider, symbol: str, limit: int = 100) -> np.ndarray:
    rows = provider._get_sync("/api/v3/klines", {"symbol": symbol.replace("/", ""), "interval": "1d", "limit": limit})
    return np.array([[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[7])] for r in rows], float)


def historical_check(data: dict[str, np.ndarray], btc: np.ndarray, days: int = 45, top: int = 5, hold: int = 7) -> dict[str, Any]:
    """Re-run the ranking on past days (only data known that day) and score the top picks over the next `hold` days."""
    n = len(btc)
    ex, hits, avg_all = [], 0, []
    for end in range(n - days - hold, n - hold):
        if end < 40:
            continue
        feats = {}
        for s, k in data.items():
            if len(k) == n and (f := features(k, btc, end)):
                feats[s] = f
        sc = score_table(feats)
        if not sc:
            continue
        b_ret = btc[end - 1 + hold, 4] / btc[end - 1, 4] - 1
        fwd = {s: data[s][end - 1 + hold, 4] / data[s][end - 1, 4] - 1 for s in feats}
        picks = sorted(sc, key=lambda s: (feats[s]["overheat"], -sc[s]))[:top]
        e = float(np.mean([fwd[s] for s in picks]) - b_ret)
        ex.append(e)
        avg_all.append(float(np.mean(list(fwd.values())) - b_ret))
        hits += e > 0
    if not ex:
        return {"days": 0}
    return {"days": len(ex), "top": top, "hold_days": hold, "avg_excess_vs_btc_pct": float(np.mean(ex) * 100),
            "beat_btc_rate": hits / len(ex), "avg_market_excess_pct": float(np.mean(avg_all) * 100),
            "note": "Overlapping 7-day windows on today's liquid coins (coins that faded away are missing), so this is "
                    "an optimistic sketch; the live record below is the real test."}


def scan(db: Database, provider, watchlist: list[str], now: int | None = None) -> dict[str, Any]:
    now = now or now_ms()
    db.execute(SCHEMA)
    cands = _universe(provider, set(watchlist))
    btc = _daily(provider, "BTC/USDT")
    data, errors = {}, 0
    for c in cands:
        try:
            k = _daily(provider, c["symbol"])
        except Exception:
            errors += 1
            continue
        if len(k) == len(btc) and (k[:, 0] == btc[:, 0]).all():
            data[c["symbol"]] = k
    # the forming daily candle is excluded: rank on closed days, show the live 24h change separately
    closed = {s: k[:-1] for s, k in data.items()}
    btc_c = btc[:-1]
    feats = {s: f for s, k in closed.items() if (f := features(k, btc_c))}
    sc = score_table(feats)
    meta = {c["symbol"]: c for c in cands}
    ranked = [s for s in sorted(sc, key=lambda s: -sc[s]) if not feats[s]["overheat"]]
    hot = [s for s in sorted(sc, key=lambda s: -sc[s]) if feats[s]["overheat"]][:3]   # parabolic: shown apart

    def card(i, s):
        f = feats[s]
        return {"rank": i + 1, "symbol": s, "score": sc[s], "price": meta[s]["last"], "change_24h_pct": meta[s]["change_pct"],
                "quote_volume": meta[s]["quote_volume"], **{k: f[k] for k in ("rs_7d", "rs_30d", "ret_7d", "ret_30d", "vol_surge", "rsi")},
                "trend": f["trend"], "breakout": bool(f["breakout"]), "overheat": bool(f["overheat"]), "reasons": reasons(f)}
    picks = []
    for i, s in enumerate(ranked[:TOP_N]):
        picks.append(card(i, s))
    # log the top 5 (one pick per coin per day) for the live record
    btc_now = float(btc[-1, 4])
    for p in picks[:5]:
        if p["overheat"]:
            continue
        if db.one("SELECT 1 FROM radar_picks WHERE symbol = ? AND ts > ?", (p["symbol"], now - DAY)):
            continue
        db.execute("INSERT INTO radar_picks (id, ts, symbol, rank, score, price, btc_price) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (new_id(), now, p["symbol"], p["rank"], p["score"], p["price"], btc_now))
    evaluate(db, provider, now)
    return {"generated_at": now, "picks": picks, "extended": [card(i, s) for i, s in enumerate(hot)], "screened": len(feats), "errors": errors,
            "historical": historical_check(closed, btc_c), "live": live_record(db),
            "method": "Screens every liquid Binance USDT coin (24h volume above $15M) not already in the app, hourly. "
                      "Ranked by strength against BTC (7 and 30 days), risk-adjusted momentum, trend, volume surge and "
                      "breakouts; coins that already went parabolic are marked and not counted as picks."}


def evaluate(db: Database, provider, now: int | None = None) -> int:
    """Score picks that are 7 days old: their return and BTC's over the same 7 days."""
    now = now or now_ms()
    n = 0
    for p in db.query("SELECT * FROM radar_picks WHERE evaluated_at IS NULL AND ts <= ?", (now - 7 * DAY,)):
        t = int(p["ts"]) + 7 * DAY
        try:
            k = provider._get_sync("/api/v3/klines", {"symbol": p["symbol"].replace("/", ""), "interval": "1h", "startTime": t, "limit": 1})
            b = provider._get_sync("/api/v3/klines", {"symbol": "BTCUSDT", "interval": "1h", "startTime": t, "limit": 1})
        except Exception:
            continue
        if not k or not b:
            continue
        db.execute("UPDATE radar_picks SET ret_7d = ?, btc_ret_7d = ?, evaluated_at = ? WHERE id = ?",
                   (float(k[0][1]) / p["price"] - 1, float(b[0][1]) / p["btc_price"] - 1, now, p["id"]))
        n += 1
    return n


def live_record(db: Database) -> dict[str, Any]:
    rows = db.query("SELECT * FROM radar_picks ORDER BY ts DESC LIMIT 200")
    done = [r for r in rows if r["evaluated_at"]]
    ex = np.array([r["ret_7d"] - r["btc_ret_7d"] for r in done], float)
    return {"picks": len(rows), "evaluated": len(done),
            "beat_btc_rate": float((ex > 0).mean()) if len(ex) else None,
            "avg_excess_vs_btc_pct": float(ex.mean() * 100) if len(ex) else None,
            "recent": [{"symbol": r["symbol"], "ts": r["ts"], "rank": r["rank"], "price": r["price"],
                        "ret_7d": r["ret_7d"], "btc_ret_7d": r["btc_ret_7d"]} for r in rows[:30]]}
