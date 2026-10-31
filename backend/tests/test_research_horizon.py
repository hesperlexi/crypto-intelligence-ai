"""Time-limit research: horizon 30 reproduces series_policy.simulate exactly; longer horizons only add candles after it."""
import numpy as np

from app import research_horizon as H
from app.ml import series_policy as SP
from tests.test_series_policy import _ctx


def _calls(ctx, n=300):
    ref = np.zeros(ctx.n, bool); ref[:600] = True
    d = SP.decide(ctx, ref)
    js = np.flatnonzero(d["trade"])[:n]
    return d, js


def test_horizon_30_reproduces_simulate():
    ctx, paths, _ = _ctx(n=900, seed=7)
    d, js = _calls(ctx)
    checked = 0
    for mode, k in (("old", 0.0), ("market", 0.0), ("confirm", 0.1), ("pullback", 0.25)):
        for j in js:
            pl = d["plan"][j]
            ref = SP.simulate(ctx, paths, int(j), int(d["side"][j]), pl, mode, k)
            got = H.simulate_h(ctx, paths, int(j), int(d["side"][j]), pl, mode, k, horizon=30)
            if ref is None:
                assert got is None or got.get("open"), (j, got)
                continue
            assert got is not None and got["filled"] == ref["filled"]
            if ref["filled"]:
                for key in ("r", "status", "exit", "closed_ts", "entry", "risk_pct"):
                    assert got[key] == ref[key], (j, key, got[key], ref[key])
            checked += 1
    assert checked > 20


def test_candidates_and_taken_h30_match_the_research_pipeline():
    ctx, paths, _ = _ctx(n=900, seed=11)
    d, _ = _calls(ctx)
    mask = np.ones(ctx.n, bool)
    a = SP.taken(ctx, SP.candidates(ctx, paths, mask, d))
    b = [t for t in H.taken_h(ctx, H.candidates_h(ctx, paths, mask, d, horizon=30)) if not t.get("open")]
    # only a call unfinished at the very end of the data may differ (kept as open instead of skipped)
    assert [t["j"] for t in a][: len(b)] == [t["j"] for t in b][: len(a)]
    assert [round(t["r"], 12) for t in a][: len(b)] == [round(t["r"], 12) for t in b][: len(a)]


def test_longer_horizon_keeps_early_exits_and_no_limit_is_open_or_resolved():
    ctx, paths, _ = _ctx(n=900, seed=7)
    d, js = _calls(ctx)
    for j in js:
        pl = d["plan"][j]
        a = H.simulate_h(ctx, paths, int(j), int(d["side"][j]), pl, horizon=30)
        b = H.simulate_h(ctx, paths, int(j), int(d["side"][j]), pl, horizon=90)
        c = H.simulate_h(ctx, paths, int(j), int(d["side"][j]), pl, horizon=0)
        if not a or not a.get("filled") or a.get("open"):
            continue
        if a["exit"] != "expired":                       # closed before the old limit: identical under any horizon
            assert b["r"] == a["r"] and c["r"] == a["r"] and b["closed_ts"] == a["closed_ts"]
        assert c.get("open") or c["exit"] != "expired"  # no limit never expires


def test_stats_block():
    tr = [{"ts": 1, "r": 1.0, "closed_ts": 3_600_000 * 5, "filled_ts": 0, "exit": "tp3", "status": "TP3"},
          {"ts": 2, "r": -1.0, "closed_ts": 3_600_000 * 2, "filled_ts": 0, "exit": "expired", "status": "EXPIRED"},
          {"ts": 3, "open": True}]
    s = H.block_stats(tr, lambda t: 3_600_000, 1.0)
    assert s["n"] == 2 and s["open_at_data_end"] == 1 and s["expired_share"] == 0.5 and s["hold_candles_median"] == 3.5


def test_per_timeframe_plan():
    p = H.PLANS["proposal"]
    assert list(p)[0] == "current" and H.horizon_of(p["current"], "1h") == 30
    assert H.horizon_of(p["proposal_1d60"], "15m") == 250 and H.horizon_of(p["proposal_1d60"], "1d") == 60
    assert H.horizon_of(p["proposal_1d100"], "3d") == 30 and H.horizon_of(p["proposal_1d30"], "4h") == 100
    assert list(H.PLANS["uniform"]) == ["h30", "h60", "h90", "no_limit"]
