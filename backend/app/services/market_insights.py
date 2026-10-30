"""Market insights for the Home page (one Firestore document, `views/market_context`).

1. BTC / ETH dominance: CoinGecko /global (already fetched by `market.external_context`) is stored once per hour in
   `market_snapshots`, so the 24h / 7d changes and the small chart come from our own history as it accumulates.
2. Altcoin season index (0-100): the common definition - the share of the top 50 coins (no stablecoins, no
   wrapped / staked / bridged / leveraged / gold tokens, no BTC) whose last-90-day return beat BTC's. Ranking from
   CoinGecko /coins/markets (market cap) when reachable, else Binance spot 24h quote volume; daily closes from Binance
   spot (data-api.binance.vision). Computed at most every 6 hours, each result stored in `altseason_history`.
3. Market pulse: total market cap + 24h change, stablecoin share, and the average perpetual funding rate across the
   watchlist with a one-word read (thresholds below).
4. Top headline: the newest headline of the last 24 hours that matches the high-impact keyword rules below.

Nothing is filled in: a block whose source failed or has too little history is null, and the page says so.
Every reading is descriptive (what the number is), never advice.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from ..db import Database, dumps, loads, now_ms

log = logging.getLogger(__name__)
HOUR, DAY = 3_600_000, 86_400_000
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS market_snapshots (
  ts BIGINT PRIMARY KEY, btc_dom DOUBLE PRECISION, eth_dom DOUBLE PRECISION, stable_share DOUBLE PRECISION,
  total_mcap DOUBLE PRECISION, mcap_change_24h DOUBLE PRECISION, fetched_at BIGINT, source TEXT)""",
    """CREATE TABLE IF NOT EXISTS altseason_history (
  ts BIGINT PRIMARY KEY, value INTEGER NOT NULL, n_beat INTEGER NOT NULL, n_total INTEGER NOT NULL,
  window_days INTEGER NOT NULL, universe TEXT, detail TEXT)""",
)

# ---- documented rules -------------------------------------------------------------------------------------------
DOM_MOVE_7D = 1.0        # BTC dominance change over 7 days, in percentage points, that counts as "rising"/"falling"
DOM_MOVE_24H = 0.3       # the same over 24 hours (used while there are fewer than 7 days of snapshots)
ALT_WINDOW_DAYS = 90
ALT_TOP_N = 50
ALT_EVERY_MS = 6 * HOUR
ALT_BITCOIN_SEASON, ALT_ALTCOIN_SEASON = 25, 75
# funding: per 8 hours (Binance / OKX convention). The exchanges' default rate is +0.01% per 8h; an average at three
# times that or more means longs are paying heavily to stay in, below -0.01% means shorts are.
FUND_LONG, FUND_SHORT = 0.0003, -0.0001
RULES = {
    "dominance": f"Rising / falling = BTC dominance moved at least {DOM_MOVE_7D} point over 7 days "
                 f"({DOM_MOVE_24H} point over 24 hours while less than 7 days are stored); otherwise steady.",
    "altseason": f"Share of the top {ALT_TOP_N} coins (stablecoins, wrapped, staked, leveraged and gold tokens and BTC "
                 f"excluded) whose {ALT_WINDOW_DAYS}-day return beat BTC. ≤{ALT_BITCOIN_SEASON} Bitcoin season, "
                 f"≥{ALT_ALTCOIN_SEASON} Altcoin season.",
    "funding": "Average current funding per 8 hours across the watchlist: ≥ +0.03% crowded long, ≤ −0.01% crowded "
               "short, otherwise neutral (the exchanges' default is +0.01%).",
    "headline": "Newest headline of the last 24 hours mentioning the Fed / rates / inflation / jobs data, the SEC or "
                "ETFs, regulation or bans, hacks or exploits, liquidations or a large exchange.",
}

STABLES = {"USDT", "USDC", "DAI", "USDE", "FDUSD", "TUSD", "USDP", "BUSD", "PYUSD", "USDD", "USDS", "USD1", "RLUSD",
           "FRAX", "GUSD", "LUSD", "SUSD", "USDX", "USDB", "USDY", "USD0", "EURC", "EURI", "AEUR", "EUR", "BFUSD",
           "XUSD", "USTC", "SUSDE", "CRVUSD", "GHO", "USDF", "USDG", "USDTB", "BUIDL"}
