"""Market-data orchestration: candle sync, order books, derivatives, external context (dominance, sentiment)."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ..config import MODEL_TIMEFRAMES, MTF_TIMEFRAMES, settings
from ..data.base import tf_ms
from ..features.liquidity import oi_price_state, trade_flow
from .runtime import Runtime, ttl_get

log = logging.getLogger(__name__)
CORE_TIMEFRAMES = list(dict.fromkeys(MTF_TIMEFRAMES + MODEL_TIMEFRAMES))   # kept in sync continuously


def make_provider(exchange: str | None = None) -> Any:
    """`EXCHANGE=csv` reads real exported candles from CSV_DIR; anything else is a CCXT exchange id."""
    exchange = exchange or settings.exchange
    if exchange in ("binance_public", "binance-public"):
        from ..data.binance_public import BinancePublicProvider

        return BinancePublicProvider()
    if exchange == "csv":
        from ..data.csv_provider import CSVProvider

        return CSVProvider(settings.csv_dir)
    from ..data.ccxt_provider import CCXTProvider

    return CCXTProvider(exchange)


async def sync_symbol(rt: Runtime, symbol: str, timeframes: list[str] | None = None, force: bool = False) -> dict[str, Any]:
    """Fetch candles that are new since the last sync. A timeframe is skipped until its next candle is due."""
    out: dict[str, Any] = {}
    now = int(time.time() * 1000)
    for tf in timeframes or CORE_TIMEFRAMES:
        last = rt.store.last_ts(rt.exchange, symbol, tf)
        # stored `last` may be a forming candle; a refresh is due once it should have closed
        if not force and last is not None and now < last + tf_ms(tf) and tf_ms(tf) > 3_600_000:
            continue
        try:
            out[tf] = await rt.store.sync(rt.provider, symbol, tf)
        except Exception as exc:  # API failure for one series must not stop the others
            rt.record_error(f"sync {symbol} {tf}", exc)
            out[tf] = f"error: {type(exc).__name__}"
    return out


async def sync_all(rt: Runtime, timeframes: list[str] | None = None) -> None:
    watched = rt.symbols()
    for symbol in watched:
        await sync_symbol(rt, symbol, timeframes)
    # a coin taken off the watchlist can still have OPEN signals: keep its candles coming on those timeframes only, so
    # the signals are followed to their real end (28 Oct 2026: LINK / SUI calls stayed "open" after testing mode)
    try:
        rows = rt.db.query("SELECT DISTINCT symbol, timeframe FROM signals WHERE status = 'OPEN' "
                           "UNION SELECT DISTINCT symbol, timeframe FROM shadow_signals WHERE status = 'OPEN'")
    except Exception:
        rows = []
    orphans: dict[str, list[str]] = {}
    for r in rows:
        if r["symbol"] not in watched:
            orphans.setdefault(r["symbol"], []).append(r["timeframe"])
    for symbol, tfs in orphans.items():
        try:
            await sync_symbol(rt, symbol, sorted(set(tfs)))
        except Exception as exc:
            rt.record_error(f"candles {symbol} (open signals)", exc)


async def refresh_order_book(rt: Runtime, symbol: str) -> dict[str, Any] | None:
    try:
        book = await rt.provider.fetch_order_book(symbol, 200)
    except Exception as exc:
        rt.record_error(f"order book {symbol}", exc)
        return None
    if book.get("bids") and book.get("asks"):
        rt.order_books[symbol] = (time.time(), book)
        return book
    return None


async def recent_trade_flow(rt: Runtime, symbol: str) -> dict[str, Any] | None:
    try:
        return trade_flow(await rt.provider.fetch_trades(symbol, 500))
    except Exception as exc:
        rt.record_error(f"trades {symbol}", exc)
        return None


async def derivatives_snapshot(rt: Runtime, symbol: str) -> dict[str, Any]:
    """Funding rate and open-interest change, with the price/OI quadrant interpretation."""
    hit = ttl_get(rt.derivs_cache, symbol, 300)
    if hit is not None:
        return hit
    if rt.derivatives is None:
        return {"available": False, "reason": "no derivatives venue configured (DERIVATIVES_EXCHANGE)"}
    out: dict[str, Any] = {"available": True, "venue": rt.derivatives.name}
    try:
        out["funding"] = await rt.derivatives.funding_rate(symbol)
    except Exception as exc:
        out["funding"], out["funding_error"] = None, f"{type(exc).__name__}: {exc}"[:160]
    try:
        hist = [h for h in await rt.derivatives.open_interest_history(symbol, "1h", 25) if h.get("oi")]
        if len(hist) >= 2:
            oi_ch = hist[-1]["oi"] / hist[0]["oi"] - 1
            df = rt.candles(symbol, "1h")
            window = df[df["ts"] >= hist[0]["ts"]]
            px_ch = float(window["close"].iloc[-1] / window["open"].iloc[0] - 1) if len(window) else None
            out["open_interest"] = {"latest": hist[-1]["oi"], "change": oi_ch, "hours": len(hist) - 1,
                                    "history": hist}
            if px_ch is not None:
                out["oi_price"] = oi_price_state(px_ch, oi_ch)
        else:
            out["open_interest"] = None
    except Exception as exc:
        out["open_interest"], out["oi_error"] = None, f"{type(exc).__name__}: {exc}"[:160]
    out["liquidations"] = {"available": False, "reason": "liquidation feeds need a dedicated (usually paid) data source"}
    if out.get("funding") is None and out.get("open_interest") is None:
        out["available"] = False
        out["reason"] = out.get("funding_error") or out.get("oi_error") or "venue returned no data for this symbol"
    rt.derivs_cache[symbol] = (time.time(), out)
    return out


async def external_context(rt: Runtime) -> dict[str, Any]:
    """BTC dominance / total market cap / stablecoin share (CoinGecko, no key) and the Fear & Greed index
    (alternative.me, no key). Each block is independent; failures are reported, never filled in."""
    if rt.context_cache and time.time() - rt.context_cache[0] < 600:
        return rt.context_cache[1]
    out: dict[str, Any] = {"enabled": settings.enable_external_context, "fetched_at": int(time.time() * 1000)}
    if not settings.enable_external_context:
        out["reason"] = "disabled (ENABLE_EXTERNAL_CONTEXT=false)"
        return out
    try:
        import httpx
    except ImportError:
        out.update(enabled=False, reason="python package 'httpx' is not installed")
        return out
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            g = (await client.get("https://api.coingecko.com/api/v3/global")).json()["data"]
            dom = g["market_cap_percentage"]
            out["market"] = {
                "source": "CoinGecko", "total_market_cap_usd": g["total_market_cap"]["usd"],
                "total_volume_usd": g["total_volume"]["usd"],
                "market_cap_change_24h_pct": g.get("market_cap_change_percentage_24h_usd"),
                "btc_dominance": dom.get("btc"), "eth_dominance": dom.get("eth"),
                "stablecoin_share": sum(dom.get(k, 0.0) for k in ("usdt", "usdc", "dai", "usde", "fdusd")),
            }
        except Exception as exc:
            out["market"] = None
            out["market_error"] = f"{type(exc).__name__}: {exc}"[:160]
        try:
            fg = (await client.get("https://api.alternative.me/fng/?limit=30")).json()["data"]
            vals = [int(d["value"]) for d in fg]
            now_v = vals[0]
            out["sentiment"] = {
                "source": "alternative.me Fear & Greed", "value": now_v, "label": fg[0]["value_classification"],
                "change_7d": now_v - vals[7] if len(vals) > 7 else None,
                "history": [{"ts": int(d["timestamp"]) * 1000, "value": int(d["value"])} for d in fg][::-1],
                "state": "EXTREME FEAR" if now_v <= 20 else "EXTREME GREED" if now_v >= 80 else
                         "FEAR" if now_v < 45 else "GREED" if now_v > 55 else "NEUTRAL",
            }
        except Exception as exc:
            out["sentiment"] = None
            out["sentiment_error"] = f"{type(exc).__name__}: {exc}"[:160]
    # price / sentiment divergence on BTC over the same 7 days
    s = out.get("sentiment")
    try:
        d1 = rt.candles("BTC/USDT", "1d")
        if s and s.get("change_7d") is not None and len(d1) > 8:
            px7 = float(d1["close"].iloc[-1] / d1["close"].iloc[-8] - 1)
            s["btc_change_7d"] = px7
            if px7 > 0.01 and s["change_7d"] <= -8:
                s["divergence"] = "Price rose while sentiment fell: price/sentiment divergence"
            elif px7 < -0.01 and s["change_7d"] >= 8:
                s["divergence"] = "Price fell while sentiment improved: price/sentiment divergence"
            else:
                s["divergence"] = None
    except Exception:
        pass
    out["not_included"] = ["crypto news headlines", "social-media sentiment", "search trends",
                           "historical BTC dominance / stablecoin flows (needed before they could be model features)"]
    out["note"] = ("Context only. These series are not model features because free historical data to backtest them "
                   "is not available; sentiment never overrides price data.")
    rt.context_cache = (time.time(), out)
    return out


async def clock_skew(rt: Runtime) -> int | None:
    try:
        t0 = time.time()
        server = await rt.provider.server_time()
        if server is None:
            return None
        rtt = time.time() - t0
        rt.clock_skew_ms = int(server - (t0 + rtt / 2) * 1000)
        return rt.clock_skew_ms
    except Exception:
        return None


async def gather_limited(coros: list, limit: int = 4) -> list:
    sem = asyncio.Semaphore(limit)

    async def run(c):
        async with sem:
            return await c

    return await asyncio.gather(*(run(c) for c in coros), return_exceptions=True)


FUNDING_HOSTS = ("https://fapi.binance.com",)


def funding_rates(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Current perpetual funding rate per symbol from Binance USDT-M futures (public, no key).

    Binance blocks its futures API for some server locations (e.g. US cloud runners). Then nothing is
    returned and callers fall back to the documented base rate, labelled as an assumption."""
    import requests

    want = {s.replace("/", "").upper(): s for s in symbols}
    for host in FUNDING_HOSTS:
        try:
            r = requests.get(f"{host}/fapi/v1/premiumIndex", timeout=8)
            if r.status_code != 200:
                continue
            out = {}
            for row in r.json():
                s = want.get(row.get("symbol"))
                if s and row.get("lastFundingRate") not in (None, ""):
                    out[s] = {"rate": float(row["lastFundingRate"]), "mark": float(row.get("markPrice") or 0) or None,
                              "next_funding_ms": int(row.get("nextFundingTime") or 0) or None, "source": "Binance futures"}
            return out
        except Exception:
            continue
    return okx_funding(symbols)


def okx_funding(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Fallback when Binance futures are blocked: OKX USDT perpetuals (8-hour funding, same convention)."""
    import requests

    out: dict[str, dict[str, Any]] = {}
    for s in symbols:
        inst = f"{s.split('/')[0].upper()}-USDT-SWAP"
        try:
            r = requests.get("https://www.okx.com/api/v5/public/funding-rate", params={"instId": inst}, timeout=8)
            d = (r.json().get("data") or [None])[0] if r.status_code == 200 else None
        except Exception:
            continue
        if d and d.get("fundingRate") not in (None, ""):
            out[s] = {"rate": float(d["fundingRate"]), "mark": None,
                      "next_funding_ms": int(d.get("fundingTime") or d.get("nextFundingTime") or 0) or None, "source": "OKX perpetual"}
    return out
