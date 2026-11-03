"""v2.14 (owner decisions, 3 Nov 2026): fresh restart (old history deleted permanently), leverage 10-50x chosen by the
engine for every futures trade (card, record, bots, Hesper, auto-trade), practice accounts start at $1,000, no edge rule."""
import json

import pytest

from app import fresh_restart_v214 as FR
from app import views, worker
from app.db import Database, loads
from app.engine import futures as F
from app.services import analysis as A
from app.services import autopaper as AP
from app.services import bots as B
from app.services import hesper as H
from app.services import tracking as T
from app.services.runtime import Runtime
from app.sinks import LocalSink

from .test_audit_record import BAR, H1, _a
from .test_hesper import NOW, STEP, _call, _put
from .test_hesper import _rt as _hrt

SYMS = ("BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT", "DOGE/USDT", "PAXG/USDT", "NEW/USDT")


# ---- leverage policy ------------------------------------------------------------------------------------------------

def test_engine_leverage_clamp_grade_factor_and_skip():
    # tight stop on BTC: the safe max is far above 50 -> 50 for grade A and B alike (75 % of it is still above 50)
    assert F.safe_max_leverage(100.0, 99.8, "BTC/USDT") > 70
    assert F.engine_leverage(100.0, 99.8, "BTC/USDT", "A") == 50 == F.engine_leverage(100.0, 99.8, "BTC/USDT", "B")
    # 2 % stop on BTC: safe max 28 -> A 28, B floor(28 x 0.75) = 21
    assert F.safe_max_leverage(100.0, 98.0, "BTC/USDT") == 28
    assert F.engine_leverage(100.0, 98.0, "BTC/USDT", "A") == 28
    assert F.engine_leverage(100.0, 98.0, "BTC/USDT", "B") == 21
    assert F.engine_leverage(100.0, 98.0, "BTC/USDT", None) == 21          # no grade: the cautious factor
    # safe max just above 10: grade B would be below 10 -> clamped up to 10 (still within the safe max)
    safe = F.safe_max_leverage(100.0, 95.0, "BTC/USDT")
    assert 10 <= safe < 14 and F.engine_leverage(100.0, 95.0, "BTC/USDT", "B") == 10
    # stop too wide for 10x: not taken at all
    assert F.safe_max_leverage(100.0, 92.0, "BTC/USDT") < 10
    assert F.engine_leverage(100.0, 92.0, "BTC/USDT", "A") is None
    assert F.engine_leverage(100.0, None, "BTC/USDT", "A") is None and F.engine_leverage(None, 98.0) is None
    # the coin's margin tier matters: the same stop allows less on a memecoin than on BTC
    assert F.engine_leverage(100.0, 97.0, "DOGE/USDT", "A") < F.engine_leverage(100.0, 97.0, "BTC/USDT", "A")


def test_engine_leverage_never_puts_liquidation_before_the_stop():
    """Both paths: the v2.14 rule (15m) and the v2.13 rule (other timeframes) keep the stop before liquidation."""
    n = 0
    for sym in SYMS:
        for pct in [x / 100 for x in range(5, 1000, 7)]:            # 0.05 % .. 10 % stops
            for side in (1, -1):
                for grade in ("A", "B", None):
                    entry = 100.0
                    stop = entry * (1 - side * pct / 100)
                    lev = F.engine_leverage(entry, stop, sym, grade, "15m")
                    safe = F.safe_max_leverage(entry, stop, sym)
                    if safe is None or safe < 10:
                        assert lev is None
                    else:
                        n += 1
                        assert 10 <= lev <= 50 and lev <= safe
                        assert F.stop_before_liquidation(entry, stop, side, lev, sym)
                        assert abs(F.liquidation_price(entry, side, lev, symbol=sym) - entry) >= 1.5 * abs(entry - stop) - 1e-9
                    for tf, cap in (("1h", 10), ("4h", 20), ("1d", 25)):
                        old = F.leverage_for(entry, stop, sym, grade, tf, cap)
                        assert old == F.safe_leverage(entry, stop, cap, symbol=sym) and 1 <= old <= cap   # v2.13, never None
                        if old > 1:
                            assert F.stop_before_liquidation(entry, stop, side, old, sym)
    assert n > 500


