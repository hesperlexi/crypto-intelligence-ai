"""V3.2 Stage 1 (Fable 5.2 audit): honest entry price (R-14), target horizon (R-10), risk-state order (R-16), dead code
(R-18)."""
from pathlib import Path

import numpy as np

from app.ml.distribution import first_passage_base_rate, first_passage_rates
from app.services import analysis, combo_gates, tracking

NOW = 1_795_000_000_000


class _Feed:
    def __init__(self, tickers, taken_ms=None):
        self.tickers = tickers
        self.taken_ms = taken_ms


class _RT:
    def __init__(self, tickers=None, taken_ms=None):
        self.feed = _Feed(tickers or {}, taken_ms)

    def ticker(self, s):
        return self.feed.tickers.get(s)


# ---- R-14 ------------------------------------------------------------------------------------------------------------
def test_live_quote_quality():
    ok = analysis.live_quote(_RT({"X": {"last": 101.0, "ts": NOW - 20_000}}), "X", 99.0, NOW)
    assert ok == {"price": 101.0, "source": "ticker", "quality": "live", "ts": NOW - 20_000, "age_s": 20.0}
    miss = analysis.live_quote(_RT({}), "X", 99.0, NOW)
    assert miss["price"] == 99.0 and miss["source"] == "last_close" and miss["quality"] == "missing"
    stale = analysis.live_quote(_RT({"X": {"last": 101.0, "ts": NOW - 3_600_000}}), "X", 99.0, NOW)
    assert stale["quality"] == "stale" and stale["price"] == 99.0 and stale["age_s"] == 3600.0
    bad = analysis.live_quote(_RT({"X": {"last": 0.0, "ts": NOW}}), "X", 99.0, NOW)
    assert bad["quality"] == "invalid" and bad["price"] == 99.0
    # a ticker without its own time uses the snapshot time of the feed
    snap = analysis.live_quote(_RT({"X": {"last": 101.0}}, taken_ms=NOW - 5_000), "X", 99.0, NOW)
    assert snap["quality"] == "live" and snap["ts"] == NOW - 5_000


def _call(decision="BUY", quality="live", price=100.0):
    setup = {"side_int": 1, "ideal_entry": 99.5, "stop": 97.0, "atr": 1.0, "risk_reward": 1.6,
             "targets": [{"price": 102.0, "rr": 1.0}, {"price": 104.0, "rr": 1.75}, {"price": 106.0, "rr": 2.5}]}
    pq = {"price": price, "source": "ticker" if quality == "live" else "last_close", "quality": quality,
          "ts": NOW, "age_s": 12.0 if quality == "live" else None}
    return {"decision": decision, "price": price, "setup": setup, "timeframe": "4h", "price_quality": pq}


def test_market_entry_needs_a_live_ticker():
    ok = tracking._plan(_call())
    assert ok["fill_status"] == "FILLED" and ok["entry"] == 100.0
    for q in ("missing", "stale", "invalid"):
        pl = tracking._plan(_call(quality=q))
        assert pl["entry"] is None and "no valid live price" in pl["skip"] and "old candle close" in pl["skip"]


def test_pending_fill_still_allowed_without_ticker():
    pl = tracking._plan(_call(decision="BUY ON PULLBACK", quality="missing"))
    assert pl["fill_status"] == "PENDING" and pl["entry"] == 99.5


def test_replays_without_price_quality_unchanged():
    a = _call()
    del a["price_quality"]
    assert tracking._plan(a)["fill_status"] == "FILLED"


# ---- R-10 ------------------------------------------------------------------------------------------------------------
def test_one_pass_base_rates_match_the_original():
    rng = np.random.default_rng(4)
    n = 4000
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    h, lo = c * (1 + abs(rng.normal(0, 0.002, n))), c * (1 - abs(rng.normal(0, 0.002, n)))
    a = np.full(n, 0.5)
    cond = rng.random(n) > 0.5
    for side in (1, -1):
        ups = [1.4, 1.75, 2.1, 2.8, 3.5, 4.2]
        many = first_passage_rates(h, lo, c, a, ups, 1.4, 250, cond, side)
        for u in ups:
            assert many[u] == first_passage_base_rate(h, lo, c, a, u, 1.4, 250, cond, side)


def test_analysis_passes_the_trade_horizon_to_the_setup(monkeypatch):
    from tests.helpers import shared_runtime
    rt, _ = shared_runtime()
    seen = []
    real = analysis.build_setup

    def spy(*a, **k):
        seen.append(k.get("horizon"))
        return real(*a, **k)
    monkeypatch.setattr(analysis, "build_setup", spy)
    for tf in ("4h", "1h"):
        seen.clear()
        out = analysis.analyze(rt, "BTC/USDT", tf, use_cache=False)
        assert seen and set(seen) == {tracking.horizon_for(tf)}
        if out.get("setup") and out["setup"].get("horizon_bars") is not None:
            assert out["setup"]["horizon_bars"] == tracking.horizon_for(tf)


def test_setup_horizon_is_the_record_horizon():
    assert {tf: tracking.horizon_for(tf) for tf in ("15m", "1h", "4h")} == {"15m": 250, "1h": 200, "4h": 100}


# ---- R-16 ------------------------------------------------------------------------------------------------------------
def test_risk_state_runs_before_the_analyses():
    src = (Path(__file__).resolve().parents[1] / "app" / "worker.py").read_text()
    assert src.count('step("risk_state"') == 1
    assert src.index('step("risk_state"') < src.index('step("analyses"')


# ---- R-18 ------------------------------------------------------------------------------------------------------------
class _DB:
    def __init__(self, total, mine):
        self.total, self.mine = total, mine

    def one(self, sql, args):
        return {"n": self.mine if "timeframe = ?" in sql else self.total}


def test_cap_block_unchanged_after_dead_code_removal(monkeypatch):
    monkeypatch.setattr(combo_gates, "SAME_SIDE_CAP", 12)
    monkeypatch.setattr(combo_gates, "SAME_SIDE_RESERVE", True)
    assert combo_gates.cap_block(_DB(11, 0), 1, "4h") is None
    assert "12 long calls" in combo_gates.cap_block(_DB(12, 3), 1, "4h")
    assert combo_gates.cap_block(_DB(12, 2), 1, "4h") is None              # V3.5: 3 per timeframe
    assert combo_gates.cap_block(_DB(12, 0), 1, "4h") is None              # the timeframe's reserved slot
    monkeypatch.setattr(combo_gates, "SAME_SIDE_CAP", 0)
    assert combo_gates.cap_block(_DB(50, 5), -1, "4h") is None
