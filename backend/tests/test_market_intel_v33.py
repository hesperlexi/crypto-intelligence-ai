"""V3.3 Stage 2 phase B: market intelligence context - data status on every field, no look-ahead, never an entry rule."""
from pathlib import Path

import numpy as np
import pandas as pd

from app.db import Database
from app.services import market_intel as MI

H = 3_600_000
NOW = 1_795_700_000_000 // H * H


def _candles(n, step, trend=0.001, seed=0, end_close=NOW):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(trend, 0.004, n)))
    ts = end_close - step * np.arange(n, 0, -1)
    return pd.DataFrame({"ts": ts, "open": c, "high": c * 1.003, "low": c * 0.997, "close": c, "volume": 1.0})


class RT:
    def __init__(self, frames=None, tickers=None, symbols=()):
        self.frames = frames or {}
        self.tickers = tickers or {}
        self.db = Database("sqlite:///:memory:")
        self._symbols = list(symbols)

    def candles(self, s, tf):
        return self.frames.get((s, tf))

    def ticker(self, s):
        return self.tickers.get(s)

    def symbols(self):
        return self._symbols


def test_field_shape_and_unavailable_has_no_value():
    f = MI.field(1.5, "confirmed", NOW - H, "x", NOW)
    assert f == {"value": 1.5, "status": "confirmed", "as_of": NOW - H, "age_h": 1.0, "source": "x"}
    assert MI.field(9, "unavailable", None, "x", NOW)["value"] is None


def test_btc_trend_uses_closed_candles_only():
    df = _candles(200, 4 * H, trend=0.002)
    rt = RT({("BTC/USDT", "4h"): df})
    base = MI.btc_trend(rt, "4h", NOW)
    assert base["status"] == "confirmed" and base["value"] == "up"
    forming = df.iloc[[-1]].copy()
    forming["ts"] = NOW
    forming[["open", "high", "low", "close"]] = 1.0                   # a crash in the still-forming candle
    rt.frames[("BTC/USDT", "4h")] = pd.concat([df, forming], ignore_index=True)
    assert MI.btc_trend(rt, "4h", NOW)["value"] == base["value"]      # not seen before it closes


def test_stale_candles_are_marked_delayed():
    rt = RT({("BTC/USDT", "4h"): _candles(200, 4 * H, end_close=NOW - 24 * H)})
    assert MI.btc_trend(rt, "4h", NOW)["status"] == "delayed"
    assert MI.btc_trend(RT(), "4h", NOW)["status"] == "unavailable"


def test_volatility_label():
    rt = RT({("BTC/USDT", "4h"): _candles(200, 4 * H), ("BTC/USDT", "1h"): _candles(60, H)})
    v = MI.btc_volatility(rt, NOW)
    assert v["status"] == "confirmed" and v["value"] in ("normal", "low", "high", "extreme") and v["atr_ratio"] > 0


def test_breadth_counts_only_fresh_coins():
    syms = [f"C{i}/USDT" for i in range(6)]
    frames = {(s, "4h"): _candles(120, 4 * H, trend=0.003 if i < 4 else -0.003, seed=i) for i, s in enumerate(syms)}
    b = MI.breadth(RT(frames, symbols=syms), syms, NOW)
    assert b["status"] == "confirmed" and b["coins"] == 6 and b["above"] == 4
    frames = {(s, "4h"): _candles(120, 4 * H, end_close=NOW - 48 * H) for s in syms}
    assert MI.breadth(RT(frames), syms, NOW)["status"] == "unavailable"


def test_funding_freshness():
    rt = RT()
    rt.db.execute("INSERT INTO derivs (symbol, kind, ts, value) VALUES ('X/USDT', 'funding_1h', ?, 0.0001)", (NOW - H,))
    f = MI.funding(rt, "X/USDT", NOW)
    assert f["status"] == "confirmed" and abs(f["value"] - 0.08) < 1e-9
    assert MI.funding(rt, "X/USDT", NOW + 10 * H)["status"] == "delayed"
    assert MI.funding(rt, "X/USDT", NOW + 30 * H)["status"] == "unavailable"
    assert MI.funding(rt, "Y/USDT", NOW)["status"] == "unavailable"


