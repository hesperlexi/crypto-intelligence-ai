"""v2.16 practice leaderboard + referral counts (services/leaderboard.py, services/referrals.py)."""
import json

from app.db import Database
from app.services import leaderboard as lb
from app.services import referrals
from app.services.runtime import Runtime
from app.sinks import LocalSink

H = 3_600_000
# 15 Nov 2026 12:00 Dubai
MID_NOV = lb.month_start_ms("2026-11") + 14 * 24 * H + 12 * H


class _Rt(Runtime):
    def symbols(self):
        return []


def _setup(tmp_path, users):
    db = Database(str(tmp_path / "x.db"))
    sink = LocalSink(tmp_path / "out", db)
    rt = _Rt(db, None)
    db.set_setting("users_cache", {"at": 1, "users": users})
    return rt, sink


def _member(username=None, **kw):
    u = {"status": "approved", "expires_at": MID_NOV + 90 * 24 * H, **kw}
    if username:
        u["username"] = username
    return u


def _acc(wallet, count=0, deposited=1000.0, realized=0.0, acc_id="a1", positions=None, orders=None):
    return {"id": acc_id, "starting_balance": 1000, "deposited": deposited, "wallet": wallet, "positions": positions or {},
            "orders": orders or {}, "totals": {"count": count, "realized": realized, "fees": 0, "funding": 0}}


def _view(sink):
    return json.loads(sink.pending["views/leaderboard"]["json"])


def test_month_key_is_dubai_time():
    start = lb.month_start_ms("2026-12")
    assert lb.month_key(start) == "2026-12"
    assert lb.month_key(start - 1) == "2026-11"          # 23:59:59 Dubai on 30 Nov = 19:59 UTC
    assert lb.month_label("2026-11") == "November 2026"


def test_equity_matches_the_trade_page_formula():
    acc = _acc(500, positions={"BTCUSDT": {"symbol": "BTC/USDT", "side": 1, "qty": 0.01, "entry": 50000, "margin": 100},
                               "ETHUSDT": {"symbol": "ETH/USDT", "side": -1, "qty": 1, "entry": 2000, "margin": 50}},
               orders={"o": {"reserve": 20.5}})
    prices = {"BTC/USDT": 51000, "ETH/USDT": 2100}
    r = lb.reading(acc, prices.get, 0)
    # 500 + 20.5 + (100 + 10) + max(0, 50 - 100)
    assert r["equity"] == 630.5
    assert r["book"] == 500 + 20.5 + 150


def test_deposits_never_count_as_profit():
    e = {"start_equity": 1000.0, "start_deposited": 1000.0, "start_count": 0, "start_realized": 0.0, "start_book": 1000.0}
    last = {"equity": 6100.0, "deposited": 6000.0, "count": 6, "realized": 100.0, "book": 6100.0}
    s = lb.score(e, last)
    assert s["deposits"] == 5000 and s["return_pct"] == round(100 / 6000 * 100, 2) and s["qualified"]
    assert not s["flags"]


def test_balance_edited_outside_trades_is_flagged():
    e = {"start_equity": 1000.0, "start_deposited": 1000.0, "start_count": 0, "start_realized": 0.0, "start_book": 1000.0}
    s = lb.score(e, {"equity": 50000.0, "deposited": 1000.0, "count": 5, "realized": 0.0, "book": 50000.0})
    assert "balance changed without trades" in s["flags"] and any("return above" in f for f in s["flags"])


def test_ranking_rules_privacy_and_reads(tmp_path):
    users = {"u1": _member("alice"), "u2": _member("bob"), "u3": _member(None), "u4": _member("old", expires_at=1),
             "u5": _member("few"), "u6": _member("cheat")}
    rt, sink = _setup(tmp_path, users)
    for uid in users:
        sink.set(f"paper/{uid}_futures", _acc(1000))
    sink.set("owner/leaderboard", {"excluded": ["u6"]})
    r = lb.run(rt, sink, now=MID_NOV)
    # only active members with a username, not excluded: u1, u2, u5 (+1 read for owner/leaderboard)
    assert r["read"] == 3
    sink.pending.clear()
    # trading during the month
    sink.set("paper/u1_futures", _acc(1200, count=5, realized=200))
    sink.set("paper/u2_futures", _acc(6100, count=7, realized=100, deposited=6000))     # +5000 Add funds
    sink.set("paper/u5_futures", _acc(1500, count=2, realized=500))                     # too few trades
    r = lb.run(rt, sink, now=MID_NOV + 30 * 60_000)
    assert r == {"skipped": "not due"}
    reads0 = sink.reads_today()
    r = lb.run(rt, sink, now=MID_NOV + 2 * H)
    assert r["read"] == 0                                     # nobody opened the app, readings < 6 h old
    assert sink.reads_today() == reads0 + 1
    rt.db.set_setting("fs_presence_seen", {"u1": MID_NOV + 2 * H + 1, "u2": MID_NOV + 2 * H + 1, "u5": MID_NOV + 2 * H + 1})
    r = lb.run(rt, sink, now=MID_NOV + 4 * H)
    assert r["read"] == 3 and r["ranked"] == 2
    v = _view(sink)
    assert [(x["rank"], x["username"]) for x in v["rows"]] == [(1, "alice"), (2, "bob")]
    assert v["rows"][0]["return_pct"] == 20.0 and v["rules"].startswith("Virtual money")
    text = sink.pending["views/leaderboard"]["json"]
    assert "u1" not in text and "@" not in text                  # usernames only
    adm = json.loads(sink.get("admin/leaderboard")["json"])
    assert {x["uid"] for x in adm["rows"]} == {"u1", "u2", "u5"}


