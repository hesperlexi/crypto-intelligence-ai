"""1-2 Nov scalping rebuild (services/scalp_backfill.py): replays the engine's decision per closed 15m candle with the
model the live engine used then, one call per coin, re-entry cooldown, rows marked, incremental and idempotent, and the
record's public outputs byte-identical."""
import json

import joblib
import pandas as pd
import pytest

from app import views
from app.data.base import tf_ms
from app.db import Database, dumps, loads
from app.ml import direction, trainer
from app.services import analysis, scalp_backfill as B, tracking as T

M15 = tf_ms("15m")
DAY = 86_400_000
W0 = B.WINDOW_START
LIVE = W0 + 40 * M15                 # the live log "shipped" 40 candles into the window
NOW = W0 + 3 * DAY


class RT:
    exchange = "binance"

    def __init__(self, db, paths, symbols):
        self.db, self.paths, self._symbols, self.errors = db, paths, symbols, []

    def symbols(self):
        return list(self._symbols)

    def candles(self, symbol, tf, as_of=None):
        df = self.paths.get(symbol)
        if df is None or tf != "15m":
            return pd.DataFrame(columns=["ts", "open", "high", "low", "close"])
        return df

    def record_error(self, where, exc):
        self.errors.append((where, str(exc)))


def _path(start, n, rows):
    """`rows`: function i -> (open, high, low, close)."""
    return pd.DataFrame([[start + i * M15, *rows(i)] for i in range(n)], columns=["ts", "open", "high", "low", "close"])


def _bundle(tmp_path, db, vid, created, data_end):
    b = {"version": vid, "symbol": "X", "timeframe": "15m", "created_at": created, "data_end": data_end,
         "edge": {"edge_confirmed": True}, "oos": {}, "prior": [1 / 3] * 3}
    path = tmp_path / f"{vid}.joblib"
    joblib.dump(b, path)
    db.execute("INSERT INTO model_versions (id, symbol, timeframe, created_at, data_end, active, path) "
               "VALUES (?, 'X', '15m', ?, ?, 0, ?)", (vid, created, data_end, str(path)))


def _pred(db, sym, bar_ts, vid, p_up=0.7):
    db.execute("INSERT INTO predictions (id, created_at, symbol, timeframe, bar_ts, target_ts, model_version_id, price, "
               "p_down, p_neutral, p_up, predicted_class, neutral_band) VALUES (?, ?, ?, '15m', ?, ?, ?, 100, ?, 0.1, ?, 2, 0.001)",
               (f"{sym}{bar_ts}{vid}", bar_ts + M15 + 120_000, sym, bar_ts, bar_ts + 2 * M15, vid, 0.9 - p_up, p_up))


