"""v2.49 futures-only coins (owner, 17 Nov 2026: "we want to have it on signals" for MSTR/USDT).

MSTR/USDT (Strategy Inc. stock perpetual) trades 24/7 on Binance USDⓈ-M and MEXC futures but has no Binance spot market,
and Binance futures is geo-blocked on the engine's US runners. Its candles, ticker, order book and trades come from MEXC
futures (contract MSTRSTOCK_USDT, public REST, no key; checked from the runner 17 Nov 2026), returned in the same shape as
the Binance spot provider, so the rest of the engine (store, models, record, bots) treats it like any other coin.
MEXC has no 12h / 3d candles: they are built from 4h / 1d candles (12h aligned to 00:00 / 12:00 UTC, 3d to whole 3-day
blocks since 1970, like Binance). Prices can differ from Binance's MSTRUSDT by a few cents.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import requests

from ..redact import redact

FUT_ONLY: dict[str, str] = {"MSTR/USDT": "MSTRSTOCK_USDT",       # app symbol -> MEXC contract
                            "ANTHROPIC/USDT": "ANTHROPIC_USDT",  # v2.65 Anthropic pre-IPO perpetual (MEXC since 14 Apr 2026)
                            "XAG/USDT": "SILVER_USDT"}           # v2.69 silver perpetual (MEXC since 29 Dec 2025), watch only
MEXC = "https://contract.mexc.com/api/v1/contract"
NATIVE = {"1m": "Min1", "5m": "Min5", "15m": "Min15", "30m": "Min30", "1h": "Min60", "4h": "Hour4", "1d": "Day1",
          "1w": "Week1"}
BUILT = {"12h": ("4h", 3), "3d": ("1d", 3)}                       # timeframe -> (source timeframe, candles per bar)
STEP_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000,
           "12h": 43_200_000, "1d": 86_400_000, "3d": 259_200_000, "1w": 604_800_000}
WINDOW = 1000                    # candles asked per request (MEXC answers up to 2000)


EXTRA_KEY = "fut_only_extra"       # v2.72: coins added from the website that have no Binance spot market {symbol: contract}


def load_extra(get_setting) -> dict[str, str]:
    """v2.72: futures-only coins the admin added (setting EXTRA_KEY) join FUT_ONLY in this process."""
    try:
        extra = get_setting(EXTRA_KEY, None) or {}
    except Exception:
        return {}
    for sym, contract in extra.items():
        if isinstance(sym, str) and isinstance(contract, str) and sym.upper() not in FUT_ONLY:
            FUT_ONLY[sym.upper()] = contract
    return extra


def mexc_contract_for(symbol: str, session: Any = None, timeout: float = 15.0) -> str | None:
    """v2.72: the MEXC USDT perpetual for a coin with no Binance spot market ('HYPE/USDT' -> 'HYPE_USDT'), or None."""
    base_ = symbol.upper().split("/")[0]
    want = f"{base_}_USDT"
    try:
        r = (session or requests).get(f"{MEXC}/detail", params={"symbol": want}, timeout=timeout)
        j = r.json()
        d = j.get("data") if isinstance(j, dict) and j.get("success") else None
        if isinstance(d, dict) and d.get("symbol") == want and int(d.get("state") or 0) == 0:
            return want
    except Exception:
        return None
    return None


def is_fut_only(symbol: str) -> bool:
    return symbol.upper() in FUT_ONLY


def mexc_rows(data: dict[str, Any], size: float) -> list[list[float]]:
    """MEXC column arrays -> [[open ms, o, h, l, c, base volume]] (volume in contracts x contract size)."""
    t = data.get("time") or []
    o, h, l, c, v = (data.get(k) or [] for k in ("open", "high", "low", "close", "vol"))
    # v2.69: thin MEXC contracts (ANTHROPIC ~9% of 15m bars) report a high below the open/close or a low above it;
    # the high / low are widened to cover the open and close, as exchanges' own candles always do
    out = []
    for i in range(min(len(t), len(o), len(h), len(l), len(c), len(v))):
        oo, hh, ll, cc = float(o[i]), float(h[i]), float(l[i]), float(c[i])
        out.append([int(t[i]) * 1000, oo, max(hh, oo, cc), min(ll, oo, cc), cc, max(float(v[i]), 0.0) * size])
    return out


def aggregate(rows: list[list[float]], step: int, n: int, now: int | None = None) -> list[list[float]]:
    """Group source candles into bars of `step` ms aligned to the epoch; a bar needs all n parts unless it is still
    forming (its end is after `now`)."""
    now = now if now is not None else now_ms()
    groups: dict[int, list[list[float]]] = {}
    for r in sorted(rows, key=lambda r: r[0]):
        groups.setdefault(int(r[0]) // step * step, []).append(r)
    out = []
    for k in sorted(groups):
        g = groups[k]
        if len(g) < n and k + step <= now:
            continue
        out.append([k, g[0][1], max(x[2] for x in g), min(x[3] for x in g), g[-1][4], sum(x[5] for x in g)])
    return out


class MexcFutures:
    """Public MEXC futures REST for the coins in FUT_ONLY, in the Binance spot provider's return shapes."""

    def __init__(self, session: Any = None, timeout: float = 15.0):
        self.session = session or requests.Session()
        self.timeout = timeout
        self._size: dict[str, float] = {}

    def _get_sync(self, path: str, params: dict[str, Any] | None = None) -> Any:
        last: Exception | None = None
        for attempt in range(3):
            try:
                r = self.session.get(f"{MEXC}/{path}", params=params, timeout=self.timeout)
            except Exception as exc:
                last = exc
                time.sleep(1 + attempt)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                last = RuntimeError(f"MEXC answered HTTP {r.status_code}")
                time.sleep(2 ** attempt)
                continue
            j = r.json()
            if not isinstance(j, dict) or not j.get("success"):
                raise ValueError(redact(f"MEXC {path}: {str(j)[:150]}"))
            return j.get("data")
        raise ConnectionError(redact(f"MEXC {path}: {type(last).__name__}: {last}")[:300])

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await asyncio.to_thread(self._get_sync, path, params)

    async def size(self, symbol: str) -> float:
        c = FUT_ONLY[symbol.upper()]
        if c not in self._size:
            d = await self._get(f"detail?symbol={c}")
            self._size[c] = float((d or {}).get("contractSize") or 1.0)
        return self._size[c]

    async def _native(self, symbol: str, tf: str, start_ms: int, end_ms: int) -> list[list[float]]:
        # MEXC fills a window that reaches past now with flat made-up candles dated in the future (probe 17 Nov 2026):
        # never ask past now, and drop any candle that opens after now
        now = now_ms()
        end_ms = min(end_ms, now)
        if end_ms < start_ms:
            return []
        d = await self._get(f"kline/{FUT_ONLY[symbol.upper()]}",
                            {"interval": NATIVE[tf], "start": start_ms // 1000, "end": end_ms // 1000})
        return [r for r in mexc_rows(d or {}, await self.size(symbol)) if r[0] <= now]

    async def fetch_ohlcv(self, symbol: str, timeframe: str, since: int | None = None,
                          limit: int = 1000) -> list[list[float]]:
        """Like Binance klines: up to `limit` candles opening at or after `since` (the newest ones when no `since`).
        Before the listing date the first windows are empty: they are skipped forward until data appears."""
        now = int(time.time() * 1000)
        tf, n = BUILT.get(timeframe, (timeframe, 1))
        if tf not in NATIVE:
            raise ValueError(f"unsupported timeframe {timeframe}")
        step, src = STEP_MS[timeframe], STEP_MS[tf]
        limit = max(1, min(int(limit), 1000))
        want = min(limit * n, WINDOW // n * n)
        if since is None:
            start = (now - want * src) // step * step
        else:
            start = int(since) // step * step
        rows: list[list[float]] = []
        for _ in range(40):                                   # skip empty windows before the listing
            if start > now:
                break
            end = start + want * src
            rows = await self._native(symbol, tf, start, end - 1)
            if rows:
                break
            start = end
        if n > 1:
            rows = aggregate(rows, step, n, now)
        if since is not None:
            rows = [r for r in rows if r[0] >= int(since) // step * step]
        return rows[-limit:] if since is None else rows[:limit]

    async def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        t = await self._get("ticker", {"symbol": FUT_ONLY[symbol.upper()]})
        last = float(t["lastPrice"])
        bid, ask = float(t.get("bid1") or 0) or None, float(t.get("ask1") or 0) or None
        spread = (ask - bid) if bid and ask else None
        size = await self.size(symbol)
        return {"symbol": symbol, "last": last, "bid": bid, "ask": ask, "spread": spread,
                "spread_bps": spread / last * 1e4 if spread is not None and last else None,
                "change_pct": float(t.get("riseFallRate") or 0) * 100, "high": float(t.get("high24Price") or last),
                "low": float(t.get("lower24Price") or last), "base_volume": float(t.get("volume24") or 0) * size,
                "quote_volume": float(t.get("amount24") or 0), "ts": int(t.get("timestamp") or now_ms())}

    async def fetch_order_book(self, symbol: str, limit: int = 100) -> dict[str, Any]:
        d = await self._get(f"depth/{FUT_ONLY[symbol.upper()]}", {"limit": min(int(limit), 200)})
        size = await self.size(symbol)
        return {"bids": [[float(r[0]), float(r[1]) * size] for r in (d or {}).get("bids", [])],
                "asks": [[float(r[0]), float(r[1]) * size] for r in (d or {}).get("asks", [])], "timestamp": None}

    async def fetch_trades(self, symbol: str, limit: int = 200) -> list[dict[str, Any]]:
        d = await self._get(f"deals/{FUT_ONLY[symbol.upper()]}", {"limit": min(int(limit), 100)})
        size = await self.size(symbol)
        rows = d if isinstance(d, list) else (d or {}).get("resultList") or []
        return sorted(({"ts": int(r["t"]), "price": float(r["p"]), "amount": float(r["v"]) * size,
                        "side": "buy" if int(r.get("T", 1)) == 1 else "sell"} for r in rows), key=lambda x: x["ts"])

    def last_price_sync(self, symbol: str) -> float | None:
        try:
            return float(self._get_sync("ticker", {"symbol": FUT_ONLY[symbol.upper()]})["lastPrice"])
        except Exception:
            return None


def now_ms() -> int:
    return int(time.time() * 1000)
