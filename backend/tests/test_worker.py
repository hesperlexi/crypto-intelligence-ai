"""Batch engine (Firebase deployment): a full cycle against a local sink, website actions, the Binance provider."""
import asyncio
import json
import tempfile
import time

from app import worker
from app.config import settings
from app.data.binance_public import BinancePublicProvider
from app.db import Database
from app.services.runtime import Runtime
from app.sinks import LocalSink
from tests.helpers import ArrayProvider


def _view(sink, name):
    doc = sink.get(f"views/{name}")
    return json.loads(doc["json"]) if doc else None


def test_engine_cycle_publishes_views_runs_jobs_and_bots():
    settings.symbols = ["BTC/USDT", "ETH/USDT"]
    settings.model_dir = tempfile.mkdtemp()
    now = int(time.time() * 1000)
    end = now - now % 900_000 + 900_000
    db = Database("sqlite:///:memory:")
    rt = Runtime(db, ArrayProvider(("BTC/USDT", "ETH/USDT"), predictable=0.15, end_ms=end))
    sink = LocalSink(tempfile.mkdtemp(), db)
    d = worker.tick(rt, sink, budget_s=900, fetch_context=False)
    assert d["status"] == "ok", d["steps"]
    assert len(d["bootstrap"]) >= 8                                    # missing models trained (fast set)
    a = _view(sink, "analysis_BTCUSDT_4h")
    assert a["status"] == "OK" and a["forecast"]["available"] and "NaN" not in sink.get("views/analysis_BTCUSDT_4h")["json"]
    for name in ("meta", "health", "dashboard_4h", "models_BTCUSDT_4h", "perf_BTCUSDT_4h", "performance", "signals",
                 "alerts", "backtests", "bots", "settings", "models_status", "replay_ranges", "cross_asset_1d"):
        assert _view(sink, name) is not None, name
    assert sink.get("config/bots")["bots"] and sink.get("config/watchlist")["symbols"]
    assert _view(sink, "health")["engine"]["ticks"] == 1

    # the website edits configuration and queues work
    sink.set("config/watchlist", {"symbols": [{"symbol": "BTC/USDT", "pinned": True}, {"symbol": "ETH/USDT"},
                                              {"symbol": "NOPE/USDT"}]})
    sink.set("config/settings", {"risk_profile": {"portfolio": 50_000}, "signal_weights": {"trend": 0.5}})
    sink.set("alerts/a1", {"type": "PRICE_ABOVE", "symbol": "BTC/USDT", "timeframe": "4h", "params": {"level": 1e9}})
    sink.set("jobs/j1", {"type": "backtest", "status": "queued", "created_at": now,
                         "params": {"symbol": "BTC-USDT", "timeframe": "4h", "strategy": "sma_cross"}})
    sink.set("jobs/j2", {"type": "bogus", "status": "queued", "created_at": now + 1, "params": {}})
    d2 = worker.tick(rt, sink, budget_s=900, fetch_context=False)
    assert d2["status"] == "ok" and d2["jobs"] == 2
    assert d2["skipped_unchanged"] > 0                                 # unchanged documents cost no writes
    assert sink.get("jobs/j1")["status"] == "done" and json.loads(sink.get("jobs/j1")["json"])["status"] == "done"
    assert sink.get("jobs/j2")["status"] == "failed"
    assert rt.watchlist()[0] == {**rt.watchlist()[0], "symbol": "BTC/USDT", "pinned": 1}
    assert "NOPE/USDT" not in rt.symbols() and d2["config"]["rejected_symbols"] == ["NOPE/USDT"]
    assert rt.risk_profile().portfolio == 50_000 and rt.signal_weights()["trend"] == 0.5
    assert "a1" in _view(sink, "alerts")["state"]
    sink.set("config/bots", {"bots": [{"id": "only", "mode": "prediction", "timeframe": "4h", "reset_token": "1"}]})
    worker.tick(rt, sink, budget_s=900, fetch_context=False)
    assert [b["config"]["id"] for b in _view(sink, "bots")["bots"]] == ["only"]


class _Resp:
    def __init__(self, status, payload, headers=None):
        self.status_code, self._p, self.headers, self.text = status, payload, headers or {}, json.dumps(payload)

    def json(self):
        return self._p


class _Session:
    def __init__(self, script):
        self.script, self.calls = script, []

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        for prefix, resp in self.script:
            if url.startswith(prefix):
                return resp
        raise ConnectionError("unreachable")

    def close(self):
        pass


def test_binance_provider_falls_back_between_hosts_and_parses():
    kline = [[1_700_000_000_000, "1", "2", "0.5", "1.5", "10", 0, "0", 0, "0", "0", "0"]]
    s = _Session([("https://geo-blocked", _Resp(451, {})), ("https://ok", _Resp(200, kline))])
    p = BinancePublicProvider(hosts=["https://geo-blocked", "https://ok"], session=s)
    rows = asyncio.run(p.fetch_ohlcv("BTC/USDT", "4h", since=0, limit=5000))
    assert rows == [[1_700_000_000_000, 1.0, 2.0, 0.5, 1.5, 10.0]] and p.host_used == "https://ok"
    asyncio.run(p.fetch_ohlcv("BTC/USDT", "4h"))
    assert s.calls[-1].startswith("https://ok")                       # the working host is tried first next time
    bad = BinancePublicProvider(hosts=["https://x"], session=_Session([("https://x", _Resp(400, {"msg": "bad symbol"}))]))
    try:
        asyncio.run(bad.fetch_ohlcv("NOPE/USDT", "1h"))
        raise AssertionError("a 400 must raise")
    except ValueError:
        pass
    down = BinancePublicProvider(hosts=["https://a"], session=_Session([]))
    try:
        asyncio.run(down.fetch_ticker("BTC/USDT"))
        raise AssertionError("no reachable host must raise")
    except ConnectionError:
        assert down.errors == 1 and down.last_error
