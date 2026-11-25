"""V3.2 Stage 1 verification fixes: holdout cannot be read by any entry point; ticker sanity; challenge entries."""
import json
import sqlite3

import numpy as np
import pytest

from app import research_verdict as RV
from app.services import analysis

H = 3_600_000
S = RV.HOLDOUT_START
NOW = 1_795_000_000_000


# ---- holdout: frozen research copies ------------------------------------------------------------------------------
def _state(tmp_path):
    from app.db import Database
    p = tmp_path / "engine.db"
    db = Database(f"sqlite:///{p}")
    rows = []
    for tf, step in (("1h", H), ("1d", 24 * H)):
        for k in range(-3, 3):
            rows.append(("binance_public", "BTC/USDT", tf, S + k * step))
    for ex, sym, tf, ts in rows:
        db.execute("INSERT INTO market_data (exchange, symbol, timeframe, ts, open, high, low, close, volume) "
                   "VALUES (?, ?, ?, ?, 1, 1, 1, 1, 1)", (ex, sym, tf, ts))
    for i, (created, closed) in enumerate(((S - 10 * H, S - 2 * H), (S - 10 * H, S + H), (S - 1, None), (S, None),
                                           (S + 5 * H, S + 9 * H))):
        db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, status, "
                   "closed_at) VALUES (?, ?, ?, '1h', ?, 'BUY', 'BUY', 100.0, 1, ?, ?)",
                   (f"s{i}", created, f"C{i}/USDT", created - H, "TP1" if closed else "OPEN", closed))
    db._conn.close()
    return p


