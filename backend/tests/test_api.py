"""HTTP layer (requires fastapi + httpx, both in requirements.txt). The exchange is replaced by the test provider."""
import asyncio

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import Database, set_db  # noqa: E402
from app.services import market  # noqa: E402
from app.services.runtime import get_runtime  # noqa: E402
from tests.helpers import ArrayProvider  # noqa: E402


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    settings.enable_background_jobs = False
    settings.derivatives_exchange = ""
    settings.enable_external_context = False
    settings.symbols = ["BTC/USDT", "ETH/USDT"]
    settings.model_dir = str(tmp_path_factory.mktemp("models"))
    set_db(Database("sqlite:///:memory:"))
    prov = ArrayProvider()
    original = market.make_provider
    market.make_provider = lambda exchange=None: prov
    from app.main import app

    with TestClient(app) as c:
        rt = get_runtime()

        async def sync():
            for s in ("BTC/USDT", "ETH/USDT"):
                for tf in ("15m", "1h", "4h", "12h", "1d", "1w"):
                    await rt.store.sync(prov, s, tf, bars=70000)

        asyncio.run(sync())
        yield c
    market.make_provider = original


def test_spec_paths_exist_with_and_without_api_prefix(client):
    for path in ("/market/BTC-USDT", "/market/BTC-USDT/ohlcv", "/forecast/BTC-USDT", "/forecast/BTC-USDT/4h",
                 "/signal/BTC-USDT", "/regime/BTC-USDT", "/indicators/BTC-USDT", "/models/BTC-USDT",
                 "/performance/BTC-USDT", "/scanner", "/system/health"):
        for prefix in ("", "/api"):
            r = client.get(prefix + path)
            assert r.status_code == 200, (prefix + path, r.text[:200])
            r.json()


def test_analysis_and_validation(client):
    a = client.get("/api/analysis/BTCUSDT?timeframe=4h").json()
    assert a["status"] == "OK" and a["symbol"] == "BTC/USDT" and "MODEL NOT TRAINED" in a["flags"]
    assert client.get("/api/analysis/DOGE?timeframe=4h").json()["status"] == "INSUFFICIENT DATA"
    assert client.get("/api/market/BTC/ohlcv?timeframe=7h").status_code == 400
    assert client.get("/api/backtest/unknown").status_code == 404
    assert client.post("/api/backtest", json={"timeframe": "4h"}).status_code == 400


def test_backtest_paper_alerts_settings_roundtrip(client):
    bt = client.post("/api/backtest", json={"symbol": "BTC-USDT", "timeframe": "4h", "strategy": "sma_cross"}).json()
    assert bt["status"] == "done" and client.get(f"/api/backtest/{bt['id']}").json()["id"] == bt["id"]
    order = client.post("/api/paper/order", json={"symbol": "BTC", "side": "BUY", "notional": 1000}).json()
    assert order["trade"]["mode"] == "PAPER" and order["state"]["mode"] == "PAPER TRADING"
    assert client.post("/api/paper/order", json={"symbol": "BTC", "side": "SELL", "qty": 1e12}).status_code == 400
    alert = client.post("/api/alerts", json={"type": "PRICE_ABOVE", "symbol": "BTC", "params": {"level": 1}}).json()
    assert alert["id"] in [x["id"] for x in client.get("/api/alerts").json()["alerts"]]
    assert client.post("/api/alerts", json={"type": "NOPE", "symbol": "BTC"}).status_code == 400
    s = client.put("/api/settings", json={"risk_profile": {"portfolio": 50000}, "forecast_refresh_s": 900}).json()
    assert s["risk_profile"]["portfolio"] == 50000 and s["forecast_refresh_s"] == 900
    assert client.put("/api/settings", json={"forecast_refresh_s": 7}).status_code == 400
    size = client.post("/api/risk/position-size", json={"entry": 100, "stop": 95}).json()
    assert abs(size["max_loss"] - 500) < 1e-6


def test_websocket_reports_disabled_feed(client):
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "status"
