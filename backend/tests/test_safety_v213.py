"""v2.13 safety fixes: lost-state guard for one-time migrations, malformed member alerts, health error split, redaction."""
import pytest

from app import reset_v1, worker
from app.db import Database
from app.redact import error_text, redact
from app.services import health
from app.services.runtime import Runtime
from app.sinks import LocalSink


class _P:
    name = "test"


def _rt():
    return Runtime(Database("sqlite:///:memory:"), _P())


BOTS = [{"id": "futures-signal-ab-4h", "mode": "decision", "timeframe": "4h", "market": "futures", "grades": "AB",
         "max_hold_bars": 100, "reset_token": "v1", "leverage": 20.0, "safe_leverage": True}]


def _live_firestore(tmp_path) -> LocalSink:
    """What Firestore looks like for a running installation: config, members' practice accounts and trades."""
    sink = LocalSink(tmp_path)
    sink.set("config/watchlist", {"symbols": [{"symbol": "BTC/USDT", "pinned": True}]})
    sink.set("config/bots", {"bots": [dict(b) for b in BOTS], "defaults_added": [d["id"] for d in worker.DEFAULT_BOTS]
                             + [b["id"] for b in BOTS]})
    sink.set("config/membership", {"support_email": "support@cryptointelai.com"})
    sink.set("paper/m1_futures", {"wallet": 12345})
    sink.set("paper_futures_trades/t1", {"uid": "m1", "pnl": 10})
    sink.set("auto_paper_state/m1", {"log": [1]})
    return sink


def _no_destruction(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a destructive historical migration ran on a fresh database")
    monkeypatch.setattr(worker, "clear_all_practice", boom)
    monkeypatch.setattr(worker, "clear_admin_practice", boom)
    monkeypatch.setattr(worker, "cleanup_bots", boom)
    monkeypatch.setattr(reset_v1, "run", boom)


def test_fresh_database_with_existing_firestore_runs_no_history(tmp_path, monkeypatch):
    _no_destruction(monkeypatch)
    rt, sink = _rt(), _live_firestore(tmp_path)
    before_bots = sink.get("config/bots")
    notes = worker.sync_config(rt, sink)
    # nothing destructive: practice accounts, trades and auto-trade logs are all still there
    assert sink.get("paper/m1_futures") == {"wallet": 12345}
    assert sink.get("paper_futures_trades/t1") and sink.get("auto_paper_state/m1")
    # the bot line-up is not reset (no fresh_start / testing / reset tokens / leverage rewrite)
    assert [b["id"] for b in sink.get("config/bots")["bots"]] == [b["id"] for b in before_bots["bots"]]
    assert sink.get("config/bots")["bots"][0]["reset_token"] == "v1"
    # the counted record is not restarted
    assert rt.db.get_setting("record_since", None) is None
    assert rt.db.get_setting("record_since_tf", None) is None
    assert rt.db.get_setting("testing_since", None) is None
    # every historical flag is now marked done, and mirrored to Firestore
    assert all(rt.db.get_setting(f, None) for f in worker.MIGRATION_FLAGS)
    assert set(notes["migrations"]["fresh_database_marked_done"]) == set(worker.MIGRATION_FLAGS)
    assert set(sink.get(worker.MIGRATIONS_DOC)["flags"]) == set(worker.MIGRATION_FLAGS)
    # a second cycle changes nothing either
    worker.sync_config(rt, sink)
    assert sink.get("paper/m1_futures") == {"wallet": 12345}


def test_flags_in_firestore_count_as_done_on_an_older_database(tmp_path, monkeypatch):
    """An older backup (has signals, some flags missing): the missing flags come from Firestore admin/migrations."""
    _no_destruction(monkeypatch)
    rt, sink = _rt(), _live_firestore(tmp_path)
    rt.db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side) "
                  "VALUES ('s1', 1, 'BTC/USDT', '4h', 1, 'BUY', 'BUY', 100, 1)")
    have = ["fresh_start_v2", "fresh_start_v23", "testing_v24", "testing_v24b"]
    for f in have:
        rt.db.set_setting(f, True)
    assert not worker._looks_fresh(rt.db)
    sink.set(worker.MIGRATIONS_DOC, {"flags": {f: True for f in worker.MIGRATION_FLAGS if f != "reset_v1_done"}
                                     | {"reset_v1_done": 1761849960000}})
    notes = worker.sync_config(rt, sink)
    assert set(notes["migrations"]["from_firestore"]) == set(worker.MIGRATION_FLAGS) - set(have)
    assert rt.db.get_setting("reset_v1_done", 0) == 1761849960000
    assert sink.get("paper/m1_futures") == {"wallet": 12345}


