"""V3.3 Stage 2 phase A: portfolio risk controller (aggregate / side / correlated / per-coin risk, conflicts, drawdown
halt + recovery, fail closed on missing data, entries only)."""
import json

import numpy as np
import pandas as pd
import pytest

from app.db import Database
from app.services import analysis, portfolio_risk as PR

H = 3_600_000
NOW = 1_795_700_000_000


class RT:
    def __init__(self, db=None, frames=None):
        self.db = db or Database("sqlite:///:memory:")
        self.frames = frames or {}
        self.errors = []

    def candles(self, s, tf):
        return self.frames.get((s, tf))

    def record_error(self, where, exc):
        self.errors.append((where, str(exc)))


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    PR._dd_cache.clear()
    PR._corr_cache.clear()
    monkeypatch.setattr(PR, "MODE", "enforce")
    yield


def _sig(db, sid, sym, tf, side, entry=100.0, stop=98.0, fill="FILLED", tp1=False, tp2=False, status="OPEN",
         created=NOW - 5 * H, closed=None, ret=None, payload=None):
    db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, "
               "tp1, tp2, tp3, status, fill_status, tp1_hit, tp2_hit, closed_at, return_net_pct, payload) "
               "VALUES (?, ?, ?, ?, ?, 'BUY', 'BUY', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (sid, created, sym, tf, created - H - hash(sid) % 1000, entry, side, entry, stop,
                entry + side * 2, entry + side * 3.5, entry + side * 5, status, fill, int(tp1), int(tp2), closed, ret,
                json.dumps(payload or {})))


def _pos(sym, side, r=1.0, tf="4h"):
    return {"symbol": sym, "side": side, "risk_r": r, "pending": False, "timeframe": tf}


ALL_CORR = lambda s: 0.9  # noqa: E731
NO_CORR = lambda s: 0.1   # noqa: E731


# ---- pure limits ------------------------------------------------------------------------------------------------------
def test_remaining_risk_falls_to_zero_at_break_even():
    assert PR.remaining_r(1, 100, 98, 2, 1.0) == 1.0
    assert PR.remaining_r(1, 100, 100, 2, 0.5) == 0.0          # TP1 hit, stop at break-even
    assert PR.remaining_r(-1, 100, 101, 2, 1.0) == 0.5          # admin tightened a short's stop
    assert PR.remaining_r(1, 100, 98, 0, 1.0) == 1.0            # unknown original risk counts a full trade


def test_aggregate_open_risk_limit():
    pos = [_pos(f"C{i}/USDT", 1 if i % 2 else -1) for i in range(8)]
    r = PR.check(pos, "NEW/USDT", 1, NO_CORR)
    assert not r["allowed"] and "portfolio limit of 8R" in r["reason"] and r["metrics"]["open_r"] == 8


def test_side_limit():
    pos = [_pos(f"C{i}/USDT", 1) for i in range(6)]
    r = PR.check(pos, "NEW/USDT", 1, NO_CORR)
    assert not r["allowed"] and "per direction" in r["reason"]
    assert PR.check(pos, "NEW/USDT", -1, NO_CORR)["allowed"]                 # the other side is free


def test_correlated_exposure_limit():
    pos = [_pos(f"C{i}/USDT", 1) for i in range(5)]
    r = PR.check(pos, "NEW/USDT", 1, ALL_CORR)
    assert not r["allowed"] and "BTC-correlated" in r["reason"]
    assert PR.check(pos, "NEW/USDT", 1, NO_CORR)["allowed"]                  # uncorrelated coin still fits


def test_unknown_correlation_counts_as_correlated():
    pos = [_pos(f"C{i}/USDT", 1) for i in range(5)]
    r = PR.check(pos, "NEW/USDT", 1, lambda s: None)
    assert not r["allowed"] and "BTC-correlated" in r["reason"] and "NEW/USDT" in r["metrics"]["unknown_corr"]


def test_duplicate_on_another_timeframe_is_refused_until_de_risked():
    r = PR.check([_pos("SOL/USDT", 1, tf="1h")], "SOL/USDT", 1, NO_CORR)
    assert not r["allowed"] and "per coin across timeframes" in r["reason"]
    assert PR.check([_pos("SOL/USDT", 1, r=0.0, tf="1h")], "SOL/USDT", 1, NO_CORR)["allowed"]   # stop at break-even


def test_conflicting_position_is_refused():
    r = PR.check([_pos("ETH/USDT", -1, r=0.0, tf="12h")], "ETH/USDT", 1, NO_CORR)
    assert not r["allowed"] and "conflicting position" in r["reason"] and "12h" in r["reason"]


def test_probation_halves_limits():
    pos = [_pos(f"C{i}/USDT", 1) for i in range(3)]
    assert PR.check(pos, "NEW/USDT", 1, NO_CORR)["allowed"]
    r = PR.check(pos, "NEW/USDT", 1, NO_CORR, factor=0.5)
    assert not r["allowed"] and "3R limit per direction" in r["reason"]


