"""v2.6 accuracy upgrades: simulator, series gate, per-series confidence, entries, structure stops - on synthetic data."""
import numpy as np
import pandas as pd

from app.engine import manage as M
from app.ml import series_policy as SP
from app.ml import series_sim as S


def _path(rng, n=60, px=100.0, vol=0.006):
    cl = px * np.exp(np.cumsum(rng.normal(0, vol, n)))
    op = np.concatenate([[px], cl[:-1]])
    hi = np.maximum(op, cl) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    lo = np.minimum(op, cl) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    return pd.DataFrame({"ts": np.arange(n) * 900_000, "open": op, "high": hi, "low": lo, "close": cl})


def test_follow_matches_the_record_rules():
    rng = np.random.default_rng(1)
    for trial in range(400):
        df = _path(rng)
        side = 1 if trial % 2 else -1
        entry = float(df["open"].iloc[0])
        dist = entry * rng.uniform(0.003, 0.02)
        stop = entry - side * dist
        tps = S.ladder(side, entry, stop)
        fill = bool(trial % 3 == 0)
        ref = M.follow(side, entry, stop, tps, df, complete=True, first_is_fill=fill)
        got = S.follow(side, entry, stop, tps, df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy(),
                       first_is_fill=fill, complete=True)
        assert got.status == ref["status"], (trial, got, ref["status"])
        assert abs(got.return_pct - ref["return_pct"]) < 1e-9
        assert got.exit_reason == ref["exit_reason"]


def test_follow_unfinished_is_none():
    hi = np.array([100.5, 100.6]); lo = np.array([99.5, 99.6]); cl = np.array([100.0, 100.1])
    assert S.follow(1, 100.0, 98.0, [102, 103.5, 105], hi, lo, cl, complete=False) is None
    o = S.follow(1, 100.0, 98.0, [102, 103.5, 105], hi, lo, cl, complete=True)
    assert o.status == "EXPIRED" and abs(o.return_pct - 0.1) < 1e-9


def test_gate_needs_a_credibly_positive_expectancy():
    rng = np.random.default_rng(0)
    assert S.gate_decision([0.5] * 10, 30, 0.8)["verdict"] == "too_few"          # no verdict: current behaviour
    assert not S.gate_decision([0.5] * 10, 30, 0.8)["blocked"]
    good = list(rng.normal(0.3, 1.0, 200))
    bad = list(rng.normal(-0.1, 1.0, 200))
    flat = list(rng.normal(0.0, 1.0, 40))
    assert not S.gate_decision(good, 30, 0.8)["blocked"]
    assert S.gate_decision(bad, 30, 0.8)["blocked"]
    g = S.gate_decision(flat, 30, 0.95)
    assert g["lb"] < g["mean_r"]                                                  # a lower bound, not the mean


def test_plan_structure_stop_is_bounded_and_uses_the_nearest_level():
    zones = {"support": [{"low": 98.0, "high": 98.4}], "resistance": [{"low": 120.0, "high": 121.0}]}
    cur = S.plan(1, 100.0, 1.0, None, zones, 96.0, 105.0, "current")
    st = S.plan(1, 100.0, 1.0, None, zones, 96.0, 105.0, "struct")
    # current: the farthest of the levels (96) - 0.25 ATR, clipped to 3 ATR; struct: the nearest (98) - 0.25 ATR
    assert abs(cur["dist"] - 3.0) < 1e-9
    assert 0.8 <= st["dist"] <= 3.5 and st["dist"] < cur["dist"]
    far = S.plan(1, 100.0, 1.0, None, {"support": [], "resistance": []}, 80.0, 105.0, "struct")
    assert abs(far["dist"] - 3.5) < 1e-9                                         # bounded at 3.5 ATR
    blocked = S.plan(1, 100.0, 1.0, None, {"support": [], "resistance": [{"low": 100.5, "high": 101}]}, 98.0, 105, "current")
    assert not blocked["valid"]


def test_fill_modes_never_use_the_future_beyond_the_window():
    pl = {"stop": 98.0, "ideal": 99.5, "extended": True}
    hi = np.array([100.2, 100.4, 101.0, 102.0]); lo = np.array([99.8, 99.9, 99.4, 99.0])
    cl = np.array([100.1, 100.3, 100.9, 101.8])
    assert S.fill("market", 1, 100.0, 1.0, pl, hi, lo, cl, 2) == (0, 100.0, False)
    assert S.fill("old", 1, 100.0, 1.0, pl, hi, lo, cl, 2) is None              # the limit trades only in candle 3
    assert S.fill("old", 1, 100.0, 1.0, pl, hi, lo, cl, 3) == (2, 99.5, True)
    # confirmation: first close above 100 + 0.25 ATR is candle 1 (100.3); the trade starts with candle 2 at that close
    assert S.fill("confirm", 1, 100.0, 1.0, pl, hi, lo, cl, 3, 0.25) == (2, 100.3, False)
    assert S.fill("confirm", 1, 100.0, 1.0, pl, hi, lo, cl, 1, 0.25) is None


