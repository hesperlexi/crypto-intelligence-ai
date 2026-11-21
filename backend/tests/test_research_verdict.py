"""v2.65 standard verdict + risk-study helpers."""
from app import research_risk as RR
from app.research_verdict import verdict

H = 3_600_000


def _t(i, r, sym="ETH/USDT", side=1):
    return {"ts": i * H, "closed_ts": i * H + 2 * H, "r": r, "sym": sym, "tf": "1h", "side": side}


def test_verdict_inconclusive_when_few_calls_differ():
    base = [_t(i, 0.1) for i in range(300)]
    assert verdict(base, base[:-5])["verdict"] == "INCONCLUSIVE"


def test_verdict_pass_when_removing_losers_everywhere():
    base = [_t(i * 24, 1.0 if i % 2 else -1.0) for i in range(600)]
    new = [t for t in base if t["r"] > 0 or t["ts"] % (4 * 24 * H)]
    v = verdict(base, new)
    assert v["verdict"] == "PASS" and v["new"]["total_r"] > v["base"]["total_r"]


def test_loss_stop_skips_after_a_bad_day():
    tr = [{"ts": i * H, "closed_ts": i * H + 1, "r": -1.0, "sym": "X", "tf": "1h", "side": 1} for i in range(1, 8)]
    kept = RR.loss_stop(tr, 3, 99)
    assert len(kept) == 3


def test_btc_shock_blocks_alt_longs_after_a_drop():
    import numpy as np
    bts = np.arange(0, 10) * H
    bclose = np.array([100, 100, 100, 96, 96, 96, 96, 96, 96, 96], float)   # -4 % in the hour opened at 3h
    tr = [_t(5, 1.0), _t(5, 1.0, sym="BTC/USDT"), _t(5, 1.0, side=-1), _t(9, 1.0)]
    out = RR.btc_shock(tr, bts, bclose, 3.0)
    assert [(t["sym"], t["side"], t["ts"]) for t in out] == [("BTC/USDT", 1, 5 * H), ("ETH/USDT", -1, 5 * H), ("ETH/USDT", 1, 9 * H)]


def test_risk_shadow_never_blocks_and_stays_private():
    from app.services import analysis, risk_shadow
    from .test_hesper import _rt
    rt = _rt()
    out = risk_shadow.assess(rt, "BTC/USDT", now=1_800_000_000_000)
    assert out["would_block"] is False and out["volatile"] is None
    assert "risk_shadow" not in analysis.public_view({"risk_shadow": out, "decision": "BUY"})
