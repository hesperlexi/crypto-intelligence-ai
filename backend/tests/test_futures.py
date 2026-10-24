"""Futures maths and futures demo bots: margin, leverage, liquidation, funding, the futures view."""
import pytest

from app.engine import futures as F
from app.services import analysis
from app.services import bots as B

from .test_bots import H4, STEP, _buy, _cfg, _now_aligned, _put, _rt


@pytest.fixture
def no_costs(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "fee_rate", 0.0)
    monkeypatch.setattr(settings, "slippage_bps", 0.0)
    monkeypatch.setattr(settings, "spread_bps", 0.0)
    monkeypatch.setattr(F, "FUTURES_FEE_RATE", 0.0)


def _fcfg(**kw):
    return _cfg(**{"market": "futures", "leverage": 5.0, "safe_leverage": False, "max_position_pct": 100.0, **kw})


def test_liquidation_and_safe_leverage():
    assert F.liquidation_price(100, 1, 10, 0.005) == pytest.approx(90.5)
    assert F.liquidation_price(100, -1, 10, 0.005) == pytest.approx(109.5)
    assert F.liquidation_price(100, 1, 1, 0.005) == pytest.approx(0.5)
    # 2% stop: liquidation must stay >= 3% away -> 1 / (0.03 + 0.005) = 28 -> capped at 20
    assert F.safe_leverage(100, 98, 20) == 20
    # 5% stop: 1 / (0.075 + 0.005) = 12.5 -> 12, and the liquidation price is beyond the stop
    lev = F.safe_leverage(100, 95, 20)
    assert lev == 12 and F.liquidation_price(100, 1, lev) < 95
    assert F.funding_times(0, 3 * F.FUNDING_INTERVAL_MS) == [F.FUNDING_INTERVAL_MS * i for i in (1, 2, 3)]


def test_futures_long_uses_margin_and_scales_pnl(monkeypatch, no_costs):
    rt = _rt()
    now = _now_aligned()
    t0 = now - 40 * STEP
    _put(rt, "BTC/USDT", t0, [100.0] * 4)
    eng = B.BotEngine(rt)
    eng.sync_configs([_fcfg()])
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: _buy())
    eng.run(t0 + 4 * STEP)
    (cfg, st), = eng.bots()
    pos = st["positions"][0]
    # same risk-based size as spot (1% of 10k / $2), but only notional / 5 is set aside as margin
    assert abs(pos["qty"] - 50.0) < 1e-9 and pos["lev"] == 5.0
    assert abs(st["cash"] - (10_000 - 50 * 100 / 5)) < 1e-6
    assert abs(eng.equity(st) - 10_000) < 1e-6
    assert pos["liq"] == pytest.approx(100 * (1 - 1 / 5 + F.MAINTENANCE_MARGIN))
    _put(rt, "BTC/USDT", t0 + 4 * STEP, [(100, 100.1, 97.5, 98)])     # stop at 98
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: {"status": "OK", "decision": "HOLD"})
    eng.run(t0 + 6 * STEP)
    t = rt.db.one("SELECT * FROM bot_trades")
    assert t["exit_reason"] == "stop" and abs(t["pnl"] + 100) < 1e-6          # the stop still limits the loss to 1%
    info = __import__("json").loads(t["info"])
    assert info["market"] == "futures" and info["leverage"] == 5.0 and abs(info["roe_pct"] + 10) < 1e-6


def test_liquidation_when_price_gaps_through(monkeypatch, no_costs):
    rt = _rt()
    now = _now_aligned()
    t0 = now - 40 * STEP
    _put(rt, "BTC/USDT", t0, [100.0] * 4)
    eng = B.BotEngine(rt)
    eng.sync_configs([_fcfg(leverage=10.0)])
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: _buy(stop=95.0))
    eng.run(t0 + 4 * STEP)
    (cfg, st), = eng.bots()
    margin = st["positions"][0]["margin"]
    cash_before = st["cash"]
    # opens far below the liquidation price (90.5) -> liquidated, the stop cannot help
    _put(rt, "BTC/USDT", t0 + 4 * STEP, [(88, 88.5, 87, 88)])
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: {"status": "OK", "decision": "HOLD"})
    eng.run(t0 + 6 * STEP)
    (cfg, st), = eng.bots()
    t = rt.db.one("SELECT * FROM bot_trades")
    assert t["exit_reason"] == "liquidated" and abs(t["pnl"] + margin) < 1e-6
    assert abs(st["cash"] - cash_before) < 1e-6 and st["liquidations"] == 1
    assert eng.report()["bots"][0]["stats"]["liquidations"] == 1


