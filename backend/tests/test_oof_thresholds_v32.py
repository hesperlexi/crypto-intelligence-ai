"""V3.2 (Fable 5.2 audit R-02): meta-model thresholds from embargoed out-of-fold scores; shadow until validated."""
import numpy as np
import pytest

from app.ml import oof
from app.ml import trade_filter2 as TF2
from app.services import analysis


def _data(n, seed):
    rng = np.random.default_rng(seed)
    F = rng.normal(size=(n, len(TF2.FEATURES)))
    signal = 0.6 * F[:, 0] + 0.3 * F[:, 1]
    R = signal + rng.normal(0, 1.4, n)                    # weak, noisy edge, like the real filters
    return F, R


def test_folds_are_time_ordered_and_embargoed():
    pos = np.arange(1200, dtype=float)
    folds = oof.time_folds(pos, embargo=30)
    assert len(folds) == oof.N_FOLDS
    for tr, te in folds:
        assert pos[tr].max() < pos[te].min() - 30          # no training label reaches the scored block
        assert np.all(np.diff(te) == 1)


def test_folds_refuse_unsorted_rows():
    with pytest.raises(ValueError):
        oof.time_folds(np.array([3.0, 1.0, 2.0] * 40))


def test_embargo_uses_bar_positions_not_row_counts():
    pos = np.r_[np.arange(600), np.arange(600) + 615].astype(float)     # a 15-bar gap in the rows
    for tr, te in oof.time_folds(pos, embargo=30):
        assert pos[te].min() - pos[tr].max() > 30


def test_kept_share_on_unseen_rows_matches_keep_fraction():
    F, R = _data(4000, 1)
    ts = np.arange(len(R)) * 3_600_000 * 4
    f = TF2.train(F, R, ts, tf="4h")
    assert f["enabled"], f.get("reason")
    assert f["threshold_method"] == "oof_embargo" and f["embargo_bars"] == 100       # 4h record horizon
    assert f["kept_share_ok"] and f["validated"]
    # brand-new rows from the same market: the kept share must be close to the intended one
    F2, _ = _data(3000, 7)
    kept = float((f["model"].predict_proba(F2)[:, 1] >= f["threshold"]).mean())
    assert abs(kept - f["keep_fraction"]) <= 0.10, (kept, f["keep_fraction"])
    assert f["threshold_in_sample"] is not None                    # the old way is recorded for comparison


def test_in_sample_quantile_misses_on_unseen_data():
    """The problem the audit found, reproduced with a model that fits its own rows closely: the refit's own score
    quantile keeps far fewer new rows than intended; the out-of-fold threshold keeps about the intended share."""
    from sklearn.ensemble import RandomForestClassifier

    def model():
        return RandomForestClassifier(n_estimators=60, min_samples_leaf=1, random_state=0)
    F, R = _data(2500, 2)
    y = (R > 0).astype(int)
    keep = 0.3
    m = model().fit(F, y)
    thr_in = np.quantile(m.predict_proba(F)[:, 1], 1 - keep)
    fit = oof.fit_threshold(F, y, np.arange(len(y), dtype=float), keep, model)
    p_new = m.predict_proba(_data(3000, 9)[0])[:, 1]
    err_in = abs((p_new >= thr_in).mean() - keep)
    err_oof = abs((p_new >= fit["threshold"]).mean() - keep)
    assert err_in > 0.10                    # in-sample: outside tolerance
    assert err_oof <= 0.10 and fit["validated"]


def test_unvalidated_check_is_not_validated():
    p = np.r_[np.full(100, np.nan), np.linspace(0, 1, 500)]
    fold = np.r_[np.full(100, -1), np.repeat(np.arange(5), 100)]
    chk = oof.kept_share_check(p, fold, 0.5)               # rising scores: the last fold is all above the threshold
    assert chk["kept_share_unseen"] == 1.0 and not chk["kept_share_ok"]


# ---- shadow mode in analysis ---------------------------------------------------------------------------------------
class _DB:
    def __init__(self):
        self.s = {}

    def get_setting(self, k, d=None):
        return self.s.get(k, d)

    def set_setting(self, k, v):
        self.s[k] = v

    def query(self, *a, **k):
        return []


class _RT:
    def __init__(self):
        self.db = _DB()


def test_unvalidated_filter_runs_in_shadow(monkeypatch):
    monkeypatch.setattr(analysis, "FILTER_ENFORCE", False)
    rt = _RT()
    assert analysis.filter_bypass(rt, "4h", {"validated": False}) is True
    assert analysis.filter_bypass(rt, "4h", {"validated": True}) is True        # enforcement switch off


def test_validated_filter_enforces_with_owner_switch(monkeypatch):
    monkeypatch.setattr(analysis, "FILTER_ENFORCE", True)
    rt = _RT()
    assert analysis.filter_bypass(rt, "4h", {"validated": True}) is False
    assert analysis.filter_bypass(rt, "4h", {"validated": False}) is True


def test_safety_net_still_makes_shadowed_filters_block(monkeypatch):
    monkeypatch.setattr(analysis, "FILTER_ENFORCE", False)
    rt = _RT()
    rt.db.set_setting("filter_off_revoked|4h", {"at": 1, "closed": 12, "avg_r": -0.3})
    assert analysis.filter_bypass(rt, "4h", {"validated": False}) is False


def test_15m_rule_unchanged(monkeypatch):
    monkeypatch.setattr(analysis, "FILTER_ENFORCE", True)
    rt = _RT()
    assert analysis.filter_bypass(rt, "15m", {"validated": True}) is True       # v2.64 FILTER_OFF_TFS


def test_runner_needs_validation_and_switch(monkeypatch):
    monkeypatch.setattr(analysis, "RUNNER_ENFORCE", False)
    assert not analysis.runner_enforced({"validated": True})
    monkeypatch.setattr(analysis, "RUNNER_ENFORCE", True)
    assert analysis.runner_enforced({"validated": True}) and not analysis.runner_enforced({"validated": False})
    assert not analysis.runner_enforced(None)


def test_shadow_stats_count_each_candle_once():
    rt = _RT()
    for _ in range(3):
        analysis.shadow_stat(rt, "trade_filter", "4h", "X/USDT", 1000, 0.3, 0.5, 0.5)
    analysis.shadow_stat(rt, "trade_filter", "4h", "Y/USDT", 1000, 0.7, 0.5, 0.5)
    st = rt.db.get_setting("filter_shadow_stats|trade_filter|4h")
    assert st["n"] == 2 and st["kept_share"] == 0.5


def test_shadow_fields_stay_private():
    a = {"decision": "BUY", "filter_shadow": [{"filter": "trade_filter"}], "runner_shadow": {"would_run": True}}
    pub = analysis.public_view(a)
    assert "filter_shadow" not in pub and "runner_shadow" not in pub