def test_account_reset_is_not_ranked(tmp_path):
    rt, sink = _setup(tmp_path, {"u1": _member("alice")})
    sink.set("paper/u1_futures", _acc(1000))
    lb.run(rt, sink, now=MID_NOV)
    sink.set("paper/u1_futures", _acc(1900, count=9, acc_id="new"))
    rt.db.set_setting("fs_presence_seen", {"u1": MID_NOV + H})
    r = lb.run(rt, sink, now=MID_NOV + 2 * H)
    assert r["ranked"] == 0 and r["taking_part"] == 1


def test_month_end_decides_winner_once_and_restarts(tmp_path):
    rt, sink = _setup(tmp_path, {"u1": _member("alice", badges=["lb:2026-10"]), "u2": _member("bob")})
    sink.set("paper/u1_futures", _acc(1000))
    sink.set("paper/u2_futures", _acc(1000))
    lb.run(rt, sink, now=MID_NOV)
    sink.set("paper/u1_futures", _acc(1100, count=5, realized=100))
    sink.set("paper/u2_futures", _acc(1300, count=6, realized=300))
    dec = lb.month_start_ms("2026-12") + 10 * 60_000
    r = lb.run(rt, sink, now=dec)
    assert r["rollover"] and r["winners"] == ["bob"] and r["read"] == 2
    w = rt.db.query("SELECT * FROM leaderboard_winners")
    assert len(w) == 1 and w[0]["month"] == "2026-11" and w[0]["uid"] == "u2"
    v = _view(sink)
    assert v["month"] == "2026-12" and v["rows"] == []                       # new month: nobody has 5 trades yet
    assert v["last_winner"]["winners"][0]["username"] == "bob"
    assert v["badges"] == {"alice": ["2026-10"]}
    # December starts from the reading after midnight: Nov profits are not counted again
    e = rt.db.one("SELECT * FROM leaderboard_entries WHERE month = '2026-12' AND uid = 'u2'")
    assert e["start_equity"] == 1300
    # running again never changes November's winner
    lb.decide_winners(rt.db, "2026-11", [{"rank": 1, "uid": "u1", "username": "alice", "return_pct": 99, "trades": 9}], dec)
    assert [x["uid"] for x in rt.db.query("SELECT * FROM leaderboard_winners")] == ["u2"]


def test_skipped_in_lean_mode(tmp_path):
    rt, sink = _setup(tmp_path, {"u1": _member("alice")})
    rt.db.set_setting("fs_writes", {"day": sink.quota_day()[0], "n": 10 ** 6})
    assert sink.lean
    assert lb.run(rt, sink, now=MID_NOV) == {"skipped": "lean"}
    assert sink.reads_today() == 0


def test_referral_counts_written_only_when_changed(tmp_path):
    users = {"r1": _member("rita", ref_code="abcd1234", history=[{"kind": "referral", "amount": 0, "free": True}]),
             "f1": _member(None, referred_by="r1", referral_reward={"to": "r1"}),
             "f2": {"status": "pending", "referred_by": "r1"},
             "self": _member(None, referred_by="self")}
    rt, sink = _setup(tmp_path, users)
    assert referrals.stats(users) == {"r1": {"joined": 2, "paid": 1, "months": 1}}
    assert referrals.sync(rt, sink, now=5)["written"] == 1
    assert sink.get("users/r1")["referral_stats"]["joined"] == 2
    assert referrals.sync(rt, sink)["skipped"]                                # cache not refreshed since
    rt.db.set_setting("users_cache", {"at": 2, "users": users})
    assert referrals.sync(rt, sink)["written"] == 0                           # nothing changed: no write
