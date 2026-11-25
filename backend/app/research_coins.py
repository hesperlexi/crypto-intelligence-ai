"""v2.33 coin study (owner, 14 Nov 2026: "suggest the coins which can give better results ... listed on binance and mexc").

Read-only on production: runs on a private copy of the engine state in a GitHub job (never saved back, no secrets).

`candidate SYMBOL`: is the coin listed on Binance spot, Binance USD-M futures and MEXC spot / futures; then its candles
(the engine's own source, data-api.binance.vision) are loaded, the engine's models trained on 15m / 1h / 4h exactly as
the nightly job does (`training.train_one`), and the models' walk-forward out-of-sample calls are replayed through the
live decision rules with the record's exits and 0.15 % costs (`research_engine.evaluate`, the method of the v2.6 study):
the first 70 % of each series tunes, the last 30 % is the untouched test. Result = test-split net R per trade, win
rate, trades per week, drawdown.

`baseline`: the same replay for the coins already on the watchlist (their existing models), so candidates are judged
against what the app has now. Aggregates only (no levels, no record rows).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import time
import urllib.request
from typing import Any

TFS = ["15m", "1h", "4h"]
MEXC_SPOT = "https://api.mexc.com/api/v3/exchangeInfo?symbol={p}"
MEXC_FUT = "https://contract.mexc.com/api/v1/contract/detail?symbol={b}_USDT"
BINANCE_FUT_FILE = "https://data.binance.vision/data/futures/um/daily/klines/{p}/1h/{p}-1h-{d}.zip"


def _get(url: str, method: str = "GET") -> tuple[int, Any]:
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "cia-research"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read() if method == "GET" else b""
            return r.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


def listings(sym: str, binance_spot: bool) -> dict[str, Any]:
    base, pair = sym.split("/")[0], sym.replace("/", "")
    d = (dt.datetime.utcnow() - dt.timedelta(days=2)).strftime("%Y-%m-%d")
    bfut = None
    for fp in (pair, "1000" + pair):                 # memecoins trade as 1000SHIB etc. on futures
        code, _ = _get(BINANCE_FUT_FILE.format(p=fp, d=d), "HEAD")
        if code == 200:
            bfut = True
            break
        if code in (403, 404):
            bfut = False
    code, j = _get(MEXC_SPOT.format(p=pair))
    mspot = (bool(j and any(s.get("symbol") == pair for s in j.get("symbols", []))) if code == 200
             else False if code == 400 else None)
    mfut = None
    for fb in (base, "1000" + base):
        code, j = _get(MEXC_FUT.format(b=fb))
        if code == 200 and isinstance(j, dict):
            mfut = bool(j.get("success") and j.get("data"))
            if mfut:
                break
    return {"binance_spot": binance_spot, "binance_futures": bfut, "mexc_spot": mspot, "mexc_futures": mfut}


def _summary(res: dict[str, Any], symbols: list[str]) -> dict[str, Any]:
    from .data.base import tf_ms
    week = 7 * 86_400_000
    out = {}
    for s in symbols:
        rows, wins, n, tot, per_week = {}, 0.0, 0, 0.0, 0.0
        for k, v in (res.get("series") or {}).items():
            sym, tf = k.rsplit(" ", 1)
            if sym != s:
                continue
            r = dict(v["test_old"])
            weeks = max(v["test_bars"] * tf_ms(tf) / week, 1e-9)
            r["trades_per_week"] = round(r["n"] / weeks, 2)
            rows[tf] = r
            n += r["n"]
            tot += r["total_r"]
            wins += (r["win_rate"] or 0) * r["n"]
            per_week += r["trades_per_week"]
        out[s] = {"by_timeframe": rows, "trades": n, "avg_r": round(tot / n, 4) if n else None, "total_r": round(tot, 2),
                  "win_rate": round(wins / n, 3) if n else None, "trades_per_week": round(per_week, 2)}
    return out


def candidate(db_url: str, sym: str, budget_s: float, cost: float) -> dict[str, Any]:
    from .config import MTF_TIMEFRAMES
    from .db import Database
    from .services import market, training
    from .services.runtime import Runtime
    from . import research_engine as RE

    t0 = time.time()
    db = Database(db_url)
    rt = Runtime(db, market.make_provider())
    try:
        listed = sym in asyncio.run(rt.provider.search_markets(sym.split("/")[0], 50))
    except Exception:
        listed = False
    out: dict[str, Any] = {"symbol": sym, "listings": listings(sym, listed)}
    if not listed:
        out["skipped"] = "not on Binance spot (the engine's data source)"
        return out
    for tf in MTF_TIMEFRAMES:                          # 15m history is filled in pages: a few passes
        for _ in range(6 if tf == "15m" else 2):
            r = asyncio.run(market.sync_symbol(rt, sym, [tf], force=True))
            if not isinstance(r.get(tf), int) or r.get(tf) == 0:
                break
    from .research_verdict import strip_holdout          # V3.2: freshly fetched candles stop before the holdout too
    strip_holdout(db)
    out["candles"] = {tf: int(db.one("SELECT COUNT(*) AS n FROM market_data WHERE symbol = ? AND timeframe = ?",
                                     (sym, tf))["n"]) for tf in TFS}
    trained = {}
    for tf in TFS:
        st = training.train_one(rt, sym, tf)
        trained[tf] = {"state": st.get("state"), "message": (st.get("error") or st.get("message") or "")[:160]}
    out["trained"] = trained
    res = RE.evaluate(rt, [sym], TFS, t0 + budget_s, cost)
    out["result"] = _summary(res, [sym])[sym]
    out["skipped_series"] = res.get("skipped")
    out["seconds"] = round(time.time() - t0, 1)
    return out


def baseline(db_url: str, budget_s: float, cost: float, symbols: list[str] | None = None) -> dict[str, Any]:
    from .db import Database
    from .services.runtime import Runtime
    from . import research_engine as RE

    class _Prov:
        name = "binance"
    db = Database(db_url)
    ex = db.one("SELECT exchange, COUNT(*) AS n FROM market_data GROUP BY exchange ORDER BY n DESC LIMIT 1")
    if ex:
        _Prov.name = ex["exchange"]
    rt = Runtime(db, _Prov())
    syms = symbols or [r["symbol"] for r in db.query(
        "SELECT DISTINCT symbol FROM model_versions WHERE active = 1 AND timeframe IN ('15m','1h','4h') ORDER BY symbol")]
    t0 = time.time()
    res = RE.evaluate(rt, syms, TFS, t0 + budget_s, cost)
    return {"coins": _summary(res, syms), "skipped_series": res.get("skipped"), "seconds": round(time.time() - t0, 1),
            "overall": (res.get("test") or {}).get("old", {}).get("overall")}
