"""AI research v3 (research only): the harness equals the live record, live targets, one call at a time, purged
folds, statistics, and the per-timeframe evaluation on fabricated candidates (dev never evaluates the holdout)."""
import numpy as np
import pandas as pd
import pytest

from app import research_v3 as R
from app.data.base import tf_ms
from app.db import Database
from app.ml import meta_v3 as MV
from app.services import tracking as T

M15 = tf_ms("15m")
H1 = tf_ms("1h")
T0 = 1_750_000_000_000 // tf_ms("4h") * tf_ms("4h")


def _p15(n=2000, seed=3, gap_at=None):
    rng = np.random.default_rng(seed)
    px, rows = 100.0, []
    for i in range(n):
        op = px * (1.03 if gap_at is not None and i == gap_at else 1.0)
        cl = op * float(np.exp(rng.normal(0, 0.004)))
        hi = max(op, cl) * (1 + abs(rng.normal(0, 0.002)))
        lo = min(op, cl) * (1 - abs(rng.normal(0, 0.002)))
        rows.append([T0 + i * M15, op, hi, lo, cl, 1.0])
        px = cl
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])


def _own(p15, tf="1h"):
    from app.data.base import resample_ohlcv
    return resample_ohlcv(p15, "15m", tf)


CASES = [
    # decision, side, rule, k, ideal offset (x price), stop offset, mults
    ("BUY", 1, "old", 0.0, -0.002, -0.012, (1.0, 1.5, 2.5)),
    ("SELL", -1, "old", 0.0, 0.002, 0.012, (1.0, 2.0, 3.0)),
    ("BUY ON PULLBACK", 1, "old", 0.0, -0.004, -0.014, (1.0, 1.75, 2.25)),
    ("SELL", -1, "confirm", 0.1, 0.002, 0.010, (1.0, 1.25, 2.0)),
    ("BUY", 1, "pullback", 0.25, -0.002, -0.012, (1.0, 2.0, 3.0)),
    ("BUY", 1, "market", 0.0, -0.003, -0.006, (1.0, 1.5, 2.0)),
]


@pytest.mark.parametrize("case", range(len(CASES)))
@pytest.mark.parametrize("start", [40, 300, 900])
def test_harness_equals_the_live_record(case, start):
    """A call simulated by the research harness ends exactly as the live record stores it: same status, close time,
    gross and net result (costs + stored hourly funding), including gap fills, pullback limits and entry rules."""
    dec, side, rule, k, io, so, mults = CASES[case]
    p15 = _p15(gap_at=start + 9)
    own = _own(p15)
    bar_close = int(p15["ts"].iloc[start]) // H1 * H1
    created = bar_close + R.DECISION_LATENCY_MS
    i15 = int(np.searchsorted(p15["ts"].to_numpy(), created, side="right") - 1)
    price = float(p15["open"].iloc[i15])
    last_close = float(p15["close"].iloc[i15 - 1])
    ideal, stop = last_close * (1 + io), last_close * (1 + so)
    atr = abs(ideal - stop) / 1.5
    fts = np.arange(T0, T0 + 600 * H1, H1)
    fval = np.where(np.arange(len(fts)) % 3 == 0, 0.0004, -0.0001)
    now = int(p15["ts"].iloc[-1]) + M15
    sim = R.simulate_call(symbol="ETH/USDT", tf="1h", side=side, decision=dec, created=created, price=price,
                          last_close=last_close, ideal=ideal, stop=stop, atr=atr, mults=mults, mode=rule, k=k, p15=p15,
                          own=own, now=now, funding=R.FundingDB(fts, fval), grade="A")
    # the live record: log the call, then follow it
    db = Database("sqlite:///:memory:")
    db.executemany("INSERT INTO derivs (symbol, kind, ts, value) VALUES (?, 'funding_1h', ?, ?)",
                   [("ETH/USDT", int(t), float(v)) for t, v in zip(fts, fval)])
    import time
    db.set_setting("entry_policy1|1h", {"chosen": f"{rule}:{k}", "at": int(time.time() * 1000)})
    d0 = abs(ideal - stop)
    a = {"symbol": "ETH/USDT", "timeframe": "1h", "bar_ts": bar_close - H1, "price": price, "last_close": last_close,
         "decision": dec, "grade": "A", "confidence": 0.6, "regime": {"regime": "BULL"}, "volatility": {"state": "NORMAL"},
         "signal": {"signal": "BUY" if side > 0 else "SELL", "score": 70, "reasons": [], "warnings": []},
         "setup": {"valid": True, "side_int": side, "ideal_entry": ideal, "stop": stop, "risk_reward": 1.6, "atr": atr,
                   "targets": [{"price": ideal + side * m * d0, "rr": m} for m in mults]}, "flags": []}
    logged = T.log_signal(db, a, now=created)
    assert logged == sim["recorded"]
    if not logged:
        return

    class RT:
        pass
    rt = RT()
    rt.db = db
    rt.candles = lambda s, tf: p15 if tf == "15m" else own
    T.update_signal_outcomes(rt, now=now)
    row = db.one("SELECT * FROM signals")
    assert row["status"] == sim["status"]
    if row["status"] in T.CLOSED_STATUSES:
        assert row["closed_at"] == sim["closed_ts"]
        assert row["return_pct"] == pytest.approx(sim["gross_pct"], abs=1e-9)
        assert row["return_net_pct"] == pytest.approx(sim["net_pct"], abs=1e-9)
        assert row["funding_pct"] == pytest.approx(sim["funding_pct"], abs=1e-12)
        risk = abs(row["entry"] - row["stop"]) / row["entry"] * 100
        assert sim["r_net"] == pytest.approx(row["return_net_pct"] / risk)
    elif row["status"] == "NOT_FILLED":
        assert not sim["filled"] and row["closed_at"] == sim["closed_ts"]


