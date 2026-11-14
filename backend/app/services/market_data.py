"""v2.22 live market data (owner, 14 Nov 2026): recorded for the market turn detector and for later tests.

Binance futures blocks the engine's US runners, so the crowd data the models use (data.binance.vision daily files) arrives
about 2 days late. OKX publishes the same kind of numbers live and free (public "rubik" statistics, no key):
  * open interest + trading volume (USD), hourly         /api/v5/rubik/stat/contracts/open-interest-volume
  * taker buy / sell volume (USD, contracts), hourly      /api/v5/rubik/stat/taker-volume
  * long / short account ratio, hourly                   /api/v5/rubik/stat/contracts/long-short-account-ratio
  * recent liquidation orders (USDT swaps)               /api/v5/public/liquidation-orders
plus the total stablecoin supply (DefiLlama, free JSON, daily) - money waiting on the side lines.
ETF flows: no clean free JSON source (the public pages are HTML tables), so they are not recorded.

Everything goes to the engine's own SQLite (tables below); only COMPLETED hourly buckets are stored, each with the time
the engine learned it (`known_at`), so a later test never sees the future. Nothing here writes Firestore and nothing
changes a call. Rate limits: OKX rubik allows 5 requests / 2 s; one run spends at most `BUDGET_S` seconds, walking the
coins in turn (BTC and ETH every run) - each rubik call returns ~ the last few days, so a coin read every few hours
still has every hour.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

from ..db import Database, dumps, loads, now_ms

log = logging.getLogger(__name__)

OKX = "https://www.okx.com"
LLAMA = "https://stablecoins.llama.fi/stablecoincharts/all"
EVERY_MS = 55 * 60_000              # at most one run an hour
BUDGET_S = 35.0                     # seconds per run
PAUSE_S = 0.45                      # between OKX calls (5 per 2 s)
HOUR = 3_600_000
DAY = 86_400_000
ALWAYS = ("BTC", "ETH")
KINDS = ("oi_usd", "vol_usd", "taker_buy", "taker_sell", "ls_ratio")

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS mkt_okx (coin TEXT NOT NULL, kind TEXT NOT NULL, ts BIGINT NOT NULL, value DOUBLE PRECISION, "
    "known_at BIGINT NOT NULL, PRIMARY KEY (coin, kind, ts))",
    "CREATE TABLE IF NOT EXISTS mkt_liq (coin TEXT NOT NULL, ts BIGINT NOT NULL, side TEXT NOT NULL, px DOUBLE PRECISION, "
    "usd DOUBLE PRECISION, known_at BIGINT NOT NULL, PRIMARY KEY (coin, ts, side, px))",
    "CREATE TABLE IF NOT EXISTS mkt_daily (kind TEXT NOT NULL, day BIGINT NOT NULL, value DOUBLE PRECISION, "
    "known_at BIGINT NOT NULL, PRIMARY KEY (kind, day))",
)


def ensure(db: Database) -> None:
    for s in SCHEMA:
        db.execute(s)


def coin_of(symbol: str) -> str:
    return symbol.split("/")[0].upper()


# ---- parsing (pure; unit-tested with fake responses) --------------------------------------------------------------

def _rows(body: Any) -> list:
    if not isinstance(body, dict) or str(body.get("code", "0")) != "0":
        return []
    d = body.get("data")
    return d if isinstance(d, list) else []


def parse_oi_volume(body: Any, now: int) -> list[tuple[str, int, float]]:
    """[[ts, oi_usd, vol_usd], ...] -> (kind, ts, value) of completed hours only."""
    out = []
    for r in _rows(body):
        try:
            ts = int(r[0])
            if ts + HOUR > now:
                continue
            out += [("oi_usd", ts, float(r[1])), ("vol_usd", ts, float(r[2]))]
        except (TypeError, ValueError, IndexError):
            continue
    return out


def parse_taker(body: Any, now: int) -> list[tuple[str, int, float]]:
    """[[ts, sell_vol, buy_vol], ...] (OKX order: sell first) -> completed hours."""
    out = []
    for r in _rows(body):
        try:
            ts = int(r[0])
            if ts + HOUR > now:
                continue
            out += [("taker_sell", ts, float(r[1])), ("taker_buy", ts, float(r[2]))]
        except (TypeError, ValueError, IndexError):
            continue
    return out


def parse_ratio(body: Any, now: int) -> list[tuple[str, int, float]]:
    out = []
    for r in _rows(body):
        try:
            ts = int(r[0])
            if ts + HOUR > now:
                continue
            out.append(("ls_ratio", ts, float(r[1])))
        except (TypeError, ValueError, IndexError):
            continue
    return out


def parse_liquidations(body: Any, ct_val: float | None) -> list[tuple[int, str, float, float]]:
    """Liquidation orders -> (ts, side, bankruptcy price, usd). side 'long' = a long was liquidated (OKX posSide long,
    or one-way side sell). usd = size (contracts) x contract value (coins) x price."""
    out = []
    for blk in _rows(body):
        for d in (blk.get("details") or []) if isinstance(blk, dict) else []:
            try:
                ts, px, sz = int(d["ts"]), float(d["bkPx"]), float(d["sz"])
                pos = (d.get("posSide") or "").lower()
                side = pos if pos in ("long", "short") else ("long" if (d.get("side") or "").lower() == "sell" else "short")
                out.append((ts, side, px, sz * float(ct_val or 1.0) * px))
            except (KeyError, TypeError, ValueError):
                continue
    return out


def parse_stablecoins(body: Any) -> list[tuple[int, float]]:
    """DefiLlama all-chains chart -> (day ms, total circulating USD)."""
    out = []
    for r in body if isinstance(body, list) else []:
        try:
            v = r.get("totalCirculatingUSD") or r.get("totalCirculating") or {}
            usd = float(v.get("peggedUSD")) if isinstance(v, dict) else float(v)
            out.append((int(r["date"]) * 1000, usd))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return out


# ---- fetching -----------------------------------------------------------------------------------------------------

def _get(session: Any, url: str, params: dict | None = None) -> Any:
    import requests
    r = (session or requests).get(url, params=params, timeout=10)
    if getattr(r, "status_code", 200) != 200:
        raise RuntimeError(f"HTTP {getattr(r, 'status_code', '?')}")
    return r.json()


def _store(db: Database, coin: str, rows: list[tuple[str, int, float]], now: int) -> int:
    n = 0
    for kind, ts, v in rows:
        n += db.execute("INSERT INTO mkt_okx (coin, kind, ts, value, known_at) VALUES (?, ?, ?, ?, ?) "
                        "ON CONFLICT (coin, kind, ts) DO NOTHING", (coin, kind, ts, v, now)) or 0
    return n


def _support(db: Database, session: Any, now: int) -> tuple[set[str], dict[str, float]]:
    """Coins OKX publishes statistics for, and USDT-swap contract values; refreshed daily (settings cache)."""
    cache = db.get_setting("mkt_okx_support", None) or {}
    if cache.get("at") and now - int(cache["at"]) < DAY and cache.get("coins"):
        return set(cache["coins"]), dict(cache.get("ct_val") or {})
    coins: set[str] = set()
    try:
        d = (_get(session, f"{OKX}/api/v5/rubik/stat/trading-data/support-coin").get("data") or {})
        coins = {c.upper() for c in (d.get("contract") or [])}
    except Exception as exc:
        log.info("okx support-coin: %s", exc)
    ct: dict[str, float] = {}
    try:
        for r in _get(session, f"{OKX}/api/v5/public/instruments", {"instType": "SWAP"}).get("data") or []:
            if str(r.get("instId", "")).endswith("-USDT-SWAP") and r.get("ctVal"):
                ct[r["instId"].split("-")[0]] = float(r["ctVal"])
    except Exception as exc:
        log.info("okx instruments: %s", exc)
    if coins or ct:
        db.set_setting("mkt_okx_support", {"at": now, "coins": sorted(coins), "ct_val": ct})
    return coins, ct


def run(db: Database, symbols: list[str], session: Any = None, now: int | None = None,
        sleep: Callable[[float], None] = time.sleep, budget_s: float = BUDGET_S) -> dict[str, Any]:
    """Record what is due (hourly). Returns a small status; never raises."""
    now = now or now_ms()
    ensure(db)
    last = int(db.get_setting("mkt_data_last", 0) or 0)
    if now - last < EVERY_MS:
        return {"skipped": "not due"}
    db.set_setting("mkt_data_last", now)
    t0 = time.monotonic()
    support, ct = _support(db, session, now)
    coins = [coin_of(s) for s in symbols if coin_of(s) in support] if support else []
    order = [c for c in ALWAYS if c in coins]
    rest = [c for c in coins if c not in ALWAYS]
    cur = int(db.get_setting("mkt_data_cursor", 0) or 0)
    if rest:
        cur %= len(rest)
        order += rest[cur:] + rest[:cur]
    out: dict[str, Any] = {"coins_due": len(order), "done": [], "rows": 0, "errors": []}
    done_rest = 0
    for c in order:
        if time.monotonic() - t0 > budget_s:
            break
        try:
            rows: list[tuple[str, int, float]] = []
            rows += parse_oi_volume(_get(session, f"{OKX}/api/v5/rubik/stat/contracts/open-interest-volume",
                                         {"ccy": c, "period": "1H"}), now)
            sleep(PAUSE_S)
            rows += parse_taker(_get(session, f"{OKX}/api/v5/rubik/stat/taker-volume",
                                     {"ccy": c, "instType": "CONTRACTS", "period": "1H"}), now)
            sleep(PAUSE_S)
            rows += parse_ratio(_get(session, f"{OKX}/api/v5/rubik/stat/contracts/long-short-account-ratio",
                                     {"ccy": c, "period": "1H"}), now)
            sleep(PAUSE_S)
            out["rows"] += _store(db, c, rows, now)
            liq = parse_liquidations(_get(session, f"{OKX}/api/v5/public/liquidation-orders",
                                          {"instType": "SWAP", "uly": f"{c}-USDT", "state": "filled"}), ct.get(c))
            for ts, side, px, usd in liq:
                db.execute("INSERT INTO mkt_liq (coin, ts, side, px, usd, known_at) VALUES (?, ?, ?, ?, ?, ?) "
                           "ON CONFLICT (coin, ts, side, px) DO NOTHING", (c, ts, side, px, usd, now))
            sleep(PAUSE_S)
            out["done"].append(c)
            if c not in ALWAYS:
                done_rest += 1
        except Exception as exc:
            out["errors"].append(f"{c}: {type(exc).__name__}: {str(exc)[:80]}")
    if rest:
        db.set_setting("mkt_data_cursor", (cur + done_rest) % len(rest))
    # stablecoin supply (daily, one call)
    if now - int(db.get_setting("mkt_stable_last", 0) or 0) >= 6 * HOUR:
        try:
            pts = parse_stablecoins(_get(session, LLAMA))
            for day, usd in pts[-30:]:
                if day + DAY <= now:                      # completed days only
                    db.execute("INSERT INTO mkt_daily (kind, day, value, known_at) VALUES ('stable_usd', ?, ?, ?) "
                               "ON CONFLICT (kind, day) DO NOTHING", (day, usd, now))
            db.set_setting("mkt_stable_last", now)
            out["stablecoin_days"] = len(pts)
        except Exception as exc:
            out["errors"].append(f"stablecoins: {type(exc).__name__}")
    db.set_setting("mkt_data_status", {"at": now, "done": out["done"], "rows": out["rows"], "errors": out["errors"][:5],
                                        "supported": len(coins)})
    return out


# ---- reading (for the detector and later tests) ------------------------------------------------------------------

def series(db: Database, coin: str, kind: str, since: int, until: int | None = None) -> list[tuple[int, float]]:
    """(ts, value) known by `until` (default: everything stored)."""
    ensure(db)
    if until is None:
        rows = db.query("SELECT ts, value FROM mkt_okx WHERE coin = ? AND kind = ? AND ts >= ? ORDER BY ts", (coin, kind, since))
    else:
        rows = db.query("SELECT ts, value FROM mkt_okx WHERE coin = ? AND kind = ? AND ts >= ? AND known_at <= ? ORDER BY ts",
                        (coin, kind, since, until))
    return [(int(r["ts"]), float(r["value"])) for r in rows if r["value"] is not None]


def liquidations(db: Database, coin: str, since: int) -> dict[str, list[tuple[int, float]]]:
    ensure(db)
    out: dict[str, list[tuple[int, float]]] = {"long": [], "short": []}
    for r in db.query("SELECT ts, side, usd FROM mkt_liq WHERE coin = ? AND ts >= ? ORDER BY ts", (coin, since)):
        out.setdefault(r["side"], []).append((int(r["ts"]), float(r["usd"] or 0)))
    return out


def stablecoins(db: Database, days: int = 30) -> list[tuple[int, float]]:
    ensure(db)
    rows = db.query("SELECT day, value FROM mkt_daily WHERE kind = 'stable_usd' ORDER BY day DESC LIMIT ?", (days,))
    return [(int(r["day"]), float(r["value"])) for r in reversed(rows)]


def status(db: Database) -> dict[str, Any]:
    ensure(db)
    st = db.get_setting("mkt_data_status", None) or {}
    n = db.one("SELECT COUNT(*) AS n, MAX(ts) AS last FROM mkt_okx") or {}
    st.update(rows_total=int(n.get("n") or 0), last_hour=n.get("last"))
    return st


__all__ = ["run", "series", "liquidations", "stablecoins", "status", "ensure", "parse_oi_volume", "parse_taker",
           "parse_ratio", "parse_liquidations", "parse_stablecoins", "dumps", "loads"]