NOT_ALTS = {"BTC", "WBTC", "CBBTC", "TBTC", "LBTC", "SOLVBTC", "BTCB", "WETH", "STETH", "WSTETH", "WEETH", "RETH",
            "CBETH", "WBETH", "METH", "EZETH", "RSETH", "BNSOL", "JITOSOL", "MSOL", "JUPSOL", "BBSOL", "STSOL",
            "WBNB", "PAXG", "XAUT", "LEO", "BGB", "OKB"}   # (exchange tokens not listed on Binance spot drop out anyway)
NAME_EXCLUDE = re.compile(r"wrapped|bridged|staked|restaked|liquid staking|\bstaking\b|\busd\b|dollar|tokenized gold|gold token", re.I)
LEVERAGED = ("UP", "DOWN", "BULL", "BEAR")
LEVERAGED_ON = {"BTC", "ETH", "BNB", "XRP", "ADA", "LINK", "DOT", "TRX", "LTC", "EOS", "XTZ", "SXP", "FIL", "AAVE",
                "SUSHI", "UNI", "YFI", "1INCH", "BCH", "XLM"}   # Binance's (retired) leveraged tokens, e.g. BTCUP
HEADLINE_RULE = re.compile(
    r"\b(fed|fomc|powell|rate (cut|hike)|interest rates?|inflation|cpi|pce|jobs report|payrolls|sec\b|etfs?|"
    r"regulat\w*|ban(s|ned)?|lawsuit|hack(ed|s)?|exploit(ed)?|liquidat\w*|tariffs?|treasury|binance|coinbase|blackrock)", re.I)


def ensure(db: Database) -> None:
    for s in SCHEMA:
        db.execute(s)


# ---- 1. dominance snapshots ---------------------------------------------------------------------------------------
def record_snapshot(db: Database, ctx: dict[str, Any] | None, now: int | None = None) -> bool:
    """Store the CoinGecko /global reading once per hour (hour bucket of the fetch time). True when a row was added."""
    m = (ctx or {}).get("market")
    if not m or m.get("btc_dominance") is None:
        return False
    ensure(db)
    fetched = int((ctx or {}).get("fetched_at") or now or now_ms())
    ts = fetched // HOUR * HOUR
    n = db.execute("INSERT INTO market_snapshots (ts, btc_dom, eth_dom, stable_share, total_mcap, mcap_change_24h, fetched_at, source) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (ts) DO NOTHING",
                   (ts, m.get("btc_dominance"), m.get("eth_dominance"), m.get("stablecoin_share"),
                    m.get("total_market_cap_usd"), m.get("market_cap_change_24h_pct"), fetched, m.get("source") or "CoinGecko"))
    db.execute("DELETE FROM market_snapshots WHERE ts < ?", (fetched - 400 * DAY,))
    return bool(n)


def _near(rows: list[dict[str, Any]], ts: int, tol: int) -> dict[str, Any] | None:
    best = min(rows, key=lambda r: abs(r["ts"] - ts), default=None)
    return best if best is not None and abs(best["ts"] - ts) <= tol else None


def dominance_reading(btc: float, ch24: float | None, ch7: float | None) -> str:
    """One plain sentence describing the reading (rules in RULES['dominance']); neutral wording, not advice."""
    if ch7 is not None:
        move, span, thr = ch7, "7 days", DOM_MOVE_7D
    elif ch24 is not None:
        move, span, thr = ch24, "24 hours", DOM_MOVE_24H
    else:
        return f"Bitcoin makes up {btc:.1f}% of the total crypto market value. Changes appear once a day of readings is stored."
    pts = f"{abs(move):.1f} point{'s' if round(abs(move), 1) != 1 else ''}"
    if move >= thr:
        return f"Bitcoin's share rose {pts} over {span} to {btc:.1f}%: Bitcoin has been gaining value faster than the rest of the market."
    if move <= -thr:
        return f"Bitcoin's share fell {pts} over {span} to {btc:.1f}%: the rest of the market has been gaining on Bitcoin."
    return f"Bitcoin's share is steady at {btc:.1f}% ({'+' if move >= 0 else '−'}{abs(move):.1f} over {span}): no clear rotation between Bitcoin and the rest."