def test_policy_is_15m_only():
    assert F.POLICY_TFS == ("15m",) and F.in_policy("15m")
    for tf in ("1h", "4h", "12h", "1d", "3d", None):
        assert not F.in_policy(tf)
    # card / record: 15m engine 10-50x; others the v2.13 suggestion (safe, capped at 10x), never refused for a wide stop
    assert F.signal_leverage(100.0, 98.0, "BTC/USDT", "A", "15m") == 28
    assert F.signal_leverage(100.0, 98.0, "BTC/USDT", "A", "1h") == 10 == F.safe_leverage(100.0, 98.0, 10, symbol="BTC/USDT")
    assert F.signal_leverage(100.0, 92.0, "BTC/USDT", "A", "15m") is None
    assert F.signal_leverage(100.0, 92.0, "BTC/USDT", "A", "4h") == F.safe_leverage(100.0, 92.0, 10, symbol="BTC/USDT") >= 1
    assert F.signal_leverage(100.0, 98.0) == F.safe_leverage(100.0, 98.0, 10)       # no timeframe: v2.13


def test_analysis_refuses_a_stop_too_wide_for_10x_on_15m_only():
    setup = {"valid": True, "ideal_entry": 100.0, "stop": 92.0}
    why = A.leverage_gate(setup, 100.0, "BTC/USDT", "A", "15m")
    assert why and why.startswith(F.TOO_WIDE_REASON)
    for tf in ("1h", "4h", "12h", "1d", "3d"):
        assert A.leverage_gate(setup, 100.0, "BTC/USDT", "A", tf) is None
    assert A.leverage_gate({**setup, "stop": 98.0}, 100.0, "BTC/USDT", "A", "15m") is None
    # fine at the card's entry but too wide at the live price (the record's market entry) -> refused too
    assert A.leverage_gate({**setup, "stop": 95.0}, 104.0, "BTC/USDT", "A", "15m")
    assert A.leverage_gate(None, 100.0, "BTC/USDT", "A", "15m") is None


def test_record_skips_a_too_wide_15m_call_but_keeps_other_timeframes():
    db = Database("sqlite:///:memory:")
    a = _a(entry=100.0, stop=90.0, tf="15m")
    assert not T.log_signal(db, a, now=BAR + H1 + 1000)
    assert a["record_status"] == "not_logged"
    d = db.one("SELECT * FROM decisions WHERE rule = 'skip_entry'")
    assert d and F.TOO_WIDE_REASON in d["inputs"]
    db2 = Database("sqlite:///:memory:")
    assert T.log_signal(db2, _a(entry=100.0, stop=90.0, tf="4h"), now=BAR + H1 + 1000)
    s = db2.one("SELECT * FROM signals")
    assert loads(s["payload"])["leverage"] == F.safe_leverage(100.0, 90.0, 10, symbol="BTC/USDT")
    db3 = Database("sqlite:///:memory:")
    assert T.log_signal(db3, _a(entry=100.0, stop=98.0, tf="15m"), now=BAR + H1 + 1000)
    assert loads(db3.one("SELECT * FROM signals")["payload"])["leverage"] == F.engine_leverage(100.0, 98.0, "BTC/USDT", "A", "15m")


def _sig15(stop=98.0, tf="15m", tps=(102.0, 103.0, 104.0)):
    return {"symbol": "BTC/USDT", "timeframe": tf, "side": 1, "price": 100.0, "grade": "A",
            "plan": {"entry": 100.0, "entry_zone": [99.5, 100.5], "stop": stop, "suggested_leverage": 7,
                     "targets": [{"price": t} for t in tps]}}


def _bot_lev(monkeypatch, tf, stop=98.0, tps=(102.0, 104.0, 106.0)):
    from .test_bots import _buy, _cfg, _now_aligned
    from .test_bots import _put as _bput
    from .test_bots import _rt as _brt
    rt2 = _brt()
    t0 = _now_aligned() - 40 * 900_000
    _bput(rt2, "BTC/USDT", t0, [100.0] * 4)
    eng = B.BotEngine(rt2)
    eng.sync_configs([_cfg(market="futures", leverage=20.0, safe_leverage=True, max_position_pct=100.0, timeframe=tf)])
    monkeypatch.setattr(A, "analyze", lambda *x, **k: {**_buy(stop=stop, tps=tps), "grade": "A"})
    eng.run(t0 + 4 * 900_000)
    st = eng.bots()[0][1]
    return st["positions"][0]["lev"] if st["positions"] else None


