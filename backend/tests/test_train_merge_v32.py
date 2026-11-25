"""V3.2 (Fable 5.2 audit R-13): a slice never silently drops due models, and the merge says why it imported what it did."""
import json

from app import worker
from app.data.base import tf_ms

H = 3_600_000
NOW = 1_795_600_000_000


class _Store:
    def __init__(self, last):
        self.last = last

    def is_current(self, ex, s, tf, now_ms=None):
        return self.last[(s, tf)] is not None and self.last[(s, tf)] + 2 * tf_ms(tf) >= NOW

    def last_ts(self, ex, s, tf):
        return self.last[(s, tf)]


class _RT:
    exchange = "binance_public"

    def __init__(self, last):
        self.store = _Store(last)


def test_a_state_copy_an_hour_old_can_still_train_15m():
    rt = _RT({("X", "15m"): NOW - 75 * 60_000})              # cache copy ~1 h old: not "current", still trainable
    assert not rt.store.is_current("", "X", "15m")
    assert worker.trainable(rt, "X", "15m", NOW)


def test_a_dead_feed_is_not_trainable():
    rt = _RT({("X", "15m"): NOW - 10 * H, ("X", "1d"): NOW - 30 * H, ("Y", "1h"): None})
    assert not worker.trainable(rt, "X", "15m", NOW)
    assert worker.trainable(rt, "X", "1d", NOW)               # 2 bars of 1d = 48 h
    assert not worker.trainable(rt, "Y", "1h", NOW)


def _manifest(path, shard, **kw):
    path.mkdir(parents=True, exist_ok=True)
    body = {"shard": shard, "of": 3, "records": [], "trained": [], "seconds": 1.0, "pairs": [], "not_trainable": [],
            "not_reached": [], "not_exported": []}
    body.update(kw)
    (path / "manifest.json").write_text(json.dumps(body))


def _merge(monkeypatch, tmp_path, rt):
    from app.services import market, series_nightly
    from app.sinks import LocalSink
    monkeypatch.setattr(market, "sync_all", lambda rt_: _noop())
    monkeypatch.setattr(series_nightly, "run", lambda rt_, budget_s=0: {"series": 0})
    monkeypatch.setattr(worker.derivs, "sync", lambda *a, **k: {})
    monkeypatch.setattr(worker.derivs, "sync_crowd", lambda *a, **k: {})
    return worker.train_merge(rt, LocalSink(str(tmp_path / "sink"), rt.db), str(tmp_path / "shards"))


async def _noop():
    return None


def test_merge_reports_why_nothing_was_imported(monkeypatch, tmp_path):
    from tests.helpers import make_runtime
    rt, _ = make_runtime(symbols=("BTC/USDT",), model_dir=str(tmp_path / "m"))
    monkeypatch.setenv("SHARDS", "3")
    _manifest(tmp_path / "shards" / "slice-0", 0, pairs=["BTC/USDT 15m"], not_reached=["BTC/USDT 15m"])
    _manifest(tmp_path / "shards" / "slice-1", 1, not_trainable=["ANTHROPIC/USDT 15m"])
    d = _merge(monkeypatch, tmp_path, rt)
    assert d["imported"] == 0 and d["shards"] == 2 and d["expected_shards"] == 3 and d["due"] == 1
    text = " | ".join(d["problems"])
    assert "1 of 3 slice manifests missing" in text
    assert "not reached within the slice budget" in text and "too old to train on" in text
    assert d["not_trainable"] == ["ANTHROPIC/USDT 15m"]
    assert d["stale_models"]["n"] >= 1                      # no models at all in this state: every pair listed
    row = rt.db.one("SELECT status FROM engine_runs WHERE kind = 'train' ORDER BY started_at DESC LIMIT 1")
    assert row["status"] == "warn"


def test_merge_with_nothing_due_says_so(monkeypatch, tmp_path):
    from tests.helpers import make_runtime
    rt, _ = make_runtime(symbols=("BTC/USDT",), model_dir=str(tmp_path / "m"))
    monkeypatch.delenv("SHARDS", raising=False)
    for k in range(2):
        _manifest(tmp_path / "shards" / f"slice-{k}", k)
    d = _merge(monkeypatch, tmp_path, rt)
    assert any("no model was due" in p for p in d["problems"])


def test_shard_manifest_lists_untrainable_due_pairs(monkeypatch, tmp_path):
    from tests.helpers import make_runtime
    rt, _ = make_runtime(symbols=("BTC/USDT",), model_dir=str(tmp_path / "m"))
    monkeypatch.setattr(worker, "MODEL_TIMEFRAMES", ["4h"])
    monkeypatch.setattr(worker, "trainable", lambda *a, **k: False)
    r = worker.train_shard(rt, 0, 1, 60, str(tmp_path / "slice-0"))
    m = json.loads((tmp_path / "slice-0" / "manifest.json").read_text())
    assert r["pairs"] == 0 and m["pairs"] == [] and m["not_trainable"] == ["BTC/USDT 4h"]
