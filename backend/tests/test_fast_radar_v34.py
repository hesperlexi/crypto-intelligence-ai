"""V3.4 Stage 3C: advanced radar - meme / alt watchlists, MEXC fallback, detections, appearance tracking, display only."""
import numpy as np

from app.db import Database
from app.services import fast_radar as FR
from tests.test_fast_radar_v33 import H, NOW, Provider, _book, _klines, _tick


class MexcProvider(Provider):
    def __init__(self, *a, mexc=None, **kw):
        super().__init__(*a, **kw)
        self.mexc = mexc or {}

    def mexc_get(self, path, params):
        s = params["symbol"]
        if s not in self.mexc:
            raise RuntimeError("not listed")
        if path == "/api/v3/klines":
            assert params["interval"] == "60m"
            return self.mexc[s]
        if path == "/api/v3/ticker/24hr":
            return _tick(s, 40e6)
        return _book(s)


def test_watchlists_default_env_setting_and_legacy(monkeypatch):
    db = Database("sqlite:///:memory:")
    w = FR.watchlists(db)
    assert w["meme"][:3] == ["DOGE", "PEPE", "BONK"] and "HYPE" in w["alt"] and "WLD" in w["alt"]
    monkeypatch.setenv("FAST_RADAR_MEME", "wif")
    monkeypatch.setenv("FAST_RADAR_ALT", "sol, sui")
    assert FR.watchlists(db) == {"meme": ["WIF"], "alt": ["SOL", "SUI"]}
    db.set_setting("fast_radar_watchlists", {"meme": ["bonk"], "alt": []})
    assert FR.watchlists(db) == {"meme": ["BONK"], "alt": []}
    db2 = Database("sqlite:///:memory:")
    monkeypatch.delenv("FAST_RADAR_MEME")
    monkeypatch.delenv("FAST_RADAR_ALT")
    db2.set_setting("fast_radar_coins", ["DOGE", "SOL"])
    assert FR.watchlists(db2) == {"meme": ["DOGE"], "alt": ["SOL"]}


def _scan(db, mexc=None):
    db.set_setting("fast_radar_watchlists", {"meme": ["UPX", "HYPEMEME"], "alt": ["FLAT"]})
    p = MexcProvider({"BTCUSDT": _klines(seed=1), "UPXUSDT": _klines(drift=0.002, seed=2, vol=3.0), "FLATUSDT": _klines(seed=3)},
                     {"UPXUSDT": _tick("UPXUSDT"), "FLATUSDT": _tick("FLATUSDT")},
                     {"UPXUSDT": _book("UPXUSDT"), "FLATUSDT": _book("FLATUSDT")}, mexc=mexc)
    return FR.scan(db, p, NOW)


def test_categories_ranks_and_mexc_fallback():
    db = Database("sqlite:///:memory:")
    out = _scan(db, mexc={"HYPEMEMEUSDT": _klines(seed=4)})
    by = {x["coin"]: x for x in out["coins"]}
    assert by["HYPEMEME"]["source"] == "MEXC spot" and by["UPX"]["source"] == "Binance spot"
    assert by["UPX"]["category"] == "meme" and by["FLAT"]["category"] == "alt" and by["FLAT"]["category_rank"] == 1
    assert out["categories"]["meme"][0] == "UPX" and out["not_covered"] == []
    assert out["display_only"] and "Not a signal" in out["note"]
    out2 = _scan(Database("sqlite:///:memory:"))                    # not on MEXC either: reported, never guessed
    assert out2["not_covered"] == ["HYPEMEME"]


def test_appearance_recorded_once_then_outcome_filled():
    db = Database("sqlite:///:memory:")
    _scan(db)
    rows = db.query("SELECT * FROM radar_opportunities")
    assert rows and all(r["status"] == "tracking" for r in rows)
    first = {r["coin"]: r["id"] for r in rows}
    _scan(db)                                                        # same hour again: no duplicate
    assert len(db.query("SELECT * FROM radar_opportunities")) == len(rows)
    r = db.query("SELECT * FROM radar_opportunities")[0]
    bar = r["bar_ts"]
    k = np.array([[bar + i * H, 1, r["price"] * 1.2, r["price"] * 0.9, r["price"] * (1 + 0.001 * i), 1] for i in range(0, 80)], float)
    btc = np.array([[bar + i * H, 1, 1, 1, (r["btc_price"] or 100), 1] for i in range(0, 80)], float)
    FR.track(db, [], {r["coin"]: k}, btc, bar + 80 * H)
    done = db.one("SELECT * FROM radar_opportunities WHERE id = ?", (first[r["coin"]],))
    assert done["status"] == "done" and done["ret_24h"] > 0 and done["worked"] == 1 and done["max_up_72h"] > 0
    s = FR.track_summary(db)
    assert s["all"]["n"] >= 1 and "not a trade result" in s["basis"] and not s["all"]["enough"]


def test_detections():
    n = 200
    c = np.r_[np.full(n - 12, 100.0), np.linspace(100, 100.5, 6), np.linspace(100.6, 104, 6)]
    ts = NOW - H * np.arange(n, 0, -1)
    k = np.c_[ts, c, c * 1.001, c * 0.999, c, np.full(n, 1e6)]
    btc = np.c_[ts, np.full(n, 100.0), np.full(n, 100.0), np.full(n, 100.0), np.full(n, 100.0), np.full(n, 1e6)]
    f = {"above_ema20": True, "above_ema50": True, "ema20_slope_6h_pct": 0.5, "volume_expansion": 0.3}
    ex = FR.extras(k, btc, f, spread_bps=30.0, prev_spread=5.0, market_regime="breakdown")
    sig, warn = " | ".join(ex["signals"]), " | ".join(ex["warnings"])
    assert "momentum accelerating" in sig and "relative-strength breakout" in sig
    assert "liquidity deteriorating" in warn and "spread expanded" in warn and "BTC regime incompatible" in warn
    calm = FR.extras(k, btc, {**f, "volume_expansion": 1.0}, 3.0, 3.0, "weak_bull")
    assert calm["warnings"] == []


def test_strategy_reads_a_compact_copy_not_the_module():
    db = Database("sqlite:///:memory:")
    _scan(db)
    last = db.get_setting("radar_fast_snapshot")
    assert last["coins"] and {"coin", "category", "flagged", "price", "liquidity_ok"} <= set(last["coins"][0])