def _hesper_lev(monkeypatch, tf, stop=98.0, tps=(102.0, 103.5, 105.0)):
    monkeypatch.setattr(A, "analyze", lambda *x, **k: {"status": "OK", "decision": "HOLD"})
    rt = _hrt()
    _put(rt, "BTC/USDT", NOW - 8 * STEP, [100.0] * 8)
    _call(rt.db, "c1", tf=tf, stop=stop, tps=tps)
    H.Hesper(rt).run(NOW)
    pos = rt.db.get_setting(H.STATE_KEY)["positions"]
    return pos[0]["lev"] if pos else None


def test_15m_card_record_bots_hesper_and_autotrade_all_use_engine_leverage(monkeypatch):
    """One function decides 15m leverage everywhere: a spy on futures.engine_leverage is what every consumer uses."""
    real = F.engine_leverage
    calls = []

    def spy(entry, stop, symbol=None, grade=None, timeframe=None, cap=F.CARD_MAX_LEVERAGE):
        if timeframe == "15m":
            calls.append(timeframe)
            return 17
        return real(entry, stop, symbol, grade, timeframe, cap)
    monkeypatch.setattr(F, "engine_leverage", spy)
    a = {"symbol": "BTC/USDT", "status": "OK", "timeframe": "15m", "price": 100.0, "decision": "BUY", "grade": "A",
         "setup": {"ideal_entry": 100.0, "stop": 98.0, "side_int": 1, "valid": True, "targets": []}}
    v = F.futures_view(a, None)["plan"]
    assert v["suggested_leverage"] == 17 and v["leverage_policy"]["max"] == 50
    db = Database("sqlite:///:memory:")
    assert T.log_signal(db, _a(entry=100.0, stop=98.0, tf="15m"), now=BAR + H1 + 1000)
    s = db.one("SELECT * FROM signals")
    assert loads(s["payload"])["leverage"] == 17 and T.margin_fields({**s, "status": "OPEN"})["leverage"] == 17
    _, res = AP.place(None, _sig15(), AP.settings_of({"scale": False, "leverage": 5}), 1000)
    assert res["action"] == "opened" and res["leverage"] == 17          # the member setting does not apply on 15m
    assert _hesper_lev(monkeypatch, "15m") == 17
    assert _bot_lev(monkeypatch, "15m") == 17
    assert len(calls) >= 5


def test_other_timeframes_keep_the_v213_leverage_exactly(monkeypatch):
    a = {"symbol": "BTC/USDT", "status": "OK", "timeframe": "4h", "price": 100.0, "decision": "BUY", "grade": "A",
         "setup": {"ideal_entry": 100.0, "stop": 98.0, "side_int": 1, "valid": True, "targets": []}}
    v = F.futures_view(a, None)["plan"]
    assert v["suggested_leverage"] == F.safe_leverage(100.0, 98.0, 10, symbol="BTC/USDT") == 10 and v["leverage_policy"] is None
    # auto-trade: v2.13 (signal -> the card's suggestion, else the member's setting; <= safe, <= 20x)
    assert AP.MAX_LEV == 20 and AP.settings_of({"leverage": 50})["leverage"] == 20
    _, res = AP.place(None, _sig15(tf="1h"), AP.settings_of({"scale": False}), 1000)
    assert res["leverage"] == 7
    _, res = AP.place(None, _sig15(tf="1h"), AP.settings_of({"scale": False, "leverage": 20}), 1000)
    entry = 100.0 * (1 + AP.ADVERSE)
    assert res["leverage"] == min(20, F.safe_leverage(entry, 98.0, 20, symbol="BTC/USDT"))
    # a stop too wide for 10x is still taken on other timeframes, at a lower safe leverage (no skip)
    _, res = AP.place(None, _sig15(stop=90.0, tf="4h", tps=(110.0, 115.0, 120.0)), AP.settings_of({"scale": False, "leverage": 20}), 1)
    assert res["action"] == "opened" and res["leverage"] == F.safe_leverage(entry, 90.0, 20, symbol="BTC/USDT") < 10
    # bots: safe up to their config (20x); Hesper: safe up to 25x
    assert _bot_lev(monkeypatch, "4h") == min(20, F.safe_leverage(100.0, 98.0, 20, symbol="BTC/USDT")) == 20
    assert _bot_lev(monkeypatch, "4h", stop=90.0, tps=(110.0, 115.0, 120.0)) == F.safe_leverage(100.0, 90.0, 20, symbol="BTC/USDT")
    assert _hesper_lev(monkeypatch, "1h") == 25 == H.MAX_LEVERAGE
    assert _hesper_lev(monkeypatch, "4h", stop=90.0, tps=(110.0, 115.0, 120.0)) == F.safe_leverage(100.0, 90.0, 25, symbol="BTC/USDT")