def dominance_block(db: Database, now: int | None = None) -> dict[str, Any] | None:
    ensure(db)
    now = now or now_ms()
    rows = db.query("SELECT ts, btc_dom, eth_dom, fetched_at FROM market_snapshots WHERE ts >= ? AND btc_dom IS NOT NULL "
                    "ORDER BY ts", (now - 31 * DAY,))
    if not rows:
        return None
    cur = rows[-1]

    def change(key: str, back: int, tol: int) -> float | None:
        old = _near(rows[:-1], cur["ts"] - back, tol)
        return None if old is None or old[key] is None or cur[key] is None else round(cur[key] - old[key], 3)

    ch24, ch7 = change("btc_dom", DAY, 2 * HOUR), change("btc_dom", 7 * DAY, 6 * HOUR)
    span = rows[-1]["ts"] - rows[0]["ts"]
    step = HOUR if span <= 7 * DAY else 4 * HOUR          # at most ~186 points (31 days at 4 hours)
    series, last_bucket = [], None
    for r in rows:
        b = r["ts"] // step
        if b != last_bucket or r is cur:
            if series and b == last_bucket:
                series.pop()
            series.append([r["ts"], round(r["btc_dom"], 3), None if r["eth_dom"] is None else round(r["eth_dom"], 3)])
            last_bucket = b
    return {"as_of": cur["fetched_at"] or cur["ts"], "btc": round(cur["btc_dom"], 3),
            "eth": None if cur["eth_dom"] is None else round(cur["eth_dom"], 3),
            "btc_change_24h": ch24, "btc_change_7d": ch7,
            "eth_change_24h": change("eth_dom", DAY, 2 * HOUR), "eth_change_7d": change("eth_dom", 7 * DAY, 6 * HOUR),
            "series": series, "series_step_h": step // HOUR, "points": len(rows),
            "reading": dominance_reading(cur["btc_dom"], ch24, ch7),
            "source": "CoinGecko /global, stored hourly by the engine", "tv_symbol": "CRYPTOCAP:BTC.D"}


# ---- 2. altcoin season index -------------------------------------------------------------------------------------
def is_excluded(sym: str, name: str = "") -> bool:
    s = sym.upper()
    return (s in STABLES or s in NOT_ALTS or "USD" in s or any(s.endswith(x) and s[:-len(x)] in LEVERAGED_ON for x in LEVERAGED)
            or bool(name and NAME_EXCLUDE.search(name)))


def season_label(v: float) -> str:
    return "Bitcoin season" if v <= ALT_BITCOIN_SEASON else "Altcoin season" if v >= ALT_ALTCOIN_SEASON else "Neither season"


def altseason_index(returns: dict[str, float], btc_return: float) -> dict[str, Any]:
    """Pure computation: share (0-100) of the coins whose window return beat BTC's."""
    if not returns:
        raise ValueError("no coins")
    beat = sorted(s for s, r in returns.items() if r > btc_return)
    value = round(100 * len(beat) / len(returns))
    return {"value": value, "n_beat": len(beat), "n_total": len(returns), "label": season_label(value), "beat": beat}


def _closed_daily(provider, base: str, now: int, limit: int) -> list[tuple[int, float]]:
    rows = provider._get_sync("/api/v3/klines", {"symbol": f"{base}USDT", "interval": "1d", "limit": limit})
    return [(int(r[0]), float(r[4])) for r in rows if int(r[0]) + DAY <= now]