def test_market_entry_is_the_price_at_publication_and_the_first_candle_is_skipped():
    p15 = _p15()
    created = int(p15["ts"].iloc[100]) + R.DECISION_LATENCY_MS
    price = float(p15["open"].iloc[100])
    sim = R.simulate_call(symbol="BTC/USDT", tf="1h", side=1, decision="BUY", created=created, price=price,
                          last_close=price, ideal=price * 0.998, stop=price * 0.99, atr=0.5, mults=(1.0, 1.5, 2.0),
                          mode="old", k=0.0, p15=p15, own=_own(p15), now=int(p15["ts"].iloc[-1]) + M15)
    assert sim["entry"] == pytest.approx(price) and sim["entry_mode"] == "market"
    assert sim["closed_ts"] >= int(p15["ts"].iloc[101])


def test_no_record_when_the_price_is_beyond_the_stop():
    p15 = _p15()
    sim = R.simulate_call(symbol="BTC/USDT", tf="1h", side=1, decision="BUY", created=int(p15["ts"].iloc[50]) + 60_000,
                          price=98.0, last_close=100.0, ideal=99.5, stop=98.5, atr=0.6, mults=(1.0, 1.5, 2.0), mode="old",
                          k=0.0, p15=p15, own=None, now=int(p15["ts"].iloc[-1]))
    assert sim == {"recorded": False, "reason": "the price is already at or beyond the stop"}


def test_funding_stub_equals_the_stored_rates():
    db = Database("sqlite:///:memory:")
    hr = 3_600_000
    ts = np.arange(0, 50 * hr, hr)
    vals = np.linspace(-0.0003, 0.0005, len(ts))
    db.executemany("INSERT INTO derivs (symbol, kind, ts, value) VALUES (?, 'funding_1h', ?, ?)",
                   [("X/USDT", int(t), float(v)) for t, v in zip(ts[::2], vals[::2])])
    stub = R.FundingDB.load(db, "X/USDT")
    segs = [(int(3.5 * hr), int(20 * hr), 1.0), (int(20 * hr), int(31.2 * hr), 0.5)]
    for side in (1, -1):
        assert T.funding_pct(stub, "X/USDT", side, segs) == pytest.approx(T.funding_pct(db, "X/USDT", side, segs))


