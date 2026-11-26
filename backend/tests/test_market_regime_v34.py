"""V3.4 Stage 3A: market regime engine - evidence, honest data status, persistence, no look-ahead, no authority."""
import re
from pathlib import Path

import numpy as np
import pandas as pd

from app.services import market_regime as MR
from tests.test_market_intel_v33 import RT, NOW, H, _candles


def f(value, status="confirmed", **extra):
    return {"value": value, "status": status, "as_of": NOW, "source": "t", **extra}


NA = {"value": None, "status": "unavailable"}


def base(**over):
    x = {"regime_4h": f("STRONG BULL", score=0.8), "regime_1d": f("BULL"), "structure": f("inside range", volume_x=1.0),
         "volatility": f("normal", atr_ratio=1.0), "breadth": f(0.75), "eth_rs": f(3.0), "alt_rs": f(2.5),
         "dominance": f(58.0, change_7d_pts=-1.2), "funding": f(0.01), "open_interest": f(1e9, change_24h_pct=2.0),
         "liquidations": f(1e6, longs_24h=3e5, shorts_24h=7e5), "spot": f(1.1)}
    x.update(over)
    return x


def test_strong_bull_with_evidence_and_confidence():
    c = MR.classify(base())
    assert c["primary"] == "strong_bull" and c["confidence"] == "high" and c["data_quality"] == "good"
    assert c["agreement"] and c["agreement"] >= 0.75 and "not a probability" in c["agreement_basis"]
    names = {e["input"] for e in c["evidence"]}
    assert {"BTC regime 4h", "Breadth (above 4h EMA50)", "BTC dominance, 7 d", "BTC funding per 8 h"} <= names
    assert all(e["status"] for e in c["evidence"])


def test_weak_bull_when_breadth_or_daily_disagree():
    assert MR.classify(base(breadth=f(0.5)))["primary"] == "weak_bull"
    assert MR.classify(base(regime_1d=f("BEAR"), breadth=f(0.62)))["primary"] == "weak_bull"


def test_bear_sideways_unstable_breakout():
    bear = base(regime_4h=f("STRONG BEAR"), regime_1d=f("BEAR"), breadth=f(0.2), eth_rs=f(-6), alt_rs=f(-6),
                dominance=f(60, change_7d_pts=1.5), liquidations=f(1, longs_24h=9, shorts_24h=1))
    assert MR.classify(bear)["primary"] == "strong_bear"
    assert MR.classify(base(regime_4h=f("NEUTRAL")))["primary"] == "sideways"
    assert MR.classify(base(regime_4h=f("HIGH-VOLATILITY / UNSTABLE")))["primary"] == "unstable"
    assert MR.classify(base(volatility=f("extreme")))["primary"] == "unstable"
    bo = MR.classify(base(structure=f("breakout", volume_x=1.6)))
    assert bo["primary"] == "breakout" and "volume" in bo["reasons"][0]
    assert MR.classify(base(structure=f("breakout", volume_x=1.0)))["primary"] != "breakout"   # no volume, no breakout
    assert MR.classify(bear | {"structure": f("breakdown", volume_x=1.5)})["primary"] == "breakdown"


def test_volatility_overlay_labels():
    assert "high_volatility" in MR.classify(base(volatility=f("high")))["labels"]
    assert "low_volatility" in MR.classify(base(volatility=f("low")))["labels"]


def test_missing_core_data_is_uncertain_never_a_trend():
    c = MR.classify(base(regime_4h=NA, breadth=NA))
    assert c["primary"] == "uncertain" and c["confidence"] == "low" and c["data_quality"] == "poor"
    c = MR.classify({k: NA for k in base()})
    assert c["primary"] == "uncertain" and c["inputs"]["unavailable"] == 12


def test_conflicting_evidence_is_uncertain():
    c = MR.classify(base(regime_4h=f("BULL"), regime_1d=f("BEAR"), breadth=f(0.3), eth_rs=f(-6), alt_rs=f(-6),
                         dominance=f(60, change_7d_pts=2), liquidations=f(1, longs_24h=9, shorts_24h=1)))
    assert c["primary"] == "uncertain"