# ---- the record's positions ---------------------------------------------------------------------------------------------
def test_record_positions_from_open_calls():
    rt = RT()
    _sig(rt.db, "a", "BTC/USDT", "4h", 1)                               # full risk
    _sig(rt.db, "b", "ETH/USDT", "1h", -1, entry=100, stop=102, tp1=True)   # TP1: break-even = 0
    _sig(rt.db, "c", "SOL/USDT", "15m", 1, fill="PENDING")               # pending = 1R
    _sig(rt.db, "d", "XRP/USDT", "4h", 1, fill="NOT_FILLED")             # not a position
    _sig(rt.db, "e", "ADA/USDT", "4h", 1, status="STOPPED", closed=NOW - H, ret=-2.0)
    pos = {p["id"]: p for p in PR.record_positions(rt.db)}
    assert set(pos) == {"a", "b", "c"}
    assert pos["a"]["risk_r"] == 1.0 and pos["b"]["risk_r"] == 0.0 and pos["c"]["risk_r"] == 1.0 and pos["c"]["pending"]


def test_admin_stop_counts_in_remaining_risk():
    rt = RT()
    _sig(rt.db, "a", "BTC/USDT", "4h", 1, entry=100, stop=98)
    rt.db.execute("INSERT INTO signal_adjustments (id, signal_id, at, field, old, new, note) VALUES "
                  "('x', 'a', ?, 'stop', 98, 99, 'tighter')", (NOW - H,))
    assert PR.record_positions(rt.db)[0]["risk_r"] == 0.5


def test_record_gate_leaves_out_the_same_running_call():
    rt = RT()
    _sig(rt.db, "a", "BTC/USDT", "4h", 1)
    assert PR.record_gate(rt, "BTC/USDT", "4h", 1, NOW)["state"] == "clear"       # the call itself, re-analysed
    g = PR.record_gate(rt, "BTC/USDT", "1h", 1, NOW)
    assert g["state"] == "block" and g["flag"] == PR.FLAG                         # a second timeframe = duplicate


# ---- missing data fails closed ------------------------------------------------------------------------------------------
class _BrokenDB:
    def query(self, *a, **k):
        raise RuntimeError("database is locked")

    def get_setting(self, k, d=None):
        return d

    def set_setting(self, k, v):
        pass


def test_unreadable_positions_fail_closed():
    with pytest.raises(PR.Unavailable):
        PR.record_positions(_BrokenDB())
    rt = RT(db=_BrokenDB())
    assert PR.record_gate(rt, "BTC/USDT", "4h", 1, NOW)["state"] == "unavailable"


def test_analysis_turns_unavailable_into_no_trade(monkeypatch):
    rt = RT()
    monkeypatch.setattr(PR, "record_gate", lambda *a, **k: {"state": "unavailable", "reason": "db locked", "mode": "enforce"})
    flags, rc = [], {"would_block": False}
    d, g, why = analysis.portfolio_gate(rt, "BTC/USDT", "4h", "BUY", "A", "ok", flags, rc)
    assert d == "NO TRADE" and g is None and flags == ["CHECK UNAVAILABLE"] and "portfolio risk check" in why
    assert "portfolio" in analysis.gate_failures(rt.db) and rc["portfolio"]["state"] == "unavailable"


def test_analysis_blocks_and_flags_in_enforce_mode_only(monkeypatch):
    rt = RT()
    blocked = {"state": "block", "reason": "open risk too high", "flag": PR.FLAG, "mode": "enforce"}
    monkeypatch.setattr(PR, "record_gate", lambda *a, **k: dict(blocked))
    flags = []
    d, g, why = analysis.portfolio_gate(rt, "BTC/USDT", "4h", "SELL", "A", "ok", flags, {})
    assert (d, why, flags) == ("NO TRADE", "open risk too high", [PR.FLAG])
    monkeypatch.setattr(PR, "MODE", "shadow")
    flags, rc = [], {}
    d, g, why = analysis.portfolio_gate(rt, "BTC/USDT", "4h", "SELL", "A", "ok", flags, rc)
    assert d == "SELL" and flags == [] and rc["portfolio"]["state"] == "block"   # recorded, not applied


def test_portfolio_flags_are_followed_as_measured_filters():
    from app.services import proof_checks
    assert PR.FLAG in proof_checks.FLAGS and PR.DD_FLAG in proof_checks.FLAGS


# ---- drawdown halt and recovery ----------------------------------------------------------------------------------------
def test_drawdown_state_machine():
    lim = dict(PR.LIMITS)
    s = PR.step_state(None, 4.0, NOW, lim)
    assert s["state"] == "NORMAL"
    s = PR.step_state(s, 10.0, NOW, lim)
    assert s["state"] == "HALT" and s["until"] == NOW + 24 * H
    assert PR.step_state(s, 11.0, NOW + 23 * H, lim)["state"] == "HALT"
    p = PR.step_state(s, 9.0, NOW + 25 * H, lim)
    assert p["state"] == "PROBATION"
    assert PR.step_state(p, 9.0, NOW + 26 * H, lim)["state"] == "PROBATION"
    assert PR.step_state(p, 13.0, NOW + 26 * H, lim)["state"] == "HALT"            # deeper by 3R: halt again
    assert PR.step_state(p, 6.0, NOW + 26 * H, lim)["state"] == "NORMAL"           # recovered
    assert PR.step_state(p, 9.0, NOW + 25 * H + 7 * 24 * H, lim)["state"] == "NORMAL"   # probation ran out


