"""Batch engine (Firebase deployment): a full cycle against a local sink, website actions, the Binance provider."""
import asyncio
import json
import tempfile
import time

from app import worker
from app.config import settings
from app.data.binance_public import BinancePublicProvider
from app.db import Database
from app.services.runtime import Runtime
from app.sinks import LocalSink
from tests.helpers import ArrayProvider


def _view(sink, name):
    doc = sink.get(f"views/{name}")
    return json.loads(doc["json"]) if doc else None


def test_engine_cycle_publishes_views_runs_jobs_and_bots():
    settings.symbols = ["BTC/USDT", "ETH/USDT"]
    settings.model_dir = tempfile.mkdtemp()
    now = int(time.time() * 1000)
    end = now - now % 900_000 + 900_000
    db = Database("sqlite:///:memory:")
    rt = Runtime(db, ArrayProvider(("BTC/USDT", "ETH/USDT"), predictable=0.15, end_ms=end))
    sink = LocalSink(tempfile.mkdtemp(), db)
    d = worker.tick(rt, sink, budget_s=900, fetch_context=False)
    assert d["status"] == "ok", d["steps"]
    assert len(d["bootstrap"]) >= 8                                    # missing models trained (fast set)
    a = _view(sink, "analysis_BTCUSDT_4h")
    assert a["status"] == "OK" and a["forecast"]["available"] and "NaN" not in sink.get("views/analysis_BTCUSDT_4h")["json"]
    for name in ("futures_4h", "futures_1h", "meta", "health", "dashboard_4h", "models_BTCUSDT_4h", "perf_BTCUSDT_4h", "performance", "signals",
                 "alerts", "backtests", "bots", "settings", "models_status", "replay_ranges", "cross_asset_1d"):
        assert _view(sink, name) is not None, name
    assert sink.get("config/bots")["bots"] and sink.get("config/watchlist")["symbols"]
    assert _view(sink, "health")["engine"]["ticks"] == 1

    # the website edits configuration and queues work
    sink.set("config/watchlist", {"symbols": [{"symbol": "BTC/USDT", "pinned": True}, {"symbol": "ETH/USDT"},
                                              {"symbol": "NOPE/USDT"}]})
    sink.set("config/settings", {"risk_profile": {"portfolio": 50_000}, "signal_weights": {"trend": 0.5}})
    sink.set("alerts/a1", {"type": "PRICE_ABOVE", "symbol": "BTC/USDT", "timeframe": "4h", "params": {"level": 1e9}})
    sink.set("jobs/j1", {"type": "backtest", "status": "queued", "created_at": now,
                         "params": {"symbol": "BTC-USDT", "timeframe": "4h", "strategy": "sma_cross"}})
    sink.set("jobs/j2", {"type": "bogus", "status": "queued", "created_at": now + 1, "params": {}})
    d2 = worker.tick(rt, sink, budget_s=900, fetch_context=False)
    assert d2["status"] == "ok" and d2["jobs"] == 2
    assert d2["skipped_unchanged"] > 0                                 # unchanged documents cost no writes
    assert sink.get("jobs/j1")["status"] == "done" and json.loads(sink.get("jobs/j1")["json"])["status"] == "done"
    assert sink.get("jobs/j2")["status"] == "failed"
    assert rt.watchlist()[0] == {**rt.watchlist()[0], "symbol": "BTC/USDT", "pinned": 1}
    assert "NOPE/USDT" not in rt.symbols() and d2["config"]["rejected_symbols"] == ["NOPE/USDT"]
    assert rt.risk_profile().portfolio == 50_000 and rt.signal_weights()["trend"] == 0.5
    assert "a1" in _view(sink, "alerts")["state"]
    assert {b["id"] for b in sink.get("config/bots")["bots"]} >= {"futures-signal-ab-4h", "signal-ab-1h"}
    # the website replaces the list (keeping the other fields, as the site does): deleted defaults stay deleted
    sink.set("config/bots", {**sink.get("config/bots"),
                             "bots": [{"id": "only", "mode": "prediction", "timeframe": "4h", "reset_token": "1"}]})
    worker.tick(rt, sink, budget_s=900, fetch_context=False)
    assert [b["config"]["id"] for b in _view(sink, "bots")["bots"]] == ["only"]


