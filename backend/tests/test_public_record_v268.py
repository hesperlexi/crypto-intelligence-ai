"""v2.68 public results page: summary and closed calls only - never an open call or any price level."""
from app import views


def test_public_record_hides_levels_and_open_calls():
    tr = {"record_since": 1, "live": {"summary": {"closed": 2, "win_rate": 0.5, "total_return_pct": 1.2, "secret": 9},
                                       "by_timeframe": {"4h": {"closed": 2, "win_rate": 0.5}}, "open": 1,
                                       "curve": [{"ts": 1795200000000, "cum_return_pct": 1.2}],
                                       "signals": [
        {"symbol": "BTC/USDT", "timeframe": "4h", "side": "LONG", "status": "OPEN", "entry": 1, "stop": 0.9, "tp1": 1.1, "return_pct": None},
        {"symbol": "ETH/USDT", "timeframe": "4h", "side": "SHORT", "status": "TP2", "entry": 2, "stop": 2.1, "tp1": 1.9, "return_pct": 1.5, "closed_at": 5},
        {"symbol": "SOL/USDT", "timeframe": "4h", "side": "LONG", "status": "STOPPED", "entry": 3, "stop": 2.9, "return_pct": -0.3, "closed_at": 4}]},
          "last_7d": {"closed": 2, "wins": 1}, "method": {"live": "m"}}
    p = views.public_record(tr)
    assert [r["symbol"] for r in p["recent"]] == ["ETH/USDT", "SOL/USDT"]
    text = str(p)
    for k in ("'entry'", "'stop'", "'tp1'", "secret", "BTC/USDT"):
        assert k not in text
    assert p["summary"]["closed"] == 2 and p["daily"][0]["cum"] == 1.2