def test_transition_needs_persistence():
    s = MR.advance(None, {"primary": "weak_bull"}, NOW)
    assert s["confirmed"] == "weak_bull"
    for i in range(1, 3):                                         # two runs of a new label: still pending
        s = MR.advance(s, {"primary": "sideways"}, NOW + i * 4 * 60_000)
        assert s["confirmed"] == "weak_bull" and s["pending"]["label"] == "sideways"
    s = MR.advance(s, {"primary": "sideways"}, NOW + 12 * 60_000)  # 3 runs but < 30 min
    assert s["confirmed"] == "weak_bull"
    s = MR.advance(s, {"primary": "sideways"}, NOW + 40 * 60_000)
    assert s["confirmed"] == "sideways" and s["changed"] and s["previous"] == "weak_bull"
    s2 = MR.advance(s, {"primary": "weak_bear"}, NOW + 44 * 60_000)
    s2 = MR.advance(s2, {"primary": "sideways"}, NOW + 48 * 60_000)  # flip-back resets the pending label
    assert s2["confirmed"] == "sideways" and s2["pending"] is None


def test_structure_uses_closed_candles_only():
    df = _candles(200, 4 * H, trend=0.0)
    rt = RT({("BTC/USDT", "4h"): df})
    a = MR.structure(rt, NOW)
    forming = df.iloc[[-1]].copy()
    forming["ts"] = NOW
    forming[["open", "high", "low", "close"]] = 1e6                 # a huge breakout in a still-forming candle
    rt.frames[("BTC/USDT", "4h")] = pd.concat([df, forming], ignore_index=True)
    assert MR.structure(rt, NOW)["value"] == a["value"]
    up = df.copy()
    up.loc[up.index[-1], ["close", "high"]] = float(df["high"].max()) * 1.05
    assert MR.structure(RT({("BTC/USDT", "4h"): up}), NOW)["value"] == "breakout"


def test_dominance_reads_only_known_snapshots():
    rt = RT()
    rt.db.execute("CREATE TABLE IF NOT EXISTS market_snapshots (ts INTEGER PRIMARY KEY, btc_dom REAL, eth_dom REAL, "
                  "stable_share REAL, total_mcap REAL, mcap_change_24h REAL, fetched_at INTEGER, source TEXT)")
    for d in range(8, -1, -1):
        rt.db.execute("INSERT INTO market_snapshots (ts, btc_dom, fetched_at) VALUES (?, ?, ?)",
                      (NOW - d * 24 * H - H, 60 - d * 0.2, NOW - d * 24 * H - 60_000))
    rt.db.execute("INSERT INTO market_snapshots (ts, btc_dom, fetched_at) VALUES (?, ?, ?)", (NOW + H, 99, NOW + H))
    d = MR.dominance(rt.db, NOW)
    assert d["status"] == "confirmed" and d["value"] < 61 and d["change_7d_pts"] > 0


def test_build_and_run_on_empty_runtime():
    rt = RT()
    v = MR.build(rt, NOW)
    assert v["primary"] == "uncertain" and v["regime"] == "uncertain" and "never" in v["authority"]

    class Sink:
        def __init__(self):
            self.views = {}

        def view(self, name, payload, **kw):
            self.views[name] = payload
    s = Sink()
    out = MR.run(rt, s, NOW)
    assert out["regime"] == "uncertain" and "market_regime" in s.views and "at" not in s.views["market_regime"]
    assert MR.current(rt.db, NOW)["regime"] == "uncertain"
    assert MR.compact(MR.current(rt.db, NOW))["primary"] == "uncertain"


def test_regime_has_no_trade_authority():
    src = Path(__file__).resolve().parents[1] / "app" / "services" / "analysis.py"
    text = src.read_text()
    uses = [m.start() for m in re.finditer(r"market_regime\.", text)]
    assert uses, "regime should be stored with calls"
    for i in uses:              # only ever stored as context (the call's risk_check, the opportunity score), never decides
        line = text[text.rfind("\n", 0, i) + 1:text.find("\n", i)]
        assert 'risk_check["regime"]' in line or "octx = " in line, line
        assert "decision" not in line
