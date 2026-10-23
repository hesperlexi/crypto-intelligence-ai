"""Model registry. Every model exposes fit(X, y) / predict_proba(X) over classes {0 DOWN, 1 NEUTRAL, 2 UP}.

Optional libraries (xgboost, lightgbm, torch, statsmodels) are detected at runtime. A model whose library
is missing is reported as unavailable - it is never silently replaced by something else.
Scalers live inside pipelines, so they are fitted on training rows only.
"""
from __future__ import annotations

import importlib.util
import os
from typing import Any, Callable

import numpy as np
from scipy.stats import norm
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ..config import settings

N_JOBS = max(1, min(4, (os.cpu_count() or 2)))
SEED = 42


def has(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def proba3(model: Any, X: np.ndarray) -> np.ndarray:
    """predict_proba mapped onto the fixed 3-class layout, even if a class was absent in training."""
    p = np.asarray(model.predict_proba(X), float)
    classes = np.asarray(getattr(model, "classes_", [0, 1, 2])).astype(int)
    out = np.zeros((len(p), 3))
    out[:, classes] = p
    s = out.sum(axis=1, keepdims=True)
    return out / np.where(s > 0, s, 1.0)


def predict_with_context(model: Any, X_all: np.ndarray, lo: int, hi: int) -> np.ndarray:
    """Predict rows [lo, hi). Sequence models also receive the preceding rows they need as context
    (past data only), so their first predictions are not made on padded windows."""
    ctx = int(getattr(model, "context_rows", 0))
    start = max(0, lo - ctx)
    return proba3(model, X_all[start:hi])[lo - start:]


class PrevCandleBaseline(BaseEstimator, ClassifierMixin):
    """Benchmark: class frequencies conditional on the sign of the last bar's return."""

    def __init__(self, col: int = 0):
        self.col = col

    def fit(self, X: np.ndarray, y: np.ndarray):
        self.classes_ = np.array([0, 1, 2])
        self.table_ = {}
        y = y.astype(int)
        for s in (-1, 1):
            m = (np.sign(X[:, self.col]) >= 0) == (s > 0)
            cnt = np.bincount(y[m], minlength=3) + 1.0
            self.table_[s] = cnt / cnt.sum()
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        up = np.sign(X[:, self.col]) >= 0
        return np.where(up[:, None], self.table_[1], self.table_[-1])


class ColumnSubset(BaseEstimator, ClassifierMixin):
    """Fit an inner estimator on a fixed subset of columns."""

    def __init__(self, cols: list[int], inner: Any):
        self.cols = cols
        self.inner = inner

    def fit(self, X: np.ndarray, y: np.ndarray):
        self.inner.fit(X[:, self.cols], y)
        self.classes_ = self.inner.classes_
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return self.inner.predict_proba(X[:, self.cols])


class ArimaDirection(BaseEstimator, ClassifierMixin):
    """ARIMA(p,0,q) one-step return forecast turned into class probabilities with a Normal error model:
    P(UP) = P(r > +band), P(DOWN) = P(r < -band). Parameters are fitted on the training window only and
    then applied (without refitting) to later data."""

    context_rows = 200

    def __init__(self, ret_col: int, sigma_col: int, order: tuple[int, int, int] = (1, 0, 1), band: float = 0.25):
        self.ret_col, self.sigma_col, self.order, self.band = ret_col, sigma_col, order, band

    def fit(self, X: np.ndarray, y: np.ndarray):
        from statsmodels.tsa.arima.model import ARIMA

        self.classes_ = np.array([0, 1, 2])
        r = X[:, self.ret_col] * 100
        self.res_ = ARIMA(r, order=self.order, trend="c").fit()
        self.resid_sd_ = float(np.std(self.res_.resid[5:])) / 100
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        r = X[:, self.ret_col] * 100
        applied = self.res_.apply(r)
        mu = np.asarray(applied.predict(start=1, end=len(r))) / 100   # forecast of r[t+1] given r[<=t]
        thr = self.band * X[:, self.sigma_col]
        sd = np.maximum(self.resid_sd_, 1e-9)
        p_up = 1 - norm.cdf((thr - mu) / sd)
        p_dn = norm.cdf((-thr - mu) / sd)
        return np.column_stack([p_dn, np.clip(1 - p_up - p_dn, 0, 1), p_up])


def _idx(names: list[str], wanted: list[str]) -> list[int]:
    return [names.index(w) for w in wanted if w in names]


def _logistic(names):
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=1000))


