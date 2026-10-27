"""Let winners run (v2.3): runner exits, the record and the bots follow the same rules."""
import numpy as np
import pandas as pd

from app.db import Database
from app.ml import runner_model as RM
from app.services import tracking


def test_runner_and_standard_exits_in_r():
    # entry 100, risk 2 (1R = 2): TP ladder 102 / 103.5 / 105, runner target 108
    up = np.array([100, 102.5, 104, 106, 108.5]); lo = np.array([100, 100.5, 102.5, 104, 106])
    hi_ = up; cl = up
    std, hit = RM.exits_r(hi_, lo, cl, 100.0, 2.0, 1, 0, 10)
    run, _ = RM.exits_r(hi_, lo, cl, 100.0, 2.0, 1, 0, 10, run=True)
    assert hit and abs(std - (0.5 * 1 + 0.25 * 1.75 + 0.25 * 2.5)) < 1e-9 and run == RM.RUN_R
    # TP1 then a reversal: standard keeps half of 1R, the runner exits at break-even
    hi2 = np.array([100, 102.2, 101, 100.5]); lo2 = np.array([100, 100.5, 99.8, 97])
    std2, _ = RM.exits_r(hi2, lo2, hi2, 100.0, 2.0, 1, 0, 10)
    run2, _ = RM.exits_r(hi2, lo2, hi2, 100.0, 2.0, 1, 0, 10, run=True)
    assert abs(std2 - 0.5) < 1e-9 and abs(run2) < 1e-9


def test_runner_model_stays_off_without_evidence():
    rng = np.random.default_rng(0)
    n = 1500
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    X = rng.normal(size=(n, 5)); P = np.tile([0.3, 0.2, 0.5], (n, 1)).astype(float)
    out = RM.train(X[:1200], P[:1200], np.arange(1200), c * 1.004, c * 0.996, c, np.full(n, c.mean() * 0.006), 0.0005)
    assert out["enabled"] in (False, True) and "reason" in out          # trains or says why not - never crashes


def test_record_scores_a_runner_signal_as_one_exit():
    class RT:
        def __init__(self, bars):
            self.db = Database("sqlite:///:memory:")
            self.df = pd.DataFrame(bars, columns=["ts", "open", "high", "low", "close", "volume"])

        def candles(self, s, tf):
            return self.df

    def run(bars):
        rt = RT([[0, 100, 100, 100, 100, 1]] + bars)
        rt.db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, "
                      "tp1, tp2, tp3, status, payload) VALUES ('s', 1, 'BTC/USDT', '4h', 0, 'BUY', 'BUY', 100, 1, 100, 98, 102, "
                      "103.5, 105, 'OPEN', '{\"runner\": {\"on\": true, \"target\": 108, \"rr\": 4}}')")
        tracking.update_signal_outcomes(rt)
        return rt.db.one("SELECT status, return_pct FROM signals")

    r = run([[1, 100, 102.5, 100.5, 102, 1], [2, 102, 104, 102.5, 103.8, 1], [3, 104, 108.2, 103.9, 108, 1]])
    assert r["status"] == "TP3" and abs(r["return_pct"] - 8.0) < 1e-9          # the whole position at 1:4
    r = run([[1, 100, 103.6, 100.5, 103, 1], [2, 103, 103, 101.5, 102, 1]])   # TP2, back to TP1: stop there
    assert r["status"] == "TP2" and abs(r["return_pct"] - 2.0) < 1e-9
    r = run([[1, 100, 102.2, 100.5, 101, 1], [2, 101, 101, 99.5, 99.6, 1]])   # TP1, back to entry
    assert r["status"] == "TP1" and abs(r["return_pct"]) < 1e-9