@pytest.mark.parametrize("seed", [1, 2])
def test_live_targets_equal_build_setup(seed):
    """TP2 / TP3 and the base-rate validity equal engine/setup.build_setup at the same bar (exact stop distance)."""
    from app.engine.setup import build_setup
    from app.features.dataset import build_frame
    from tests.helpers import synthetic_candles
    df = synthetic_candles(1500, "1h", seed=seed)
    ind = build_frame(df, "1h").ind
    br = R.BaseRates(ind["high"], ind["low"], ind["close"], ind["atr"], ind["regime_score"])
    checked = 0
    for p in range(400, 1500, 97):
        price = float(ind["close"].iloc[p])
        atr = float(ind["atr"].iloc[p])
        for side in (1, -1):
            zones = {"support": [{"low": price - 3.2 * atr, "high": price - 3.0 * atr}],
                     "resistance": [{"low": price + 2.6 * atr, "high": price + 2.8 * atr}]}
            if side < 0:
                zones = {"support": [{"low": price - 2.8 * atr, "high": price - 2.6 * atr}],
                         "resistance": [{"low": price + 3.0 * atr, "high": price + 3.2 * atr}]}
            s = build_setup(ind.iloc[:p + 1], zones, side, 1.25, live_price=price)
            dist = abs(s["ideal_entry"] - s["stop"])
            tg = R.pick_targets(br, p, side, dist, atr, R.walls_of(zones, side, s["ideal_entry"], dist), snap=False)
            assert tg["m2"] == pytest.approx(s["targets"][1]["rr"]) and tg["m3"] == pytest.approx(s["targets"][2]["rr"])
            if s.get("expectancy_r") is not None:
                assert tg["exp_r"] == pytest.approx(s["expectancy_r"], abs=1e-9)
                bad = s["expectancy_r"] < -0.15
                assert tg["valid"] == (not bad)
            checked += 1
    assert checked > 10


def test_take_live_one_call_at_a_time_cooldown_and_reentry_cap():
    step = H1
    ts = np.array([0, 2, 5, 9, 14, 20, 26, 32]) * step
    closed = np.array([4, 3, 8, 12, 18, 24, 30, 40]) * step + 0.0
    side = np.ones(8, int)
    exits = np.array(["stop"] * 8, dtype=object)
    idx = R.take_live(ts, closed, side, exits, step, cooldown=0, window=100, rmax=2)
    # call 0 (closes 4) blocks call 1; 2 is the 1st re-entry after the stop of 0, 3 the 2nd; then the cap holds
    assert list(idx) == [0, 2, 3]
    idx = R.take_live(ts, closed, side, np.array(["tp3"] * 8, dtype=object), step, cooldown=2, window=100, rmax=2)
    assert list(idx) == [0, 3, 5, 7]   # cooldown: 2 bars after the exit candle (closed + 15 min + 2 h)
    # a call still open at the end of the data blocks everything after it
    c2 = closed.copy()
    c2[2] = np.inf
    assert list(R.take_live(ts, c2, side, np.array(["tp3"] * 8, dtype=object), step, cooldown=0, window=1, rmax=9)) == [0, 2]


def test_purged_folds_train_only_on_trades_closed_before_validation():
    rng = np.random.default_rng(0)
    ts = np.sort(rng.integers(0, 1000, 600)) * H1
    closed = ts + rng.integers(1, 50, 600) * H1
    folds = MV.purged_folds(ts, closed, k=5, embargo_ms=50 * H1, min_train=10)
    assert len(folds) >= 3
    for tr, va in folds:
        start = ts[va].min()
        assert (closed[tr] < start).all() and (ts[tr] < start - 50 * H1).all()


def test_statistics_family_and_calibration():
    rng = np.random.default_rng(5)
    n = 600
    sym = rng.choice(["A", "B", "C"], n)
    ts = np.sort(rng.integers(0, 52, n)) * MV.WEEK_MS
    keys = MV.block_keys(sym, ts)
    noise = {f"s{i}": (rng.normal(0, 1, n), keys) for i in range(6)}
    fam = MV.family_test(noise, n_boot=500)
    assert fam["reality_check_p"] > 0.05 and fam["spa_p"] > 0.05
    strong = dict(noise)
    strong["good"] = (rng.normal(0.4, 1, n), keys)
    fam = MV.family_test(strong, n_boot=500)
    assert fam["best"] == "good" and fam["spa_p"] < 0.05 and fam["strategies"]["good"]["p_holm"] < 0.05
    b = MV.bootstrap_mean(rng.normal(0.0, 1, n), keys, n_boot=500)
    assert b["ci95"][0] < 0 < b["ci95"][1]
    p = rng.random(5000)
    y = (rng.random(5000) < p).astype(int)
    rel = MV.reliability(p, y)
    assert rel["ece"] < 0.03 and rel["brier"] < rel["brier_climatology"]
    cal = MV.Calibrator().fit(p * 0.5, y)
    assert MV.reliability(cal(p * 0.5), y)["ece"] < 0.03
    assert MV.holm({"a": 0.01, "b": 0.04, "c": None}) == {"a": 0.02, "b": 0.04, "c": None}


