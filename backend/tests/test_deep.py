"""Sequence models: train, save / load round trip (the network is rebuilt from weights), predict."""
import io

import joblib
import numpy as np
import pytest

torch = pytest.importorskip("torch")

from app.ml.deep import SequenceClassifier  # noqa: E402


@pytest.mark.parametrize("kind", ["lstm", "gru", "transformer"])
def test_sequence_model_roundtrip(kind, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "enable_deep_models", True)
    rng = np.random.default_rng(0)
    X = rng.standard_normal((600, 6))
    y = np.digitize(X[:, 0] + 0.3 * rng.standard_normal(600), [-0.4, 0.4])
    m = SequenceClassifier(kind=kind, seq_len=8, hidden=16, epochs=3).fit(X, y)
    p = m.predict_proba(X)
    assert p.shape == (600, 3) and np.allclose(p.sum(axis=1), 1, atol=1e-5)
    buf = io.BytesIO()
    joblib.dump(m, buf)
    buf.seek(0)
    m2 = joblib.load(buf)
    assert np.allclose(m2.predict_proba(X), p, atol=1e-6)


def test_deep_models_are_skipped_while_switched_off(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "enable_deep_models", True)
    rng = np.random.default_rng(1)
    X = rng.standard_normal((300, 4))
    y = rng.integers(0, 3, 300)
    m = SequenceClassifier(kind="gru", seq_len=6, hidden=8, epochs=1).fit(X, y)
    buf = io.BytesIO()
    joblib.dump(m, buf)
    buf.seek(0)
    m2 = joblib.load(buf)                        # loading never builds the network
    assert m2.net_ is None
    monkeypatch.setattr(settings, "enable_deep_models", False)
    with pytest.raises(RuntimeError):
        m2.predict_proba(X)
