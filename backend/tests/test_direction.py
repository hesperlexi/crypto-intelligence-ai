"""Engine v2: directional confidence and the per-model margin policy are measured out-of-sample."""
import numpy as np

from app.ml import direction


def _oos(n=3000, skill=0.12, seed=1):
    rng = np.random.default_rng(seed)
    margin = rng.uniform(0, 0.4, n)
    side = rng.choice([-1, 1], n)
    up = 0.33 + side * margin / 2
    down = 0.33 - side * margin / 2
    P = np.c_[down, 1 - up - down, up]
    # the bigger the margin, the more often the next move goes that way
    p_right = 0.5 + skill * margin / 0.4
    right = rng.random(n) < p_right
    fwd = np.where(right, side, -side) * rng.uniform(0.001, 0.02, n)
    return {"P_ens": P, "fwd_ret": fwd, "ts": np.arange(n) * 3_600_000}


def test_policy_finds_a_margin_with_a_real_edge_and_none_without():
    good = direction.direction_policy(_oos(skill=0.14))
    assert good["edge"] and good["best"]["ci95"][0] > 0.5 and good["best"]["margin"] > 0.02
    flat = direction.direction_policy(_oos(skill=0.0, seed=3))
    assert not flat["edge"]


def test_directional_confidence_uses_comparable_calls():
    oos = _oos(skill=0.14)
    hi = direction.directional_confidence(oos, 1, 0.35)["confidence"]
    lo = direction.directional_confidence(oos, 1, 0.03)["confidence"]
    assert hi > lo and 0.5 < hi < 0.7


def test_view_reports_side_margin_and_policy():
    oos = _oos(skill=0.14)
    fc = {"available": True, "probabilities": {"up": 0.55, "neutral": 0.2, "down": 0.25}}
    v = direction.view(fc, {"oos": oos, "version": "t1"})
    assert v["side"] == 1 and abs(v["margin"] - 0.30) < 1e-9 and v["clears_policy"] and v["policy_edge"]
    assert direction.view({"available": False}, None) is None