class _Resp:
    def __init__(self, status, payload, headers=None):
        self.status_code, self._p, self.headers, self.text = status, payload, headers or {}, json.dumps(payload)

    def json(self):
        return self._p


class _Session:
    def __init__(self, script):
        self.script, self.calls = script, []

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        for prefix, resp in self.script:
            if url.startswith(prefix):
                return resp
        raise ConnectionError("unreachable")

    def close(self):
        pass


def test_binance_provider_falls_back_between_hosts_and_parses():
    kline = [[1_700_000_000_000, "1", "2", "0.5", "1.5", "10", 0, "0", 0, "0", "0", "0"]]
    s = _Session([("https://geo-blocked", _Resp(451, {})), ("https://ok", _Resp(200, kline))])
    p = BinancePublicProvider(hosts=["https://geo-blocked", "https://ok"], session=s)
    rows = asyncio.run(p.fetch_ohlcv("BTC/USDT", "4h", since=0, limit=5000))
    assert rows == [[1_700_000_000_000, 1.0, 2.0, 0.5, 1.5, 10.0]] and p.host_used == "https://ok"
    asyncio.run(p.fetch_ohlcv("BTC/USDT", "4h"))
    assert s.calls[-1].startswith("https://ok")                       # the working host is tried first next time
    bad = BinancePublicProvider(hosts=["https://x"], session=_Session([("https://x", _Resp(400, {"msg": "bad symbol"}))]))
    try:
        asyncio.run(bad.fetch_ohlcv("NOPE/USDT", "1h"))
        raise AssertionError("a 400 must raise")
    except ValueError:
        pass
    down = BinancePublicProvider(hosts=["https://a"], session=_Session([]))
    try:
        asyncio.run(down.fetch_ticker("BTC/USDT"))
        raise AssertionError("no reachable host must raise")
    except ConnectionError:
        assert down.errors == 1 and down.last_error


def test_track_record_view_is_honest_and_complete():
    from app import views
    from app.db import Database
    from app.services.runtime import Runtime

    rt = Runtime(Database("sqlite:///:memory:"), None)
    ins = ("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, "
           "tp1, tp2, tp3, status, return_pct, closed_at, payload) VALUES (?, ?, 'BTC/USDT', '4h', ?, 'BUY', 'BUY', 100, 1, "
           "100, 95, 105, 110, 115, ?, ?, ?, ?)")
    rt.db.execute(ins, ("a", 1, 1, "TP2", 6.0, 10, '{"grade": "A"}'))
    rt.db.execute(ins, ("b", 2, 2, "STOPPED", -5.0, 20, '{"grade": "B"}'))
    rt.db.execute(ins, ("c", 3, 3, "OPEN", None, None, '{}'))
    v = views.track_record(rt, {"bots": []})
    s = v["live"]["summary"]
    assert s["closed"] == 2 and s["win_rate"] == 0.5 and abs(s["total_return_pct"] - 1.0) < 1e-9
    assert v["live"]["open"] == 1 and v["live"]["by_grade"]["A"]["closed"] == 1 and len(v["live"]["signals"]) == 3
    assert [p["cum_return_pct"] for p in v["live"]["curve"]] == [6.0, 1.0]