def _fake_series(seed: int, symbol: str, tf: str = "4h", n: int = 1400, edge: float = 0.0):
    rng = np.random.default_rng(seed)
    step = tf_ms(tf)
    recs, F = [], []
    for j in range(n):
        ts = T0 + j * step
        for side in (1, -1):
            x = rng.normal(size=6)
            p_win = 0.45 + edge * np.tanh(x[0] * side)
            win = rng.random() < p_win
            r = (abs(rng.normal(1.0, 0.3)) if win else -1.0) - 0.1
            pipe = bool(j % 5 == 0 and side == (1 if j % 2 else -1))
            filled = not (pipe and j % 35 == 0)
            recs.append({"j": j, "pos": j, "ts": ts, "side": side, "pipe": pipe, "grid": j % 2 == 0, "grade": "A" if j % 3 else "B",
                         "decision": "BUY" if side > 0 else "SELL", "conf": 0.55, "model_side": 1, "trend_side": 1,
                         "rand_side": 1 if rng.random() < 0.5 else -1, "recorded": True, "status": "TP1" if win else "STOPPED",
                         "filled": filled, "finished": True, "closed": float(ts + rng.integers(1, 8) * step),
                         "r_net": r if filled else np.nan, "r_gross": r + 0.1, "net_pct": r, "funding_pct": 0.0, "risk_pct": 1.0,
                         "tp1": int(win), "exit": "tp3" if win else "stop", "hold_h": 5.0, "entry_mode": "market"})
            F.append(x.astype(np.float32))
    hold = {i: {"v1_keep": bool(i % 2), "runner": {"recorded": True, "filled": True, "r_net": 0.2, "closed": recs[i]["closed"],
                                                    "exit": "tp3"}}
            for i, r in enumerate(recs) if r["pipe"] and r["ts"] >= T0 + int(n * 0.8) * step}
    tf2 = {i: rng.normal(size=17).astype(np.float32) for i, r in enumerate(recs) if r["pipe"]}
    return {"key": f"{symbol} {tf}", "symbol": symbol, "tf": tf, "now": T0 + (n + 10) * step, "recs": recs,
            "F": np.vstack(F), "fnames": [f"f{i}" for i in range(6)], "old_pieces": {"holdout_calls": hold}, "tf2": tf2}


@pytest.mark.parametrize("final", [False, True])
def test_evaluate_tf_runs_and_dev_never_touches_the_holdout(final):
    series = [_fake_series(1, "AAA/USDT", edge=0.15), _fake_series(2, "BBB/USDT", edge=0.15)]
    cut = T0 + int(1400 * 0.8) * tf_ms("4h")
    reg: list = []
    ev = R.evaluate_tf("4h", series, cut, final, {"AAA/USDT"}, reg, {"symbols": ["AAA/USDT", "BBB/USDT"], "null_perms": 2})
    assert ev["dev_rows"] > 0 and ev["holdout_rows"] > 0 and ev["folds"]
    assert any(r["config"] == "filter_grid" for r in reg) and all(r["tf"] == "4h" for r in reg)
    if not final:
        assert ev["holdout"] == "not evaluated (dev mode)" and "tests" not in ev
        assert R.verdict("4h", ev) == {"evaluated": False}
        return
    h = ev["holdout"]
    for k in ("current_core", "baseline_random", "baseline_always_long", "filter_er_pos_ab", "direction_er_pos",
              "old_trade_filter_v1", "old_runner", "current_full"):
        assert k in h
    assert h["current_core"]["n"] > 0 and h["current_core"]["trades_per_month_watchlist"] <= h["current_core"]["trades_per_month"]
    assert set(ev["tests"]) == {"new_vs_zero", "new_vs_current", "old_vs_current", "baselines_and_current_vs_zero"}
    cal = ev["calibration_holdout"]["all_candidates"]["meta_v3_calibrated"]
    assert cal["n"] > 0 and 0 <= cal["ece"] <= 1
    v = R.verdict("4h", ev)
    assert v["evaluated"] and isinstance(v["new_configs_passing"], list)
