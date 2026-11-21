"""v2.63 Last Stand: a second all-in run inside the Hesper Challenge. Admin start with any amount, admin close all / 50%
on its own trade only, runs until liquidation, then waits for the admin. Own state and tables."""
import pytest

from app.services import hesper as H

from .test_hesper import NOW, STEP, _call, _put, _rt, quiet  # noqa: F401  (fixture)


def _ls(rt):
    return rt.db.get_setting(H.LastStand.STATE_KEY)


def test_never_starts_by_itself_then_admin_starts_with_any_amount(quiet):
    rt = _rt()
    _put(rt, "BTC/USDT", NOW - 8 * STEP, [100.0] * 8)
    _call(rt.db, "a")
    assert H.LastStand(rt).run(NOW) == [] and _ls(rt) is None
    v = H.view(rt, H.LastStand)
    assert v["id"] == "laststand" and v["current"] is None and not v["started"] and not v["auto_restart"]
    with pytest.raises(ValueError):
        H.LastStand(rt).start_new(1)
    out = H.LastStand(rt).start_new(10, NOW)
    assert out["run"] == 1 and _ls(rt)["cash"] == 10
    ev = H.LastStand(rt).run(NOW)
    assert ev and ev[0]["bot"] == "laststand" and ev[0]["type"] == "open"
    # the Hesper Challenge is separate: its own state and tables
    H.Hesper(rt).run(NOW)
    assert rt.db.get_setting(H.STATE_KEY)["cash"] != _ls(rt)["cash"]
    assert rt.db.one("SELECT COUNT(*) AS n FROM laststand_runs")["n"] == 1
    assert rt.db.one("SELECT COUNT(*) AS n FROM hesper_runs")["n"] == 1


def test_close_half_then_all_only_touches_last_stand(quiet, monkeypatch):
    rt = _rt()
    _put(rt, "BTC/USDT", NOW - 8 * STEP, [100.0] * 8)
    _call(rt.db, "c", stop=98.0, tps=(102.0, 103.5, 105.0))
    H.LastStand(rt).start_new(10, NOW)
    H.LastStand(rt).run(NOW)
    H.Hesper(rt).run(NOW)
    hz_before = rt.db.get_setting(H.STATE_KEY)
    pos = _ls(rt)["positions"][0]
    monkeypatch.setattr(rt, "live_price", lambda s: 101.0)
    r = H.LastStand(rt).admin_close(0.5, NOW + STEP)
    assert r["closed"] == "half" and r["pnl"] == pytest.approx(pos["qty"] * 0.5 * 1.0, abs=1e-3)
    p2 = _ls(rt)["positions"][0]
    assert p2["qty_open"] == pytest.approx(pos["qty"] * 0.5) and p2["leg_scale"] == 0.5
    # TP1 now takes half of what is left (25 % of the original), not everything
    _put(rt, "BTC/USDT", NOW, [(100, 102.2, 99.9, 102)])
    H.LastStand(rt).run(NOW + 2 * STEP)
    p3 = _ls(rt)["positions"][0]
    assert p3["tp_hit"] == 1 and p3["qty_open"] == pytest.approx(pos["qty"] * 0.25)
    r = H.LastStand(rt).admin_close(1, NOW + 3 * STEP)
    assert r["closed"] == "all" and not _ls(rt)["positions"]
    t = rt.db.one("SELECT * FROM laststand_trades")
    assert t["exit_reason"] == "closed by admin" and t["pnl"] > 0
    assert rt.db.one("SELECT run, result FROM laststand_runs") == {"run": 1, "result": "RUNNING"}    # the run goes on
    assert rt.db.get_setting(H.STATE_KEY)["positions"][0]["id"] == hz_before["positions"][0]["id"]  # Hesper untouched
    assert rt.db.one("SELECT COUNT(*) AS n FROM hesper_trades")["n"] == 0
    with pytest.raises(ValueError):
        H.LastStand(rt).admin_close(0.3)


def test_liquidation_ends_the_run_and_waits_for_the_admin(quiet):
    rt = _rt()
    _put(rt, "BTC/USDT", NOW - 8 * STEP, [100.0] * 8)
    _call(rt.db, "liq", stop=99.5, tps=(100.5, 101.0, 101.5))
    H.LastStand(rt).start_new(10, NOW)
    H.LastStand(rt).run(NOW)
    pos = _ls(rt)["positions"][0]
    _put(rt, "BTC/USDT", NOW, [(pos["liq"] - 1, pos["liq"] - 0.5, pos["liq"] - 2, pos["liq"] - 1)])
    ev = H.LastStand(rt).run(NOW + 2 * STEP)
    end = [e for e in ev if e["type"] == "run_end"][0]
    assert end["reason"] == "liquidated" and end["restart"] is False
    assert "when you're ready" in H.push_text(end)[1] and H.push_text(end)[0].startswith("Last Stand")
    st = _ls(rt)
    assert st["idle"] and st["run"] == 1 and H.LastStand(rt).run(NOW + 3 * STEP) == []
    out = H.LastStand(rt).start_new(25, NOW + 4 * STEP)
    assert out["run"] == 2 and _ls(rt)["cash"] == 25


def test_jobs_are_admin_only(quiet):
    from app import worker
    rt = _rt()
    with pytest.raises(PermissionError):
        worker.run_job(rt, {"type": "laststand_start", "params": {"amount": 10}}, 0)
    out = worker.run_job(rt, {"type": "laststand_start", "params": {"amount": 10}, "_admin": True}, 0)
    assert out["run"] == 1
    with pytest.raises(PermissionError):
        worker.run_job(rt, {"type": "laststand_close", "params": {"fraction": 1}}, 0)
    with pytest.raises(ValueError):
        worker.run_job(rt, {"type": "laststand_close", "params": {"fraction": 1}, "_admin": True}, 0)   # no trade yet
    out = worker.run_job(rt, {"type": "laststand_stop", "params": {}, "_admin": True}, 0)
    assert out["stopped_run"] == 1


def test_push_urls_and_tags_keep_hesper_unchanged():
    m = H.push_messages([{"bot": "laststand", "type": "open", "symbol": "BTC/USDT", "side": 1, "price": 1, "run": 2}], ["u1"])
    assert m[0]["title"] == "Last Stand · run #2" and m[0]["url"] == "/rich?c=laststand" and m[0]["tag"].startswith("laststand-2")
    assert m[1]["url"] == "/results?tab=challenge&c=laststand"
    h = H.push_messages([{"bot": "hesper", "type": "open", "symbol": "BTC/USDT", "side": 1, "price": 1, "run": 2}])
    assert h[0]["title"] == "Hesper Challenge · run #2" and h[0]["url"] == "/rich" and h[0]["tag"].startswith("hesper-2")
