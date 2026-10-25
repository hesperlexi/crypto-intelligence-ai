"""Process-wide runtime: providers, candle store, live feed, caches, watchlist, user settings."""
from __future__ import annotations

import logging
import time
from typing import Any

from ..config import DEFAULT_SIGNAL_WEIGHTS, settings
from ..data.base import closed_only, truncate_as_of
from ..data.store import CandleStore
from ..db import Database, get_db, now_ms
from ..engine.risk import RiskProfile
from ..features.dataset import Dataset, Frame, InsufficientData, build_frame, make_dataset

log = logging.getLogger(__name__)
USER = "local"   # single local user; the schema already carries user_id for multi-user deployments


class Runtime:
    def __init__(self, db: Database | None = None, provider: Any = None):
        self.db = db or get_db()
        self.store = CandleStore(self.db)
        self.provider = provider
        self.derivatives: Any = None
        self.feed: Any = None
        self.started_ms = now_ms()
        self._frames: dict[tuple[str, str], tuple[int, int, Frame]] = {}
        self._datasets: dict[tuple, tuple] = {}
        self._derivs: dict[str, tuple[float, Any]] = {}
        self.analysis_cache: dict[tuple, tuple[float, dict[str, Any]]] = {}
        self.order_books: dict[str, tuple[float, dict[str, Any]]] = {}
        self.derivs_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.context_cache: tuple[float, dict[str, Any]] | None = None
        self.training: dict[str, dict[str, Any]] = {}       # "SYMBOL|tf" -> status
        self.errors: list[dict[str, Any]] = []
        self.clock_skew_ms: int | None = None
        self.funding_rates: dict[str, dict[str, Any]] = {}     # perpetual funding per symbol (engine only)
        self._seed()

    # -- bootstrap ------------------------------------------------------------------------------------
    def _seed(self) -> None:
        if not self.db.one("SELECT id FROM users WHERE id = ?", (USER,)):
            self.db.execute("INSERT INTO users (id, name, created_at) VALUES (?, ?, ?)", (USER, "Local user", now_ms()))
            for s in settings.symbols:
                self.add_symbol(s)

    @property
    def exchange(self) -> str:
        return getattr(self.provider, "name", settings.exchange)

    def record_error(self, where: str, exc: Exception) -> None:
        self.errors.append({"ts": now_ms(), "where": where, "error": f"{type(exc).__name__}: {exc}"[:300]})
        del self.errors[:-100]

    # -- watchlist ------------------------------------------------------------------------------------
    def watchlist(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT symbol, pinned, added_at FROM watchlists WHERE user_id = ? "
                             "ORDER BY pinned DESC, added_at", (USER,))

    def symbols(self) -> list[str]:
        return [r["symbol"] for r in self.watchlist()]

    def add_symbol(self, symbol: str) -> None:
        self.db.execute("INSERT INTO watchlists (user_id, symbol, pinned, added_at) VALUES (?, ?, 0, ?) "
                        "ON CONFLICT (user_id, symbol) DO NOTHING", (USER, symbol.upper(), now_ms()))
        if self.feed is not None:
            self.feed.set_symbols(self.symbols())

    def remove_symbol(self, symbol: str) -> None:
        self.db.execute("DELETE FROM watchlists WHERE user_id = ? AND symbol = ?", (USER, symbol.upper()))
        if self.feed is not None:
            self.feed.set_symbols(self.symbols())

    def pin_symbol(self, symbol: str, pinned: bool) -> None:
        self.db.execute("UPDATE watchlists SET pinned = ? WHERE user_id = ? AND symbol = ?",
                        (int(pinned), USER, symbol.upper()))

    # -- user settings --------------------------------------------------------------------------------
    def signal_weights(self) -> dict[str, float]:
        return {**DEFAULT_SIGNAL_WEIGHTS, **(self.db.get_setting("signal_weights", {}) or {})}

    def risk_profile(self) -> RiskProfile:
        return RiskProfile.from_dict(self.db.get_setting("risk_profile", {}))

    def refresh_seconds(self) -> int:
        return int(self.db.get_setting("forecast_refresh_s", settings.forecast_refresh_s))

    # -- market data ----------------------------------------------------------------------------------
    def candles(self, symbol: str, timeframe: str, as_of: int | None = None, include_forming: bool = False):
        df = self.store.load(self.exchange, symbol, timeframe)
        if as_of is not None:
            return truncate_as_of(df, timeframe, as_of)
        return df if include_forming else closed_only(df, timeframe)

    def frame(self, symbol: str, timeframe: str, as_of: int | None = None) -> Frame:
        """Analysis frame on CLOSED candles. Cached until a new candle closes. Raises InsufficientData."""
        df = self.candles(symbol, timeframe, as_of)
        if df.empty:
            raise InsufficientData(f"no {timeframe} candles stored for {symbol}")
        if as_of is not None:
            return build_frame(df, timeframe)
        key = (symbol, timeframe)
        sig = (int(df["ts"].iloc[-1]), len(df))
        hit = self._frames.get(key)
        if hit and (hit[0], hit[1]) == sig:
            return hit[2]
        fr = build_frame(df, timeframe)
        self._frames[key] = (sig[0], sig[1], fr)
        return fr

    def dataset(self, symbol: str, timeframe: str, with_btc: bool, as_of: int | None = None,
                htf_tf: str | None = None) -> Dataset:
        fr = self.frame(symbol, timeframe, as_of)
        btc = None
        if with_btc and not symbol.startswith("BTC/"):
            btc = self.frame("BTC/USDT", timeframe, as_of)
        htf = self.frame(symbol, htf_tf, as_of) if htf_tf else None
        # futures-positioning columns are always built (zeros when no data); each model version uses only
        # the columns it was trained with, so versions with and without them work side by side
        deriv = self.deriv_frame(symbol)
        if as_of is not None:
            return make_dataset(fr, btc, htf=htf, deriv=deriv)
        key = (symbol, timeframe, with_btc, htf_tf)
        ts = int(fr.df["ts"].iloc[-1])
        dts = int(deriv["ts"].iloc[-1]) if len(deriv) else 0
        hit = self._datasets.get(key)
        if hit and hit[0] == ts and hit[3] == dts and (htf is None or hit[2] == int(htf.df["ts"].iloc[-1])):
            return hit[1]
        ds = make_dataset(fr, btc, htf=htf, deriv=deriv)
        self._datasets[key] = (ts, ds, int(htf.df["ts"].iloc[-1]) if htf is not None else None, dts)
        return ds

    def deriv_frame(self, symbol: str):
        """Hourly funding / premium history (data.derivs), cached for 10 minutes."""
        from ..data import derivs

        hit = self._derivs.get(symbol)
        if hit and time.time() - hit[0] < 600:
            return hit[1]
        try:
            df = derivs.load(self.db, symbol)
        except Exception:                      # older database without the table
            import pandas as pd
            df = pd.DataFrame(columns=["ts", "funding", "premium"])
        self._derivs[symbol] = (time.time(), df)
        return df

    def live_price(self, symbol: str) -> float | None:
        t = self.feed.tickers.get(symbol) if self.feed is not None else None
        if t and t.get("last"):
            return float(t["last"])
        return None

    def ticker(self, symbol: str) -> dict[str, Any] | None:
        return self.feed.tickers.get(symbol) if self.feed is not None else None

    def uptime_s(self) -> float:
        return (now_ms() - self.started_ms) / 1000


_runtime: Runtime | None = None


def get_runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        _runtime = Runtime()
    return _runtime


def set_runtime(rt: Runtime | None) -> None:
    global _runtime
    _runtime = rt


def ttl_get(cache: dict, key: Any, ttl: float) -> Any:
    hit = cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    return None
