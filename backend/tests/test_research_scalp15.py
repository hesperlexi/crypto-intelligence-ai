"""15m restart research: the free-ladder follower equals the record's rules at 1R / 50-25-25; variants behave sanely."""
import numpy as np

from app import research_scalp15 as X
from app.ml import series_policy as SP, series_sim as S
from tests.test_series_policy import _ctx


def _calls(ctx, n=300):
    ref = np.zeros(ctx.n, bool); ref[:600] = True
    d = SP.decide(ctx, ref)
    return d, np.flatnonzero(d["trade"])[:n]


def test_follow_x_equals_series_sim_follow_on_the_current_ladder():
    rng = np.random.default_rng(3)
    checked = 0
    for _ in range(3000):
        n = int(rng.integers(1, 60))
        px = 100 * np.exp(np.cumsum(rng.normal(0, 0.006, n)))
        hi = px * (1 + rng.uniform(0, 0.006, n)); lo = px * (1 - rng.uniform(0, 0.006, n))
        side = int(rng.choice([-1, 1]))
        entry = 100.0
        stop = entry - side * rng.uniform(0.3, 2.0)
        tps = S.ladder(side, entry, stop)
        fif, comp = bool(rng.random() < 0.3), bool(rng.random() < 0.8)
        a = S.follow(side, entry, stop, tps, hi, lo, px, first_is_fill=fif, complete=comp)
        b = X.follow_x(side, entry, stop, tps, S.TP_SPLIT, hi, lo, px, first_is_fill=fif, complete=comp)
        if a is None:
            assert b is None
            continue
        assert (b["status"], b["exit"], b["exit_idx"]) == (a.status, a.exit_reason, a.exit_idx)
        assert abs(b["return_pct"] - a.return_pct) < 1e-12 and abs(b["risk_pct"] - a.risk_pct) < 1e-12
        assert b["mae_pct"] >= 0
        if a.status == "STOPPED":
            assert b["mae_pct"] >= a.risk_pct - 1e-9         # reached the stop
        checked += 1
    assert checked > 1000


def test_all_at_tp1_closes_at_tp1():
    hi = np.array([100.2, 100.6, 101.5]); lo = np.array([99.8, 100.1, 100.4]); cl = np.array([100.1, 100.5, 101.2])
    o = X.follow_x(1, 100.0, 99.0, S.ladder(1, 100.0, 99.0, (0.5, 1.75, 2.5)), (1.0, 0, 0), hi, lo, cl)
    assert o["status"] == "TP1" and o["exit"] == "tp1" and o["exit_idx"] == 1 and abs(o["return_pct"] - 0.5) < 1e-12
    assert abs(o["mae_pct"] - 0.2) < 1e-9


def test_simulate_x_matches_horizon_research_at_current_rules():
    from app import research_horizon as H
    n = 0
    cases = []
    for seed in (7, 11, 5):
        ctx, paths, _ = _ctx(n=900, seed=seed)
        d, js = _calls(ctx)
        cases += [(ctx, paths, d, int(j), mode, k) for j in js
                  for mode, k in (("market", 0.0), ("confirm", 0.1), ("pullback", 0.25))]
    for ctx, paths, d, j, mode, k in cases:
        pl = d["plan"][j]
        a = H.simulate_h(ctx, paths, j, int(d["side"][j]), pl, mode, k, cost_pct=0.15, horizon=30)
        b = X.simulate_x(ctx, paths, j, int(d["side"][j]), pl, mode, k, 30, S.TP_LADDER, S.TP_SPLIT)
        if a is None:
            assert b is None
            continue
        assert a["filled"] == b["filled"] and a.get("open") == b.get("open")
        if a["filled"] and not a["open"]:
            assert abs(X.net_r(b, 0.15) - a["r"]) < 1e-12 and a["closed_ts"] == b["closed_ts"]
            n += 1
    assert n > 20


def test_nearer_tp1_raises_tp1_hits_and_liquidation_numbers():
    ctx, paths, _ = _ctx(n=900, seed=7)
    d, js = _calls(ctx)
    rows = {}
    for x in (0.3, 1.0):
        tr = []
        for j in js:
            r = X.simulate_x(ctx, paths, int(j), int(d["side"][j]), d["plan"][j], "market", 0.0, 30, (x, 1.75, 2.5), (1.0, 0, 0))
            if r and r["filled"] and not r["open"]:
                tr.append({**r, "ts": int(j), "grade": str(d["grade"][j])})
        rows[x] = X.stats_x(tr, 0.15, 10.0)
    assert rows[0.3]["tp1_hit_rate"] >= rows[1.0]["tp1_hit_rate"]
    for k in ("liquidated_20x", "liquidated_25x", "stop_beyond_liq_20x"):
        assert 0.0 <= rows[0.3][k] <= 1.0
    assert rows[0.3]["liquidated_25x"] >= rows[0.3]["liquidated_20x"]
    for lev in (20, 25):
        assert rows[0.3][f"liquidated_{lev}x"] <= rows[0.3][f"stop_beyond_liq_{lev}x"]
    assert abs(X.liq_dist_pct(20) - 4.5) < 1e-9 and abs(X.liq_dist_pct(25) - 3.5) < 1e-9


def test_variant_grid():
    v = X.variants()
    assert list(v)[0] == "AB_current_h30" and "AB_current_h250" in v
    assert sum(1 for k in v if k.startswith("A_")) == 4 * 2 * 2
    assert sum(1 for k in v if k.startswith("AB_tp")) == 4 * 2 * 2 - 2


def test_a_stop_nearer_than_liquidation_is_never_liquidated():
    # stop 2 % away, one candle runs 6 % through it: stopped at the stop, not liquidated at 20x (4.5 %) or 25x (3.5 %)
    t = {"ts": 1, "grade": "A", "status": "STOPPED", "exit": "stop", "return_pct": -2.0, "risk_pct": 2.0, "mae_pct": 6.0,
         "closed_ts": 900_000, "filled_ts": 0}
    st = X.stats_x([t], 0.15, 1.0)
    assert st["liquidated_20x"] == 0.0 and st["liquidated_25x"] == 0.0
    assert abs(st["roi_margin_avg_20x"] - (-2.15 * 20)) < 1e-9
    t2 = dict(t, risk_pct=4.0, return_pct=-4.0)
    st2 = X.stats_x([t2], 0.15, 1.0)
    assert st2["liquidated_20x"] == 0.0 and st2["liquidated_25x"] == 1.0 and st2["roi_margin_avg_25x"] == -100.0