def test_a_new_migration_still_runs_on_a_real_database(tmp_path):
    """The guard does not block migrations on a database with history: a flag missing everywhere still runs once."""
    rt, sink = _rt(), _live_firestore(tmp_path)
    for f in worker.MIGRATION_FLAGS:
        if f != "public_15m_v211":
            rt.db.set_setting(f, True)
    worker.sync_config(rt, sink)
    assert rt.db.get_setting("public_15m_v211", False)
    assert "futures-signal-ab-15m" in {b["id"] for b in sink.get("config/bots")["bots"]}


def test_mirror_only_writes_when_the_set_grows(tmp_path):
    rt, sink = _rt(), LocalSink(tmp_path)
    rt.db.set_setting("fresh_start_v2", True)
    assert worker.mirror_migrations(rt, sink) is True
    assert worker.mirror_migrations(rt, sink) is False
    rt.db.set_setting("tf_policy_v28", True)
    assert worker.mirror_migrations(rt, sink) is True
    assert set(sink.get(worker.MIGRATIONS_DOC)["flags"]) == {"fresh_start_v2", "tf_policy_v28"}


def test_every_flag_used_in_sync_config_is_listed():
    import inspect
    import re
    src = inspect.getsource(worker.sync_config) + inspect.getsource(worker.tick)
    used = set(re.findall(r'get_setting\("([a-z0-9_]+_v\d+[a-z]?)"', src))
    assert used <= set(worker.MIGRATION_FLAGS), used - set(worker.MIGRATION_FLAGS)


# ---- malformed member alerts -------------------------------------------------------------------------------

def test_alert_row_validation():
    ok = {"type": "PRICE_ABOVE", "symbol": "BTC/USDT", "timeframe": "1h", "params": {"price": 1}, "cooldown_s": 600,
          "enabled": True, "owner_uid": "m1"}
    assert worker.alert_row(ok)[:3] == ("PRICE_ABOVE", "BTC/USDT", "1h")
    assert worker.alert_row({**ok, "cooldown_s": "soon"})[4] == 3600
    assert worker.alert_row({**ok, "cooldown_s": float("nan")})[4] == 3600
    assert worker.alert_row({**ok, "cooldown_s": 1})[4] == 60
    assert worker.alert_row({**ok, "cooldown_s": 10 ** 12})[4] == 365 * 86_400
    assert worker.alert_row({**ok, "owner_uid": "gone"}, {"gone"})[5] == 0
    for bad in ({**ok, "symbol": 7}, {**ok, "symbol": None}, {**ok, "symbol": {"x": 1}}, {**ok, "symbol": "BTC/USDT; DROP"},
                {**ok, "type": "NOPE"}, {**ok, "params": "x"}, "not a dict", None):
        assert worker.alert_row(bad) is None


def test_malformed_alerts_never_stop_sync_config(tmp_path):
    rt, sink = _rt(), _live_firestore(tmp_path)
    for f in worker.MIGRATION_FLAGS:
        rt.db.set_setting(f, True)
    sink.set("alerts/good", {"type": "PRICE_ABOVE", "symbol": "ETH/USDT", "params": {"price": 1}, "cooldown_s": 600, "owner_uid": "m1"})
    sink.set("alerts/bad1", {"type": "PRICE_ABOVE", "symbol": 12, "cooldown_s": 600, "owner_uid": "m1"})
    sink.set("alerts/bad2", {"type": "PRICE_ABOVE", "symbol": "ETH/USDT", "cooldown_s": "x", "params": "y", "owner_uid": "m1"})
    sink.set("alerts/bad3", {"type": "PRICE_ABOVE", "symbol": "ETH/USDT", "created_at": "yesterday", "owner_uid": 5})
    notes = worker.sync_config(rt, sink)
    ids = {r["id"] for r in rt.db.query("SELECT id FROM alerts")}
    assert "good" in ids and "bad1" not in ids and "bad2" not in ids
    assert "bad3" in ids                          # odd created_at / owner are tolerated (now / the engine user)
    assert notes.get("bad_alerts_skipped", 0) == 0     # skipped by validation, nothing raised