def top_universe(provider, session: Any = None) -> tuple[list[str], str]:
    """Ranked candidate bases available on Binance spot: CoinGecko market-cap order, else Binance quote volume."""
    tick = provider._get_sync("/api/v3/ticker/24hr")
    vol = {t["symbol"][:-4]: float(t.get("quoteVolume") or 0) for t in tick
           if str(t.get("symbol", "")).endswith("USDT") and float(t.get("lastPrice") or 0) > 0}
    try:
        import requests
        r = (session or requests).get("https://api.coingecko.com/api/v3/coins/markets",
                                      params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": 150, "page": 1},
                                      timeout=15)
        coins = r.json() if r.status_code == 200 else None
        if isinstance(coins, list) and len(coins) >= 60:
            out = []
            for c in coins:
                s = str(c.get("symbol") or "").upper()
                if s and s in vol and s not in out and not is_excluded(s, str(c.get("name") or "")):
                    out.append(s)
            if len(out) >= ALT_TOP_N:
                return out, "CoinGecko market-cap ranking (coins listed on Binance spot)"
    except Exception as exc:
        log.info("altseason: CoinGecko ranking unavailable (%s)", type(exc).__name__)
    ranked = [b for b, _ in sorted(vol.items(), key=lambda kv: -kv[1]) if not is_excluded(b)]
    return ranked, "Binance spot 24h quote-volume ranking (CoinGecko unreachable)"


def compute_altseason(provider, now: int | None = None, session: Any = None, max_fetch: int = 75) -> dict[str, Any]:
    """Fetch and compute (network). Coins with fewer than 90 days of closed daily candles are skipped and the next
    ranked coin is taken, up to `max_fetch` kline requests."""
    now = now or now_ms()
    need = ALT_WINDOW_DAYS + 1
    btc = _closed_daily(provider, "BTC", now, need + 2)
    if len(btc) < need:
        raise RuntimeError("not enough BTC daily history")
    end_ts = btc[-1][0]
    btc_ret = btc[-1][1] / btc[-need][1] - 1
    ranked, universe = top_universe(provider, session)
    rets: dict[str, float] = {}
    skipped, fetched = [], 0
    for b in ranked:
        if len(rets) >= ALT_TOP_N or fetched >= max_fetch:
            break
        fetched += 1
        try:
            k = _closed_daily(provider, b, now, need + 2)
        except Exception:
            skipped.append(b)
            continue
        if len(k) < need or k[-1][0] != end_ts or k[-need][1] <= 0:
            skipped.append(b)                          # too new (or stale) for a 90-day comparison
            continue
        rets[b] = k[-1][1] / k[-need][1] - 1
    if len(rets) < 30:
        raise RuntimeError(f"only {len(rets)} coins with {ALT_WINDOW_DAYS} days of history")
    out = altseason_index(rets, btc_ret)
    out.update(as_of=end_ts + DAY, computed_at=now, window_days=ALT_WINDOW_DAYS, universe=universe,
               btc_return=round(btc_ret, 4), skipped=skipped[:20],
               best=sorted(({"coin": s, "vs_btc": round(r - btc_ret, 4)} for s, r in rets.items()), key=lambda x: -x["vs_btc"])[:5])
    return out


def refresh_altseason(db: Database, provider, now: int | None = None, session: Any = None, force: bool = False) -> dict[str, Any]:
    """At most every 6 hours; stores each result. Returns a short status for the cycle log."""
    ensure(db)
    now = now or now_ms()
    last = int(db.get_setting("altseason_at", 0) or 0)
    if not force and now - last < ALT_EVERY_MS:
        return {"skipped": "fresh"}
    if not hasattr(provider, "_get_sync"):
        return {"skipped": "provider has no Binance REST access"}
    db.set_setting("altseason_at", now)                # also on failure: no hammering the sources every 5 minutes
    r = compute_altseason(provider, now, session)
    detail = {k: r[k] for k in ("beat", "best", "skipped", "btc_return", "universe", "as_of")}
    db.execute("INSERT INTO altseason_history (ts, value, n_beat, n_total, window_days, universe, detail) VALUES (?, ?, ?, ?, ?, ?, ?) "
               "ON CONFLICT (ts) DO UPDATE SET value = excluded.value, n_beat = excluded.n_beat, n_total = excluded.n_total, "
               "detail = excluded.detail", (now, r["value"], r["n_beat"], r["n_total"], r["window_days"], r["universe"], dumps(detail)))
    db.execute("DELETE FROM altseason_history WHERE ts < ?", (now - 400 * DAY,))
    return {"value": r["value"], "n_beat": r["n_beat"], "n_total": r["n_total"]}


