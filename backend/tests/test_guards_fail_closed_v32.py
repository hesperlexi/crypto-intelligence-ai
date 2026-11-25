"""V3.2 (Fable 5.2 audit R-01): BTC shock, liquidity sweep and capital-protection guards fail CLOSED.

For each guard: an exception, missing data, stale data and insufficient history give an explicit "unavailable" state,
and `analysis.entry_guards` turns it into NO TRADE "CHECK UNAVAILABLE" with a logged error and a Health entry.
Normal operation and recovery after an error are unchanged."""
import numpy as np
import pandas as pd
import pytest

from app.services import analysis, btc_shock, risk_shadow
from app.services import sweep_guard as SG

H = 3_600_000
H4 = 4 * H


class _DB:
    def __init__(self):
        self.s = {}

    def get_setting(self, k, d=None):
        return self.s.get(k, d)

    def set_setting(self, k, v):
        self.s[k] = v

    def query(self, *a, **k):
        return []


class RT:
    """Fake runtime: per (symbol, timeframe) candles; `boom` makes a read raise."""

    def __init__(self, frames=None, boom=()):
        self.frames = frames or {}
        self.boom = set(boom)
        self.db = _DB()
        self.errors = []

    def candles(self, s, tf):
        if (s, tf) in self.boom or s in self.boom:
            raise RuntimeError("database locked")
        return self.frames.get((s, tf))

    def record_error(self, where, exc):
        self.errors.append((where, str(exc)))


def _btc(n=900, jump=0.0, seed=3):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    if jump:
        c[-6:] *= 1 + jump
    return pd.DataFrame({"ts": np.arange(n) * H, "close": c})


def _flat_1h(n=120, sweep_at=None):
    c = np.full(n, 100.0)
    h, l = c + 0.5, c - 0.5
    if sweep_at is not None:
        l[sweep_at], c[sweep_at] = 97.0, 100.2
    return pd.DataFrame({"ts": np.arange(n) * H, "open": c, "high": h, "low": l, "close": c, "volume": 1.0})


def _4h(n=200, end_close_at=None):
    rng = np.random.default_rng(1)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    ts = np.arange(n) * H4
    if end_close_at is not None:
        ts = ts - (ts[-1] + H4) + end_close_at
    return pd.DataFrame({"ts": ts, "open": c, "high": c * 1.002, "low": c * 0.998, "close": c, "volume": 1.0})


# ---- BTC shock -------------------------------------------------------------------------------------------------------
def _btc_now(df):
    return int(df["ts"].iloc[-1]) + H                      # the newest candle has just closed


@pytest.fixture(autouse=True)
def _clear():
    btc_shock._cache.clear()
    risk_shadow._cache.clear()
    yield


def test_btc_normal_operation():
    df = _btc()
    rt = RT({("BTC/USDT", "1h"): df})
    assert btc_shock.status(rt, 1, _btc_now(df))["state"] == "clear"
    df = _btc(jump=0.06)
    btc_shock._cache.clear()
    rt = RT({("BTC/USDT", "1h"): df})
    assert btc_shock.status(rt, -1, _btc_now(df))["state"] == "block"
    assert btc_shock.status(rt, 1, _btc_now(df))["state"] == "clear"


def test_btc_missing_data_is_unavailable():
    st = btc_shock.status(RT({}), 1, 10 ** 12)
    assert st["state"] == "unavailable" and "no BTC" in st["reason"]


def test_btc_exception_is_unavailable():
    st = btc_shock.status(RT(boom={"BTC/USDT"}), -1, 10 ** 12)
    assert st["state"] == "unavailable" and "database locked" in st["reason"]


def test_btc_stale_data_is_unavailable():
    df = _btc()
    st = btc_shock.status(RT({("BTC/USDT", "1h"): df}), 1, _btc_now(df) + 3 * H)
    assert st["state"] == "unavailable" and "stale" in st["reason"]


def test_btc_insufficient_history_is_unavailable():
    df = _btc(n=500)
    st = btc_shock.status(RT({("BTC/USDT", "1h"): df}), 1, _btc_now(df))
    assert st["state"] == "unavailable" and "insufficient" in st["reason"]