def test_alert_insert_error_is_counted_not_raised(tmp_path, monkeypatch):
    rt, sink = _rt(), _live_firestore(tmp_path)
    for f in worker.MIGRATION_FLAGS:
        rt.db.set_setting(f, True)
    sink.set("alerts/a", {"type": "PRICE_ABOVE", "symbol": "ETH/USDT", "owner_uid": "m1"})
    monkeypatch.setattr(worker, "alert_row", lambda a, inactive=frozenset(): (_ for _ in ()).throw(ValueError("x")))
    notes = worker.sync_config(rt, sink)
    assert notes["bad_alerts_skipped"] == 1


# ---- errors: admin-only view and redaction -------------------------------------------------------------------

TOKEN = "bot1234567890:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"


def test_redact_tokens_and_url_secrets():
    s = f"HTTPSConnectionPool(host='api.telegram.org'): Max retries with url: /{TOKEN}/sendPhoto?chat_id=1"
    assert "AAHdq" not in redact(s) and "bot<redacted>" in redact(s)
    s = "GET https://generativelanguage.googleapis.com/v1/models:generate?key=AIzaSyA-1234567890abcdefghijklmnopqrstu&alt=json"
    out = redact(s)
    assert "AIzaSy" not in out and "key=<redacted>" in out and "alt=json" in out
    assert redact("https://x.io/a?token=abc123&x=1") == "https://x.io/a?token=<redacted>&x=1"
    assert redact("plain message") == "plain message" and redact(None) is None
    assert "AAHdq" not in error_text(RuntimeError(f"failed /{TOKEN}/send"))


def test_runtime_errors_are_redacted():
    rt = _rt()
    rt.record_error("engine telegram", RuntimeError(f"POST https://api.telegram.org/{TOKEN}/sendMessage failed"))
    assert "AAHdq" not in rt.errors[-1]["error"]


def test_health_split_keeps_raw_errors_out_of_the_member_view():
    h = {"status": "LIVE", "generated_at": 1, "recent_errors": [{"ts": 1, "where": "engine telegram", "error": f"x /{TOKEN}/y"}],
         "exchange": {"errors": 2, "last_error": "klines: HTTP 451 ?key=abc"}, "market_data": {"status": "OK", "last_error": "boom"},
         "models": [{"symbol": "BTC/USDT", "timeframe": "1h", "state": "failed", "message": "ValueError: bad"}], "engine": {"ticks": 3}}
    public, admin = health.split_errors(h)
    assert "recent_errors" not in public and public["recent_errors_count"] == 1
    assert public["exchange"]["last_error"] is None and public["exchange"]["has_error"] is True
    assert public["market_data"]["last_error"] is None and "message" not in public["models"][0]
    assert public["engine"] == {"ticks": 3} and public["status"] == "LIVE"
    assert "AAHdq" not in admin["recent_errors"][0]["error"] and admin["exchange_last_error"].endswith("key=<redacted>")
    assert admin["model_messages"] == [{"symbol": "BTC/USDT", "timeframe": "1h", "message": "ValueError: bad"}]
    import json
    assert "AAHdq" not in json.dumps(public) and "ValueError" not in json.dumps(public)


def test_state_guard_script(tmp_path, monkeypatch):
    import importlib.util
    import os
    spec = importlib.util.spec_from_file_location("state_guard", os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "state_guard.py"))
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    assert g.state_ok(str(tmp_path / "missing.db"))[0] is False
    db = Database(f"sqlite:///{tmp_path / 'x.db'}")
    db.set_setting("a", 1)
    assert g.state_ok(str(tmp_path / "x.db"))[0] is False             # settings but no candles: looks empty
    db.execute("INSERT INTO market_data (exchange, symbol, timeframe, ts, open, high, low, close, volume) "
               "VALUES ('x', 'BTC/USDT', '1h', 1, 1, 1, 1, 1, 1)")
    assert g.state_ok(str(tmp_path / "x.db"))[0] is True
    monkeypatch.setattr("sys.argv", ["state_guard.py", str(tmp_path / "missing.db")])
    monkeypatch.delenv("FRESH_INSTALL", raising=False)
    assert g.main() == 1
    monkeypatch.setenv("FRESH_INSTALL", "1")
    assert g.main() == 0