def test_take_one_call_at_a_time_with_cooldown():
    ts = np.array([0, 10, 20, 30, 40]); closed = np.array([25, 15, 35, 45, 60])
    assert list(SP.take(ts, closed, step=5, cooldown_bars=0)) == [0, 3]
    assert list(SP.take(ts, closed, step=5, cooldown_bars=2)) == [0, 4]


def test_confidence_against_reference_only():
    rng = np.random.default_rng(3)
    n = 600
    side = np.where(rng.random(n) < 0.5, 1.0, -1.0); margin = rng.uniform(0, 0.3, n)
    hit = (rng.random(n) < 0.55).astype(float)
    c = SP._confidence(side[:400], margin[:400], hit[:400], side, margin)
    # changing outcomes AFTER the reference rows must not change any confidence (no look-ahead)
    hit2 = hit.copy(); hit2[400:] = 1 - hit2[400:]
    c2 = SP._confidence(side[:400], margin[:400], hit2[:400], side, margin)
    assert np.allclose(np.nan_to_num(c), np.nan_to_num(c2)) and np.isfinite(c).mean() > 0.9


def _ctx(n=900, seed=5, edge=0.0):
    """A minimal Context on a synthetic 1h series (P leans the way the next bar goes with probability 0.5 + edge)."""
    from app.features.dataset import build_frame
    from tests.helpers import synthetic_candles
    df = synthetic_candles(n + 400, "1h", seed=seed)
    fr = build_frame(df, "1h")
    rng = np.random.default_rng(seed)
    fwd = np.sign(df["close"].shift(-1) - df["close"]).to_numpy()[-n - 1:-1]
    lean = np.where(rng.random(n) < 0.5 + edge, fwd, -fwd)
    p_up = 0.33 + 0.12 * lean * rng.uniform(0.2, 1.0, n)
    P = np.column_stack([0.66 - p_up, np.full(n, 0.34), p_up])
    bundle = {"oos": {"ts": df["ts"].to_numpy()[-n - 1:-1], "P_ens": P, "fwd_ret": fwd},
              "edge": {"edge_confirmed": True}}
    ctx = SP.build_context("BTC/USDT", "1h", bundle, {"1h": fr}, None)
    return ctx, SP.Paths(None, df), df


def test_context_is_causal_and_decide_runs():
    ctx, paths, df = _ctx()
    assert ctx.n == 900
    # S/R zones at row j only use swings confirmed by its bar
    j = 500
    z = ctx.zones(j)
    for side in ("support", "resistance"):
        for zz in z[side]:
            assert zz["last_touch_pos"] <= ctx.rows[j]
    ref = np.zeros(ctx.n, bool); ref[:600] = True
    d = SP.decide(ctx, ref)
    assert set(np.unique(d["grade"])) <= {"", "A", "B"}
    assert (d["trade"] <= (d["side"] != 0)).all()
    # stricter confidence -> never more calls
    d2 = SP.decide(ctx, ref, conf_b=0.6)
    assert d2["trade"].sum() <= d["trade"].sum()
    # decisions on rows < 600 do not change when the outcomes of later rows change (no look-ahead via the reference)
    ctx.fwd_sign = ctx.fwd_sign.copy(); ctx.fwd_sign[600:] *= -1
    d3 = SP.decide(ctx, ref)
    assert (d3["trade"] == d["trade"]).all()


def test_compute_and_apply_policy():
    from app.config import settings
    ctx, paths, _ = _ctx(edge=0.0)
    pol = SP.compute(ctx, paths, min_n=5, q=0.8)
    assert pol["gate"]["verdict"] in ("too_few", "proven", "no_edge") and "conf_table" in pol
    old = (settings.series_gate, settings.series_conf)
    try:
        settings.series_gate, settings.series_conf = True, True
        a = SP.apply({"gate": {"blocked": True, "n": 40, "mean_r": -0.1}, "conf_b": None})
        assert a["blocked"] and "no proven edge yet" in a["reason"] and a["conf_b"] == settings.series_conf_default
        settings.series_gate, settings.series_conf = False, False
        assert SP.apply({"gate": {"blocked": True}, "conf_b": 0.56}) == {"blocked": False, "reason": None, "conf_b": None}
    finally:
        settings.series_gate, settings.series_conf = old
