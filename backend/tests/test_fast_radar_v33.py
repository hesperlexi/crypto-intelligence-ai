"""V3.3 Stage 2 phase C: Fast Opportunity Radar - display only, closed candles, transparent ranking, warnings."""
from pathlib import Path

import numpy as np

from app.db import Database
from app.services import fast_radar as FR

H = 3_600_000
NOW = 1_795_700_000_000 // H * H


def _klines(n=200, drift=0.0, seed=0, vol=1.0, end_open=None, pump_last=0.0):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(drift, 0.004, n)))
    if pump_last:
        c[-1] *= 1 + pump_last
    end_open = NOW - H if end_open is None else end_open
    ts = end_open - H * np.arange(n - 1, -1, -1)
    o = np.r_[c[0], c[:-1]]
    return [[int(t), o[i], max(o[i], c[i]) * 1.001, min(o[i], c[i]) * 0.999, c[i], 1.0, int(t) + H - 1, vol * 1e6]
            for i, t in enumerate(ts)]


class Provider:
    def __init__(self, series, tickers, books, fail=()):
        self.series, self.tickers, self.books, self.fail = series, tickers, books, set(fail)
        self.calls = []

    def _get_sync(self, path, params=None):
        self.calls.append((path, params))
        if path == "/api/v3/klines":
            s = params["symbol"]
            if s in self.fail:
                raise RuntimeError("boom")
            return self.series[s]
        if path == "/api/v3/ticker/24hr":
            return [self.tickers[s] for s in self.tickers]
        if path == "/api/v3/ticker/bookTicker":
            return [self.books[s] for s in self.books]
        raise KeyError(path)


def _tick(s, qv=50e6):
    return {"symbol": s, "quoteVolume": qv, "lastPrice": 100}


def _book(s, bid=99.99, ask=100.01):
    return {"symbol": s, "bidPrice": bid, "askPrice": ask}


def test_closed_rows_drop_the_forming_candle():
    rows = _klines(10, end_open=NOW)                          # the last candle opens NOW: still forming
    assert len(FR.closed_rows(rows, NOW)) == 9


def test_strong_coin_ranks_first_with_reasons():
    db = Database("sqlite:///:memory:")
    db.set_setting("fast_radar_coins", ["UPX", "FLAT"])
    p = Provider({"BTCUSDT": _klines(seed=1), "UPXUSDT": _klines(drift=0.002, seed=2, vol=3.0), "FLATUSDT": _klines(seed=3)},
                 {"UPXUSDT": _tick("UPXUSDT"), "FLATUSDT": _tick("FLATUSDT")},
                 {"UPXUSDT": _book("UPXUSDT"), "FLATUSDT": _book("FLATUSDT")})
    out = FR.scan(db, p, NOW)
    assert out["available"] and out["display_only"] and out["not_covered"] == []
    top = out["coins"][0]
    assert top["coin"] == "UPX" and top["rank"] == 1 and top["reasons"] and set(top["points"]) <= set(FR.WEIGHTS)
    assert top["spread_bps"] == 2.0


def test_warnings():
    f = {"rs_7d_pct": 40.0, "rs_24h_pct": 30.0, "above_ema20": True, "above_ema50": True, "ema20_slope_6h_pct": 3.0,
         "ret_24h_pct": 32.0, "rsi14": 88.0, "volume_expansion": 4.0, "volatility_expansion": 2.5, "wick_share_24h": 0.7,
         "largest_1h_move_pct": 20.0, "bars": 100}
    j = FR.judge(f, quote_vol=5e6, spread_bps=45.0, regime="SEVERE")
    w = " | ".join(j["warnings"])
    for word in ("parabolic", "thin liquidity", "wide spread", "wick-heavy", "one-candle pump", "short history", "SEVERE"):
        assert word in w, word
    assert j["regime_compatibility"] == "incompatible"
    clean = FR.judge({**f, "ret_24h_pct": 5.0, "rsi14": 60.0, "wick_share_24h": 0.2, "largest_1h_move_pct": 2.0, "bars": 200},
                     quote_vol=80e6, spread_bps=3.0, regime="NORMAL")
    assert clean["warnings"] == [] and clean["score"] > j["score"]


def test_volume_without_price_warning():
    f = {"rs_7d_pct": 0.0, "rs_24h_pct": 0.0, "above_ema20": False, "above_ema50": False, "ema20_slope_6h_pct": 0.0,
         "ret_24h_pct": 0.5, "rsi14": 50.0, "volume_expansion": 3.5, "volatility_expansion": 1.0, "wick_share_24h": 0.3,
         "largest_1h_move_pct": 0.4, "bars": 200}
    assert any("wash" in w for w in FR.judge(f, 50e6, 3.0, "NORMAL")["warnings"])


def test_missing_coins_and_failures_are_reported_not_guessed():
    db = Database("sqlite:///:memory:")
    db.set_setting("fast_radar_coins", ["AAA", "MEXCONLY", "BAD"])
    p = Provider({"BTCUSDT": _klines(seed=1), "AAAUSDT": _klines(seed=2)},
                 {"AAAUSDT": _tick("AAAUSDT"), "BADUSDT": _tick("BADUSDT")}, {"AAAUSDT": _book("AAAUSDT")},
                 fail={"BADUSDT"})
    out = FR.scan(db, p, NOW)
    assert out["not_covered"] == ["MEXCONLY"]
    bad = next(x for x in out["coins"] if x["coin"] == "BAD")
    assert bad["score"] is None and bad["status"] == "unavailable"
    aaa = next(x for x in out["coins"] if x["coin"] == "AAA")
    assert any("spread unknown" not in w for w in aaa["warnings"]) or aaa["spread_bps"] is not None


def test_configurable_watchlist(monkeypatch):
    db = Database("sqlite:///:memory:")
    assert FR.coins(db) == list(FR.DEFAULT_COINS)
    monkeypatch.setenv("FAST_RADAR_COINS", "doge, pepe")
    assert FR.coins(db) == ["DOGE", "PEPE"]
    db.set_setting("fast_radar_coins", ["wif"])
    assert FR.coins(db) == ["WIF"]


def test_radar_is_never_connected_to_trading():
    app = Path(FR.__file__).resolve().parents[1]
    users = [str(p.relative_to(app)) for p in app.rglob("*.py") if "fast_radar" in p.read_text() and p.name != "fast_radar.py"]
    assert users == ["worker.py"]                              # only the hourly radar step publishes it
    src = (app / "worker.py").read_text()
    assert 'r["fast"] = fast_radar.scan(rt.db, rt.provider)' in src