def altseason_block(db: Database, now: int | None = None) -> dict[str, Any] | None:
    ensure(db)
    now = now or now_ms()
    rows = db.query("SELECT * FROM altseason_history WHERE ts >= ? ORDER BY ts", (now - 90 * DAY,))
    if not rows:
        return None
    cur = rows[-1]
    d = loads(cur["detail"], {}) or {}
    return {"value": cur["value"], "label": season_label(cur["value"]), "n_beat": cur["n_beat"], "n_total": cur["n_total"],
            "window_days": cur["window_days"], "as_of": d.get("as_of") or cur["ts"], "computed_at": cur["ts"],
            "btc_return": d.get("btc_return"), "best": d.get("best", [])[:3], "universe": cur["universe"],
            "history": [[r["ts"], r["value"]] for r in rows][-120:],
            "source": "Binance spot daily closes; computed by the engine every 6 hours"}


# ---- 3. pulse ------------------------------------------------------------------------------------------------------
def funding_read(avg: float) -> str:
    return "crowded long" if avg >= FUND_LONG else "crowded short" if avg <= FUND_SHORT else "neutral"


def funding_block(db: Database, live: dict[str, dict[str, Any]] | None, symbols: list[str], now: int | None = None) -> dict[str, Any] | None:
    """Live 8-hour rates from the cycle's snapshot (Binance futures, else OKX); else the newest stored hourly rate
    (Hyperliquid, x8 to the 8-hour convention) when it is under 3 hours old."""
    now = now or now_ms()
    rates, srcs = {}, set()
    for s in symbols:
        x = (live or {}).get(s)
        if x and x.get("rate") is not None:
            rates[s] = float(x["rate"])
            srcs.add(x.get("source") or "exchange")
    as_of = now
    if not rates:
        for s in symbols:
            row = db.one("SELECT ts, value FROM derivs WHERE symbol = ? AND kind = 'funding_1h' ORDER BY ts DESC LIMIT 1", (s,))
            if row and now - int(row["ts"]) < 3 * HOUR:
                rates[s] = float(row["value"]) * 8
                as_of = min(as_of, int(row["ts"]))
        if rates:
            srcs.add("Hyperliquid hourly funding (x8)")
    if not rates:
        return None
    avg = sum(rates.values()) / len(rates)
    return {"avg_rate_8h": avg, "read": funding_read(avg), "n": len(rates), "as_of": as_of, "source": ", ".join(sorted(srcs)),
            "high": max(rates.items(), key=lambda kv: kv[1])[0].split("/")[0],
            "low": min(rates.items(), key=lambda kv: kv[1])[0].split("/")[0]}


# ---- 4. headline ---------------------------------------------------------------------------------------------------
def top_headline(heads: dict[str, Any] | None, now: int | None = None) -> dict[str, Any] | None:
    now = now or now_ms()
    for h in (heads or {}).get("items", []):            # newest first
        if h.get("ts") and now - h["ts"] <= DAY and HEADLINE_RULE.search(h.get("title") or ""):
            return {k: h.get(k) for k in ("title", "url", "source", "ts")}
    return None


# ---- the view ------------------------------------------------------------------------------------------------------
def view(db: Database, ctx: dict[str, Any] | None, funding: dict[str, dict[str, Any]] | None, symbols: list[str],
         heads: dict[str, Any] | None, now: int | None = None) -> dict[str, Any]:
    now = now or now_ms()
    m = (ctx or {}).get("market") or None
    pulse = None
    if m:
        pulse = {"as_of": (ctx or {}).get("fetched_at"), "total_market_cap_usd": m.get("total_market_cap_usd"),
                 "market_cap_change_24h_pct": m.get("market_cap_change_24h_pct"), "stablecoin_share": m.get("stablecoin_share"),
                 "source": m.get("source") or "CoinGecko"}
    try:
        dom = dominance_block(db, now)
    except Exception as exc:
        log.warning("dominance block: %s", exc)
        dom = None
    try:
        alt = altseason_block(db, now)
    except Exception as exc:
        log.warning("altseason block: %s", exc)
        alt = None
    return {"generated_at": now, "dominance": dom, "altseason": alt, "pulse": pulse,
            "funding": funding_block(db, funding, symbols, now), "headline": top_headline(heads, now),
            "errors": [e for e in ((ctx or {}).get("market_error"),) if e], "rules": RULES}