def _fake_analyze(calls):
    def analyze(rt, symbol, tf, as_of=None, bundle=None, detail=True, use_cache=True, multipliers=None):
        calls.append((symbol, as_of, bundle["version"], multipliers))
        assert as_of is not None and bundle is not None and bundle["created_at"] < as_of + M15
        return {"status": "OK", "symbol": symbol, "timeframe": "15m", "bar_ts": as_of - M15, "price": 100.0,
                "last_close": 100.0, "decision": "BUY", "grade": "A", "demo": None, "stale": False, "confidence": 0.6,
                "regime": {"regime": "BULL"}, "volatility": {"state": "NORMAL"}, "mtf": {},
                "signal": {"signal": "BUY", "score": 70}, "forecast": {"probabilities": {"up": 0.7, "down": 0.2},
                                                                       "model_version": bundle["version"]},
                "setup": {"valid": True, "side_int": 1, "ideal_entry": 100.0, "stop": 99.0, "risk_reward": 1.4,
                          "atr": 0.5, "risk_pct": 1.0, "targets": [{"price": 101.0, "rr": 1.0}, {"price": 101.5, "rr": 1.5},
                                                                   {"price": 102.0, "rr": 2.0}]}}
    return analyze


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setattr(T, "now_ms", lambda: NOW)
    monkeypatch.setattr(views, "now_ms", lambda: NOW)
    monkeypatch.setattr(direction, "view", lambda fc, b: {"margin": abs(fc["probabilities"]["up"] - fc["probabilities"]["down"]),
                                                          "policy_margin": 0.3})
    from app.services import series_nightly
    monkeypatch.setattr(series_nightly, "entry_rule", lambda db, tf: ("old", 0.0))
    calls: list = []
    monkeypatch.setattr(analysis, "analyze", _fake_analyze(calls))
    B._bundles.clear()
    db = Database("sqlite:///:memory:")
    db.set_setting("scalping_since", LIVE)
    db.set_setting("scalping_v1", True)
    _bundle(tmp_path, db, "v_old", W0 - 5 * DAY, W0 - 6 * DAY)          # trained well before the window
    _bundle(tmp_path, db, "v_new", W0 + 20 * M15, W0 + 19 * M15)        # trained during the window
    db.execute("INSERT INTO model_versions (id, symbol, timeframe, created_at, active, path) "
               "VALUES ('v_gone', 'X', '15m', ?, 0, ?)", (W0 - 5 * DAY, str(tmp_path / "missing.joblib")))
    n = int((NOW - W0) / M15) + 8
    start = W0 - 4 * M15
    paths = {
        # BTC: calm, the first call never reaches stop or target -> one call for the whole window (one per coin)
        "BTC/USDT": _path(start, n, lambda i: (100, 100.3, 99.7, 100)),
        # ETH: every 10th candle dips to the stop -> a call, a stop, the cooldown, the next call ...
        "ETH/USDT": _path(start, n, lambda i: (100, 100.3, 98.5 if i % 10 == 9 else 99.7, 100)),
        "SOL/USDT": _path(start, n, lambda i: (100, 100.3, 99.7, 100)),
        "XRP/USDT": _path(start, n, lambda i: (100, 100.3, 99.7, 100)),
    }
    for k in range(-1, 45):
        bar = W0 + (k - 1) * M15                        # closes at W0 + k*M15
        _pred(db, "BTC/USDT", bar, "v_old")
        _pred(db, "ETH/USDT", bar, "v_old")
        # SOL: before candle 20 the live engine used a model that is gone; then one trained mid-window, which the
        # replay may use only for candles after its training (never for the ones before)
        _pred(db, "SOL/USDT", bar, "v_gone" if k < 20 else "v_new")
        # XRP: the live AI lean was below its threshold except on a few candles
        _pred(db, "XRP/USDT", bar, "v_old", p_up=0.7 if k in (5, 30) else 0.5)
    rt = RT(db, paths, ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"])
    return rt, calls


def _rows(db):
    return db.query("SELECT * FROM scalp_signals ORDER BY symbol, created_at")


def test_backfill_rebuilds_marks_and_follows(world):
    rt, calls = world
    out = B.run(rt, budget_s=60, max_analyses=10_000, now=NOW)
    assert out["done"] and rt.db.get_setting(B.DONE_FLAG) is True
    rows = _rows(rt.db)
    by = {}
    for r in rows:
        by.setdefault(r["symbol"], []).append(r)
    # one call per coin at a time: BTC's first call ran past the end of the window (250-candle limit)
    btc = by["BTC/USDT"][0]
    assert len(by["BTC/USDT"]) == 1 and btc["status"] == "EXPIRED" and btc["closed_at"] > LIVE
    assert by["BTC/USDT"][0]["created_at"] == W0 + 120_000                      # when the live engine analysed it
    # ETH: stopped calls, each next call only after the stop was known and the cooldown passed
    eth = by["ETH/USDT"]
    assert len(eth) >= 3
    for a, b in zip(eth, eth[1:]):
        assert a["status"] == "STOPPED" and b["created_at"] >= a["closed_at"] + M15 * (1 + B.settings.reentry_cooldown_bars)
    # SOL: model file gone before candle 20; candle 20 skipped (its model was trained on data up to candle 19, whose
    # label needs candle 20's close); usable from candle 21 on
    sol = by.get("SOL/USDT", [])
    assert sol and sol[0]["bar_ts"] + M15 == W0 + 21 * M15
    st = rt.db.get_setting(B.STATE_KEY)
    assert st["skipped"]["model_file_missing"] >= 19 and st["skipped"]["model_newer_than_call"] >= 1
    # XRP: only where the live AI lean cleared its threshold
    # (the one at candle 30 is not made: the candle-5 call was still running - one call per coin)
    assert [r["bar_ts"] + M15 for r in by["XRP/USDT"]] == [W0 + 5 * M15]
    assert st["skipped"]["ai_below_threshold"] >= 5 and st["skipped"]["already_open"] >= 30
    # nothing at or after the moment the live log started; every row marked
    for r in rows:
        p = loads(r["payload"])
        assert r["created_at"] < LIVE and p["backfilled"] is True and p["rebuilt_at"] == NOW and p["grade"] == "A"
        assert p["replay"]["model_trained_at"] < r["created_at"] and p["replay"]["as_of"] == r["bar_ts"] + M15
        assert p["horizon_bars"] == 250
    assert all(a[3] == {} for a in calls)                                        # weights as they stood (none scored)
    # migration: counted from 1 Nov 00:00 Dubai, live start kept
    assert rt.db.get_setting("scalping_since") == W0 and rt.db.get_setting(B.LIVE_SINCE_KEY) == LIVE
    assert rt.db.get_setting(B.KEEP_KEY) == []                                    # model files released when done


def test_backfill_is_incremental_and_idempotent(world):
    rt, calls = world
    steps = 0
    while not B.run(rt, budget_s=60, max_analyses=2, now=NOW)["done"]:
        steps += 1
        assert steps < 200
    assert steps > 1
    first = dumps(_rows(rt.db))
    # a second pass (flags cleared, cursor reset) adds nothing
    rt.db.set_setting(B.DONE_FLAG, False)
    st = rt.db.get_setting(B.STATE_KEY)
    st["cursor"] = {s: W0 for s in st["symbols"]}
    rt.db.set_setting(B.STATE_KEY, st)
    B.run(rt, budget_s=60, max_analyses=10_000, now=NOW)
    again = _rows(rt.db)
    assert dumps(again) == first
    assert len({(r["symbol"], r["bar_ts"]) for r in again}) == len(again)


def test_backfill_keeps_model_files_until_done(world):
    rt, _ = world
    B.init(rt, NOW)
    keep = set(rt.db.get_setting(B.KEEP_KEY))
    assert {"v_old", "v_new", "v_gone"} <= keep
    rt.db.execute("UPDATE model_versions SET created_at = 0")
    assert trainer.prune_files(rt.db) == 0                                       # the needed files survive the clean-up


def test_backfill_leaves_the_record_byte_identical(world):
    from tests.test_scalping import _counts, _public, _record_fixture
    rt, _ = world
    _record_fixture(rt.db)
    before, counts = _public(rt), _counts(rt.db)
    sig = dumps(rt.db.query("SELECT * FROM signals ORDER BY id"))
    shadow = dumps(rt.db.query("SELECT * FROM shadow_signals ORDER BY id"))
    B.run(rt, budget_s=60, max_analyses=10_000, now=NOW)
    assert _rows(rt.db)
    after = _public(rt)
    for k in before:
        assert after[k] == before[k], k
    assert _counts(rt.db) == counts
    assert dumps(rt.db.query("SELECT * FROM signals ORDER BY id")) == sig
    assert dumps(rt.db.query("SELECT * FROM shadow_signals ORDER BY id")) == shadow


def test_view_splits_rebuilt_and_live_and_flags_overlaps(world):
    rt, _ = world
    # a live call on BTC after the log shipped, while the rebuilt BTC call was still running
    rt.db.execute("INSERT INTO scalp_signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, "
                  "stop, tp1, tp2, tp3, status, return_pct, closed_at, payload, fill_status) VALUES ('live1', ?, 'BTC/USDT', "
                  "'15m', ?, 'BUY', 'BUY', 100, 1, 100, 99, 101, 101.5, 102, 'TP1', 0.5, ?, ?, 'FILLED')",
                  (LIVE + M15, LIVE, LIVE + 5 * M15, json.dumps({"grade": "A", "scalp": True, "leverage": 20})))
    B.run(rt, budget_s=60, max_analyses=10_000, now=NOW)
    btc = rt.db.one("SELECT payload FROM scalp_signals WHERE symbol = 'BTC/USDT' AND id != 'live1'")
    assert loads(btc["payload"])["overlaps_live"] == ["live1"]
    v = views.scalping(rt)
    assert v["since"] == W0 and v["backfill"]["state"] == "done" and v["backfill"]["live_since"] == LIVE
    assert "rebuilt" in v["backfill"]["note"]
    assert v["counts"]["live"] == 1 and v["counts"]["rebuilt"] == v["logged"] - 1
    assert v["split"]["live"]["closed"] == 1 and v["split"]["rebuilt"]["closed"] == v["summary"]["closed"] - 1
    assert any(x["rebuilt"] for x in v["recent"] + v["open"]) and not next(x for x in v["recent"] if x["id"] == "live1")["rebuilt"]
    assert "roi" not in dumps(v).lower()


def test_backfill_with_a_real_model_and_no_look_ahead(tmp_path, monkeypatch):
    """End to end on synthetic candles with a real (fast) 15m model trained on candles before the window: the replayed
    analysis runs through analysis.analyze(as_of=...) and a model trained after a candle is never used for it."""
    from tests.helpers import make_runtime

    rt, _ = make_runtime(symbols=("BTC/USDT",), model_dir=str(tmp_path))
    df = rt.candles("BTC/USDT", "15m")
    w0 = int(df["ts"].iloc[-12])
    monkeypatch.setattr(B, "WINDOW_START", w0)
    cut = w0 - 40 * M15
    b = trainer.train_bundle("BTC/USDT", "15m", rt.frame("BTC/USDT", "15m", cut), None, fast=True)
    b["created_at"] = cut + 60_000
    trainer.save_bundle(b, rt.db)
    assert b["data_end"] + 2 * M15 <= cut
    for k in range(0, 8):
        _pred(rt.db, "BTC/USDT", w0 + (k - 1) * M15, b["version"])
    rt.db.set_setting("scalping_since", w0 + 8 * M15)
    seen = []
    real = analysis.analyze

    def spy(*a, **kw):
        seen.append(kw.get("as_of"))
        return real(*a, **kw)
    monkeypatch.setattr(analysis, "analyze", spy)
    monkeypatch.setattr(direction, "view", lambda fc, bb: {"margin": 1.0, "policy_margin": 0.0})   # replay every candle
    from app.config import settings
    monkeypatch.setattr(settings, "require_edge_for_trade", False)     # default off since v2.14; this test replays every candle
    B._bundles.clear()
    out = B.run(rt, budget_s=600, max_analyses=10_000)
    assert out["done"] and len(seen) == 8 and all(s is not None for s in seen)
    for r in rt.db.query("SELECT * FROM scalp_signals"):
        p = loads(r["payload"])
        assert p["backfilled"] and p["replay"]["model_data_end"] + 2 * M15 <= p["replay"]["as_of"]