def test_15m_bots_hesper_and_autotrade_skip_a_stop_too_wide_for_10x(monkeypatch):
    acc, res = AP.place(None, _sig15(stop=90.0, tps=(110.0, 115.0, 120.0)), AP.settings_of({}), 1000)
    assert acc is None and res["action"] == "skipped" and res["reason"] == F.TOO_WIDE_REASON
    assert _hesper_lev(monkeypatch, "15m", stop=90.0, tps=(110.0, 115.0, 120.0)) is None
    assert _bot_lev(monkeypatch, "15m", stop=90.0, tps=(110.0, 115.0, 120.0)) is None


# ---- practice accounts ------------------------------------------------------------------------------------------------

def test_new_auto_trade_account_starts_with_1000_and_records_the_deposit():
    acc = AP.new_account(5)
    assert AP.START_BALANCE == 1000.0
    assert acc["starting_balance"] == acc["wallet"] == acc["deposited"] == 1000.0 and acc["deposits"] == []
    sink_acc, res = AP.place(None, {"symbol": "BTC/USDT", "timeframe": "1h", "side": 1, "price": 100.0, "grade": "A",
                                    "plan": {"entry": 100.0, "entry_zone": [99.5, 100.5], "stop": 98.0,
                                             "targets": [{"price": 102.0}, {"price": 103.0}, {"price": 104.0}]}},
                             AP.settings_of({"scale": False}), 1000)
    assert sink_acc["starting_balance"] == 1000.0 and sink_acc["deposited"] == 1000.0


def test_existing_member_account_is_kept_as_it_is(tmp_path):
    sink = LocalSink(tmp_path)
    old = AP.new_account(1, balance=10_000.0)
    old.pop("deposited"), old.pop("deposits")
    new, res = AP.place(old, {"symbol": "BTC/USDT", "timeframe": "1h", "side": 1, "price": 100.0, "grade": "A",
                              "plan": {"entry": 100.0, "entry_zone": [99.5, 100.5], "stop": 98.0,
                                       "targets": [{"price": 102.0}, {"price": 103.0}, {"price": 104.0}]}},
                       AP.settings_of({"scale": False}), 1000)
    assert new["starting_balance"] == 10_000.0 and "deposited" not in new


# ---- no edge rule ---------------------------------------------------------------------------------------------------------

def test_edge_rule_is_off_by_default_but_the_switch_stays():
    from app.config import settings
    assert settings.require_edge_for_trade is False
    assert A.edge_gate({"edge_confirmed": False}, {"policy_edge": False}) is None
    assert A.edge_gate({"edge_confirmed": False}, {"policy_edge": False}, required=True)


# ---- fresh restart v2.14 -----------------------------------------------------------------------------------------------

class _P:
    name = "test"


def _rt():
    return Runtime(Database("sqlite:///:memory:"), _P())


BOTS = [{"id": "futures-signal-ab-4h", "mode": "decision", "timeframe": "4h", "market": "futures", "grades": "A",
         "max_hold_bars": 100, "reset_token": "v212", "leverage": 20.0, "safe_leverage": True, "starting_balance": 10_000},
        {"id": "signal-ab-1h", "mode": "decision", "timeframe": "1h", "market": "spot", "grades": "AB",
         "max_hold_bars": 200, "reset_token": "v23", "leverage": 1.0, "starting_balance": 10_000}]


