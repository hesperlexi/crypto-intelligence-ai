"""V3.0 Stage 2: market risk state (deterministic, RECOVERY after HIGH/SEVERE, missing data never 'safe') and the
practice auto-trade protection (risk state, daily loss limit, exposure limit)."""
from app.services import autopaper, risk_state
from tests.test_autopaper import row

H = risk_state.H


def _a(score, now, data_ok=True):
    raw = "SEVERE" if score >= 6 else "HIGH" if score >= 4 else "CAUTION" if score >= 2 else "NORMAL"
    fs = [risk_state._f("data", "Data freshness", 0 if data_ok else 2, "ok" if data_ok else "high", critical=True)]
    if not data_ok and raw in ("NORMAL", "CAUTION"):
        raw = "HIGH"
    return {"at": now, "score": score, "raw": raw, "factors": fs, "unavailable": []}


def test_states_and_recovery():
    t = 1_800_000_000_000
    s = risk_state.step_state(None, _a(1, t))
    assert s["state"] == "NORMAL"
    s = risk_state.step_state(s, _a(3, t + H))
    assert s["state"] == "CAUTION"
    s = risk_state.step_state(s, _a(6, t + 2 * H))
    assert s["state"] == "SEVERE"
    s = risk_state.step_state(s, _a(1, t + 3 * H))
    assert s["state"] == "RECOVERY" and s["recovery_until"] == t + 3 * H + risk_state.RECOVERY_MS
    s = risk_state.step_state(s, _a(4, t + 4 * H))            # back up: recovery clock restarts
    assert s["state"] == "HIGH"
    s = risk_state.step_state(s, _a(0, t + 5 * H))
    assert s["state"] == "RECOVERY"
    s = risk_state.step_state(s, _a(0, t + 5 * H + risk_state.RECOVERY_MS + 1))
    assert s["state"] == "NORMAL"


def test_blind_engine_is_never_safe():
    t = 1_800_000_000_000
    s = risk_state.step_state(None, _a(2, t, data_ok=False))
    assert s["state"] == "HIGH"


def test_practice_policy():
    assert risk_state.practice_policy("SEVERE") == {"open_new": False, "size": 0.0}
    assert risk_state.practice_policy("HIGH")["size"] == 0.5
    assert risk_state.practice_policy(None)["open_new"]


def test_auto_trade_follows_risk_and_limits():
    s = autopaper.settings_of({"margin": 100})
    sig = {**row(), "timeframe": "1h"}
    _, res = autopaper.place(None, sig, s, 1, {"risk": "SEVERE"})
    assert res["action"] == "skipped" and "severe" in res["reason"]
    acc, res = autopaper.place(None, sig, s, 1, {"risk": "HIGH"})
    assert res["action"] == "opened" and abs(res["margin"] - 60) < 1e-6       # grade A 1.2x, half size
    off = autopaper.settings_of({"margin": 100, "follow_risk": False})
    _, res = autopaper.place(None, sig, off, 1, {"risk": "SEVERE"})
    assert res["action"] == "opened"
    # daily loss: the account started the day at 1000 and is now at 940 (6% down, limit 5%)
    poor = {**autopaper.new_account(1, 1000.0), "wallet": 940.0}
    _, res = autopaper.place(poor, sig, s, 1, {"day": {"d": 0, "eq": 1000.0, "dep": 1000.0}})
    assert res["action"] == "skipped" and "daily loss" in res["reason"]
    # a deposit today is not a profit or a loss
    topped = {**autopaper.new_account(1, 1000.0), "wallet": 1440.0, "deposited": 1500.0}
    _, res = autopaper.place(topped, sig, s, 1, {"day": {"d": 0, "eq": 1000.0, "dep": 1000.0}})
    assert res["action"] == "opened"
    # exposure: 55% of the account already in use
    busy = {**autopaper.new_account(1, 1000.0), "wallet": 450.0,
            "positions": {"ETHUSDT": {"symbol": "ETH/USDT", "side": -1, "margin": 550.0}}}
    _, res = autopaper.place(busy, sig, autopaper.settings_of({"margin": 100, "max_same_side": 5}), 1)
    assert res["action"] == "skipped" and "exposure" in res["reason"]


def test_assess_runs_on_a_runtime(tmp_path):
    import numpy as np
    import pandas as pd
    from app.db import Database
    db = Database(f"sqlite:///{tmp_path}/x.db")
    now = 1_800_000_000_000

    class RT:
        def __init__(self):
            self.db = db

        def symbols(self):
            return ["BTC/USDT", "ETH/USDT"]

        def candles(self, s, tf):
            step = {"15m": 900_000, "1h": H, "4h": 4 * H}[tf]
            n = 300
            ts = np.arange(n) * step + (now - n * step)
            c = 100 + np.cumsum(np.sin(np.arange(n) / 7))
            return pd.DataFrame({"ts": ts, "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1.0})

    rt = RT()
    out = risk_state.run(rt, None, now)
    assert out["state"] in risk_state.STATES
    st = db.get_setting("risk_state")
    keys = {f["key"] for f in st["factors"]}
    assert {"data", "btc_vol", "btc_move", "record", "exposure"} <= keys
    assert db.get_setting("risk_state_log")[-1]["to"] == st["state"]
    v = risk_state.view(rt, st)
    assert v["levels"][0]["state"] == "NORMAL" and v["series"]