def test_open_interest_has_no_look_ahead():
    from app.services import market_data
    rt = RT()
    for sql in market_data.DDL if hasattr(market_data, "DDL") else []:
        rt.db.execute(sql)
    rt.db.execute("CREATE TABLE IF NOT EXISTS mkt_okx (coin TEXT NOT NULL, kind TEXT NOT NULL, ts BIGINT NOT NULL, "
                  "value DOUBLE PRECISION, known_at BIGINT NOT NULL, PRIMARY KEY (coin, kind, ts))")
    rt.db.execute("INSERT INTO mkt_okx VALUES ('X', 'oi_usd', ?, 5e6, ?)", (NOW - 2 * H, NOW + H))   # known only later
    rt.db.execute("INSERT INTO derivs (symbol, kind, ts, value) VALUES ('X/USDT', 'oi_1h', ?, 4e6)", (NOW - 3 * 24 * H,))
    rt.db.execute("INSERT INTO derivs (symbol, kind, ts, value) VALUES ('X/USDT', 'oi_1h', ?, 9e9)", (NOW - H,))
    oi = MI.open_interest(rt, "X/USDT", NOW)
    assert oi["status"] == "delayed" and oi["value"] == 4e6 and "2 days late" in oi["source"]   # the 9e9 is not public yet
    rt.db.execute("INSERT INTO mkt_okx VALUES ('X', 'oi_usd', ?, 6e6, ?)", (NOW - H, NOW - H + 60_000))
    rt.db.execute("INSERT INTO mkt_okx VALUES ('X', 'oi_usd', ?, 5e6, ?)", (NOW - 25 * H, NOW - 25 * H + 60_000))
    oi = MI.open_interest(rt, "X/USDT", NOW)
    assert oi["status"] == "confirmed" and oi["value"] == 6e6 and oi["change_24h_pct"] == 20.0


def test_liquidations_only_closed_bars():
    rt = RT()
    rt.db.execute("INSERT INTO derivs (symbol, kind, ts, value) VALUES ('X/USDT', 'liq_long_1hour', ?, 100)", (NOW - 2 * H,))
    rt.db.execute("INSERT INTO derivs (symbol, kind, ts, value) VALUES ('X/USDT', 'liq_short_1hour', ?, 50)", (NOW - 2 * H,))
    rt.db.execute("INSERT INTO derivs (symbol, kind, ts, value) VALUES ('X/USDT', 'liq_long_1hour', ?, 9999)", (NOW - H // 2,))
    lq = MI.liquidations(rt, "X/USDT", NOW)
    assert lq["status"] == "confirmed" and lq["value"] == 150 and lq["longs_24h"] == 100   # the open bar is left out


def test_liquidity_tiers_and_missing_ticker():
    rt = RT(tickers={"X/USDT": {"quote_volume": 20e6, "spread_bps": 3.0, "ts": NOW - 30_000}})
    lq = MI.liquidity(rt, "X/USDT", NOW)
    assert lq["status"] == "confirmed" and lq["tier"] == "ok" and lq["spread_bps"] == 3.0
    assert MI.liquidity(rt, "Y/USDT", NOW)["status"] == "unavailable"


def test_relative_strength_vs_btc():
    btc = _candles(200, H, trend=0.0, seed=1)
    coin = btc.copy()
    coin["close"] = coin["close"] * np.linspace(1.0, 1.1, len(coin))       # 10 % stronger over the window
    rt = RT({("BTC/USDT", "1h"): btc, ("X/USDT", "1h"): coin})
    rs = MI.relative_strength(rt, "X/USDT", NOW)
    assert rs["status"] == "confirmed" and rs["rs_7d_pct"] > 0 and rs["rs_24h_pct"] > 0


def test_coin_context_never_raises_and_market_run_stores_status():
    rt = RT(symbols=["BTC/USDT"])
    c = MI.coin_context(rt, "X/USDT", NOW)
    assert c["authority"] == "context only" and set(c["summary"].values()) == {"unavailable"}
    summary = MI.run(rt, NOW)
    assert set(summary) >= {"btc_regime_4h", "btc_trend_4h", "btc_volatility", "breadth", "risk_state"}
    assert MI.current(rt.db, NOW)["authority"].startswith("context only")
    assert MI.current(rt.db, NOW + 3600_000) is None                       # stale context is not served


def test_context_is_never_an_entry_authority():
    """The only use of market_intel in the decision code is storing the context with the call."""
    src = (Path(MI.__file__).parent / "analysis.py").read_text()
    uses = [ln.strip() for ln in src.splitlines() if "market_intel" in ln]
    assert uses == ["from . import market_intel", 'risk_check["intel"] = market_intel.coin_context(rt, symbol)'] or \
        all(("import market_intel" in u) or ('risk_check["intel"]' in u) or u.startswith("try:") or u.startswith("#")
            for u in uses)
    for f in ("bots.py", "hesper.py", "autopaper.py", "tracking.py", "combo_gates.py", "portfolio_risk.py"):
        assert "market_intel" not in (Path(MI.__file__).parent / f).read_text(), f