def _rf(names):
    return RandomForestClassifier(n_estimators=200, max_depth=6, min_samples_leaf=20, max_features="sqrt",
                                  n_jobs=N_JOBS, random_state=SEED)


def _hgb(names):
    return HistGradientBoostingClassifier(max_depth=4, learning_rate=0.04, max_iter=200, l2_regularization=1.0,
                                          min_samples_leaf=30, random_state=SEED)


def _xgb(names):
    from xgboost import XGBClassifier

    return XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.03, subsample=0.8, colsample_bytree=0.7,
                         min_child_weight=5, reg_lambda=2.0, objective="multi:softprob", tree_method="hist",
                         n_jobs=N_JOBS, random_state=SEED, verbosity=0)


def _lgbm(names):
    from lightgbm import LGBMClassifier

    return LGBMClassifier(n_estimators=300, num_leaves=15, learning_rate=0.03, subsample=0.8, subsample_freq=1,
                          colsample_bytree=0.7, min_child_samples=30, reg_lambda=2.0, n_jobs=N_JOBS,
                          random_state=SEED, verbose=-1)


def _tech(names):
    cols = _idx(names, ["sc_trend", "sc_momentum", "sc_volume", "sc_structure", "tech_score", "regime_score"])
    return ColumnSubset(cols, make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=1000)))


def _prior(names):
    return DummyClassifier(strategy="prior")


def _prev(names):
    return PrevCandleBaseline(col=names.index("ret_1"))


def _arima(names):
    return ArimaDirection(names.index("ret_1"), names.index("sigma_bar"), band=settings.neutral_band_sigma)


def _seq(kind: str) -> Callable[[list[str]], Any]:
    def make(names):
        from .deep import SequenceClassifier

        return SequenceClassifier(kind=kind)
    return make


# name -> spec. `baseline` models are benchmarks: evaluated and displayed, never part of the ensemble.
REGISTRY: dict[str, dict[str, Any]] = {
    "prior_baseline": {"label": "Baseline: class prior (random)", "make": _prior, "baseline": True, "requires": None},
    "prev_candle": {"label": "Baseline: previous candle", "make": _prev, "baseline": True, "requires": None},
    "logistic": {"label": "Logistic Regression", "make": _logistic, "baseline": False, "requires": None},
    "technical_rules": {"label": "Technical rules model", "make": _tech, "baseline": False, "requires": None},
    "random_forest": {"label": "Random Forest", "make": _rf, "baseline": False, "requires": None},
    "hist_gbm": {"label": "Gradient Boosting (scikit-learn)", "make": _hgb, "baseline": False, "requires": None},
    "xgboost": {"label": "XGBoost", "make": _xgb, "baseline": False, "requires": "xgboost"},
    "lightgbm": {"label": "LightGBM", "make": _lgbm, "baseline": False, "requires": "lightgbm"},
    "arima": {"label": "ARIMA(1,0,1)", "make": _arima, "baseline": False, "requires": "statsmodels"},
    "lstm": {"label": "LSTM", "make": _seq("lstm"), "baseline": False, "requires": "torch", "deep": True},
    "gru": {"label": "GRU", "make": _seq("gru"), "baseline": False, "requires": "torch", "deep": True},
    "transformer": {"label": "Transformer encoder", "make": _seq("transformer"), "baseline": False,
                    "requires": "torch", "deep": True},
}
FAST_MODELS = ["prior_baseline", "prev_candle", "logistic", "technical_rules", "hist_gbm"]


def model_status() -> list[dict[str, Any]]:
    out = []
    for name, spec in REGISTRY.items():
        req = spec["requires"]
        ok = req is None or has(req)
        reason = None if ok else f"python package '{req}' is not installed"
        if ok and spec.get("deep") and not settings.enable_deep_models:
            ok, reason = False, "disabled (set ENABLE_DEEP_MODELS=true)"
        out.append({"name": name, "label": spec["label"], "available": ok, "reason": reason,
                    "baseline": spec["baseline"]})
    return out


def default_models(fast: bool = False) -> list[str]:
    avail = [m["name"] for m in model_status() if m["available"]]
    return [m for m in avail if m in FAST_MODELS] if fast else avail


def make_model(name: str, feature_names: list[str]) -> Any:
    return REGISTRY[name]["make"](feature_names)
