"""Trade management (engine/manage.py): identical to the v2.4 record with managed exits off; managed exits as specified."""
import numpy as np
import pytest

from app.engine import manage as M

OFF = {"managed": False}
ON = {"managed": True, "giveback_arm_r": 0.6, "giveback_frac": 0.5, "trail_atr_k": 2.0, "time_stop_bars": 12,
      "time_stop_min_r": 0.25}


def old_follow(side, entry, stop, tps, rows, final=None, covered=True):
    """Verbatim copy of the v2.4 tracking.update_signal_outcomes inner loop (the reference)."""
    hit = [False, False, False]
    stop_hit, closed_ts = False, None
    final_hit = False
    level = stop
    for c in rows:
        ts, op, hi, lo, cl = c
        if (side > 0 and lo <= level) or (side < 0 and hi >= level):
            stop_hit, closed_ts = True, ts
            break
        for i, tp in enumerate(tps):
            if (side > 0 and hi >= tp) or (side < 0 and lo <= tp):
                hit[i] = True
        if final is None:
            level = tps[0] if hit[1] else entry if hit[0] else stop
            if hit[2]:
                closed_ts = ts
                break
        else:
            level = tps[1] if hit[2] else tps[0] if hit[1] else entry if hit[0] else stop
            if (side > 0 and hi >= final) or (side < 0 and lo <= final):
                final_hit, closed_ts = True, ts
                hit = [True, True, True]
                break
    expired = closed_ts is None and covered
    last_close = rows[-1][4]
    fallback = level if stop_hit else last_close
    if final is None:
        ret = float(sum(w * side * ((tps[i] if hit[i] else fallback) / entry - 1) for i, w in enumerate((0.5, 0.25, 0.25)))) * 100
        status = "STOPPED" if stop_hit and not hit[0] else "TP3" if hit[2] else \
            ("TP2" if hit[1] else "TP1" if hit[0] else "EXPIRED") if (stop_hit or expired) else "OPEN"
    else:
        ret = float(side * ((final if final_hit else fallback) / entry - 1)) * 100
        status = "TP3" if final_hit else "STOPPED" if stop_hit and not hit[0] else \
            ("TP3" if hit[2] else "TP2" if hit[1] else "TP1" if hit[0] else "EXPIRED") if (stop_hit or expired) else "OPEN"
    if closed_ts is None and expired:
        closed_ts = rows[-1][0]
    return status, hit, stop_hit, ret, closed_ts if status != "OPEN" else None


def _path(rng, n, px=100.0, vol=0.006, drift=0.0):
    rows, t = [], 0
    for _ in range(n):
        op = px
        cl = op * float(np.exp(rng.normal(drift, vol)))
        hi = max(op, cl) * (1 + abs(rng.normal(0, vol / 2)))
        lo = min(op, cl) * (1 - abs(rng.normal(0, vol / 2)))
        rows.append((t, op, hi, lo, cl))
        px, t = cl, t + 900_000
    return rows


def test_managed_off_reproduces_the_old_record_on_many_random_paths():
    rng = np.random.default_rng(42)
    for k in range(3000):
        side = 1 if k % 2 else -1
        entry = 100.0
        risk = float(rng.uniform(0.5, 3.0))
        stop = entry - side * risk
        m2, m3 = float(rng.uniform(1.25, 2.0)), float(rng.uniform(2.0, 3.0))
        tps = [entry + side * risk, entry + side * m2 * risk, entry + side * m3 * risk]
        final = entry + side * 4 * risk if k % 5 == 0 else None
        rows = _path(rng, int(rng.integers(1, 60)), vol=float(rng.uniform(0.002, 0.012)), drift=float(rng.normal(0, 0.001)))
        covered = bool(k % 3)
        ref = old_follow(side, entry, stop, tps, rows, final, covered)
        new = M.follow(side, entry, stop, tps, rows, runner_target=final, atr=1.0, params=OFF, complete=covered)
        assert (new["status"], new["hits"], new["stop_hit"], new["closed_ts"]) == (ref[0], ref[1], ref[2], ref[4]), k
        assert new["return_pct"] == pytest.approx(ref[3], abs=1e-9), k
        assert new["managed"] == 0
        if new["status"] != "OPEN":
            assert new["exit_reason"] in ("tp3", "stop", "break_even", "trail", "expired")
        assert new["peak_r"] >= 0


def test_exit_reasons_and_peak_with_managed_exits_off():
    tps = [102, 103, 104]
    r = M.follow(1, 100, 98, tps, [(0, 100, 102.5, 100.5, 102), (1, 101, 101, 99.9, 100)], params=OFF)
    assert r["status"] == "TP1" and r["exit_reason"] == "break_even" and r["peak_r"] == pytest.approx(1.25)
    assert r["peak_pct"] == pytest.approx(2.5)
    r = M.follow(1, 100, 98, tps, [(0, 100, 101, 97.5, 98)], params=OFF)
    assert r["status"] == "STOPPED" and r["exit_reason"] == "stop" and r["return_r"] == pytest.approx(-1)
    r = M.follow(1, 100, 98, tps, [(0, 100, 104.5, 100, 104)], params=OFF)
    assert r["exit_reason"] == "tp3"
    r = M.follow(1, 100, 98, tps, [(0, 100, 101, 99, 100.5)], params=OFF, complete=True)
    assert r["status"] == "EXPIRED" and r["exit_reason"] == "expired" and r["return_pct"] == pytest.approx(0.5)


