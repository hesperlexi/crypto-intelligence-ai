"""Opportunity radar: ranks strong coins, logs picks once a day, scores them 7 days later against BTC."""
import numpy as np

from app.db import Database
from app.services import radar

DAY = 86_400_000


class Prov:
    def __init__(self, now):
        self.now = now
        rng = np.random.default_rng(4)
        days = 100
        self.ts = [now // DAY * DAY - (days - 1 - i) * DAY for i in range(days)]
        drift = {"BTC": 0.0, "STRONG": 0.012, "WEAK": -0.01, "PUMP": 0.0, **{f"C{i}": rng.normal(0, 0.002) for i in range(8)}}
        self.px = {}
        for b, d in drift.items():
            r = d + rng.normal(0, 0.02, days)
            if b == "PUMP":
                r[-8:] += 0.12                       # parabolic last week
            self.px[b] = 10 * np.exp(np.cumsum(r))

    def _get_sync(self, path, params=None):
        if path == "/api/v3/ticker/24hr":
            rows = [{"symbol": f"{b}USDT", "quoteVolume": "5e7", "priceChangePercent": "1", "lastPrice": str(p[-1])} for b, p in self.px.items()]
            return rows + [{"symbol": "USDCUSDT", "quoteVolume": "9e9", "priceChangePercent": "0", "lastPrice": "1"},
                           {"symbol": "BTCUPUSDT", "quoteVolume": "9e7", "priceChangePercent": "0", "lastPrice": "1"}]
        b = params["symbol"][:-4]
        p = self.px[b]
        if params["interval"] == "1h":
            return [[params["startTime"], str(p[-1] * 1.05), "0", "0", "0", "0", 0, "0"]]
        return [[t, str(c), str(c * 1.01), str(c * 0.99), str(c), "1", 0, "2e7"] for t, c in zip(self.ts, p)]


def test_radar_ranks_strength_flags_pumps_and_keeps_a_record():
    now = 1_793_000_000_000
    db, prov = Database("sqlite:///:memory:"), Prov(now)
    r = radar.scan(db, prov, ["BTC/USDT", "ETH/USDT"], now=now)
    syms = [p["symbol"] for p in r["picks"]]
    assert "USDC/USDT" not in syms and "BTCUP/USDT" not in syms and "BTC/USDT" not in syms
    assert syms[0] == "STRONG/USDT" and syms.index("STRONG/USDT") < syms.index("WEAK/USDT")
    assert "PUMP/USDT" not in syms
    pump = next(p for p in r["extended"] if p["symbol"] == "PUMP/USDT")
    assert pump["overheat"] and any("extended" in x for x in pump["reasons"])
    assert r["historical"]["days"] > 20 and r["live"]["picks"] >= 1
    logged = r["live"]["picks"]
    radar.scan(db, prov, ["BTC/USDT"], now=now + 3_600_000)          # same day: no duplicate picks
    assert radar.live_record(db)["picks"] == logged
    assert radar.evaluate(db, prov, now + 8 * DAY) == logged
    rec = radar.live_record(db)
    assert rec["evaluated"] == logged and rec["beat_btc_rate"] is not None
