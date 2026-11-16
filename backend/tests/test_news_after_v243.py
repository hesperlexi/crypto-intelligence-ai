"""v2.43: after a high-impact release the news view shows the surprise reading and BTC's actual reaction."""
import pandas as pd

from app.services import news


def _candles(t0, prices):
    rows = []
    for i, p in enumerate(prices):
        rows.append({"ts": t0 + i * 900_000, "open": p[0], "high": max(p) * 1.001, "low": min(p) * 0.999, "close": p[1]})
    return pd.DataFrame(rows)


def test_surprise_reading():
    assert news.parse_num("3.1%") == 3.1 and news.parse_num("256K") == 256000 and news.parse_num(None) is None
    hot = news.surprise({"title": "CPI m/m", "actual": "0.4%", "forecast": "0.3%"})
    assert hot["read"] == "bearish" and "hotter" in hot["words"]
    claims = news.surprise({"title": "Unemployment Claims", "actual": "250K", "forecast": "230K"})
    assert claims["read"] == "bullish"
    assert news.surprise({"title": "CPI m/m", "actual": None, "forecast": "0.3%"}) is None


def test_after_release_uses_btc_reaction():
    t0 = 1_800_000_000_000 - (1_800_000_000_000 % 900_000)
    df = _candles(t0, [(100, 99.5), (99.5, 99.0), (99.0, 98.8), (98.8, 98.9)] + [(98.9, 98.9)] * 16)
    e = {"title": "CPI m/m", "impact": "High", "country": "USD", "ts": t0 + 60_000, "actual": "0.4%", "forecast": "0.3%"}
    a = news.after_release(e, df, t0 + 5 * 3_600_000)
    assert a["verdict"] == "bearish" and a["data_read"] == "bearish" and a["move_1h"] == -1.1
    assert "hotter than expected" in a["summary"] and "BTC fell 1.10%" in a["summary"]
    # no actual in the calendar: reaction only
    a2 = news.after_release({**e, "actual": None}, df, t0 + 5 * 3_600_000)
    assert a2["data_read"] is None and a2["verdict"] == "bearish"
    # too early: nothing yet
    assert news.after_release({**e, "actual": None}, df, e["ts"] + 60_000) is None
