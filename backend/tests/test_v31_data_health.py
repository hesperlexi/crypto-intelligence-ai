"""v3.1: old source holes no longer degrade a fresh series; a coin Binance stopped trading moves to MEXC."""
import pandas as pd

from app.data.quality import check_candles

DAY = 86_400_000


def _df(ts):
    return pd.DataFrame({"ts": ts, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 1.0})


def test_old_gap_is_ok_recent_gap_is_degraded():
    now = 400 * DAY
    full = list(range(0, now, DAY))
    old_gap = [t for t in full if not (10 * DAY <= t < 20 * DAY)]        # a hole a year ago
    q = check_candles(_df(old_gap), "1d", now + DAY)
    assert q["quality_pct"] < 99 and q["recent_missing"] == 0 and q["status"] == "OK"
    recent_gap = [t for t in full if not ((now - 10 * DAY) <= t < (now - 5 * DAY))]
    q = check_candles(_df(recent_gap + [now - DAY]), "1d", now + DAY)
    assert q["recent_missing"] > 0 and q["status"] in ("OK", "DEGRADED")
    q2 = check_candles(_df([t for t in full if not ((now - 40 * DAY) <= t < (now - 5 * DAY))]), "1d", now + DAY)
    assert q2["status"] == "DEGRADED"


def test_delisted_coin_moves_to_mexc(monkeypatch):
    from app import worker
    from app.data import futures_only as F

    class DB:
        def __init__(self):
            self.s = {}
        def get_setting(self, k, d=None):
            return self.s.get(k, d)
        def set_setting(self, k, v):
            self.s[k] = v
        def one(self, sql, params):
            return {"ts": 1} if params[0] == "XMR/USDT" else {"ts": 10**13}

    class RT:
        db = DB()
        store = type("S", (), {"_cache": {}})()
        def symbols(self):
            return ["BTC/USDT", "XMR/USDT"]

    monkeypatch.setattr(F, "mexc_contract_for", lambda s, **k: "XMR_USDT" if s.startswith("XMR") else None)
    rt = RT()
    try:
        assert worker.delisted_to_mexc(rt, now=10**13) == ["XMR/USDT"]
        assert F.FUT_ONLY["XMR/USDT"] == "XMR_USDT"
        assert worker.delisted_to_mexc(rt, now=10**13 + 1000) == []          # checked at most every 6 h
    finally:
        F.FUT_ONLY.pop("XMR/USDT", None)