def test_weekly_report_shows_best_trades_and_the_full_totals():
    from app import views
    from app.db import Database
    from app.services.runtime import Runtime

    rt = Runtime(Database("sqlite:///:memory:"), None)
    st = views.week_start(1_793_000_000_000)
    assert (st // 86_400_000 + 3) % 7 == 0 and st % 86_400_000 == 0          # a Monday, midnight UTC
    ins = ("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, "
           "tp1, tp2, tp3, status, return_pct, closed_at, payload) VALUES (?, ?, ?, '4h', ?, 'BUY', 'BUY', 100, 1, 100, 95, "
           "105, 110, 115, ?, ?, ?, '{}')")
    rt.db.execute(ins, ("a", st + 1, "BTC/USDT", 1, "TP3", 9.0, st + 10))
    rt.db.execute(ins, ("b", st + 2, "ETH/USDT", 2, "STOPPED", -4.0, st + 20))
    rt.db.execute(ins, ("c", st + 3, "SOL/USDT", 3, "TP1", 2.0, st + views.WEEK + 5))     # closes next week
    r = views.weekly_report(rt, st)
    assert r["closed"] == 2 and r["wins"] == 1 and r["losses"] == 1 and r["issued"] == 3
    assert r["best"][0]["symbol"] == "BTC/USDT" and r["worst"]["symbol"] == "ETH/USDT" and abs(r["total_return_pct"] - 5) < 1e-9


def test_achievements_unlock_only_from_real_results():
    from app import views
    from app.db import Database
    from app.services.runtime import Runtime

    rt = Runtime(Database("sqlite:///:memory:"), None)
    ins = ("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, "
           "tp1, tp2, tp3, status, return_pct, closed_at, payload) VALUES (?, ?, 'BTC/USDT', '4h', ?, 'BUY', 'BUY', 100, 1, "
           "100, 95, 105, 110, 115, ?, ?, ?, '{}')")
    now = views.now_ms()
    for i, (st, r) in enumerate([("TP1", 1.0), ("TP3", 7.5), ("TP2", 3.0), ("STOPPED", -2.0)] * 3):
        rt.db.execute(ins, (str(i), now - 1000 + i, i, st, r, now - 10 * 86_400_000 + i * 3_600_000))
    v = views.track_record(rt, {"bots": []})
    a = {x["id"]: x for x in v["achievements"]}
    assert a["signals_10"]["unlocked"] and not a["signals_50"]["unlocked"] and 0 < a["signals_50"]["progress"] < 1
    assert a["best_trade"]["value"] == "+75.0% ROI" and a["best_trade"]["leverage"] == 10 and a["best_trade"]["return_pct"] == 7.5 and a["win_streak"]["value"] == "3 in a row" and a["all_targets"]["unlocked"]
    assert not a["win_rate_30d"]["unlocked"]                # 12 signals: fewer than the 20 required
    assert v["achievements"][0]["unlocked"] and not v["achievements"][-1]["unlocked"]


def test_wins_today_lists_real_recent_wins_only():
    from app import views
    from app.db import Database
    from app.services.runtime import Runtime

    rt = Runtime(Database("sqlite:///:memory:"), None)
    now = views.now_ms()
    ins = ("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, "
           "tp1, tp2, tp3, status, return_pct, closed_at, payload) VALUES (?, 1, ?, '1h', ?, 'BUY', 'BUY', 100, 1, 100, 95, "
           "105, 110, 115, ?, ?, ?, '{}')")
    rt.db.execute(ins, ("a", "BTC/USDT", 1, "TP2", 4.0, now - 3_600_000))
    rt.db.execute(ins, ("b", "ETH/USDT", 2, "STOPPED", -2.0, now - 3_600_000))
    rt.db.execute(ins, ("c", "SOL/USDT", 3, "TP1", 1.0, now - 3 * 86_400_000))
    v = views.wins_today(rt)
    assert v["period"] == "today" and [w["symbol"] for w in v["wins"]] == ["BTC/USDT"] and v["wins"][0]["target"] == 110
    rt.db.execute("DELETE FROM signals WHERE id = 'a'")
    v = views.wins_today(rt)
    assert v["period"] == "this week" and v["wins"][0]["symbol"] == "SOL/USDT"


def test_v2_fresh_start_resets_bots_once_and_starts_the_record(tmp_path):
    from app import worker
    from app.db import Database
    from app.services.runtime import Runtime
    from app.sinks import LocalSink

    class _P:
        name = "test"

        async def search_markets(self, q, limit=50):
            return []

    rt = Runtime(Database("sqlite:///:memory:"), _P())
    rt.db.set_setting("fresh_start_v23", True)          # this test covers the v2.0 reset only
    sink = LocalSink(tmp_path)
    sink.set("config/bots", {"bots": [{**worker.DEFAULT_BOTS[0]}], "defaults_added": [b["id"] for b in worker.DEFAULT_BOTS]})
    worker.sync_config(rt, sink)
    tokens = [b["reset_token"] for b in sink.get("config/bots")["bots"]]
    assert all(t.startswith("v2-") for t in tokens) and rt.db.get_setting("record_since", 0) > 0
    worker.sync_config(rt, sink)
    assert [b["reset_token"] for b in sink.get("config/bots")["bots"]] == tokens        # only once


def test_parallel_training_slices_are_registered_by_the_merge(monkeypatch, tmp_path):
    """A slice trains on its own copy of the state and exports the models; the merge registers them in the real
    state (a newer model that is already active is never replaced)."""
    import shutil

    from app.ml import trainer
    from app.services import training
    from app.sinks import LocalSink
    from tests.helpers import make_runtime

    rt, _ = make_runtime(symbols=("BTC/USDT",), predictable=0.15)
    monkeypatch.setattr(worker, "MODEL_TIMEFRAMES", ["4h"])
    monkeypatch.setattr(training, "train_one", lambda rt_, s, tf, fast=False: _orig(rt_, s, tf, True))   # fast set in tests
    monkeypatch.setattr(rt.store, "is_current", lambda *a, **k: True)                                      # test data ends earlier
    out = tmp_path / "slice-0"
    r = worker.train_shard(rt, 0, 1, 600, str(out))
    assert r["exported"] == 1 and (out / "manifest.json").exists()
    rec = json.loads((out / "manifest.json").read_text())["records"][0]
    # the "real" state: a fresh database that has never seen this model
    rt2, _ = make_runtime(symbols=("BTC/USDT",), predictable=0.15, model_dir=str(tmp_path / "models2"))
    sink = LocalSink(str(tmp_path / "sink"), rt2.db)
    d = worker.train_merge(rt2, sink, str(tmp_path))
    assert d["imported"] == 1 and trainer.active_version("BTC/USDT", "4h", rt2.db)["id"] == rec["version"]
    assert trainer.load_bundle("BTC/USDT", "4h", rt2.db)["version"] == rec["version"]
    assert worker.train_merge(rt2, sink, str(tmp_path))["imported"] == 0          # importing twice changes nothing


from app.services import training as _training  # noqa: E402

_orig = _training.train_one


def test_firestore_batches_are_cut_by_size_and_count():
    from app.sinks import chunks
    docs = {f"views/a{i}": {"json": "x" * 300_000, "updated_at": 1} for i in range(60)}       # 18 MB in total
    groups = list(chunks(docs, max_docs=400, max_bytes=7_000_000))
    assert sum(len(g) for g in groups) == 60 and all(sum(len(d["json"]) for _, d in g) <= 7_000_000 for g in groups)
    small = {f"views/b{i}": {"json": "y", "updated_at": 1} for i in range(900)}
    assert [len(g) for g in chunks(small)] == [400, 400, 100]


def test_push_sending_has_a_hard_time_limit(monkeypatch):
    import subprocess
    import time
    from app.sinks import FirestoreSink
    sink = FirestoreSink.__new__(FirestoreSink)
    sink.PUSH_TIMEOUT_S = 1

    def hang(*a, **k):
        raise subprocess.TimeoutExpired("push", 1)
    monkeypatch.setattr(subprocess, "run", hang)
    t = time.time()
    out = sink.send_push([{"title": "x", "body": "y"}])
    assert time.time() - t < 5 and "did not answer" in out["error"]


def test_fresh_start_v23_clears_bots_admin_practice_and_restarts_the_record(tmp_path, monkeypatch):
    from app.db import Database
    from app.services.runtime import Runtime
    from app.sinks import LocalSink
    from app import worker
    db = Database("sqlite:///:memory:")
    rt = Runtime(db, None)
    sink = LocalSink(tmp_path, db)
    import os
    os.environ["ADMIN_EMAILS"] = "owner@x.com"
    monkeypatch.setattr(LocalSink, "uid_for_email", lambda self, e: "ADMIN" if e == "owner@x.com" else None)
    sink.set("paper/ADMIN_futures", {"balance": 1}); sink.set("paper/MEMBER_futures", {"balance": 2})
    sink.set("paper_futures_trades/t1", {"uid": "ADMIN"}); sink.set("paper_futures_trades/t2", {"uid": "MEMBER"})
    sink.set("auto_paper/ADMIN", {"enabled": True})
    out = worker.clear_admin_practice(sink)
    assert out["accounts"] == 1 and out["trades"] == 1
    assert sink.get("paper/MEMBER_futures") and sink.get("paper_futures_trades/t2") and sink.get("auto_paper/ADMIN")
    assert sink.get("paper/ADMIN_futures") is None and sink.get("paper_futures_trades/t1") is None



def test_fresh_start_v23_runs_once(tmp_path):
    from app import worker
    from app.db import Database
    from app.services.runtime import Runtime
    from app.sinks import LocalSink

    class _P:
        name = "test"

        async def search_markets(self, q, limit=50):
            return []
    rt = Runtime(Database("sqlite:///:memory:"), _P())
    for f in ("fresh_start_v2", "bots_cleanup_v22", "bots_lev20_v23"):
        rt.db.set_setting(f, True)
    sink = LocalSink(tmp_path, rt.db)
    sink.set("config/bots", {"bots": [{"id": "old-bot", "mode": "decision", "timeframe": "4h"}]})
    notes = worker.sync_config(rt, sink)
    ids = [b["id"] for b in sink.get("config/bots")["bots"]]
    assert "old-bot" not in ids and len(ids) == 7 and sum(i.startswith("futures-") for i in ids) == 4      # v2.8: 15m public + 1d bots off, 15m demo bot on
    assert notes["fresh_start_v23"]["bots"] == 10 and rt.db.get_setting("record_since", 0) > 0
    first = rt.db.get_setting("record_since", 0)
    worker.sync_config(rt, sink)
    assert rt.db.get_setting("record_since", 0) == first                     # only once


def test_15m_record_restart_counts_wins_and_losses_alike_from_the_restart():
    from app import views
    from app.db import Database
    from app.services.runtime import Runtime
    rt = Runtime(Database("sqlite:///:memory:"), None)
    rt.db.set_setting("record_since", 1000)
    ins = ("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, "
           "tp1, tp2, tp3, status, return_pct, closed_at) VALUES (?, ?, 'BTC/USDT', ?, ?, 'BUY', 'BUY', 100, 1, 100, 98, "
           "102, 104, 106, ?, ?, ?)")
    rt.db.execute(ins, ("a", 2000, "15m", 1, "TP2", 1.5, 2500))     # old 15m win
    rt.db.execute(ins, ("b", 2100, "15m", 2, "STOPPED", -1.0, 2600))  # old 15m loss
    rt.db.execute(ins, ("c", 2200, "1h", 3, "STOPPED", -1.0, 2700))   # 1h loss stays
    rt.db.execute(ins, ("d", 6000, "15m", 4, "TP1", 0.5, 6500))       # new 15m
    rt.db.set_setting("record_since_tf", {"15m": 5000})
    rc, rp = views.record_clause(rt)
    ids = [r["id"] for r in rt.db.query(f"SELECT id FROM signals WHERE {rc} ORDER BY id", rp)]
    assert ids == ["c", "d"] and views.record_for(rt, "15m") == 5000 and views.record_for(rt, "1h") == 1000


def test_sink_paces_views_counts_writes_and_backs_off_on_quota(tmp_path):
    from app.db import Database
    from app.sinks import LocalSink
    s = LocalSink(tmp_path / "out", Database(str(tmp_path / "x.db")))
    s.view("a", {"x": 1}, min_interval_s=900, core=["BUY"])
    assert s.flush() == 1
    s.view("a", {"x": 2}, min_interval_s=900, core=["BUY"])     # changed numbers, same call: held back
    assert s.flush() == 0
    s.view("a", {"x": 3}, min_interval_s=900, core=["SELL"])    # the call changed: goes out at once
    assert s.flush() == 1 and s.writes_today() == 2

    def quota(docs):
        raise RuntimeError("429 Quota exceeded.")
    s._write_many = quota
    s.view("b", {"y": 1})
    assert s.flush() == 0 and s.blocked()                       # no exception, no retries
    s.view("c", {"y": 1})
    assert s.flush() == 0 and s.held == 2
