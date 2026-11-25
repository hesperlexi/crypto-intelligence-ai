"""v3.2 (owner, 25 Nov 2026): both challenges take up to 5 fresh grade-A calls at once, each sized so its stop costs a
fixed share of the balance (Hesper 10 %, Last Stand 15 %), one trade per coin, and rest 4 h after 2 losses in a row."""
import pytest

from app.services import hesper as H
from tests.test_hesper import NOW, STEP, _call, _put, _rt, _state, quiet  # noqa: F401


@pytest.fixture
def slots(monkeypatch):
    monkeypatch.setattr(H.Hesper, "SLOTS", 5)
    monkeypatch.setattr(H.Hesper, "RISK_PCT", 10.0)


def test_several_grade_a_calls_open_together_each_risking_ten_percent(quiet, slots):
    rt = _rt()
    for i, sym in enumerate(("BTC/USDT", "ETH/USDT", "SOL/USDT")):
        _put(rt, sym, NOW - 20 * STEP, [100.0] * 20)
        _call(rt.db, f"c{i}", symbol=sym, entry=100.0, stop=98.0)
    _call(rt.db, "dup", symbol="BTC/USDT", tf="4h", entry=100.0, stop=98.0)          # same coin: not a second trade
    eng = H.Hesper(rt)
    eng._price = lambda s: 100.0
    eng.run(NOW)
    st = _state(rt)
    assert len(st["positions"]) == 3 and {p["symbol"] for p in st["positions"]} == {"BTC/USDT", "ETH/USDT", "SOL/USDT"}
    for p in st["positions"]:
        loss_at_stop = p["qty"] * (p["entry"] - p["stop0"])
        assert loss_at_stop == pytest.approx(10.0, rel=0.05)                       # 10 % of the $100 start
        assert p["info"]["cfg"]["timeframe"] == "1h"
    v = H.view(rt)
    assert len(v["current"]["opens"]) == 3 and v["current"]["slots"] == 5 and v["current"]["risk_pct"] == 10.0


def test_two_losses_in_a_row_pause_new_entries_for_four_hours(quiet, slots):
    rt = _rt()
    eng = H.Hesper(rt)
    eng._price = lambda s: 100.0
    eng.run(NOW)
    st = _state(rt)
    for i in range(2):
        pos = {"id": f"p{i}", "symbol": "BTC/USDT", "side": 1, "entry": 100.0, "qty": 1.0, "qty_open": 0.0, "realized": -3.0,
               "exit_value": 97.0, "fees": 0.0, "tp_hit": 0, "opened_at": NOW, "margin": 10.0, "info": {"run": st["run"]}}
        st["positions"].append(pos)
        eng._close_trade(H.BOT_ID, st, pos, NOW + i, "stop")
    assert st["pause_until"] == NOW + 1 + H.Hesper.PAUSE_MS
    _put(rt, "ETH/USDT", NOW - 20 * STEP, [100.0] * 20)
    _call(rt.db, "late", symbol="ETH/USDT")
    assert eng._enter(st, NOW + 60_000) == []                                       # resting
