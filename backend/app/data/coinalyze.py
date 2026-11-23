"""v2.80 liquidation history from Coinalyze (owner, 23 Nov 2026; free API key, secret / env COINALYZE_API_KEY - never in
the repo, never printed).

API (https://api.coinalyze.net/v1, key in the `api_key` header, 40 calls a minute, each symbol = one call):
* `future-markets` - every futures market; we use Binance USDT perpetuals (`<BASE>USDT_PERP.A`, 1000-prefixed coins too);
* `liquidation-history?symbols=..&interval=..&from=..&to=..&convert_to_usd=true` - per bar `t` (seconds), `l` long and
  `s` short liquidations in USD.
Coinalyze keeps only 1,500-2,000 points of intraday history (1h ~ 2-3 months, 4h ~ 1 year); daily history is kept. So the
engine stores what it fetches in `derivs` (kinds `liq_long_<iv>`, `liq_short_<iv>`; ts = bar open, ms) and keeps it,
building a longer hourly history over time.
"""
from __future__ import annotations

import os
import time
from typing import Any

import requests

API = "https://api.coinalyze.net/v1"
KEY_ENV = "COINALYZE_API_KEY"
INTERVALS = {"1hour": 3_600_000, "4hour": 14_400_000, "daily": 86_400_000}
PER_MIN = 38                       # stay under the 40 calls / minute limit


def key() -> str | None:
    k = os.environ.get(KEY_ENV, "").strip()
    return k or None


class Client:
    def __init__(self, api_key: str, session: Any = None):
        self.s = session or requests.Session()
        self.s.headers.update({"api_key": api_key, "User-Agent": "crypto-intelligence-ai/2"})
        self.calls: list[float] = []

    def _wait(self, n: int) -> None:
        now = time.time()
        self.calls = [t for t in self.calls if now - t < 60]
        if len(self.calls) + n > PER_MIN:
            time.sleep(max(0.0, 60 - (now - self.calls[0])) + 0.5)
            self.calls = []
        self.calls += [time.time()] * n

    def get(self, path: str, params: dict | None = None, cost: int = 1) -> Any:
        for attempt in range(3):
            self._wait(cost)
            r = self.s.get(f"{API}/{path}", params=params or {}, timeout=30)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After") or 30) + 1)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("rate limited")

    def markets(self) -> dict[str, str]:
        """BASE -> Coinalyze symbol of its Binance USDT perpetual."""
        out: dict[str, str] = {}
        for m in self.get("future-markets") or []:
            sym = str(m.get("symbol") or "")
            if not (m.get("is_perpetual") and sym.endswith("USDT_PERP.A")):
                continue
            base = sym[:-len("USDT_PERP.A")]
            out.setdefault(base[4:] if base.startswith("1000") and len(base) > 4 else base, sym)
            out[base] = sym
        return out

    def liquidations(self, symbols: list[str], interval: str, start_ms: int, end_ms: int) -> dict[str, list[tuple[int, float, float]]]:
        out: dict[str, list[tuple[int, float, float]]] = {}
        for i in range(0, len(symbols), 20):
            chunk = symbols[i:i + 20]
            data = self.get("liquidation-history", {"symbols": ",".join(chunk), "interval": interval,
                                                    "from": int(start_ms // 1000), "to": int(end_ms // 1000),
                                                    "convert_to_usd": "true"}, cost=len(chunk))
            for row in data or []:
                out[row.get("symbol")] = [(int(h["t"]) * 1000, float(h.get("l") or 0), float(h.get("s") or 0))
                                          for h in row.get("history") or []]
        return out


def store(db: Any, symbol: str, interval: str, rows: list[tuple[int, float, float]]) -> int:
    recs = [(symbol, f"liq_long_{interval}", t, l) for t, l, _ in rows] + [(symbol, f"liq_short_{interval}", t, s) for t, _, s in rows]
    if recs:
        db.executemany("INSERT INTO derivs (symbol, kind, ts, value) VALUES (?, ?, ?, ?) "
                       "ON CONFLICT (symbol, kind, ts) DO UPDATE SET value = excluded.value", recs)
    return len(rows)


def sync(db: Any, symbols: list[str], intervals: tuple[str, ...] = ("1hour", "4hour", "daily"), now: int | None = None,
         session: Any = None, budget_s: float = 90, bars: int | None = None) -> dict[str, Any]:
    """Fetch the history Coinalyze still holds for every coin (Binance perpetual) and store it. Safe to repeat: rows are
    upserted. Returns counts only (no key, no values)."""
    k = key()
    if not k:
        return {"skipped": "no COINALYZE_API_KEY"}
    t0 = time.time()
    now = now or int(time.time() * 1000)
    c = Client(k, session)
    try:
        mk = c.markets()
    except Exception as exc:
        return {"error": f"markets: {type(exc).__name__}"}
    pairs = [(s, mk.get(s.split("/")[0].upper())) for s in symbols]
    have = [(s, cz) for s, cz in pairs if cz]
    out: dict[str, Any] = {"coins": len(have), "missing": [s for s, cz in pairs if not cz], "rows": {}}
    for iv in intervals:
        if time.time() - t0 > budget_s:
            out["stopped"] = "time budget"
            break
        span = INTERVALS[iv] * (bars or (2000 if iv != "daily" else 1500))
        try:
            got = c.liquidations([cz for _, cz in have], iv, now - span, now)
        except Exception as exc:
            out.setdefault("errors", []).append(f"{iv}: {type(exc).__name__}")
            continue
        n = 0
        for s, cz in have:
            n += store(db, s, iv, got.get(cz) or [])
        out["rows"][iv] = n
    return out


EVERY_MS = 3_600_000
DONE = "coinalyze_full_at"


def hourly(db: Any, symbols: list[str], now: int | None = None) -> dict[str, Any]:
    """Engine step: once a day the whole history Coinalyze still holds (1h / 4h / daily), otherwise the last 48 hours
    of 1h bars - so the stored hourly history grows past Coinalyze's 2-3 months. Nothing without the key."""
    if not key():
        return {"skipped": "no key"}
    now = now or int(time.time() * 1000)
    if now - int(db.get_setting(DONE, 0) or 0) >= 86_400_000:
        out = sync(db, symbols, now=now, budget_s=120)
        if not out.get("errors") and not out.get("error"):
            db.set_setting(DONE, now)
        return out
    return sync(db, symbols, intervals=("1hour",), now=now, budget_s=30, bars=48)
