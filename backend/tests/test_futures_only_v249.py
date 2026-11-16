"""v2.49: futures-only coins (MSTR/USDT) come from MEXC futures in the Binance provider's shapes."""
import asyncio
import time

from app.data import futures_only as F
from app.data.binance_public import BinancePublicProvider

H4, D1 = 14_400_000, 86_400_000


class Resp:
    def __init__(self, j, code=200):
        self._j, self.status_code = j, code

    def json(self):
        return self._j


class FakeMexc:
    """MSTRSTOCK_USDT listed at `listed` (ms); 15m / 4h / 1d candles up to now."""
    def __init__(self, listed):
        self.listed, self.calls = listed, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if "detail" in url:
            return Resp({"success": True, "data": {"contractSize": 0.01}})
        if "ticker" in url:
            return Resp({"success": True, "data": {"lastPrice": 104.0, "bid1": 103.99, "ask1": 104.01, "riseFallRate": -0.012,
                                                   "high24Price": 106, "lower24Price": 100, "volume24": 1000, "amount24": 1040.0,
                                                   "timestamp": 1}})
        if "depth" in url:
            return Resp({"success": True, "data": {"bids": [[103.9, 200, 1]], "asks": [[104.1, 300, 1]]}})
        if "deals" in url:
            return Resp({"success": True, "data": [{"p": 104, "v": 100, "T": 2, "t": 2}, {"p": 103, "v": 50, "T": 1, "t": 1}]})
        step = {"Min15": 900_000, "Hour4": H4, "Day1": D1}[params["interval"]]
        now = int(time.time() * 1000)
        a = max(params["start"] * 1000, self.listed)
        a = -(-a // step) * step
        b = min(params["end"] * 1000, now)
        ts = list(range(a, b + 1, step))[:2000]
        return Resp({"success": True, "data": {"time": [t // 1000 for t in ts], "open": [1.0] * len(ts),
                                               "high": [2.0 + i for i in range(len(ts))], "low": [0.5] * len(ts),
                                               "close": [1.5] * len(ts), "vol": [100] * len(ts)}})


def prov(listed):
    p = BinancePublicProvider(hosts=["https://x"])
    p.fut = F.MexcFutures(session=FakeMexc(listed))
    return p


def test_candles_skip_to_listing_and_shape():
    now = int(time.time() * 1000)
    listed = now - 20 * D1
    p = prov(listed)
    rows = asyncio.run(p.fetch_ohlcv("MSTR/USDT", "15m", since=now - 300 * D1, limit=1000))
    assert rows and rows[0][0] >= listed and len(rows) <= 1000
    assert rows[0][5] == 1.0                         # 100 contracts x 0.01
    assert all(b[0] - a[0] == 900_000 for a, b in zip(rows, rows[1:]))


def test_12h_and_3d_built_aligned_and_complete():
    now = int(time.time() * 1000)
    p = prov(now - 400 * D1)
    for tf, step in (("12h", 3 * H4), ("3d", 3 * D1)):
        rows = asyncio.run(p.fetch_ohlcv("MSTR/USDT", tf, since=now - 100 * step, limit=1000))
        assert rows and all(r[0] % step == 0 for r in rows)
        assert all(b[0] - a[0] == step for a, b in zip(rows, rows[1:]))
        assert all(abs(r[5] - 3.0) < 1e-9 for r in rows if r[0] + step <= now)       # 3 full parts of 1.0


def test_aggregate_drops_incomplete_old_bar_keeps_forming():
    rows = [[0, 1, 2, 0.5, 1.5, 1], [H4, 1, 3, 0.4, 1.6, 1], [3 * H4, 1, 2, 0.5, 1.7, 1]]
    out = F.aggregate(rows, 3 * H4, 3, now=3 * H4 + 1)
    assert [r[0] for r in out] == [3 * H4]                       # bar 0 lacks a part; bar 1 is still forming
    out = F.aggregate(rows + [[2 * H4, 1, 9, 0.1, 1.55, 1]], 3 * H4, 3, now=3 * H4 + 1)
    assert out[0] == [0, 1, 9, 0.1, 1.55, 3]


def test_ticker_book_trades_and_search():
    p = prov(0)
    t = asyncio.run(p.fetch_ticker("MSTR/USDT"))
    assert t["last"] == 104.0 and abs(t["change_pct"] + 1.2) < 1e-9 and t["base_volume"] == 10.0
    ob = asyncio.run(p.fetch_order_book("MSTR/USDT", 200))
    assert ob["bids"] == [[103.9, 2.0]] and ob["asks"] == [[104.1, 3.0]]
    tr = asyncio.run(p.fetch_trades("MSTR/USDT", 500))
    assert [x["side"] for x in tr] == ["buy", "sell"] and tr[0]["amount"] == 0.5
    p._symbols = ["BTCUSDT"]
    assert asyncio.run(p.search_markets("MSTR")) == ["MSTR/USDT"]


def test_store_sync_backfills_from_listing():
    from app.data.store import CandleStore
    from app.db import Database
    now = int(time.time() * 1000)
    p = prov(now - 15 * D1)
    st = CandleStore(Database("sqlite:///:memory:"))
    n = asyncio.run(st.sync(p, "MSTR/USDT", "15m", bars=30000))
    assert n >= 15 * 96 - 2 and st.count("binance", "MSTR/USDT", "15m") >= 15 * 96 - 2


def test_mstr_added_to_watchlist_once(tmp_path, monkeypatch):
    from app import worker
    from app.db import Database
    from app.services.runtime import Runtime
    from app.sinks import LocalSink
    monkeypatch.setenv("ADD_MSTR", "1")

    class _P:
        name = "test"

        async def search_markets(self, q, limit=50):
            return [f"{q}/USDT"]

    rt = Runtime(Database("sqlite:///:memory:"), _P())
    for f in ("coins_growth_v216", "watchlist_majors_v2", "gold_paxg_v21"):
        rt.db.set_setting(f, True)
    sink = LocalSink(tmp_path)
    sink.set("config/watchlist", {"symbols": [{"symbol": "BTC/USDT", "pinned": True}]})
    notes = worker.sync_config(rt, sink)
    assert notes.get("mstr_v249") == "MSTR/USDT" and "MSTR/USDT" in rt.symbols()
    assert rt.db.get_setting("mstr_v249") is True
    sink.set("config/watchlist", {"symbols": [{"symbol": "BTC/USDT", "pinned": True}]})    # admin removes it: stays removed
    worker.sync_config(rt, sink)
    assert "MSTR/USDT" not in rt.symbols()