def test_record_drawdown_from_closed_calls(monkeypatch):
    from app import views
    rt = RT()
    monkeypatch.setattr(views, "record_since", lambda rt_: 0)
    for i, ret in enumerate([2.0, 2.0, -2.0, -2.0, -2.0, 2.0]):      # risk 2 % each = +1, +1, -1, -1, -1, +1 R
        _sig(rt.db, f"s{i}", f"C{i}/USDT", "4h", 1, status="TP1" if ret > 0 else "STOPPED", closed=NOW - (10 - i) * H,
             ret=ret)
    dd = PR.record_drawdown(rt)
    assert dd["n"] == 6 and dd["peak_r"] == pytest.approx(2.0) and dd["dd_r"] == pytest.approx(2.0)


def test_halt_blocks_new_record_entries(monkeypatch):
    rt = RT()
    monkeypatch.setattr(PR, "record_drawdown", lambda rt_: {"n": 40, "total_r": -6, "peak_r": 5, "dd_r": 11.0})
    g = PR.record_gate(rt, "BTC/USDT", "4h", 1, NOW)
    assert g["state"] == "block" and g["flag"] == PR.DD_FLAG and "drawdown" in g["reason"]
    assert rt.db.get_setting("portfolio_state")["state"] == "HALT"
    assert rt.db.get_setting("portfolio_state_log")[-1]["to"] == "HALT"


# ---- bot / challenge books ---------------------------------------------------------------------------------------------
def _book(*positions):
    return {"positions": [{"symbol": s, "side": sd, "entry": 100.0, "stop": st, "stop0": 98.0, "qty": 1.0, "qty_open": q}
                          for s, sd, st, q in positions], "pending": []}


def test_book_check_uses_the_same_limits(monkeypatch):
    rt = RT()
    monkeypatch.setattr(PR, "btc_corr", lambda rt_, s, bars=None: 0.1)
    st = _book(("BTC/USDT", 1, 98.0, 1.0))
    assert not PR.book_check(rt, st, "BTC/USDT", -1)["allowed"]                     # conflict
    assert PR.book_check(rt, st, "ETH/USDT", 1)["allowed"]
    st = _book(*[(f"C{i}/USDT", 1, 98.0, 1.0) for i in range(6)])
    assert not PR.book_check(rt, st, "NEW/USDT", 1)["allowed"]
    st = _book(*[(f"C{i}/USDT", 1, 100.0, 0.5) for i in range(6)])               # all at break-even after TP1
    assert PR.book_check(rt, st, "NEW/USDT", 1)["allowed"]


def test_unreadable_book_is_refused_and_shadow_never_blocks(monkeypatch):
    rt = RT()
    bad = {"positions": [{"symbol": "X/USDT"}]}                                   # malformed position
    assert PR.book_check(rt, bad, "BTC/USDT", 1)["allowed"] is False
    monkeypatch.setattr(PR, "MODE", "shadow")
    monkeypatch.setattr(PR, "btc_corr", lambda rt_, s, bars=None: 0.1)
    st = _book(("BTC/USDT", 1, 98.0, 1.0))
    r = PR.book_check(rt, st, "BTC/USDT", -1)
    assert r["allowed"] and r["would_block"]


# ---- correlation ------------------------------------------------------------------------------------------------------
def test_btc_correlation_from_hourly_returns():
    rng = np.random.default_rng(0)
    n = 100
    b = np.cumsum(rng.normal(0, 0.01, n))
    ts = np.arange(n) * H
    frames = {("BTC/USDT", "1h"): pd.DataFrame({"ts": ts, "close": 100 * np.exp(b)}),
              ("FOL/USDT", "1h"): pd.DataFrame({"ts": ts, "close": 50 * np.exp(b * 1.2 + rng.normal(0, 0.001, n))}),
              ("IND/USDT", "1h"): pd.DataFrame({"ts": ts, "close": 50 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))}),
              ("NEW/USDT", "1h"): pd.DataFrame({"ts": ts[:20], "close": np.ones(20)})}
    rt = RT(frames=frames)
    assert PR.btc_corr(rt, "FOL/USDT") > 0.95
    assert abs(PR.btc_corr(rt, "IND/USDT")) < 0.4
    assert PR.btc_corr(rt, "NEW/USDT") is None                                     # too short: unknown
    assert PR.btc_corr(rt, "BTC/USDT") == 1.0


def test_summary_reports_equity_at_risk():
    rt = RT()
    _sig(rt.db, "a", "BTC/USDT", "4h", 1)
    _sig(rt.db, "b", "ETH/USDT", "4h", -1, entry=100.0, stop=102.0)
    s = PR.summary(rt)
    assert s["available"] and s["open_r"] == 2.0 and s["equity_at_risk_pct_ref"] == 0.5
    assert s["by_side_r"] == {"long": 1.0, "short": 1.0} and s["risk_per_trade_pct_ref"] == 0.25
