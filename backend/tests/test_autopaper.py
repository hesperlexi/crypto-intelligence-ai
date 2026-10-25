"""Signals are placed automatically in members' paper futures accounts, once per signal, with their settings."""
from app.services import autopaper
from app.sinks import LocalSink


def row(sym="BTC/USDT", side=1, price=100.0, zone=(99.0, 101.0), grade="A"):
    return {"symbol": sym, "side": side, "price": price, "grade": grade,
            "plan": {"valid": True, "entry": 100.0, "entry_zone": list(zone), "stop": 96.0 if side > 0 else 104.0,
                     "targets": [{"price": 104.0 if side > 0 else 96.0}, {"price": 108.0 if side > 0 else 92.0}, {"price": 112.0 if side > 0 else 88.0}],
                     "suggested_leverage": 5}}


def test_auto_paper_opens_once_respects_settings_and_balance(tmp_path):
    sink = LocalSink(tmp_path)
    now = 1_793_000_000_000
    sink.set("users/m1", {"status": "approved", "expires_at": now + 86_400_000})
    sink.set("users/gone", {"status": "approved", "expires_at": now - 1})
    sink.set("auto_paper/m1", {"enabled": True, "margin": 250, "leverage": "signal", "timeframes": ["1h"], "grades": "AB", "take": "tp2"})
    sink.set("auto_paper/gone", {"enabled": True})
    sink.set("auto_paper/off", {"enabled": False})
    rows = {"1h": [row(), row("ETH/USDT", -1, price=103.0, zone=(99, 101), grade="B")], "4h": [row("SOL/USDT")]}
    r = autopaper.run(sink, rows, now)
    assert r["members"] == 1 and r["opened"] == 1 and r["orders"] == 1
    acc = sink.get("paper/m1_futures")
    pos = acc["positions"]["BTCUSDT"]
    assert pos["auto"] and pos["margin"] == 250 and pos["leverage"] == 5 and pos["stop"] == 96 and pos["take"] == 108
    od = next(iter(acc["orders"].values()))
    assert od["symbol"] == "ETH/USDT" and od["price"] == 100.0 and od["side"] == -1      # outside the zone: limit at the ideal entry
    assert abs(acc["wallet"] - (10_000 - 250 - pos["fees"] - od["reserve"])) < 1e-6
    assert sink.get("paper/gone_futures") is None and sink.get("paper/off_futures") is None
    assert len([1 for _ in sink.list("paper_futures_trades")]) == 1
    # next run: the same signals are not entered again
    r2 = autopaper.run(sink, rows, now + 900_000)
    assert r2["opened"] == 0 and r2["orders"] == 0
    st = sink.get("auto_paper_state/m1")
    assert len(st["log"]) == 2 and st["log"][0]["action"] in ("opened", "limit order")


def test_leverage_is_capped_so_liquidation_never_comes_before_the_stop(tmp_path):
    s = autopaper.settings_of({"leverage": 50, "margin": 100})
    acc, res = autopaper.place(None, {**row(), "timeframe": "1h"}, s, 1)
    p = acc["positions"]["BTCUSDT"]
    assert p["leverage"] < 50 and p["liq"] < p["stop"]
    poor = autopaper.new_account(1, balance=10)
    _, res = autopaper.place(poor, {**row(), "timeframe": "1h"}, autopaper.settings_of({"margin": 100}), 1)
    assert res["action"] == "skipped" and "balance" in res["reason"]
