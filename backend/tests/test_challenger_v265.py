"""v2.65 champion / challenger wiring: logged in shadow, enforced only with CHALLENGER_ENFORCE."""
from app.config import settings
from app.db import Database
from app.ml import trainer


def _rec(v, ch):
    return {"version": v, "symbol": "BTC/USDT", "timeframe": "1h", "created_at": int(v[1:]), "data_start": 0, "data_end": 1,
            "n_samples": 10, "n_oos": 5, "edge_confirmed": 0, "summary": {}, "metrics": [], "challenger": ch}


def _active(db):
    return [r["id"] for r in db.query("SELECT id FROM model_versions WHERE active = 1")]


def test_shadow_logs_but_activates(monkeypatch):
    monkeypatch.setattr(settings, "challenger_enforce", False)
    db = Database("sqlite:///:memory:")
    trainer.register(_rec("v1", {"activate": True, "basis": "first model"}), "x", db)
    trainer.register(_rec("v2", {"activate": False, "basis": "head-to-head", "brier_new": 0.7, "brier_old": 0.6}), "y", db)
    assert _active(db) == ["v2"]
    log = db.get_setting(trainer.CHALLENGER_LOG)
    assert log[-1]["verdict"] is False and log[-1]["activated"] is True and log[-1]["enforced"] is False


def test_enforced_keeps_the_live_model(monkeypatch):
    monkeypatch.setattr(settings, "challenger_enforce", True)
    db = Database("sqlite:///:memory:")
    trainer.register(_rec("v1", None), "x", db)
    trainer.register(_rec("v2", {"activate": False, "basis": "head-to-head"}), "y", db)
    assert _active(db) == ["v1"]
    assert db.one("SELECT active FROM model_versions WHERE id = 'v2'")["active"] == 0
    trainer.register(_rec("v3", {"activate": True, "basis": "head-to-head"}), "z", db)
    assert _active(db) == ["v3"]
