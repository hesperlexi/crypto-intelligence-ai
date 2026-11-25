"""V3.2 (Fable 5.2 audit R-03): 95 % bootstrap bar, Holm correction over a study, variant count, frozen forward holdout."""
import json
import types

import numpy as np
import pytest

from app import research_verdict as RV

H = 3_600_000
T0 = RV.HOLDOUT_START - 800 * 24 * H           # well before the holdout


def _t(i, r, sym="ETH/USDT"):
    return {"ts": T0 + i * H, "closed_ts": T0 + i * H + 2 * H, "r": r, "sym": sym, "tf": "1h", "side": 1}


def _base(n=600, seed=0):
    rng = np.random.default_rng(seed)
    return [_t(i * 12, float(rng.normal(0.0, 1.0))) for i in range(n)]


def _drop(base, frac, seed):
    rng = np.random.default_rng(seed)
    return [t for t in base if rng.random() > frac]


def test_bar_is_95_percent():
    assert RV.MIN_SHARE == 0.95 and abs(RV.ALPHA - 0.05) < 1e-12


def test_verdict_reports_p_value():
    base = _base()
    v = RV.verdict(base, _drop(base, 0.3, 1))
    assert v["p_value"] == pytest.approx(1 - v["bootstrap_better_share"], abs=1e-3)


def test_holm_textbook_example():
    out = RV.holm({"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.005}, alpha=0.05)
    assert out["d"]["reject"] and out["a"]["reject"]
    assert not out["c"]["reject"] and not out["b"]["reject"]          # 0.03 > 0.05/2 stops the step-down
    assert out["d"]["p_adj"] == pytest.approx(0.02) and out["a"]["p_adj"] == pytest.approx(0.03)
    assert out["b"]["p_adj"] >= out["c"]["p_adj"] >= out["a"]["p_adj"]


def test_noise_variants_do_not_survive_correction():
    """36 random filters on pure-noise calls: whatever passes raw, nothing passes after Holm."""
    RV.reset_count()
    base = _base(900, 3)
    res = {f"v{k}": RV.verdict(base, _drop(base, 0.25, 100 + k)) for k in range(36)}
    out = RV.finalize({"variants": res}, "noise")
    assert out["multiple_testing"]["n_variants"] == 36
    assert all(v["corrected_verdict"] != "PROVISIONAL PASS" for v in res.values())
    assert all(v["promotable"] is False for v in res.values())


def test_real_effect_survives_but_is_only_provisional():
    RV.reset_count()
    base = [_t(i * 12, 1.0 if i % 2 else -1.0) for i in range(800)]
    good = [t for t in base if t["r"] > 0 or (t["ts"] // H) % 3]
    noise = {f"n{k}": RV.verdict(base, _drop(base, 0.2, k)) for k in range(5)}
    out = RV.finalize({"good": RV.verdict(base, good), **noise}, "real")
    assert out["good"]["verdict"] == "PASS" and out["good"]["corrected_verdict"] == "PROVISIONAL PASS"
    assert out["good"]["promotable"] is False and "forward holdout" in out["good"]["corrected_reason"]
    assert out["multiple_testing"]["n_variants"] == 6


def test_dropped_variants_still_count():
    RV.reset_count()
    base = _base()
    for k in range(10):
        RV.verdict(base, _drop(base, 0.3, k))           # computed, then left out of the output
    out = RV.finalize({"best": RV.verdict(base, _drop(base, 0.3, 99))}, "dropped")
    assert out["multiple_testing"]["n_variants"] == 11


def test_registered_variants_fix_the_count_before_outcomes():
    RV.reset_count()
    reg = RV.register("reg", ["a", "b", "c", "d"])
    assert reg["n_variants"] == 4 and reg["variants_sha1"]
    base = _base()
    out = RV.finalize({"a": RV.verdict(base, _drop(base, 0.3, 1))}, "reg")
    mt = out["multiple_testing"]
    assert mt["n_variants"] == 4 and mt["variants_registered_before_outcomes"] and mt["variants"] == ["a", "b", "c", "d"]
    RV.reset_count()
    RV.register("reg2", ["a"])
    with pytest.raises(ValueError):
        RV.finalize({"a": RV.verdict(base, base[:-200]), "b": RV.verdict(base, base[:-150])}, "reg2")


def test_verdicts_are_reproducible():
    base = _base()
    new = _drop(base, 0.3, 5)
    a, b = RV.verdict(base, new), RV.verdict(base, new)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    out = RV.finalize({"x": RV.verdict(base, new)}, "repro", base=base)
    assert out["reproducibility"]["seed"] == RV.SEED and out["reproducibility"]["base_fingerprint"] == RV.fingerprint(base)


# ---- forward holdout ------------------------------------------------------------------------------------------------
def test_verdict_refuses_holdout_trades():
    late = [{"ts": RV.HOLDOUT_START + i * H, "closed_ts": RV.HOLDOUT_START + i * H + H, "r": 0.1, "sym": "X", "tf": "1h"}
            for i in range(200)]
    with pytest.raises(RV.HoldoutLocked):
        RV.verdict(_base(), _base() + late)
    RV.verdict(late, late[:-150], holdout=True)          # the confirmation run may, explicitly


class _DB:
    def __init__(self, rows):
        self.rows = rows

    def query(self, sql, args):
        start = args[0]
        statuses = set(args[1:])
        return [r for r in self.rows if r["created_at"] >= start and r["status"] in statuses]


def _rows(n, start=RV.HOLDOUT_START):
    return [{"created_at": start + i * H, "status": "TP1", "fill_status": "FILLED"} for i in range(n)]


def test_holdout_reader_locked_until_300_closed():
    db = _DB(_rows(299) + _rows(50, start=RV.HOLDOUT_START - 10 ** 9))   # older calls do not count
    st = RV.holdout_status(db)
    assert st["locked"] and st["closed"] == 299 and st["needed"] == 300
    with pytest.raises(RV.HoldoutLocked):
        RV.read_holdout(db)
    db.rows += _rows(1, start=RV.HOLDOUT_START + 10 ** 9)
    assert not RV.holdout_status(db)["locked"]
    with pytest.raises(RV.HoldoutLocked):                  # V3.2 verification: only the single-use reader may read it
        RV.read_holdout(db)


def test_unfilled_calls_do_not_count_toward_the_holdout():
    rows = _rows(300)
    rows[0]["fill_status"] = "NOT_FILLED"
    assert RV.holdout_status(_DB(rows))["closed"] == 299


def test_research_split_stops_before_the_holdout():
    from app import research_engine as RE
    from app.data.base import tf_ms
    from app.ml import series_policy as SP
    step = tf_ms("4h")
    ts = np.arange(RV.HOLDOUT_START - 3000 * step, RV.HOLDOUT_START + 500 * step, step, dtype=np.int64)
    tune, test, cut = RE._split(types.SimpleNamespace(ts=ts, tf="4h"))
    assert ts[test].max() < RV.HOLDOUT_START - SP.HORIZON_BARS * step + 1
    assert not (tune & test).any() and ts[tune].max() < cut
    # more candles after the holdout start do not move the split
    ts2 = np.r_[ts, ts[-1] + step * np.arange(1, 400)]
    _, test2, cut2 = RE._split(types.SimpleNamespace(ts=ts2, tf="4h"))
    assert cut2 == cut and test2[: len(test)].tolist() == test.tolist()