def _live(tmp_path, rt):
    """A running installation: history in every table, plus what must be kept."""
    db = rt.db
    sink = LocalSink(tmp_path)
    sink.set("config/watchlist", {"symbols": [{"symbol": "BTC/USDT", "pinned": True}]})
    sink.set("config/bots", {"bots": [dict(b) for b in BOTS], "defaults_added": [d["id"] for d in worker.DEFAULT_BOTS]
                             + [b["id"] for b in BOTS] + ["futures-signal-ab-3d"]})
    sink.set("config/membership", {"support_email": "support@cryptointelai.com"})
    sink.set("users/m1", {"status": "approved", "expires_at": 9_999_999_999_999, "email": "m1@example.com"})
    sink.set("paper/m1_futures", {"wallet": 12345, "starting_balance": 10_000})
    sink.set("paper/m1_spot", {"cash": 777, "starting_balance": 10_000})
    sink.set("paper_futures_trades/t1", {"uid": "m1", "pnl": 10})
    sink.set("paper_trades/t2", {"uid": "m1", "pnl": 3})
    sink.set("auto_paper/m1", {"enabled": True})
    sink.set("auto_paper_state/m1", {"log": [1]})
    sink.set("owner/telegram", {"token": "keep-me", "post_wins": True})
    sink.set("owner/telegram_drafts", {"items": [{"id": "d1", "kind": "win"}]})
    sink.set("views/scalping", {"json": "{}"})
    sink.set("views/bot_old", {"json": "{}"})
    sink.set("views/signals", {"json": "{}"})
    # history
    _call(db, "s1")
    _call(db, "s2", status="STOPPED", bar=1)
    db.execute("INSERT INTO shadow_signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, status) "
               "VALUES ('sh', 1, 'BTC/USDT', '1h', 1, 'BUY', 'BUY', 100, 1, 'OPEN')")
    db.execute("INSERT INTO scalp_signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, status) "
               "VALUES ('sc', 1, 'BTC/USDT', '15m', 1, 'BUY', 'BUY', 100, 1, 'TP1')")
    db.execute("INSERT INTO signal_proofs (signal_id, created_at, text, hash) VALUES ('s1', 1, 't', 'h')")
    db.execute("INSERT INTO signal_adjustments (id, signal_id, at, field, old, new, note) VALUES ('a1', 's1', 1, 'stop', 1, 2, 'n')")
    T.log_decision(db, "admin_close", "BTC/USDT", "1h", "s1", {"x": 1}, ts=1)
    db.execute("INSERT INTO bots (id, config, state, reset_token, created_at) VALUES ('futures-signal-ab-4h', ?, ?, 'v212', 1)",
               (json.dumps(BOTS[0]), json.dumps({"cash": 9000})))
    db.execute("INSERT INTO bot_trades (id, bot_id, symbol, side, opened_at, closed_at, entry, exit, qty, pnl, fees, "
               "return_pct, exit_reason) VALUES ('bt', 'futures-signal-ab-4h', 'BTC/USDT', 1, 1, 2, 100, 99, 1, -1, 0, -1, 'stop')")
    db.execute("INSERT INTO bot_equity (bot_id, ts, equity) VALUES ('futures-signal-ab-4h', 1, 9000)")
    db.execute("INSERT INTO hesper_runs (run, started_at, result, start_balance, peak) VALUES (1, 1, 'FAIL', 100, 150)")
    db.execute("INSERT INTO hesper_runs (run, started_at, result, start_balance, peak) VALUES (2, 2, 'RUNNING', 100, 100)")
    db.execute("INSERT INTO hesper_trades (id, run, symbol, timeframe, side, leverage, opened_at, closed_at, entry, exit, qty, "
               "margin, pnl, fees, funding, exit_reason, balance_before, balance_after) VALUES ('ht', 1, 'BTC/USDT', '1h', 1, 25, "
               "1, 2, 100, 90, 1, 99, -99, 0, 0, 'liquidated', 100, 1)")
    db.set_setting("hesper_state", {"run": 2, "cash": 100})
    db.set_setting("hesper_since", 1)
    db.set_setting("hesper_v1", True)
    db.set_setting("safety:BTC/USDT:1h", {"paused_at": 1})
    db.set_setting("honest_record_since", 5)
    db.set_setting("record_since", 5)
    db.set_setting("record_since_tf", {"15m": 9})
    db.execute("INSERT INTO published (doc_id, hash, ts) VALUES ('signals', 'x', 1)")
    # kept
    db.execute("INSERT INTO market_data (exchange, symbol, timeframe, ts, open, high, low, close, volume) "
               "VALUES ('test', 'BTC/USDT', '1h', 1, 1, 1, 1, 1, 1)")
    db.execute("INSERT INTO model_versions (id, symbol, timeframe, created_at, path) VALUES ('m1', 'BTC/USDT', '1h', 1, 'p')")
    db.execute("INSERT INTO predictions (id, created_at, symbol, timeframe, bar_ts, target_ts, model_version_id, price, "
               "p_down, p_neutral, p_up, predicted_class, neutral_band) VALUES ('p1', 1, 'BTC/USDT', '1h', 1, 2, 'm1', 100, "
               ".3, .2, .5, 2, .001)")
    db.set_setting("risk_profile", {"x": 1})
    return sink


