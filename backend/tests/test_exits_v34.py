"""V3.4 Stage 3E: exit research options - off by default (identical to the live simulator), each changes only its rule."""
import numpy as np

from app import research_exits as RX
from app import research_exits_v34 as RX4
from app.ml import series_sim as S


def _path(seed=1, n=3000):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    o = np.r_[c[0], c[:-1]]
    return np.maximum(o, c) * 1.002, np.minimum(o, c) * 0.998, c, o


def test_defaults_equal_the_live_simulator():
    h, l, c, o = _path()
    chk = RX._selfcheck(h, l, c, o)
    assert chk["diff"] == 0 and chk["same"] >= 250


def test_each_option_changes_only_its_rule():
    h, l, c, o = _path()
    e = c[100]
    st = e * 0.99
    tps = S.ladder(1, e, st)
    sl = slice(101, 400)
    base = RX.follow_x(1, e, st, tps, h[sl], l[sl], c[sl], open_=o[sl])
    split = RX.follow_x(1, e, st, tps, h[sl], l[sl], c[sl], open_=o[sl], split=(0.7, 0.15, 0.15))
    assert split.exit_idx == base.exit_idx and split.return_pct != base.return_pct
    trail = RX.follow_x(1, e, st, tps, h[sl], l[sl], c[sl], open_=o[sl], trail_r=1.0)
    assert trail.exit_reason in ("trail_r", "break_even", "tp3", "trail")
    lock = RX.follow_x(1, e, st, tps, h[sl], l[sl], c[sl], open_=o[sl], tp1_lock=0.25)
    assert lock.return_pct >= base.return_pct - 1e-9 or lock.exit_idx != base.exit_idx


def test_failed_breakout_exit():
    e, st = 100.0, 99.0
    hi = np.array([100.5, 100.1, 99.8, 99.9])
    lo = np.array([100.0, 99.7, 99.6, 99.6])
    cl = np.array([100.3, 99.8, 99.65, 99.7])
    o = RX.follow_x(1, e, st, (101, 101.75, 102.5), hi, lo, cl, fail_n=8, fail_r=0.3)
    assert o.exit_reason == "failed_breakout" and o.exit_idx == 2
    assert RX.follow_x(1, e, st, (101, 101.75, 102.5), hi, lo, cl).exit_reason == "expired"


def test_variants_are_registered_before_outcomes():
    names = [k for k in RX4.VARIANTS if k != "base"]
    assert len(names) == 10 and "base" in RX4.VARIANTS
    assert all(set(v) <= set(RX.OPT_KEYS) | {"hmult", "ladder"} for v in RX4.VARIANTS.values())
