"""V3.4 Stage 4: model activation needs validation + loading, registry statuses, strategy suitability is measured and
advisory only, one trade authority."""
import re
from pathlib import Path

import joblib

from app.db import Database
from app.ml import trainer
from app.services import model_registry as MRG
from app.services import strategy_select as SS

H = 3_600_000


def _rec(v, n_oos=500, metrics=(("ensemble", "brier", 0.6),), created=1_000):
    return {"version": v, "symbol": "BTC/USDT", "timeframe": "4h", "created_at": created, "data_start": 1, "data_end": 2,
            "n_samples": 1000, "n_oos": n_oos, "edge_confirmed": 0, "summary": {"models": ["rf"]},
            "metrics": [list(m) for m in metrics], "challenger": None}


def _file(tmp_path, v, good=True):
    p = tmp_path / f"{v}.joblib"
    if good:
        joblib.dump({"version": v, "models": {"rf": 1}}, p)
    else:
        p.write_bytes(b"not a model")
    return str(p)


def test_validation_problems(tmp_path):
    assert trainer.validate_candidate(_rec("a"), _file(tmp_path, "a"))[0] == []
    probs = trainer.validate_candidate(_rec("b"), _file(tmp_path, "b", good=False))[0]
    assert any("does not load" in p for p in probs)
    assert any("out-of-sample" in p for p in trainer.validate_candidate(_rec("c", n_oos=5), _file(tmp_path, "c"))[0])
    assert any("another version" in p for p in trainer.validate_candidate(_rec("d"), _file(tmp_path, "zz"))[0])
    assert any("finite" in p for p in trainer.validate_candidate(_rec("e", metrics=()), _file(tmp_path, "e"))[0])


def test_invalid_model_never_replaces_the_live_one(tmp_path):
    db = Database("sqlite:///:memory:")
    assert trainer.register(_rec("live", created=1), _file(tmp_path, "live"), db, problems=[], source="t")
    bad = _rec("bad", created=2)
    assert not trainer.register(bad, _file(tmp_path, "bad", good=False), db,
                                problems=trainer.validate_candidate(bad, _file(tmp_path, "bad", good=False))[0], source="t")
    assert trainer.active_version("BTC/USDT", "4h", db)["id"] == "live"
    log = db.get_setting(trainer.ACTIVATION_LOG)
    assert log[-1]["version"] == "bad" and not log[-1]["activated"] and log[-1]["problems"]


def test_import_bundle_validates(tmp_path, monkeypatch):
    monkeypatch.setattr(trainer.settings, "model_dir", str(tmp_path / "models"), raising=False)
    db = Database("sqlite:///:memory:")
    src = tmp_path / "src"
    src.mkdir()
    good = _rec("g1", created=5)
    joblib.dump({"version": "g1", "models": {"rf": 1}}, src / "g1.joblib")
    trainer.import_bundle(good, str(src / "g1.joblib"), db)
    assert trainer.active_version("BTC/USDT", "4h", db)["id"] == "g1"
    broken = _rec("g2", created=9)
    (src / "g2.joblib").write_bytes(b"junk")
    trainer.import_bundle(broken, str(src / "g2.joblib"), db)
    assert trainer.active_version("BTC/USDT", "4h", db)["id"] == "g1"          # the failed file never went live


def test_production_callers_always_validate():
    src = (Path(trainer.__file__)).read_text()
    for m in re.finditer(r"\bregister\(", src):
        line = src[src.rfind("\n", 0, m.start()) + 1:src.find("\n", m.start())]
        if line.lstrip().startswith("def "):
            continue
        assert "problems=" in line, line


def test_registry_statuses(tmp_path):
    class RT:
        def __init__(self):
            self.db = Database("sqlite:///:memory:")

        def symbols(self):
            return ["BTC/USDT", "ETH/USDT"]

        def candles(self, s, tf):
            return None
    rt = RT()
    now = 1_000 + 100 * H
    trainer.register(_rec("v1", created=now - 2 * H), _file(tmp_path, "v1"), rt.db, problems=[], source="t")
    v = MRG.build(rt, now)
    rows = {(r["symbol"], r["timeframe"]): r for r in v["models"]}
    assert rows[("BTC/USDT", "4h")]["status"] == "active" and rows[("BTC/USDT", "4h")]["n_oos"] == 500
    assert rows[("ETH/USDT", "4h")]["status"] == "missing"
    bad = _rec("v2", created=now - H)
    trainer.register(bad, "x", rt.db, problems=["file does not load (OSError)"], source="t")
    v = MRG.build(rt, now)
    r = {(x["symbol"], x["timeframe"]): x for x in v["models"]}[("BTC/USDT", "4h")]
    assert r["status"] == "invalid" and "failed validation" in r["reasons"][0]
    assert "rule" in v and v["counts"]["missing"] >= 1


def test_suitability_cells():
    assert SS._cell([])["state"] == "unproven"
    assert SS._cell([0.5 + (i % 3) * 0.1 for i in range(40)])["state"] == "suitable"
    assert SS._cell([-0.5 - (i % 3) * 0.1 for i in range(40)])["state"] == "unsuitable"
    assert SS._cell([0.5, -0.5] * 20)["state"] == "unproven"
    assert SS._cell([0.5] * 10)["state"] == "unproven"                       # too few


def test_advice_labels_never_decide():
    tbl = {"main": {"4h|weak_bear": {"n": 40, "state": "unsuitable"}, "4h|weak_bull": {"n": 40, "state": "suitable"}}}
    a = {"status": "OK", "timeframe": "4h", "decision": "BUY", "forecast": {"available": True}, "flags": []}
    assert SS.advise(a, tbl, "weak_bull")["action"] == "TRADE"
    u = SS.advise(a, tbl, "weak_bear")
    assert u["action"] == "STRATEGY UNSUITABLE" and "the call stands" in u["reason"]
    assert SS.advise({**a, "stale": True}, tbl, "weak_bull")["action"] == "INSUFFICIENT DATA"
    assert SS.advise({**a, "forecast": {"available": False}}, tbl, "weak_bull")["action"] == "INSUFFICIENT DATA"
    w = SS.advise({**a, "decision": "NO TRADE", "setup": {"ideal_entry": 1}, "flags": ["NEWS PAUSE", "NO TRADE"]}, tbl, "weak_bull")
    assert w["action"] == "WAIT"
    assert SS.advise({**a, "decision": "NO TRADE"}, tbl, None)["action"] == "NO TRADE"
    text = (Path(SS.__file__).resolve().parents[0] / "analysis.py").read_text()
    for m in re.finditer(r"strategy_fit", text):
        line = text[text.rfind("\n", 0, m.start()) + 1:text.find("\n", m.start())]
        assert "decision =" not in line and "decision," not in line.split("=")[0]


def test_fast_strategy_steps_aside_for_the_main_record():
    db = Database("sqlite:///:memory:")
    assert SS.main_conflict(db, "SOL/USDT", 1) is False
