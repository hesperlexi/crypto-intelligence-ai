"""V3.4 Stage 3B: opportunity score - transparent components, honest coverage, independent validation, no authority."""
import re
from pathlib import Path

from app.services import opportunity_score as OS


def analysis(**over):
    a = {"status": "OK", "decision": "BUY", "price": 100.2, "last_close": 100.0, "quote_volume_24h": 250e6,
         "regime": {"group": "Bull", "regime": "BULL", "adx": 28},
         "indicators": {"rsi": 60, "macd_hist": 0.4, "ema_50": 98, "ema_200": 95, "atr": 1.0},
         "liquidity": {"relative_volume": 1.4, "buy_pressure": 0.6, "order_book": {"spread_bps": 2}},
         "volatility": {"state": "normal"},
         "setup": {"side_int": 1, "ideal_entry": 100.0, "stop": 98.5, "atr": 1.0, "entry_zone": [99.8, 100.4],
                   "risk_reward": 1.9},
         "price_quality": {"quality": "live", "age_s": 3}, "flags": [], "bar_close_ts": 1}
    a.update(over)
    return a


CTX = {"regime": {"primary": "weak_bull"}, "intel": {"relative_strength": {"status": "confirmed", "rs_7d_pct": 3.0}},
       "correlation": {"same_side_corr_r": 1.0, "limit_r": 5}}


def test_good_long_scores_high_with_all_components():
    op = OS.score(analysis(), CTX)
    assert op["side"] == "LONG" and op["coverage"] == 1.0 and op["score"] >= 70
    assert set(op["components"]) == set(OS.COMPONENTS)
    assert "not a chance of winning" in op["label"] and op["weights"].startswith("equal")
    assert op["positive"] and not op["rejection"]


def test_bad_short_into_bull_market_scores_low():
    a = analysis(decision="SELL", setup={"side_int": -1, "ideal_entry": 100.0, "stop": 100.2, "atr": 1.0,
                                         "entry_zone": [100.0, 100.3], "risk_reward": 1.1})
    op = OS.score(a, CTX)
    assert op["side"] == "SHORT" and op["score"] < 50
    assert OS.score(analysis(), CTX)["score"] - op["score"] >= 25
    neg = " ".join(op["negative"])
    assert "regime" in neg or "trend" in neg
    assert op["components"]["costs"]["score"] <= 45                 # 0.2 % stop vs ~0.3 % costs


def test_missing_inputs_lower_coverage_not_score():
    op = OS.score(analysis(indicators={}, liquidity={}, quote_volume_24h=None), {})
    assert op["coverage"] < 0.7
    assert op["components"]["correlation"]["status"] == "unavailable"
    assert op["components"]["regime"]["status"] == "unavailable"


def test_no_trade_lists_rejection_reasons_and_warnings():
    a = analysis(decision="NO TRADE", flags=["PORTFOLIO LIMIT", "NO TRADE"], decision_reason="portfolio full",
                 quote_volume_24h=3e6, liquidity={"order_book": {"spread_bps": 40}, "relative_volume": 1.0},
                 price_quality={"quality": "stale"})
    op = OS.score(a, CTX)
    assert op["rejection"] == ["PORTFOLIO LIMIT"] and op["rejection_reason"] == "portfolio full" and not op["is_trade_call"]
    assert any("liquidity" in w for w in op["warnings"]) and "price stale" in op["warnings"]


def test_no_side_no_score():
    assert OS.score(analysis(decision="NO TRADE", setup=None), CTX) is None
    assert OS.score({"status": "INSUFFICIENT DATA"}, CTX) is None


def test_chasing_past_zone_is_penalised():
    near = OS.score(analysis(), CTX)["components"]["entry"]["score"]
    far = OS.score(analysis(price=103.0), CTX)["components"]["entry"]["score"]
    assert far < near and far <= 35


def test_evaluate_each_component_independently():
    rows = []
    for i in range(120):
        hi = i % 2 == 0
        rows.append({"opportunity": {"score": 80 if hi else 30, "components": {"reward": 90 if hi else 20, "trend": 50}},
                     "net_r": 0.5 if hi else -0.4})
    ev = OS.evaluate(rows)
    assert ev["score"]["enough"] and ev["score"]["spread_r"] > 0.5
    assert ev["reward"]["spread_r"] > 0.5 and ev["trend"]["n"] == 120
    assert ev["momentum"]["n"] == 0 and not ev["momentum"]["enough"]
    assert not OS.evaluate(rows[:30])["score"]["enough"]


def test_score_has_no_trade_authority():
    text = (Path(__file__).resolve().parents[1] / "app" / "services" / "analysis.py").read_text()
    for m in re.finditer(r"\bOS\.|opportunity", text):
        line = text[text.rfind("\n", 0, m.start()) + 1:text.find("\n", m.start())]
        assert "decision" not in line.split("#")[0] or "side_of" in line, line