def test_giveback_closes_after_a_retrace_and_uses_only_prior_peaks():
    # entry 100, stop 98 (1R = 2). Candle 1 peaks at +0.8R (101.6). Candle 2 dips to +0.3R: threshold 0.4R = 100.8
    rows = [(0, 100, 101.6, 99.9, 101.4), (1, 101.4, 101.5, 100.6, 100.7)]
    r = M.follow(1, 100, 98, [102, 103, 104], rows, params=ON)
    assert r["exit_reason"] == "giveback" and r["managed"] == 1 and r["exit_price"] == pytest.approx(100.8)
    assert r["return_r"] == pytest.approx(0.4) and r["peak_r"] == pytest.approx(0.8)
    # same candle reaching the peak and dipping: the peak of that candle does not count against itself
    r = M.follow(1, 100, 98, [102, 103, 104], [(0, 100, 101.6, 100.1, 100.2)], params=ON)
    assert r["status"] == "OPEN"
    # gap below the threshold: fills at the open
    rows = [(0, 100, 101.6, 99.9, 101.4), (1, 100.5, 100.6, 100.2, 100.3)]
    r = M.follow(1, 100, 98, [102, 103, 104], rows, params=ON)
    assert r["exit_price"] == pytest.approx(100.5)
    # stop first: a candle reaching both the stop and the give-back level is a stop
    rows = [(0, 100, 101.6, 99.9, 101.4), (1, 101.4, 101.4, 97.0, 97.5)]
    assert M.follow(1, 100, 98, [102, 103, 104], rows, params=ON)["exit_reason"] == "stop"
    # not armed below 0.6R; off when managed exits are off
    rows = [(0, 100, 101.0, 99.9, 100.9), (1, 100.9, 100.9, 98.5, 98.6)]
    assert M.follow(1, 100, 98, [102, 103, 104], rows, params=ON)["status"] == "OPEN"
    rows = [(0, 100, 101.6, 99.9, 101.4), (1, 101.4, 101.5, 100.6, 100.7)]
    assert M.follow(1, 100, 98, [102, 103, 104], rows, params=OFF)["status"] == "OPEN"


def test_giveback_short_mirror():
    rows = [(0, 100, 100.1, 98.4, 98.6), (1, 98.6, 99.4, 98.5, 99.3)]
    r = M.follow(-1, 100, 102, [98, 97, 96], rows, params=ON)
    assert r["exit_reason"] == "giveback" and r["exit_price"] == pytest.approx(99.2)


def test_atr_trailing_stop_after_tp1():
    # TP1 at 102 hit, closes at 103.5 -> trail 103.5 - 2*0.5 = 102.5 (above break-even 100); a dip to 102.4 exits at 102.5
    rows = [(0, 100, 103.6, 100.2, 103.5), (1, 103.5, 103.6, 102.4, 102.6)]
    r = M.follow(1, 100, 98, [102, 104, 106], rows, atr=0.5, params=ON)
    assert r["exit_reason"] == "trail" and r["managed"] == 1 and r["status"] == "TP1"
    assert r["return_pct"] == pytest.approx(0.5 * 2 + 0.5 * 2.5)
    off = M.follow(1, 100, 98, [102, 104, 106], rows, atr=0.5, params=OFF)
    assert off["status"] == "OPEN"                           # break-even stop at 100 not reached


def test_time_stop():
    flat = [(i * 900_000, 100, 100.3, 99.7, 100.1) for i in range(20)]
    r = M.follow(1, 100, 98, [102, 103, 104], flat, params={**ON, "time_stop_bars": 12}, bar_ms=900_000)
    assert r["exit_reason"] == "time" and r["closed_ts"] == 11 * 900_000 and r["status"] == "EXPIRED"
    up = [(i * 900_000, 100, 101.0, 99.9, 100.8) for i in range(20)]       # +0.4R open profit: kept
    assert M.follow(1, 100, 98, [102, 103, 104], up, params={**ON, "time_stop_bars": 12, "giveback_arm_r": 1.0},
                    bar_ms=900_000)["status"] == "OPEN"


def test_fill_candle_counts_the_stop_but_not_earlier_profit():
    rows = [(0, 101, 103, 99.8, 100.5)]              # limit 100 filled; the high came before the fill
    r = M.follow(1, 100, 98, [102, 103, 104], rows, params=OFF, first_is_fill=True)
    assert r["status"] == "OPEN" and not r["hits"][0] and r["peak_r"] == pytest.approx(0.25)
    assert M.find_fill(1, 100, [(0, 101, 102, 100.2, 101), (1, 101, 101, 99.9, 100)]) == 1
    assert M.find_fill(1, 100, [(0, 101, 102, 100.2, 101)]) is None
    assert M.find_fill(-1, 100, [(0, 99, 100.1, 98, 99)]) == 0