# ---- liquidity sweep -------------------------------------------------------------------------------------------------
def test_sweep_normal_operation():
    rt = RT({("X/USDT", "1h"): _flat_1h(sweep_at=110)})
    assert SG.status(rt, "X/USDT", -1, 113 * H)["state"] == "block"
    assert SG.status(rt, "X/USDT", 1, 113 * H)["state"] == "clear"
    assert SG.status(RT({("X/USDT", "1h"): _flat_1h()}), "X/USDT", 1, 120 * H)["state"] == "clear"


@pytest.mark.parametrize("rt,now,word", [
    (RT({}), 120 * H, "no X/USDT"),                                           # missing
    (RT(boom={"X/USDT"}), 120 * H, "database locked"),                        # exception
    (RT({("X/USDT", "1h"): _flat_1h()}), 125 * H, "stale"),                   # newest closed 5 h ago
    (RT({("X/USDT", "1h"): _flat_1h(n=40)}), 40 * H, "insufficient"),        # short history
])
def test_sweep_faults_are_unavailable(rt, now, word):
    st = SG.status(rt, "X/USDT", 1, now)
    assert st["state"] == "unavailable" and word in st["reason"]


# ---- capital protection ----------------------------------------------------------------------------------------------
NOW = 1_800_000_000_000


def test_capital_protection_normal_operation(monkeypatch):
    monkeypatch.setattr(risk_shadow, "loss_sums", lambda rt, now: (0.0, 0.0))
    rt = RT({("X/USDT", "4h"): _4h(end_close_at=NOW - H)})
    out = risk_shadow.assess(rt, "X/USDT", now=NOW)
    assert out["unavailable"] == [] and out["would_block"] is False and out["volatile"] is False


@pytest.mark.parametrize("frames,boom,word", [
    ({}, (), "no 4h"),                                                         # missing
    ({}, ("X/USDT",), "unreadable"),                                           # exception
    ({("X/USDT", "4h"): _4h(end_close_at=NOW - 20 * H)}, (), "stale"),        # stale
    ({("X/USDT", "4h"): _4h(n=50, end_close_at=NOW - H)}, (), "insufficient"),  # short history
])
def test_capital_protection_volatility_faults(monkeypatch, frames, boom, word):
    monkeypatch.setattr(risk_shadow, "loss_sums", lambda rt, now: (0.0, 0.0))
    out = risk_shadow.assess(RT(frames, boom), "X/USDT", now=NOW)
    assert out["unavailable"] == ["volatility"] and word in out["unavailable_reason"]


def test_capital_protection_loss_stop_query_failure(monkeypatch):
    def boom(rt, now):
        raise RuntimeError("no such table")
    monkeypatch.setattr(risk_shadow, "loss_sums", boom)
    out = risk_shadow.assess(RT({("X/USDT", "4h"): _4h(end_close_at=NOW - H)}), "X/USDT", now=NOW)
    assert out["unavailable"] == ["loss_stop"] and out["loss_stop"] is False


def test_capital_protection_drift_warmup_is_not_a_failure(monkeypatch):
    monkeypatch.setattr(risk_shadow, "loss_sums", lambda rt, now: (0.0, 0.0))
    monkeypatch.setattr(risk_shadow, "drift", lambda rt, s, tf: None)
    out = risk_shadow.assess(RT({("X/USDT", "4h"): _4h(end_close_at=NOW - H)}), "X/USDT", now=NOW, timeframe="3d")
    assert out["drift_state"] == "insufficient_history" and out["unavailable"] == []

    def boom(rt, s, tf):
        raise ValueError("bad bundle")
    monkeypatch.setattr(risk_shadow, "drift", boom)
    out = risk_shadow.assess(RT({("X/USDT", "4h"): _4h(end_close_at=NOW - H)}), "X/USDT", now=NOW, timeframe="3d")
    assert out["drift_state"] == "error" and out["unavailable"] == ["drift"]


def test_risk_shadow_wrapper_never_returns_none_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaput")
    monkeypatch.setattr(risk_shadow, "assess", boom)
    rt = RT()
    out = analysis._risk_shadow(rt, "X/USDT", "4h")
    assert out["unavailable"] == ["assessment"] and "kaput" in out["unavailable_reason"]
    assert rt.errors


