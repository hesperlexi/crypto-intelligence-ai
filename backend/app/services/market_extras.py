"""v2.75 market extras for members (owner, 22 Nov 2026: "go for all 15").

One hourly view, `views/derivs`, built from data the engine already records plus three free public sources:

* per coin (OKX rubik numbers already in `mkt_okx` / `mkt_liq`, Hyperliquid funding in `derivs`): open interest and its
  24 h change, long/short account ratio, taker buy share over 24 h, liquidations over 24 h, funding now and per day for
  7 days (8 h equivalent, %),
* liquidation map (ESTIMATE) for the coins with the most open interest: every hour in the last 7 days where open
  interest rose is treated as new positions opened at that hour's close, split long / short by that hour's taker buy
  share, at a spread of common leverages; positions whose liquidation price the price has already crossed since are
  dropped. What is left is binned around the current price,
* Deribit (public API): BTC / ETH volatility index (DVOL) and the options book - put / call open-interest ratio and the
  "max pain" price of the next large expiry,
* traditional markets (Yahoo Finance chart API): S&P 500, Nasdaq, dollar index, gold, US 10-year yield, with BTC's
  30-day correlation to the S&P 500 (daily returns),
* token unlocks (DefiLlama's free per-project emissions datasets): tokens scheduled to unlock in the next 30 days.

Nothing here changes a call. Every source is optional: a failed one is left out of the view (never invented).
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any

import requests

from ..db import Database
from . import market_data as MD

HOUR = 3_600_000
DAY = 86_400_000
EVERY_S = 3600
UA = {"User-Agent": "Mozilla/5.0 (compatible; cia-engine)"}
DERIBIT = "https://www.deribit.com/api/v2/public"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart"
LLAMA = "https://defillama-datasets.llama.fi/emissions"
MACRO = {"SPX": ("^GSPC", "S&P 500"), "NDX": ("^IXIC", "Nasdaq"), "DXY": ("DX-Y.NYB", "Dollar index"),
         "GOLD": ("GC=F", "Gold"), "US10Y": ("^TNX", "US 10-year yield")}
LEVERAGE_MIX = ((10, 0.35), (25, 0.35), (50, 0.2), (100, 0.1))     # share of new positions at each leverage (estimate)
LIQ_COINS = 6
LIQ_BINS = 40
LIQ_RANGE = 0.15                                                   # ±15 % around the price
# coin -> DefiLlama emissions slug (only projects with a free dataset; others are left out)
UNLOCK_SLUGS = {"SUI": "sui", "APT": "aptos", "AVAX": "avalanche", "ENA": "ethena",
                "LINK": "chainlink", "NEAR": "near", "UNI": "uniswap", "AAVE": "aave", "SEI": "sei", "ARB": "arbitrum",
                "TIA": "celestia", "HYPE": "hyperliquid", "ONDO": "ondo-finance", "WLD": "worldcoin",
                "PYTH": "pyth-network", "JUP": "jupiter", "STRK": "starknet", "HBAR": "hedera", "PENGU": "pudgy-penguins", "SOL": "solana",
                "TRX": "tron", "DOGE": "dogecoin", "LTC": "litecoin"}   # checked on the runner 22 Nov 2026


def _get(session: Any, url: str, params: dict | None = None, timeout: float = 15.0) -> Any:
    r = (session or requests).get(url, params=params, timeout=timeout, headers=UA)
    r.raise_for_status()
    return r.json()


def _num(v: Any) -> float | None:
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- per coin (data already recorded)
def coin_stats(db: Database, symbol: str, now: int) -> dict[str, Any] | None:
    c = MD.coin_of(symbol)
    oi = MD.series(db, c, "oi_usd", now - 8 * DAY)
    out: dict[str, Any] = {}
    if oi:
        last_ts, last = oi[-1]
        prev = [v for t, v in oi if t <= last_ts - DAY]
        out["oi_usd"] = last
        out["oi_chg_24h"] = (last / prev[-1] - 1) * 100 if prev and prev[-1] else None
        out["oi_series"] = [round(v) for t, v in oi if t >= last_ts - 7 * DAY][-48:]
    ls = MD.series(db, c, "ls_ratio", now - 2 * DAY)
    if ls:
        out["ls_ratio"] = ls[-1][1]
        out["long_pct"] = ls[-1][1] / (1 + ls[-1][1]) * 100
    buy = sum(v for t, v in MD.series(db, c, "taker_buy", now - DAY))
    sell = sum(v for t, v in MD.series(db, c, "taker_sell", now - DAY))
    if buy + sell > 0:
        out["taker_buy_pct"] = buy / (buy + sell) * 100
    liq = MD.liquidations(db, c, now - DAY)
    tot = {k: round(sum(u for _, u in v)) for k, v in (liq or {}).items()}
    if any(tot.values()):
        out["liq_24h"] = tot
    fr = db.query("SELECT ts, value FROM derivs WHERE symbol = ? AND kind = 'funding_1h' AND ts >= ? ORDER BY ts",
                  (symbol, now - 8 * DAY))
    if fr:
        out["funding_8h_pct"] = sum(r["value"] for r in fr[-8:]) * 100
        days: dict[int, float] = {}
        for r in fr:
            days[int(r["ts"]) // DAY] = days.get(int(r["ts"]) // DAY, 0.0) + float(r["value"])
        out["funding_days"] = [[d * DAY, round(v / 3 * 100, 5)] for d, v in sorted(days.items())][-7:]   # per 8 h, %
        out["funding_at"] = int(fr[-1]["ts"])
    return out or None


def liquidation_map(db: Database, symbol: str, closes: list[tuple[int, float, float, float]], now: int) -> dict[str, Any] | None:
    """closes: 1h candles (ts, high, low, close), oldest first. ESTIMATE - see the module notes."""
    c = MD.coin_of(symbol)
    oi = dict(MD.series(db, c, "oi_usd", now - 8 * DAY))
    if len(oi) < 48 or len(closes) < 48:
        return None
    buy = dict(MD.series(db, c, "taker_buy", now - 8 * DAY))
    sell = dict(MD.series(db, c, "taker_sell", now - 8 * DAY))
    price = closes[-1][3]
    lo_b, hi_b = price * (1 - LIQ_RANGE), price * (1 + LIQ_RANGE)
    step = (hi_b - lo_b) / LIQ_BINS
    longs, shorts = [0.0] * LIQ_BINS, [0.0] * LIQ_BINS
    by_ts = {t: i for i, (t, *_rest) in enumerate(closes)}
    ts_sorted = sorted(oi)
    for a, b in zip(ts_sorted, ts_sorted[1:]):
        new = oi[b] - oi[a]
        if new <= 0 or b not in by_ts:
            continue
        i = by_ts[b]
        entry = closes[i][3]
        tb, ts_ = buy.get(b), sell.get(b)
        long_share = tb / (tb + ts_) if tb is not None and ts_ is not None and tb + ts_ > 0 else 0.5
        later = closes[i + 1:]
        lo_after = min((x[2] for x in later), default=entry)
        hi_after = max((x[1] for x in later), default=entry)
        for lev, w in LEVERAGE_MIX:
            liq_l, liq_s = entry * (1 - 1 / lev + 0.005), entry * (1 + 1 / lev - 0.005)
            if lo_after > liq_l and lo_b <= liq_l < hi_b:          # not yet reached by the price since
                longs[int((liq_l - lo_b) / step)] += new * w * long_share
            if hi_after < liq_s and lo_b <= liq_s < hi_b:
                shorts[int((liq_s - lo_b) / step)] += new * w * (1 - long_share)
    if not any(longs) and not any(shorts):
        return None
    return {"price": price, "low": lo_b, "high": hi_b, "longs": [round(v) for v in longs], "shorts": [round(v) for v in shorts],
            "note": "estimate from open-interest changes, taker flow and common leverages"}


# ---------------------------------------------------------------- Deribit
def deribit(session: Any, now: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for cur in ("BTC", "ETH"):
        try:
            d = _get(session, f"{DERIBIT}/get_volatility_index_data", {"currency": cur, "resolution": "3600",
                                                                       "start_timestamp": now - 8 * DAY, "end_timestamp": now})
            rows = (d.get("result") or {}).get("data") or []
            if rows:
                last = rows[-1][4]
                prev = [r[4] for r in rows if r[0] <= rows[-1][0] - DAY]
                daily = {}
                for r in rows:
                    daily[r[0] // DAY] = r[4]
                out.setdefault("dvol", {})[cur] = {"value": last, "chg_24h": (last - prev[-1]) if prev else None,
                                                   "series": [round(v, 2) for _, v in sorted(daily.items())][-8:]}
        except Exception:
            pass
        try:
            book = (_get(session, f"{DERIBIT}/get_book_summary_by_currency", {"currency": cur, "kind": "option"}) or {}).get("result") or []
            opts = []
            for b in book:
                p = str(b.get("instrument_name", "")).split("-")
                if len(p) != 4:
                    continue
                exp = datetime.strptime(p[1], "%d%b%y").replace(hour=8, tzinfo=timezone.utc).timestamp() * 1000
                opts.append((exp, float(p[2]), p[3], float(b.get("open_interest") or 0), _num(b.get("underlying_price"))))
            if opts:
                calls = sum(o[3] for o in opts if o[2] == "C"); puts = sum(o[3] for o in opts if o[2] == "P")
                upcoming = sorted({o[0] for o in opts if o[0] > now})
                tot = {e: sum(o[3] for o in opts if o[0] == e) for e in upcoming}
                big = max(tot.values()) if tot else 0
                exp = next((e for e in upcoming if tot[e] >= 0.1 * big), None)     # next expiry with real size
                mp = None
                if exp:
                    sel = [o for o in opts if o[0] == exp]
                    strikes = sorted({o[1] for o in sel})
                    mp = min(strikes, key=lambda s: sum(o[3] * max(0.0, s - o[1]) for o in sel if o[2] == "C")
                             + sum(o[3] * max(0.0, o[1] - s) for o in sel if o[2] == "P"))
                und = next((o[4] for o in opts if o[4]), None)
                out.setdefault("options", {})[cur] = {"put_call": puts / calls if calls else None, "oi_coins": round(calls + puts),
                                                      "max_pain": mp, "expiry": int(exp) if exp else None, "underlying": und}
        except Exception:
            pass
    if out:
        out["source"] = "Deribit"
    return out


# ---------------------------------------------------------------- traditional markets
def macro(session: Any, btc_daily: list[tuple[int, float]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, (sym, name) in MACRO.items():
        try:
            r = (_get(session, f"{YAHOO}/{requests.utils.quote(sym, safe='')}", {"range": "3mo", "interval": "1d"}).get("chart") or {}).get("result") or []
            if not r:
                continue
            ts, cl = r[0].get("timestamp") or [], ((r[0].get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
            pts = [(int(t) * 1000, float(c)) for t, c in zip(ts, cl) if c is not None]
            if len(pts) < 3:
                continue
            last, prev = pts[-1][1], pts[-2][1]
            out[k] = {"name": name, "value": last, "chg_1d": (last / prev - 1) * 100 if prev else None,
                      "series": [round(v, 4) for _, v in pts[-22:]], "at": pts[-1][0]}
            if k == "SPX" and len(btc_daily) > 20:
                out[k]["btc_corr_30d"] = _corr_daily(pts, btc_daily)
        except Exception:
            continue
    if out:
        out["source"] = "Yahoo Finance (delayed)"
    return out


def _corr_daily(a: list[tuple[int, float]], b: list[tuple[int, float]]) -> float | None:
    da = {t // DAY: v for t, v in a}
    db_ = {t // DAY: v for t, v in b}
    days = sorted(set(da) & set(db_))[-31:]
    ra, rb = [], []
    for x, y in zip(days, days[1:]):
        if da[x] and db_[x]:
            ra.append(da[y] / da[x] - 1); rb.append(db_[y] / db_[x] - 1)
    n = len(ra)
    if n < 15:
        return None
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((p - ma) * (q - mb) for p, q in zip(ra, rb))
    va, vb = sum((p - ma) ** 2 for p in ra), sum((q - mb) ** 2 for q in rb)
    return round(cov / math.sqrt(va * vb), 2) if va and vb else None


# ---------------------------------------------------------------- token unlocks
def unlocks(session: Any, coins: list[str], now: int) -> list[dict[str, Any]]:
    out = []
    for coin in coins:
        slug = UNLOCK_SLUGS.get(coin)
        if not slug:
            continue
        try:
            d = _get(session, f"{LLAMA}/{slug}", timeout=20)
        except Exception:
            continue
        series = ((d.get("documentedData") or {}).get("data") or (d.get("data") if isinstance(d.get("data"), list) else None) or [])
        now_s, end_s = now / 1000, (now + 30 * DAY) / 1000
        total_now = total_end = 0.0
        next_step = None
        for blk in series:
            pts = [(float(p.get("timestamp", 0)), float(p.get("unlocked") or 0)) for p in (blk.get("data") or []) if isinstance(p, dict)]
            if not pts:
                continue
            at = lambda t: max((u for s, u in pts if s <= t), default=0.0)            # noqa: E731
            a, b = at(now_s), at(end_s)
            total_now += a; total_end += b
            for (s1, u1), (s2, u2) in zip(pts, pts[1:]):
                if now_s < s2 <= end_s and u2 - u1 > 0 and (next_step is None or s2 < next_step):
                    next_step = s2
        if total_end > total_now > 0:
            out.append({"coin": coin, "tokens_30d": total_end - total_now, "pct_of_unlocked": (total_end / total_now - 1) * 100,
                        "next_at": int(next_step * 1000) if next_step else None})
    return sorted(out, key=lambda x: -x["pct_of_unlocked"])


# ---------------------------------------------------------------- view
def build(rt: Any, session: Any = None, now: int | None = None) -> dict[str, Any]:
    now = now or int(time.time() * 1000)
    syms = rt.symbols()
    coins: dict[str, Any] = {}
    for s in syms:
        st = coin_stats(rt.db, s, now)
        if st:
            coins[s] = st
    view: dict[str, Any] = {"generated_at": now, "coins": coins}
    ranked = sorted((s for s in coins if coins[s].get("oi_usd")), key=lambda s: -coins[s]["oi_usd"])[:LIQ_COINS]
    maps = {}
    for s in ranked:
        try:
            df = rt.store.load(rt.exchange, s, "1h")
            if df is None or len(df) < 50:
                continue
            tail = df[df["ts"] >= now - 8 * DAY]
            closes = [(int(r.ts), float(r.high), float(r.low), float(r.close)) for r in tail.itertuples()]
            m = liquidation_map(rt.db, s, closes, now)
            if m:
                maps[s] = m
        except Exception:
            continue
    view["liq_maps"] = maps
    view["volatility"] = deribit(session, now)
    btc_daily: list[tuple[int, float]] = []
    try:
        d1 = rt.store.load(rt.exchange, "BTC/USDT", "1d")
        btc_daily = [(int(r.ts), float(r.close)) for r in d1.tail(120).itertuples()]
    except Exception:
        pass
    view["macro"] = macro(session, btc_daily)
    view["unlocks"] = unlocks(session, [MD.coin_of(s) for s in syms], now)
    view["core"] = {"coins": len(coins), "maps": len(maps), "hour": now // HOUR}
    return view


def publish(rt: Any, sink: Any) -> dict[str, Any]:
    v = build(rt)
    sink.view("derivs", v, min_interval_s=EVERY_S - 300, core=v["core"])
    return {"coins": len(v["coins"]), "maps": len(v["liq_maps"]), "vol": bool(v["volatility"]), "macro": len(v["macro"]),
            "unlocks": len(v["unlocks"])}