def _n(db, t):
    return db.one(f"SELECT COUNT(*) AS n FROM {t}")["n"]


def _all_but(flag):
    return [f for f in worker.MIGRATION_FLAGS if f != flag]


def test_fresh_restart_deletes_exactly_the_history_and_keeps_the_rest(tmp_path, monkeypatch):
    rt = _rt()
    sink = _live(tmp_path, rt)
    for f in _all_but("fresh_restart_v214"):
        if f != "honest_record_v213":
            rt.db.set_setting(f, True)
    sink.set(worker.MIGRATIONS_DOC, {"flags": {f: True for f in _all_but("fresh_restart_v214") if f != "honest_record_v213"}})
    preds_before = _n(rt.db, "predictions")
    notes = worker.sync_config(rt, sink)
    out = notes["fresh_restart_v214"]
    assert out["sqlite_rows"]["signals"] == 2 and out["sqlite_rows"]["hesper_runs"] == 2
    # deleted (engine)
    for t in ("signals", "shadow_signals", "scalp_signals", "signal_proofs", "signal_adjustments", "decisions",
              "bot_trades", "bot_equity", "hesper_runs", "hesper_trades"):
        assert _n(rt.db, t) == 0, t
    for k in ("hesper_state", "hesper_since", "hesper_v1", "safety:BTC/USDT:1h", "honest_record_since"):
        assert rt.db.get_setting(k, None) is None, k
    # restarted: record, bots (same line-up, fresh books, engine leverage), one note on Results
    now = rt.db.get_setting("fresh_restart_v214")
    assert rt.db.get_setting("record_since") == now and rt.db.get_setting("record_since_tf") == {}
    assert rt.db.get_setting("record_restart")["text"].startswith("Fresh start ")
    assert rt.db.get_setting("record_restart")["text"].endswith(": real entry prices, after fees.")
    assert rt.db.get_setting("honest_record_v213") is True
    cfg = sink.get("config/bots")["bots"]
    assert [b["id"] for b in cfg] == [b["id"] for b in BOTS]
    assert all(b["reset_token"] == "v214" for b in cfg) and cfg[0]["leverage"] == 20.0 and cfg[1]["leverage"] == 1.0
    rows = {r["id"]: r for r in rt.db.query("SELECT * FROM bots")}
    assert loads(rows["futures-signal-ab-4h"]["state"])["cash"] == 10_000 and rows["futures-signal-ab-4h"]["reset_token"] == "v214"
    # Firestore: old-history views and Telegram drafts gone; publish cache emptied
    assert sink.get("views/scalping") is None and sink.get("views/bot_old") is None
    assert sink.get("owner/telegram_drafts")["items"] == []
    assert _n(rt.db, "published") == 0
    # kept: candles, models, forecasts, users, Telegram settings, members' practice accounts / trades / auto-trade logs
    assert _n(rt.db, "market_data") == 1 and _n(rt.db, "model_versions") == 1 and _n(rt.db, "predictions") == preds_before == 1
    assert sink.get("users/m1")["email"] == "m1@example.com"
    assert sink.get("owner/telegram")["token"] == "keep-me"
    assert sink.get("paper/m1_futures") == {"wallet": 12345, "starting_balance": 10_000}
    assert sink.get("paper/m1_spot") == {"cash": 777, "starting_balance": 10_000}
    assert sink.get("paper_futures_trades/t1") and sink.get("paper_trades/t2")
    assert sink.get("auto_paper/m1") and sink.get("auto_paper_state/m1") == {"log": [1]}
    # mirrored, so a lost database never runs it again
    assert sink.get(worker.MIGRATIONS_DOC)["flags"]["fresh_restart_v214"]
    # Hesper starts again at Run #1 with $100
    st = H.Hesper(rt).start(now + 1)
    assert st["run"] == 1 and st["cash"] == H.START_BALANCE
    # the track record shows the one restart line
    tr = views.track_record(rt)
    assert tr["restart"]["text"] == rt.db.get_setting("record_restart")["text"] and "honest_since" not in tr
    assert tr["live"]["summary"].get("closed", 0) in (0, None)