def test_safe_leverage_keeps_liquidation_beyond_stop(monkeypatch, no_costs):
    rt = _rt()
    now = _now_aligned()
    t0 = now - 40 * STEP
    _put(rt, "BTC/USDT", t0, [100.0] * 4)
    eng = B.BotEngine(rt)
    eng.sync_configs([_cfg(market="futures", leverage=20.0, safe_leverage=True, max_position_pct=100.0)])
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: _buy(stop=95.0))
    eng.run(t0 + 4 * STEP)
    pos = eng.bots()[0][1]["positions"][0]
    assert pos["lev"] == 12 and pos["liq"] < 95


def test_funding_is_charged_every_8_hours(monkeypatch, no_costs):
    rt = _rt()
    rt.funding_rates = {"BTC/USDT": {"rate": 0.001, "source": "test"}}
    t0 = (_now_aligned() // F.FUNDING_INTERVAL_MS - 3) * F.FUNDING_INTERVAL_MS + STEP
    _put(rt, "BTC/USDT", t0 - 4 * STEP, [100.0] * 4)
    eng = B.BotEngine(rt)
    eng.sync_configs([_fcfg(max_hold_bars=1000)])
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: _buy(stop=90.0, tps=(150.0, 160.0, 170.0)))
    eng.run(t0)
    _put(rt, "BTC/USDT", t0, [100.0] * 70)
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: {"status": "OK", "decision": "HOLD"})
    eng.run(t0 + 2 * F.FUNDING_INTERVAL_MS)                     # two funding times passed
    (cfg, st), = eng.bots()
    pos = st["positions"][0]
    expected = 2 * pos["qty_open"] * 100 * 0.001                # a long pays a positive rate
    assert abs(st["funding_paid"] - expected) < 1e-6 and abs(pos["funding"] - expected) < 1e-6


def test_futures_prediction_tracker_and_view(monkeypatch, no_costs):
    rt = _rt()
    rt.funding_rates = {"BTC/USDT": {"rate": 0.0, "source": "test"}}     # isolate the price P&L
    now = _now_aligned()
    bar_ts = now - now % H4 - 3 * H4
    bar_close = bar_ts + H4
    _put(rt, "BTC/USDT", bar_close - 8 * STEP, [100.0] * 8)
    eng = B.BotEngine(rt)
    eng.sync_configs([{"id": "fp", "mode": "prediction", "market": "futures", "leverage": 3, "timeframe": "4h",
                       "position_pct": 10, "reset_token": "1"}])
    fc = {"available": True, "bar_ts": bar_ts, "predicted_class": 0, "predicted": "DOWN", "p_max": 0.5,
          "probabilities": {"up": 0.2, "down": 0.5}, "confidence": {"confidence": 0.47}, "model_version": "v",
          "edge_confirmed": False, "expected_return": -0.002}
    monkeypatch.setattr(analysis, "model_forecast", lambda *a, **k: fc)
    eng.run(bar_close + STEP)
    pos = eng.bots()[0][1]["positions"][0]
    assert pos["side"] == -1 and abs(pos["qty"] - 30.0) < 1e-9          # 10% margin x 3 = $3,000 notional
    _put(rt, "BTC/USDT", bar_close, [100.0] * 15 + [97.0])
    eng.run(bar_close + H4 + 2 * STEP)
    t = rt.db.one("SELECT * FROM bot_trades")
    assert t["correct"] == 1 and abs(t["pnl"] - 90.0) < 1e-6            # 3% x $3,000

    a = {**_buy("SELL", -1, 100.0, 102.0, (98.0, 96.0, 94.0)), "symbol": "BTC/USDT", "timeframe": "4h", "price": 100.0}
    a["setup"]["targets"] = [{"name": f"TP{i}", "price": p, "rr": i} for i, p in enumerate((98.0, 96.0, 94.0), 1)]
    v = F.futures_view(a, {"rate": 0.0002, "source": "test"})
    assert v["action"] == "SHORT" and v["plan"]["side"] == "SHORT"
    assert v["plan"]["suggested_leverage"] == 10 and v["plan"]["liquidation_at_suggested"] > 102
    assert v["plan"]["funding_per_day_pct"] == pytest.approx(0.06)     # a short receives a positive rate
