"""V3.4 Stage 3D: isolated Fast Opportunity paper strategy - own book, 0.25 % risk, costs, duplicates, cooldown, regime
rules, central portfolio approval, outage behaviour, promotion never automatic, no link to the trading engine."""
import re
from pathlib import Path

from app.db import Database
from app.services import fast_strategy as FS
from app.services import portfolio_risk as PR

H = 3_600_000
NOW = 1_795_700_000_000 // H * H


class RT:
    def __init__(self):
        self.db = Database("sqlite:///:memory:")

    def candles(self, s, tf):
        return None


def coin(name="AAA", price=100.0, bars=None, **over):
    bars = bars if bars is not None else [[NOW - (6 - i) * H, price * 1.001, price * 0.999, price] for i in range(6)]
    x = {"coin": name, "symbol": f"{name}/USDT", "category": "alt", "source": "Binance spot", "score": 0.6,
         "category_rank": 1, "flagged": True, "price": price, "warnings": [], "liquidity_ok": True, "spread_bps": 2.0,
         "above_ema20": True, "above_ema50": True, "atr_24": 1.0, "recent_bars": bars}
    x.update(over)
    return x


def snap(coins, at=NOW, regime="NORMAL", mregime="weak_bull"):
    return {"at": at, "regime": regime, "market_regime": mregime, "coins": coins}


def test_entry_size_costs_and_record():
    rt = RT()
    rt.db.set_setting("radar_fast_snapshot", snap([coin()]))
    out = FS.run(rt, NOW)
    assert len(out["opened"]) == 1
    t = FS.open_trades(rt.db)[0]
    assert abs(t["risk_usd"] - 10_000 * 0.0025) < 0.01                  # 0.25 % of equity
    assert t["entry"] > 100 and t["stop0"] == 98.0 and t["target"] > t["entry"]
    assert t["cost_pct"] > 0.001                                       # fee + slippage + half spread
    assert FS.run(rt, NOW)["opened"] == []                             # same bar never taken twice


def test_risk_never_above_default():
    rt = RT()
    rt.db.set_setting("fast_strategy_config", {"risk_pct": 2.0})
    assert FS.config(rt.db)["risk_pct"] == 0.25


def test_regime_and_risk_restrictions_and_stale_snapshot():
    for kw in ({"mregime": "weak_bear"}, {"mregime": "uncertain"}, {"mregime": None}, {"regime": "SEVERE"},
               {"at": NOW - 5 * H}):
        rt = RT()
        rt.db.set_setting("radar_fast_snapshot", snap([coin()], **kw))
        out = FS.run(rt, NOW)
        assert out["opened"] == [] and out["skipped"], kw


def test_warnings_or_thin_liquidity_are_never_taken():
    rt = RT()
    rt.db.set_setting("radar_fast_snapshot", snap([coin("W", warnings=["parabolic"]), coin("T", liquidity_ok=False),
                                               coin("R", category_rank=4), coin("E", above_ema50=False)]))
    assert FS.run(rt, NOW)["opened"] == []


def test_portfolio_controller_is_asked(monkeypatch):
    rt = RT()
    rt.db.set_setting("radar_fast_snapshot", snap([coin()]))
    monkeypatch.setattr(PR, "book_check", lambda *a, **k: {"allowed": False, "reason": "PORTFOLIO LIMIT"})
    out = FS.run(rt, NOW)
    assert out["opened"] == [] and any("PORTFOLIO LIMIT" in s for s in out["skipped"])


def _open(rt):
    rt.db.set_setting("radar_fast_snapshot", snap([coin()]))
    FS.run(rt, NOW)
    return FS.open_trades(rt.db)[0]


def test_stop_then_cooldown_and_costs_in_result():
    rt = RT()
    t = _open(rt)
    later = [[NOW + i * H, 100.5, 97.0 if i == 1 else 99.5, 99.0] for i in range(0, 3)]
    rt.db.set_setting("radar_fast_snapshot", snap([coin(bars=later)], at=NOW + 3 * H))
    out = FS.run(rt, NOW + 3 * H)
    assert out["closed"] and out["closed"][0]["reason"] == "stop" and out["closed"][0]["r"] < -1.0   # costs make it worse
    assert out["opened"] == []                                         # cooldown
    st = FS.stats(rt.db)
    assert st["overall"]["n"] == 1 and st["fees"] > 0


def test_target_and_break_even():
    rt = RT()
    t = _open(rt)
    risk = t["entry"] - t["stop0"]
    bars = [[NOW, t["entry"] + risk * 1.2, t["entry"] + 0.1, t["entry"] + risk * 1.1],
            [NOW + H, t["entry"] + 0.2, t["entry"] - 0.05, t["entry"]]]
    rt.db.set_setting("radar_fast_snapshot", snap([coin(bars=bars)], at=NOW + 2 * H))
    out = FS.run(rt, NOW + 2 * H)
    assert out["closed"][0]["reason"] == "break-even"
    rt2 = RT()
    t2 = _open(rt2)
    bars = [[NOW, t2["target"] + 1, t2["entry"], t2["target"]]]
    rt2.db.set_setting("radar_fast_snapshot", snap([coin(bars=bars)], at=NOW + H))
    c = FS.run(rt2, NOW + H)["closed"][0]
    assert c["reason"] == "target" and 1.5 < c["r"] < 2.0


def test_outage_assumes_nothing_then_catches_up():
    rt = RT()
    _open(rt)
    rt.db.set_setting("radar_fast_snapshot", snap([], at=NOW + 10 * H))     # coin missing for hours
    assert FS.run(rt, NOW + 10 * H)["closed"] == [] and len(FS.open_trades(rt.db)) == 1
    bars = [[NOW + i * H, 101, 97.5 if i == 3 else 99.6, 99.8] for i in range(1, 5)]
    rt.db.set_setting("radar_fast_snapshot", snap([coin(bars=bars)], at=NOW + 11 * H))
    assert FS.run(rt, NOW + 11 * H)["closed"][0]["reason"] == "stop"


def test_promotion_is_never_automatic():
    rt = RT()
    p = FS.promotion(rt.db)
    assert p["eligible"] is False and p["promoted"] is False
    assert any("300" in f for f in p["failed"]) and any("holdout" in f for f in p["failed"])


def test_isolated_from_the_trading_engine():
    app = Path(FS.__file__).resolve().parents[1]
    users = sorted(str(p.relative_to(app)) for p in app.rglob("*.py")
                   if re.search(r"import fast_strategy|\bfast_strategy\.", p.read_text()) and p.name != "fast_strategy.py")
    assert users == ["services/perf_lab.py", "worker.py"]
    src = Path(FS.__file__).read_text()
    assert "import fast_radar" not in src and "from .fast_radar" not in src
    for forbidden in ("tracking", "bots", "hesper", "autopaper", "telegram", "alerts"):
        assert f"from . import {forbidden}" not in src and f"from .{forbidden}" not in src
