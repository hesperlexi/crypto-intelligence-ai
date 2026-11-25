"""v2.57: ARIMA left out of 12h training only (model-set study); other timeframes keep every model."""
from app.config import _model_exclude, settings
from app.ml import models
from app import worker


def test_parse():
    assert _model_exclude("12h:arima") == {"12h": {"arima"}}
    assert _model_exclude("12h:arima, 1d:lstm,bad,:x") == {"12h": {"arima"}, "1d": {"lstm"}}
    assert _model_exclude("") == {}


def test_default_is_12h_arima_and_1d_random_forest():
    # v3.1 (25 Nov 2026): 1d without Random Forest passed on both windows (ablation group rf)
    assert settings.model_exclude == {"12h": {"arima"}, "1d": {"random_forest"}}


def test_default_models_per_timeframe(monkeypatch):
    monkeypatch.setattr(models, "model_status", lambda: [{"name": n, "available": True} for n in ("random_forest", "arima", "logistic")])
    assert "arima" not in models.default_models(timeframe="12h")
    for tf in ("15m", "1h", "4h", "1d", "3d", None):
        assert "arima" in models.default_models(timeframe=tf)
    assert "random_forest" not in models.default_models(timeframe="1d")
    for tf in ("15m", "1h", "4h", "12h", "3d"):
        assert "random_forest" in models.default_models(timeframe=tf)


def test_12h_bundle_without_arima_is_not_missing_models(monkeypatch):
    monkeypatch.setattr(worker, "default_models", lambda fast=False, timeframe=None: models.default_models(fast, timeframe))
    monkeypatch.setattr(models, "model_status", lambda: [{"name": n, "available": True} for n in ("random_forest", "arima")])
    assert worker._missing_models({"models": ["random_forest"]}, "12h") is False
    assert worker._missing_models({"models": ["random_forest"]}, "4h") is True