def test_fresh_restart_runs_once(tmp_path):
    rt = _rt()
    sink = _live(tmp_path, rt)
    for f in _all_but("fresh_restart_v214"):
        rt.db.set_setting(f, True)
    worker.sync_config(rt, sink)
    first = rt.db.get_setting("fresh_restart_v214")
    # new history after the restart is never deleted again
    _call(rt.db, "new1", bar=2)
    rt.db.execute("INSERT INTO hesper_runs (run, started_at, result, start_balance, peak) VALUES (1, 5, 'RUNNING', 100, 100)")
    notes = worker.sync_config(rt, sink)
    assert "fresh_restart_v214" not in notes
    assert _n(rt.db, "signals") == 1 and _n(rt.db, "hesper_runs") == 1
    assert rt.db.get_setting("fresh_restart_v214") == first
    assert FR.maybe_run(rt, sink, 123) is None


def test_fresh_restart_never_on_a_fresh_database(tmp_path, monkeypatch):
    """Empty engine database next to a live Firestore (lost state): the guard marks it done, nothing is deleted."""
    def boom(*a, **k):
        raise AssertionError("fresh restart ran on a fresh database")
    monkeypatch.setattr(FR, "run", boom)
    rt = _rt()
    sink = LocalSink(tmp_path)
    sink.set("config/bots", {"bots": [dict(b) for b in BOTS], "defaults_added": [d["id"] for d in worker.DEFAULT_BOTS]
                             + [b["id"] for b in BOTS] + ["futures-signal-ab-3d"]})
    sink.set("paper/m1_futures", {"wallet": 12345})
    sink.set("views/scalping", {"json": "{}"})
    notes = worker.sync_config(rt, sink)
    assert "fresh_restart_v214" in notes["migrations"]["fresh_database_marked_done"]
    assert rt.db.get_setting("fresh_restart_v214") and rt.db.get_setting("record_since", None) is None
    assert rt.db.get_setting("record_restart", None) is None
    assert [b["reset_token"] for b in sink.get("config/bots")["bots"]] == ["v212", "v23"]
    assert sink.get("views/scalping") is not None and sink.get("paper/m1_futures") == {"wallet": 12345}
    # and the module's own check: no history -> only the flag
    rt2 = _rt()
    assert FR.maybe_run(rt2, sink, 7) == {"skipped": "empty database"} and rt2.db.get_setting(FR.FLAG) == 7


def test_fresh_restart_flag_from_firestore_counts_as_done(tmp_path, monkeypatch):
    """An older backup restored (history present, flag missing locally) but Firestore says it ran: it never runs twice."""
    def boom(*a, **k):
        raise AssertionError("fresh restart ran twice")
    monkeypatch.setattr(FR, "run", boom)
    rt = _rt()
    sink = _live(tmp_path, rt)
    for f in _all_but("fresh_restart_v214"):
        rt.db.set_setting(f, True)
    sink.set(worker.MIGRATIONS_DOC, {"flags": {f: True for f in worker.MIGRATION_FLAGS}})
    worker.sync_config(rt, sink)
    assert _n(rt.db, "signals") == 2


def test_note_text_uses_the_dubai_date():
    # 3 Nov 2026 22:00 UTC is already 4 Nov in Dubai
    assert FR.note_text(1793743200000) == "Fresh start 4 Nov 2026: real entry prices, after fees."
    assert FR.note_text(1793700000000) == "Fresh start 3 Nov 2026: real entry prices, after fees."