def _dump(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    out = list(c.iterdump())
    c.close()
    return out


def test_frozen_copy_removes_the_holdout_period_and_never_touches_the_source(tmp_path):
    p = _state(tmp_path)
    before = _dump(p)
    url = RV.frozen_copy(f"sqlite:///{p}")
    assert _dump(p) == before                                            # the engine state is only read
    c = sqlite3.connect(url.replace("sqlite:///", ""))
    md = c.execute("SELECT timeframe, ts FROM market_data ORDER BY timeframe, ts").fetchall()
    for tf, ts in md:                                                    # every kept candle closed by the start
        assert ts + {"1h": H, "1d": 24 * H}[tf] <= S
    assert ("1h", S - H) in md and ("1d", S - 24 * H) in md              # boundary: closes exactly at the start = kept
    ids = sorted(r[0] for r in c.execute("SELECT id FROM signals"))
    assert ids == ["s0", "s2"]                  # closed after the start, created at / after the start: all removed


def test_run_study_only_sees_the_frozen_copy(tmp_path):
    p = _state(tmp_path)
    seen = {}

    def study(url):
        seen["url"] = url
        c = sqlite3.connect(url.replace("sqlite:///", ""))
        seen["late"] = c.execute("SELECT COUNT(*) FROM signals WHERE created_at >= ?", (S,)).fetchone()[0]
        return {"x": RV.verdict([{"ts": 0, "closed_ts": 1, "r": 1.0}], [])}
    out = RV.run_study("t", study, f"sqlite:///{p}")
    assert seen["url"] != f"sqlite:///{p}" and seen["late"] == 0
    assert out["holdout"]["locked"] and out["holdout"]["closed"] == 1      # read-only count on the source (s4)
    assert out["multiple_testing"]["n_variants"] == 1


def test_research_dispatcher_refuses_non_sqlite_state():
    from app import research as R
    with pytest.raises(RV.HoldoutLocked):
        R.main(["engine", "--db", "postgresql://prod/db"])


def test_entry_points_use_the_frozen_copy():
    from pathlib import Path
    app = Path(RV.__file__).parent
    for f in ("guard15_live", "filters_live", "loss_review", "v3_review", "v3_guard_audit", "evaluate", "diagnose",
              "laststand_whatif", "research"):
        assert "frozen_copy" in (app / f"{f}.py").read_text(), f
    for f in ("research_btc", "research_sweep", "research_risk", "research_v265", "research_exits_coin", "research_liq",
              "research_turn", "research_slots"):
        assert "run_study(" in (app / f"{f}.py").read_text() and "lambda u:" in (app / f"{f}.py").read_text(), f
    assert "strip_holdout(db)" in (app / "research_coins.py").read_text()


def test_verdict_refuses_trades_that_close_inside_the_holdout():
    base = [{"ts": S - 10 * H, "closed_ts": S - H, "r": 1.0}]
    RV.verdict(base, base)
    with pytest.raises(RV.HoldoutLocked):
        RV.verdict(base, [{"ts": S - 10 * H, "closed_ts": S + H, "r": 1.0}])


class _DB:
    def __init__(self, rows):
        self.rows = rows

    def query(self, sql, args):
        return [r for r in self.rows if r["created_at"] >= args[0] and r["status"] in set(args[1:])]


def test_each_holdout_window_is_used_once(tmp_path):
    rows = [{"created_at": S + i * H, "status": "TP1", "fill_status": "FILLED"} for i in range(450)]
    ledger = tmp_path / "ledger.json"
    first = RV.read_holdout_once(_DB(rows), str(ledger), "a", "sha-a")
    assert len(first) == 300 and json.loads(ledger.read_text())[0]["cutoff"] == S + 299 * H
    with pytest.raises(RV.HoldoutLocked):                     # only 150 unused calls left: a second look is refused
        RV.read_holdout_once(_DB(rows), str(ledger), "b", "sha-b")
    rows += [{"created_at": S + (450 + i) * H, "status": "TP1", "fill_status": "FILLED"} for i in range(150)]
    second = RV.read_holdout_once(_DB(rows), str(ledger), "b", "sha-b")
    assert min(r["created_at"] for r in second) == S + 300 * H     # a NEW window, never the one already used
    ledger.write_text("{not json")
    with pytest.raises(RV.HoldoutLocked):
        RV.read_holdout_once(_DB(rows), str(ledger), "c", "sha-c")


# ---- ticker sanity --------------------------------------------------------------------------------------------------
class _Feed:
    def __init__(self, t):
        self.tickers, self.taken_ms = t, None


class _RT:
    def __init__(self, t):
        self.feed = _Feed(t)

    def ticker(self, s):
        return self.feed.tickers.get(s)

    def live_price(self, s):
        t = self.feed.tickers.get(s)
        return float(t["last"]) if t and t.get("last") else None


@pytest.mark.parametrize("tk,q", [
    ({"symbol": "X", "last": 100.4, "ts": NOW - 10_000}, "live"),
    ({"symbol": "X", "last": -1.0, "ts": NOW}, "invalid"),
    ({"symbol": "X", "last": 0.0, "ts": NOW}, "invalid"),
    ({"symbol": "X", "last": float("nan"), "ts": NOW}, "invalid"),
    ({"symbol": "X", "last": float("inf"), "ts": NOW}, "invalid"),
    ({"symbol": "X", "last": "abc", "ts": NOW}, "missing"),
    ({"symbol": "X", "last": 100.0, "ts": NOW + 120_000}, "future"),
    ({"symbol": "X", "last": 100.0, "ts": NOW + 30_000}, "live"),          # small clock skew allowed
    ({"symbol": "X", "last": 100.0, "ts": NOW - 301_000}, "stale"),
    ({"symbol": "Y", "last": 100.0, "ts": NOW}, "mismatch"),
    ({"symbol": "X", "last": 112.0, "ts": NOW}, "deviant"),                 # 12 away, limit max(4 x 2, 0.5) = 8
    ({"symbol": "X", "last": 107.5, "ts": NOW}, "live"),
])
def test_ticker_quality(tk, q):
    out = analysis.live_quote(_RT({"X": tk}), "X", 100.0, NOW, atr=2.0)
    assert out["quality"] == q, out
    if q != "live":
        assert out["price"] == 100.0 and out["source"] == "last_close"
    else:
        assert out["price"] == float(tk["last"])


def test_deviation_floor_for_tiny_atr():
    out = analysis.live_quote(_RT({"X": {"symbol": "X", "last": 100.4, "ts": NOW}}), "X", 100.0, NOW, atr=1e-6)
    assert out["quality"] == "live"                                         # within the 0.5 % floor


@pytest.mark.parametrize("q", ["missing", "stale", "future", "invalid", "mismatch", "deviant"])
def test_no_recorded_market_fill_without_a_live_ticker(q):
    from app.services import tracking
    a = {"decision": "SELL", "price": 100.0, "timeframe": "4h", "price_quality": {"quality": q, "age_s": None},
         "setup": {"side_int": -1, "ideal_entry": 100.5, "stop": 103.0, "atr": 1.0, "risk_reward": 1.6,
                   "targets": [{"price": 98.0, "rr": 1.0}, {"price": 96.0, "rr": 1.75}, {"price": 94.0, "rr": 2.5}]}}
    pl = tracking._plan(a)
    assert pl["entry"] is None and pl["skip"]


# ---- challenge entries ---------------------------------------------------------------------------------------------
def test_challenge_does_not_enter_at_a_candle_fallback(monkeypatch):
    from app.services import hesper
    h = hesper.Hesper.__new__(hesper.Hesper)
    h.rt = _RT({})                                              # a feed is in place, but it has no price for the coin
    monkeypatch.setattr(h, "_price", lambda s: 100.0, raising=False)  # the 15m-close fallback would give one
    r = {"symbol": "X", "side": 1, "timeframe": "1h", "stop": 98.0, "tp1": 102.0, "decision": "BUY", "entry": 100.0}
    assert h._enter_call({"cash": 100.0}, r, NOW) is None


def test_drift_warmup_never_hides_another_unavailable_rule(monkeypatch):
    from app.services import risk_shadow
    risk_shadow._cache.clear()
    monkeypatch.setattr(risk_shadow, "drift", lambda rt, s, tf: None)          # warm-up: not enough forecasts

    def boom(rt, now):
        raise RuntimeError("locked")
    monkeypatch.setattr(risk_shadow, "loss_sums", boom)

    class _R:
        def candles(self, s, tf):
            return None
    out = risk_shadow.assess(_R(), "X/USDT", now=NOW, timeframe="3d")
    assert out["drift_state"] == "insufficient_history"
    assert out["unavailable"] == ["loss_stop", "volatility"]
    flags = []
    d, g, why = analysis.entry_guards(_GuardRT(), "X/USDT", "3d", "BUY", "A", "ok", flags, out)
    assert d == "NO TRADE" and "CHECK UNAVAILABLE" in flags


class _GuardRT:
    """Healthy sweep / BTC inputs, so only the capital-protection result decides."""
    def __init__(self):
        import time
        now = int(time.time() * 1000) // H * H
        n = 900
        rng = np.random.default_rng(3)
        import pandas as pd
        self.btc = pd.DataFrame({"ts": now - (np.arange(n)[::-1] + 1) * H,
                                 "close": 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))})
        c = np.full(120, 100.0)
        self.coin = pd.DataFrame({"ts": now - (np.arange(120)[::-1] + 1) * H, "open": c, "high": c + 0.5,
                                  "low": c - 0.5, "close": c, "volume": 1.0})

        class _D(dict):
            def get_setting(self, k, d=None):
                return self.get(k, d)

            def set_setting(self, k, v):
                self[k] = v
        self.db = _D()

    def candles(self, s, tf):
        return self.btc if s == "BTC/USDT" else self.coin

    def record_error(self, *a):
        pass