# ---- analysis.entry_guards: the live decision -------------------------------------------------------------------------
def _healthy_rt(now):
    btc = _btc()
    btc["ts"] = btc["ts"] - (int(btc["ts"].iloc[-1]) + H) + now           # newest BTC candle closed at `now`
    coin = _flat_1h()
    coin["ts"] = coin["ts"] - (int(coin["ts"].iloc[-1]) + H) + now
    return RT({("BTC/USDT", "1h"): btc, ("X/USDT", "1h"): coin})


def _ok_check():
    return {"would_block": False, "reason": None, "unavailable": [], "unavailable_reason": None}


def _run(rt, risk_check, decision="BUY"):
    flags = []
    d, g, why = analysis.entry_guards(rt, "X/USDT", "4h", decision, "A", "ok", flags, risk_check)
    return d, g, why, flags


def _now():
    import time
    return int(time.time() * 1000) // H * H


def test_entry_guards_pass_a_healthy_call():
    rc = _ok_check()
    d, g, why, flags = _run(_healthy_rt(_now()), rc)
    assert (d, g, flags) == ("BUY", "A", [])
    assert rc["guards"] == {"sweep_guard": "clear", "btc_shock": "clear"}


@pytest.mark.parametrize("fault", ["btc_missing", "btc_stale", "btc_short", "btc_error", "sweep_missing", "sweep_error",
                                   "sweep_stale", "capital_unavailable"])
def test_entry_guards_fail_closed(fault):
    now = _now()
    rt = _healthy_rt(now)
    rc = _ok_check()
    if fault == "btc_missing":
        del rt.frames[("BTC/USDT", "1h")]
    elif fault == "btc_stale":
        rt.frames[("BTC/USDT", "1h")] = rt.frames[("BTC/USDT", "1h")].iloc[:-4]
    elif fault == "btc_short":
        rt.frames[("BTC/USDT", "1h")] = rt.frames[("BTC/USDT", "1h")].tail(200)
    elif fault == "btc_error":
        rt.boom.add("BTC/USDT")
    elif fault == "sweep_missing":
        del rt.frames[("X/USDT", "1h")]
    elif fault == "sweep_error":
        rt.boom.add("X/USDT")
    elif fault == "sweep_stale":
        rt.frames[("X/USDT", "1h")] = rt.frames[("X/USDT", "1h")].iloc[:-5]
    elif fault == "capital_unavailable":
        rc = {**rc, "unavailable": ["volatility"], "unavailable_reason": "volatility: no 4h candles"}
    d, g, why, flags = _run(rt, rc)
    assert d == "NO TRADE" and g is None
    assert flags == ["CHECK UNAVAILABLE"]
    assert "could not be checked" in why and "fail-safe" in why
    gate = {"b": "btc_shock", "s": "sweep_guard", "c": "capital_protection"}[fault[0]]
    assert gate in analysis.gate_failures(rt.db)                                # shown on Health
    assert rt.errors                                                            # logged


def test_entry_guards_leave_non_entries_alone():
    rt = RT()                                                                   # everything missing
    for d0 in ("HOLD", "NO TRADE", "INSUFFICIENT DATA"):
        d, g, why, flags = _run(rt, None, decision=d0)
        assert d == d0 and flags == [] and not rt.errors


def test_entry_guards_recover_after_an_error():
    now = _now()
    rt = _healthy_rt(now)
    rt.boom.add("BTC/USDT")
    assert _run(rt, _ok_check())[0] == "NO TRADE"
    rt.boom.clear()                                                             # data back
    d, g, why, flags = _run(rt, _ok_check())
    assert (d, flags) == ("BUY", [])


def test_entry_guards_real_blocks_unchanged():
    now = _now()
    rt = _healthy_rt(now)
    rc = {**_ok_check(), "would_block": True, "reason": "loss limit"}
    d, g, why, flags = _run(rt, rc)
    assert d == "NO TRADE" and flags == ["CAPITAL PROTECTION"] and why == "capital protection: loss limit"


def test_check_unavailable_is_not_counted_as_a_proven_gate_block():
    from app.services import proof_checks
    assert "CHECK UNAVAILABLE" in proof_checks.SKIP_FLAGS
