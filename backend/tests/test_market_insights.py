"""Home-page market insights: dominance snapshots, altcoin season index (synthetic data), funding read, headline."""
import json

from app.db import Database
from app.services import market_insights as mi
from app.sinks import LocalSink

HOUR, DAY = 3_600_000, 86_400_000
NOW = 1_793_000_000_000 // DAY * DAY + 10 * HOUR


def ctx(ts, btc, eth=12.0):
    return {"fetched_at": ts, "market": {"source": "CoinGecko", "total_market_cap_usd": 3.1e12, "market_cap_change_24h_pct": -1.2,
                                          "btc_dominance": btc, "eth_dominance": eth, "stablecoin_share": 7.5}}


def test_altseason_index_counts_coins_that_beat_btc():
    rets = {f"C{i}": 0.10 * i for i in range(10)}                  # 0 .. 0.9
    r = mi.altseason_index(rets, btc_return=0.45)
    assert r["n_beat"] == 5 and r["n_total"] == 10 and r["value"] == 50 and r["label"] == "Neither season"
    assert mi.altseason_index({"A": -0.5, "B": -0.2, "C": 0.3, "D": -0.1}, 0.0)["value"] == 25
    assert mi.season_label(25) == "Bitcoin season" and mi.season_label(75) == "Altcoin season"


def test_exclusions():
    for s in ("USDT", "USDC", "FDUSD", "WBTC", "STETH", "PAXG", "BTCUP", "ETHDOWN", "BTC"):
        assert mi.is_excluded(s), s
    for s in ("ETH", "SOL", "DOGE", "SUPER", "JUP"):
        assert not mi.is_excluded(s), s
    assert mi.is_excluded("XYZ", "Wrapped XYZ") and mi.is_excluded("ABC", "Lido Staked ABC")


class Prov:
    """Binance-like spot REST with synthetic daily closes: coin i drifts at its own rate, BTC flat-ish."""

    def __init__(self, now, n=70):
        self.now = now
        self.days = 95
        self.drift = {"BTC": 0.001, "USDC": 0.0, "NEW": 0.01, **{f"C{i:02d}": (i - 35) * 0.0002 for i in range(n)}}

    def _get_sync(self, path, params=None):
        if path == "/api/v3/ticker/24hr":
            return [{"symbol": f"{b}USDT", "quoteVolume": str(1e9 - i), "lastPrice": "1"} for i, b in enumerate(self.drift)]
        b = params["symbol"][:-4]
        start = self.now // DAY * DAY - (self.days - 1) * DAY        # the last candle is today's (still forming)
        n = 20 if b == "NEW" else self.days
        rows = []
        for j in range(self.days - n, self.days):
            rows.append([start + j * DAY, "1", "1", "1", str(100 * (1 + self.drift[b]) ** j), "1", 0, "1"])
        return rows[-params["limit"]:]


class NoGecko:
    def get(self, *a, **k):
        raise ConnectionError("blocked")


def test_compute_altseason_from_synthetic_candles_and_cache():
    db = Database("sqlite:///:memory:")
    prov = Prov(NOW)
    r = mi.compute_altseason(prov, NOW, session=NoGecko())
    assert r["n_total"] == 50 and "NEW" in r["skipped"] and "USDC" not in r["beat"]
    # coins C00..C49 drift (i-35)*0.0002; BTC 0.001 -> beaters are i > 40 within the first 50 -> C41..C49
    assert r["n_beat"] == 9 and r["value"] == 18 and r["label"] == "Bitcoin season"
    assert r["as_of"] == NOW // DAY * DAY and "quote-volume" in r["universe"]
    assert mi.refresh_altseason(db, prov, NOW, session=NoGecko())["value"] == 18
    assert mi.refresh_altseason(db, prov, NOW + HOUR, session=NoGecko()) == {"skipped": "fresh"}      # 6-hour cache
    b = mi.altseason_block(db, NOW + HOUR)
    assert b["value"] == 18 and b["n_beat"] == 9 and b["history"] == [[NOW, 18]]


def test_dominance_snapshots_hourly_changes_and_reading():
    db = Database("sqlite:///:memory:")
    assert mi.dominance_block(db, NOW) is None
    for h in range(8 * 24, -1, -1):                                 # 8 days, hourly, dominance rising 0.01 / hour
        mi.record_snapshot(db, ctx(NOW - h * HOUR + 5 * 60_000, 55.0 + (8 * 24 - h) * 0.01), NOW)
    assert not mi.record_snapshot(db, ctx(NOW + 10 * 60_000, 99.0))     # same hour: kept once
    d = mi.dominance_block(db, NOW + HOUR)
    assert abs(d["btc"] - 56.92) < 1e-9 and abs(d["btc_change_24h"] - 0.24) < 1e-6 and abs(d["btc_change_7d"] - 1.68) < 1e-6
    assert "rose 1.7 points over 7 days" in d["reading"] and d["eth_change_7d"] == 0
    assert 40 < len(d["series"]) < 60 and d["series"][-1][1] == d["btc"]          # 4-hour steps past 7 days
    assert "steady" in mi.dominance_reading(55.0, 0.1, 0.4) and "fell" in mi.dominance_reading(55.0, None, -1.2)
    assert "once a day" in mi.dominance_reading(55.0, None, None)


def test_funding_read_and_headline_and_view(tmp_path):
    assert mi.funding_read(0.0004) == "crowded long" and mi.funding_read(0.0001) == "neutral" and mi.funding_read(-0.0002) == "crowded short"
    db = Database("sqlite:///:memory:")
    f = mi.funding_block(db, {"BTC/USDT": {"rate": 0.0001, "source": "OKX perpetual"}, "ETH/USDT": {"rate": 0.0003, "source": "OKX perpetual"}},
                         ["BTC/USDT", "ETH/USDT"], NOW)
    assert abs(f["avg_rate_8h"] - 0.0002) < 1e-12 and f["read"] == "neutral" and f["high"] == "ETH" and f["n"] == 2
    assert mi.funding_block(db, {}, ["BTC/USDT"], NOW) is None
    heads = {"items": [{"title": "Memecoin of the week", "url": "https://a.test", "source": "X", "ts": NOW - HOUR},
                       {"title": "Fed holds rates, Powell signals patience", "url": "https://b.test", "source": "Y", "ts": NOW - 2 * HOUR},
                       {"title": "SEC approves ETF", "url": "https://c.test", "source": "Z", "ts": NOW - 3 * DAY}]}
    assert mi.top_headline(heads, NOW)["url"] == "https://b.test"
    assert mi.top_headline({"items": heads["items"][2:]}, NOW) is None
    mi.record_snapshot(db, ctx(NOW, 56.0), NOW)
    v = mi.view(db, ctx(NOW, 56.0), {"BTC/USDT": {"rate": 0.0005}}, ["BTC/USDT"], heads, NOW)
    assert v["dominance"]["btc"] == 56.0 and v["altseason"] is None and v["funding"]["read"] == "crowded long"
    assert v["pulse"]["stablecoin_share"] == 7.5 and v["headline"]["source"] == "Y"
    # published like every view: deduplicated, at most hourly
    sink = LocalSink(tmp_path, db)
    sink.view("market_context", v, min_interval_s=3600)
    assert sink.flush() == 1 and json.loads(sink.get("views/market_context")["json"])["dominance"]["btc"] == 56.0
    sink.view("market_context", {**v, "generated_at": NOW + 1})
    assert sink.flush() == 0
    assert len(json.dumps(v)) < 20_000
