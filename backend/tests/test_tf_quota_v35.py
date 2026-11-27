"""V3.5 (owner, 27 Nov 2026): one risk quota per timeframe and direction for the record."""
from app.services import portfolio_risk as PR
from tests.test_portfolio_risk_v33 import RT, NOW, _sig, _pos


def test_twelve_hour_shorts_never_use_up_the_15m_room():
    rt = RT()
    for i in range(3):
        _sig(rt.db, f"h{i}", f"C{i}/USDT", "12h", -1, stop=102.0)
    g12 = PR.record_gate(rt, "D/USDT", "12h", -1, NOW)
    assert g12["state"] == "block" and "12h" in g12["reason"] and "quota" in g12["reason"]   # 4th 12h short: quota 3
    assert PR.record_gate(rt, "E/USDT", "15m", -1, NOW)["state"] == "clear"                   # 15m keeps its own 3
    assert PR.record_gate(rt, "E/USDT", "4h", 1, NOW)["state"] == "clear"


def test_break_even_trades_free_the_quota_and_coin_rules_stay():
    rt = RT()
    for i in range(3):
        _sig(rt.db, f"h{i}", f"C{i}/USDT", "15m", -1, stop=102.0, tp1=True)          # after TP1 the stop is at entry: 0 R left
    assert PR.record_gate(rt, "D/USDT", "15m", -1, NOW)["state"] == "clear"
    _sig(rt.db, "x", "BTC/USDT", "12h", -1, stop=102.0)
    assert PR.record_gate(rt, "BTC/USDT", "15m", -1, NOW)["state"] == "block"          # one trade per coin
    assert PR.record_gate(rt, "BTC/USDT", "15m", 1, NOW)["state"] == "block"           # no long + short on a coin


def test_quota_off_restores_shared_limits():
    lim = {**PR.LIMITS, "tf_quota": False}
    pos = [_pos(f"C{i}/USDT", -1, tf="12h") for i in range(6)]
    assert not PR.check(pos, "E/USDT", -1, lambda s: 0.9, lim=lim, timeframe="15m")["allowed"]
    assert PR.check(pos, "E/USDT", -1, lambda s: 0.9, timeframe="15m")["allowed"]
