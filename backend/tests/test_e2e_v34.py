"""V3.4 Stage 7 end-to-end scenarios not covered elsewhere (the rest are mapped in the final report):
normal path (regime -> score -> advice), Fast Radar rejection for poor liquidity, engine restart with an open paper
position, missing data during an open position, a stale regime never trusted."""
from app.db import Database
from app.services import fast_radar as FR
from app.services import fast_strategy as FS
from app.services import market_regime as MR
from app.services import opportunity_score as OS
from app.services import strategy_select as SS
from tests.test_fast_strategy_v34 import NOW, RT, coin, snap
from tests.test_market_regime_v34 import base


def test_normal_conditions_end_to_end_is_advisory_only():
    reg = MR.classify(base())
    assert reg["primary"] == "strong_bull"
    a = {"status": "OK", "decision": "BUY", "timeframe": "4h", "price": 100.1, "last_close": 100.0, "quote_volume_24h": 200e6,
         "regime": {"group": "Bull", "regime": "BULL", "adx": 27}, "indicators": {"rsi": 58, "macd_hist": 0.2, "ema_50": 98, "ema_200": 95},
         "liquidity": {"relative_volume": 1.3, "buy_pressure": 0.57, "order_book": {"spread_bps": 2}}, "volatility": {"state": "normal"},
         "setup": {"side_int": 1, "ideal_entry": 100.0, "stop": 98.4, "atr": 1.0, "entry_zone": [99.8, 100.3], "risk_reward": 1.8},
         "forecast": {"available": True}, "flags": [], "price_quality": {"quality": "live"}}
    op = OS.score(a, {"regime": {"primary": reg["primary"]}})
    fit = SS.advise({**a, "opportunity": op}, {"main": {}}, reg["primary"])
    assert op["score"] >= 65 and fit["action"] == "TRADE" and "not yet proven" in fit["reason"]
    assert a["decision"] == "BUY"                                    # nothing above changed the decision


def test_fast_radar_rejects_poor_liquidity_and_the_strategy_never_takes_it():
    f = {"rs_7d_pct": 25.0, "rs_24h_pct": 9.0, "above_ema20": True, "above_ema50": True, "ema20_slope_6h_pct": 1.0,
         "ret_24h_pct": 9.0, "rsi14": 64.0, "volume_expansion": 2.0, "volatility_expansion": 1.6, "wick_share_24h": 0.2,
         "largest_1h_move_pct": 2.0, "bars": 200}
    j = FR.judge(f, quote_vol=4e6, spread_bps=35.0, regime="NORMAL")
    assert any("thin liquidity" in w for w in j["warnings"]) and any("wide spread" in w for w in j["warnings"])
    rt = RT()
    rt.db.set_setting("radar_fast_snapshot", snap([coin("THIN", warnings=j["warnings"], liquidity_ok=False)]))
    assert FS.run(rt, NOW)["opened"] == []


def test_engine_restart_with_an_open_paper_position():
    path = "sqlite:///:memory:"
    rt = RT()
    rt.db.set_setting("radar_fast_snapshot", snap([coin()]))
    FS.run(rt, NOW)
    assert len(FS.open_trades(rt.db)) == 1
    # "restart": a new runtime on the same database (state is only in SQLite), then the stop is hit on later bars
    rt2 = RT()
    rt2.db = rt.db
    bars = [[NOW + i * 3_600_000, 100.5, 97.0 if i == 2 else 99.6, 99.7] for i in range(1, 4)]
    rt2.db.set_setting("radar_fast_snapshot", snap([coin(bars=bars)], at=NOW + 4 * 3_600_000))
    out = FS.run(rt2, NOW + 4 * 3_600_000)
    assert out["closed"] and out["closed"][0]["reason"] == "stop" and not FS.open_trades(rt2.db)
    assert path


def test_stale_regime_is_never_used():
    db = Database("sqlite:///:memory:")
    db.set_setting("market_regime", {"at": NOW - 2 * 3_600_000, "regime": "strong_bull"})
    assert MR.current(db, NOW) is None                              # older than 30 min: treated as missing
    assert SS.advise({"status": "OK", "decision": "BUY", "timeframe": "1h", "forecast": {"available": True}, "flags": []},
                     None, None)["fit"]["state"] == "unproven"
