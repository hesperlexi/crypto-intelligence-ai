"""V3.0 reset archives (never deletes) the testing results, in one transaction, and restarts the record."""
from app.db import Database
from app import fresh_restart_v3 as R


class Sink:
    def __init__(self):
        self.docs = {"config/bots": {"bots": [{"id": "b1", "reset_token": "v218"}]},
                     "owner/telegram_drafts": {"items": [1]}}

    def get(self, k):
        return self.docs.get(k)

    def set(self, k, v, merge=False):
        self.docs[k] = {**(self.docs.get(k) or {}), **v} if merge else v


def _db(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/x.db")
    db.init_schema()
    db.migrate()
    db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, status) "
               "VALUES ('s1', 1, 'BTC/USDT', '4h', 1, 'SHORT', 'SELL', 100, -1, 'STOPPED')")
    db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, status) "
               "VALUES ('s2', 2, 'ETH/USDT', '4h', 2, 'LONG', 'BUY', 100, 1, 'TP1')")
    db.set_setting("record_since", 1)
    db.set_setting("hesper_state", {"run": 3})
    db.set_setting("safety:BTC|4h", {"paused": True})
    db.set_setting("candles_keep", 1)
    return db


def test_archive_reset(tmp_path):
    db = _db(tmp_path)
    rt = type("RT", (), {"db": db})()
    sink = Sink()
    out = R.maybe_run(rt, sink, 1_800_000_000_000)
    assert out["archived"]["signals"] == 2
    assert out["verify"]["empty"]["signals"] == 0 and out["verify"]["archived"]["signals"] == 2
    rows = db.query("SELECT id, archived_at FROM archive_v3_signals ORDER BY id")
    assert [r["id"] for r in rows] == ["s1", "s2"] and rows[0]["archived_at"] == 1_800_000_000_000
    assert db.get_setting("record_since") == 1_800_000_000_000
    assert db.get_setting("hesper_state") is None and db.get_setting("safety:BTC|4h") is None
    assert db.get_setting("candles_keep") == 1
    assert db.get_setting("archive_v3_settings")["values"]["hesper_state"] == {"run": 3}
    assert sink.docs["config/bots"]["bots"][0]["reset_token"] == "v3"
    assert sink.docs["owner/telegram_drafts"]["items"] == []
    assert R.maybe_run(rt, sink, 1_800_000_000_001) is None          # runs once


def test_failed_check_changes_nothing(tmp_path, monkeypatch):
    db = _db(tmp_path)
    rt = type("RT", (), {"db": db})()
    real = R.plan
    monkeypatch.setattr(R, "plan", lambda d: {**real(d), "archive": {**real(d)["archive"], "signals": 99}})
    try:
        R.run(rt, Sink(), 5)
        raise AssertionError("should fail")
    except RuntimeError:
        pass
    assert len(db.query("SELECT id FROM signals")) == 2
    assert not db.query("SELECT name FROM sqlite_master WHERE name = 'archive_v3_signals'")
    assert db.get_setting("fresh_restart_v3") is None
