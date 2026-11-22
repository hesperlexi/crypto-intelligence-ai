"""v2.75 views/derivs: per-coin derivatives, liquidation map estimate, options / volatility, macro, unlocks."""
from app.db import Database
from app.services import market_data as MD, market_extras as X

H, D = X.HOUR, X.DAY
NOW = 1_795_000_000_000 // H * H


def _db():
    db = Database("sqlite:///:memory:")
    MD.ensure(db)
    return db


def test_coin_stats_from_recorded_data():
    db = _db()
    for i in range(30):
        t = NOW - (30 - i) * H
        db.execute("INSERT INTO mkt_okx (coin, kind, ts, value, known_at) VALUES ('BTC','oi_usd',?,?,?)", (t, 1e9 + i * 1e7, NOW))
        db.execute("INSERT INTO mkt_okx (coin, kind, ts, value, known_at) VALUES ('BTC','taker_buy',?,60,?)", (t, NOW))
        db.execute("INSERT INTO mkt_okx (coin, kind, ts, value, known_at) VALUES ('BTC','taker_sell',?,40,?)", (t, NOW))
    db.execute("INSERT INTO mkt_okx (coin, kind, ts, value, known_at) VALUES ('BTC','ls_ratio',?,1.5,?)", (NOW - H, NOW))
    for i in range(48):
        db.execute("INSERT INTO derivs (symbol, kind, ts, value) VALUES ('BTC/USDT','funding_1h',?,0.0000125)", (NOW - i * H,))
    st = X.coin_stats(db, "BTC/USDT", NOW)
    assert round(st["taker_buy_pct"]) == 60 and round(st["long_pct"]) == 60 and st["oi_chg_24h"] > 0
    assert abs(st["funding_8h_pct"] - 0.01) < 1e-9 and st["funding_days"]
    assert X.coin_stats(db, "ETH/USDT", NOW) is None


def test_liquidation_map_drops_crossed_levels():
    db = _db()
    closes = []
    for i in range(60):
        t = NOW - (60 - i) * H
        db.execute("INSERT INTO mkt_okx (coin, kind, ts, value, known_at) VALUES ('BTC','oi_usd',?,?,?)", (t, 1e9 + i * 1e6, NOW))
        closes.append((t, 100.5, 99.5, 100.0))
    m = X.liquidation_map(db, "BTC/USDT", closes, NOW)
    assert m and m["price"] == 100.0 and sum(m["longs"]) > 0 and sum(m["shorts"]) > 0
    mid = X.LIQ_BINS // 2
    assert sum(m["longs"][mid:]) == 0 and sum(m["shorts"][:mid]) == 0   # long liquidations sit below the price, shorts above


class _S:
    def __init__(self, routes): self.routes = routes
    def get(self, url, params=None, timeout=None, headers=None):
        for k, v in self.routes.items():
            if k in url:
                return type("R", (), {"json": lambda self, v=v: v, "raise_for_status": lambda self: None})()
        raise RuntimeError("no route")


def test_deribit_max_pain_and_put_call():
    exp = "28NOV26"
    book = {"result": [{"instrument_name": f"BTC-{exp}-90000-C", "open_interest": 100, "underlying_price": 95000},
                       {"instrument_name": f"BTC-{exp}-100000-C", "open_interest": 300},
                       {"instrument_name": f"BTC-{exp}-90000-P", "open_interest": 200},
                       {"instrument_name": f"BTC-{exp}-100000-P", "open_interest": 50}]}
    dvol = {"result": {"data": [[NOW - 2 * D, 0, 0, 0, 50.0], [NOW - D, 0, 0, 0, 52.0], [NOW, 0, 0, 0, 55.0]]}}
    v = X.deribit(_S({"get_book_summary": book, "volatility_index": dvol}), 1_795_000_000_000)
    o = v["options"]["BTC"]
    assert o["put_call"] == 250 / 400 and o["max_pain"] in (90000.0, 100000.0) and v["dvol"]["BTC"]["value"] == 55.0


def test_unlocks_next_30_days():
    t0 = NOW / 1000
    data = {"documentedData": {"data": [{"label": "Team", "data": [{"timestamp": t0 - 86400, "unlocked": 100},
                                                                   {"timestamp": t0 + 10 * 86400, "unlocked": 110}]}]}}
    u = X.unlocks(_S({"emissions/sui": data}), ["SUI", "BTC"], NOW)
    assert u == [{"coin": "SUI", "tokens_30d": 10.0, "pct_of_unlocked": 10.000000000000009, "next_at": int((t0 + 10 * 86400) * 1000)}] or (
        len(u) == 1 and abs(u[0]["pct_of_unlocked"] - 10) < 1e-6)


def test_corr_daily():
    a = [(NOW - (40 - i) * D, 100 + i + (i % 3)) for i in range(40)]
    assert X._corr_daily(a, a) == 1.0
